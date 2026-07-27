"""Agent-friendly CAD tooling layer over ezdxf.

Step 2 of the draftsmith roadmap: the "hands" of the system. Every
operation validates its inputs and raises :class:`ToolError` with a
message written for an LLM agent to act on. Mutating operations return
entity handles so agents can reference, inspect, edit and delete what
they drew; inspection operations return plain JSON-friendly dicts.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import ezdxf
from ezdxf import bbox
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment

from draftsmith.errors import ToolError
from draftsmith.renderer import render_doc

Point = Sequence[float]

__all__ = ["Sketch", "ToolError"]


def _pt(p: Point, name: str) -> tuple[float, float]:
    try:
        x, y = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        raise ToolError(
            f"{name} must be a point like (x, y), got {p!r}"
        ) from None
    return (x, y)


class Sketch:
    """A 2D DXF drawing session with validated draw/edit/inspect operations.

    All coordinates are in millimetres.
    """

    def __init__(self, doc: Drawing | None = None) -> None:
        if doc is None:
            doc = ezdxf.new("R2018", setup=True)
            doc.header["$INSUNITS"] = 4  # millimetres
        self.doc = doc
        self.msp = doc.modelspace()

    @classmethod
    def open(cls, path: str | Path) -> "Sketch":
        return cls(ezdxf.readfile(str(path)))

    # ------------------------------------------------------------------ layers

    def add_layer(self, name: str, color: int = 7) -> str:
        """Create a layer (no-op if it already exists). Returns the layer name."""
        if not name or name != name.strip():
            raise ToolError(f"invalid layer name {name!r}")
        if name not in self.doc.layers:
            self.doc.layers.add(name, color=color)
        return name

    def layers(self) -> list[dict[str, Any]]:
        return [
            {"name": layer.dxf.name, "color": layer.color}
            for layer in self.doc.layers
        ]

    def _attribs(self, layer: str) -> dict[str, str]:
        self.add_layer(layer)  # forgiving: auto-create missing layers
        return {"layer": layer}

    # -------------------------------------------------------------- primitives

    def add_line(self, start: Point, end: Point, layer: str = "0") -> str:
        p1, p2 = _pt(start, "start"), _pt(end, "end")
        if p1 == p2:
            raise ToolError(f"line has zero length: start == end == {p1}")
        return self.msp.add_line(p1, p2, dxfattribs=self._attribs(layer)).dxf.handle

    def add_polyline(
        self, points: Iterable[Point], closed: bool = False, layer: str = "0"
    ) -> str:
        pts = [_pt(p, f"points[{i}]") for i, p in enumerate(points)]
        if len(pts) < 2:
            raise ToolError(f"polyline needs at least 2 points, got {len(pts)}")
        e = self.msp.add_lwpolyline(pts, close=closed, dxfattribs=self._attribs(layer))
        return e.dxf.handle

    def add_rect(self, corner: Point, width: float, height: float, layer: str = "0") -> str:
        x, y = _pt(corner, "corner")
        if width <= 0 or height <= 0:
            raise ToolError(
                f"rect width and height must be positive, got {width} x {height}"
            )
        return self.add_polyline(
            [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
            closed=True,
            layer=layer,
        )

    def add_circle(self, center: Point, radius: float, layer: str = "0") -> str:
        if radius <= 0:
            raise ToolError(f"circle radius must be positive, got {radius}")
        e = self.msp.add_circle(_pt(center, "center"), radius, dxfattribs=self._attribs(layer))
        return e.dxf.handle

    def add_arc(
        self,
        center: Point,
        radius: float,
        start_angle: float,
        end_angle: float,
        layer: str = "0",
    ) -> str:
        """Circular arc from start_angle to end_angle, counter-clockwise, degrees."""
        if radius <= 0:
            raise ToolError(f"arc radius must be positive, got {radius}")
        e = self.msp.add_arc(
            center=_pt(center, "center"),
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
            dxfattribs=self._attribs(layer),
        )
        return e.dxf.handle

    def add_text(
        self,
        text: str,
        position: Point,
        height: float = 250,
        layer: str = "0",
        align: str = "MIDDLE_CENTER",
    ) -> str:
        if not text:
            raise ToolError("text must not be empty")
        if height <= 0:
            raise ToolError(f"text height must be positive, got {height}")
        try:
            alignment = TextEntityAlignment[align]
        except KeyError:
            valid = ", ".join(a.name for a in TextEntityAlignment)
            raise ToolError(f"unknown alignment {align!r}; valid: {valid}") from None
        e = self.msp.add_text(text, height=height, dxfattribs=self._attribs(layer))
        e.set_placement(_pt(position, "position"), align=alignment)
        return e.dxf.handle

    def add_aligned_dim(
        self,
        p1: Point,
        p2: Point,
        offset: float = 700,
        text_height: float = 250,
        layer: str = "0",
    ) -> str:
        """Dimension the distance p1->p2, with the dimension line ``offset`` mm
        to the side. Annotation is pre-scaled for millimetre drawings."""
        a, b = _pt(p1, "p1"), _pt(p2, "p2")
        if a == b:
            raise ToolError("cannot dimension two identical points")
        dim = self.msp.add_aligned_dim(
            p1=a,
            p2=b,
            distance=offset,
            override={
                "dimtxt": text_height,
                "dimasz": text_height * 0.8,
                "dimexe": 100,
                "dimexo": 100,
                "dimgap": text_height * 0.3,
                "dimdec": 0,
                "dimlfac": 1,
            },
            dxfattribs=self._attribs(layer),
        )
        dim.render()
        return dim.dimension.dxf.handle

    # ------------------------------------------------------------------- edits

    def _get(self, handle: str):
        e = self.doc.entitydb.get(handle)
        if e is None or not e.is_alive or e.dxf.owner != self.msp.layout_key:
            raise ToolError(
                f"no modelspace entity with handle {handle!r}; "
                "use entities() to list valid handles"
            )
        return e

    def delete(self, handle: str) -> None:
        self.msp.delete_entity(self._get(handle))

    def translate(self, handle: str, dx: float, dy: float) -> str:
        e = self._get(handle)
        try:
            e.translate(dx, dy, 0)
        except (AttributeError, NotImplementedError):
            raise ToolError(
                f"entity {handle!r} ({e.dxftype()}) does not support translate"
            ) from None
        return handle

    # -------------------------------------------------------------- inspection

    @staticmethod
    def _geometry(e) -> dict[str, Any]:
        t = e.dxftype()
        if t == "LINE":
            return {
                "start": tuple(e.dxf.start)[:2],
                "end": tuple(e.dxf.end)[:2],
            }
        if t == "LWPOLYLINE":
            return {
                "points": [tuple(p)[:2] for p in e.get_points("xy")],
                "closed": e.closed,
            }
        if t == "CIRCLE":
            return {"center": tuple(e.dxf.center)[:2], "radius": e.dxf.radius}
        if t == "ARC":
            return {
                "center": tuple(e.dxf.center)[:2],
                "radius": e.dxf.radius,
                "start_angle": e.dxf.start_angle,
                "end_angle": e.dxf.end_angle,
            }
        if t in ("TEXT", "MTEXT"):
            return {"text": e.plain_text() if t == "MTEXT" else e.dxf.text}
        if t == "DIMENSION":
            return {"measurement": e.get_measurement()}
        return {}

    def describe(self, handle: str) -> dict[str, Any]:
        e = self._get(handle)
        return {
            "handle": handle,
            "type": e.dxftype(),
            "layer": e.dxf.layer,
            **self._geometry(e),
        }

    def entities(self, layer: str | None = None) -> list[dict[str, Any]]:
        """List modelspace entities as JSON-friendly dicts, optionally
        filtered by layer."""
        result = []
        for e in self.msp:
            if layer is not None and e.dxf.layer != layer:
                continue
            result.append(
                {
                    "handle": e.dxf.handle,
                    "type": e.dxftype(),
                    "layer": e.dxf.layer,
                    **self._geometry(e),
                }
            )
        return result

    def extents(self) -> dict[str, tuple[float, float]] | None:
        """Bounding box of the drawing, or None if it is empty."""
        box = bbox.extents(self.msp, fast=True)
        if not box.has_data:
            return None
        return {
            "min": tuple(box.extmin)[:2],
            "max": tuple(box.extmax)[:2],
        }

    @staticmethod
    def measure(p1: Point, p2: Point) -> float:
        a, b = _pt(p1, "p1"), _pt(p2, "p2")
        return math.dist(a, b)

    def summary(self) -> dict[str, Any]:
        """Counts by entity type and by layer, plus extents — the cheap
        'what does the drawing contain' read-back for agents."""
        by_type: dict[str, int] = {}
        by_layer: dict[str, int] = {}
        for e in self.msp:
            by_type[e.dxftype()] = by_type.get(e.dxftype(), 0) + 1
            by_layer[e.dxf.layer] = by_layer.get(e.dxf.layer, 0) + 1
        return {
            "entities": sum(by_type.values()),
            "by_type": by_type,
            "by_layer": by_layer,
            "extents": self.extents(),
        }

    # --------------------------------------------------------------------- io

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.saveas(path)
        return path

    def render(self, path: str | Path, dpi: int = 300, dark: bool = False) -> Path:
        return render_doc(self.doc, path, dpi=dpi, dark=dark)
