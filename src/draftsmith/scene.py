"""The floorplan scene graph — draftsmith's semantic IR.

A :class:`Scene` holds *facts* about a floorplan: walls (centerline +
thickness), openings hosted on walls (doors, windows), labels and
dimensions. How those facts are *drawn* (symbols, hatches, line weights)
is decided later by the style compiler; what they *enclose* (rooms,
adjacency) is derived by the geometry module, never stored.

Objects get typed sequential IDs (W1, D2, N1, L1, M1). IDs are never
reused after deletion, so references in an agent's conversation history
stay unambiguous forever.

All coordinates are integer-ish millimetres; angles are degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from draftsmith.errors import ToolError

Point = tuple[float, float]

_EPS = 1e-6

DEFAULT_WALL_THICKNESS = 230
DEFAULT_DOOR_WIDTH = 900
DEFAULT_HINGE = "near"
DEFAULT_SWING = "left"

# Style-pack slots and their defaults; a Scene can override per-slot in
# scene.styles, and individual openings can override per-object via .style.
DEFAULT_STYLES = {
    "wall": "plain",
    "door": "arc",
    "window": "triple",
    "label": "plain",
}


def _pt(p: Sequence[float], name: str) -> Point:
    try:
        return (float(p[0]), float(p[1]))
    except (TypeError, ValueError, IndexError):
        raise ToolError(f"{name} must be a point like (x, y), got {p!r}") from None


@dataclass
class Wall:
    id: str
    start: Point
    end: Point
    thickness: float = DEFAULT_WALL_THICKNESS

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def direction(self) -> Point:
        """Unit vector start -> end."""
        length = self.length
        return (
            (self.end[0] - self.start[0]) / length,
            (self.end[1] - self.start[1]) / length,
        )

    @property
    def normal(self) -> Point:
        """Unit left-hand normal (90 degrees CCW from direction)."""
        u = self.direction
        return (-u[1], u[0])

    def point_at(self, offset: float) -> Point:
        u = self.direction
        return (self.start[0] + u[0] * offset, self.start[1] + u[1] * offset)


@dataclass
class Opening:
    """Base for wall-hosted objects: a gap of `width` starting `offset` mm
    from the host wall's start."""

    id: str
    wall: str
    offset: float
    width: float
    style: str | None = None

    @property
    def end_offset(self) -> float:
        return self.offset + self.width


@dataclass
class Door(Opening):
    hinge: str = DEFAULT_HINGE  # "near" (wall-start side) or "far"
    swing: str = DEFAULT_SWING  # "left" = CCW from the closed leaf direction


@dataclass
class Window(Opening):
    pass


@dataclass
class Label:
    id: str
    position: Point
    text: str


DIM_ARROWS = ("default", "arrow", "tick", "empty")


@dataclass
class Dim:
    """Aligned dimension between two points; `offset` is the signed distance
    of the dimension line from p1->p2 (positive = left-hand side).
    `arrows` picks the terminator style: default (filled), arrow (open),
    tick (architectural), or empty."""

    id: str
    p1: Point
    p2: Point
    offset: float = -700
    arrows: str = "default"


_PREFIXES = {"W": Wall, "D": Door, "N": Window, "L": Label, "M": Dim}
_PREFIX_OF = {Wall: "W", Door: "D", Window: "N", Label: "L", Dim: "M"}


@dataclass
class Scene:
    units: str = "mm"
    styles: dict[str, str] = field(default_factory=dict)
    _objects: dict[str, Any] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=lambda: {p: 0 for p in _PREFIXES})

    # ------------------------------------------------------------------- ids

    def _new_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}{self._counters[prefix]}"

    def _register(self, obj: Any, obj_id: str | None) -> Any:
        prefix = _PREFIX_OF[type(obj)]
        if obj_id is not None:
            if obj_id in self._objects:
                raise ToolError(f"duplicate id {obj_id!r}")
            if not obj_id.startswith(prefix) or not obj_id[len(prefix):].isdigit():
                raise ToolError(
                    f"invalid id {obj_id!r} for {type(obj).__name__}; expected {prefix}<number>"
                )
            num = int(obj_id[len(prefix):])
            if num <= 0:
                raise ToolError(f"invalid id {obj_id!r}; numbering starts at 1")
            self._counters[prefix] = max(self._counters[prefix], num)
            obj.id = obj_id
        else:
            obj.id = self._new_id(prefix)
        self._objects[obj.id] = obj
        return obj

    # ------------------------------------------------------------------ walls

    def add_wall(
        self,
        start: Sequence[float],
        end: Sequence[float],
        thickness: float = DEFAULT_WALL_THICKNESS,
        id: str | None = None,
    ) -> Wall:
        s, e = _pt(start, "start"), _pt(end, "end")
        if math.dist(s, e) < _EPS:
            raise ToolError(f"wall has zero length: start == end == {s}")
        if thickness <= 0:
            raise ToolError(f"wall thickness must be positive, got {thickness}")
        return self._register(Wall("", s, e, float(thickness)), id)

    # --------------------------------------------------------------- openings

    def _validate_opening(
        self, wall_id: str, offset: float, width: float, exclude: str | None = None
    ) -> Wall:
        wall = self.get(wall_id)
        if not isinstance(wall, Wall):
            raise ToolError(f"{wall_id!r} is not a wall (it is a {type(wall).__name__})")
        if width <= 0:
            raise ToolError(f"opening width must be positive, got {width}")
        if offset < -_EPS:
            raise ToolError(f"opening offset must be >= 0, got {offset}")
        if offset + width > wall.length + _EPS:
            raise ToolError(
                f"opening spans {offset}..{offset + width} mm but wall {wall_id} "
                f"is only {wall.length:.0f} mm long"
            )
        for other in self.openings_on(wall_id):
            if other.id == exclude:
                continue
            if offset < other.end_offset - _EPS and other.offset < offset + width - _EPS:
                raise ToolError(
                    f"opening {offset}..{offset + width} overlaps {other.id} "
                    f"({other.offset}..{other.end_offset}) on wall {wall_id}"
                )
        return wall

    def add_door(
        self,
        wall: str,
        offset: float,
        width: float = DEFAULT_DOOR_WIDTH,
        hinge: str = DEFAULT_HINGE,
        swing: str = DEFAULT_SWING,
        style: str | None = None,
        id: str | None = None,
    ) -> Door:
        if hinge not in ("near", "far"):
            raise ToolError(f"hinge must be 'near' or 'far', got {hinge!r}")
        if swing not in ("left", "right"):
            raise ToolError(f"swing must be 'left' or 'right', got {swing!r}")
        self._validate_opening(wall, offset, width)
        return self._register(
            Door("", wall, float(offset), float(width), style, hinge, swing), id
        )

    def add_window(
        self,
        wall: str,
        offset: float,
        width: float,
        style: str | None = None,
        id: str | None = None,
    ) -> Window:
        self._validate_opening(wall, offset, width)
        return self._register(Window("", wall, float(offset), float(width), style), id)

    # ------------------------------------------------------------ annotations

    def add_label(self, text: str, position: Sequence[float], id: str | None = None) -> Label:
        if not text:
            raise ToolError("label text must not be empty")
        return self._register(Label("", _pt(position, "position"), text), id)

    def add_dim(
        self,
        p1: Sequence[float],
        p2: Sequence[float],
        offset: float = -700,
        arrows: str = "default",
        id: str | None = None,
    ) -> Dim:
        a, b = _pt(p1, "p1"), _pt(p2, "p2")
        if math.dist(a, b) < _EPS:
            raise ToolError("cannot dimension two identical points")
        if arrows not in DIM_ARROWS:
            raise ToolError(f"arrows must be one of {DIM_ARROWS}, got {arrows!r}")
        return self._register(Dim("", a, b, float(offset), arrows), id)

    def update_dim(
        self,
        dim_id: str,
        offset: float | None = None,
        arrows: str | None = None,
    ) -> Dim:
        obj = self.get(dim_id)
        if not isinstance(obj, Dim):
            raise ToolError(f"{dim_id!r} is not a dimension")
        if offset is not None:
            if abs(float(offset)) < _EPS:
                raise ToolError("dimension offset must be non-zero")
            obj.offset = float(offset)
        if arrows is not None:
            if arrows not in DIM_ARROWS:
                raise ToolError(f"arrows must be one of {DIM_ARROWS}, got {arrows!r}")
            obj.arrows = arrows
        return obj

    # ----------------------------------------------------------------- access

    def get(self, obj_id: str) -> Any:
        obj = self._objects.get(obj_id)
        if obj is None:
            raise ToolError(
                f"no object with id {obj_id!r} (it may have been deleted; "
                "deleted ids are never reused)"
            )
        return obj

    def _of_type(self, cls: type) -> list[Any]:
        return [o for o in self._objects.values() if type(o) is cls]

    @property
    def walls(self) -> list[Wall]:
        return self._of_type(Wall)

    @property
    def doors(self) -> list[Door]:
        return self._of_type(Door)

    @property
    def windows(self) -> list[Window]:
        return self._of_type(Window)

    @property
    def labels(self) -> list[Label]:
        return self._of_type(Label)

    @property
    def dims(self) -> list[Dim]:
        return self._of_type(Dim)

    def openings_on(self, wall_id: str) -> list[Opening]:
        return sorted(
            (o for o in self._objects.values()
             if isinstance(o, Opening) and o.wall == wall_id),
            key=lambda o: o.offset,
        )

    def __iter__(self) -> Iterator[Any]:
        return iter(self._objects.values())

    def __len__(self) -> int:
        return len(self._objects)

    # ----------------------------------------------------------------- edits

    def delete(self, obj_id: str) -> None:
        obj = self.get(obj_id)
        if isinstance(obj, Wall):
            hosted = [o.id for o in self.openings_on(obj_id)]
            if hosted:
                raise ToolError(
                    f"cannot delete {obj_id}: openings {', '.join(hosted)} are "
                    f"hosted on it; delete them first or move them to another wall"
                )
        del self._objects[obj_id]

    def move_opening(self, opening_id: str, offset: float) -> Opening:
        obj = self.get(opening_id)
        if not isinstance(obj, Opening):
            raise ToolError(f"{opening_id!r} is not a door or window")
        self._validate_opening(obj.wall, offset, obj.width, exclude=obj.id)
        obj.offset = float(offset)
        return obj

    # ------------------------------------------------------------------ style

    def style_for(self, slot: str, override: str | None = None) -> str:
        return override or self.styles.get(slot) or DEFAULT_STYLES[slot]
