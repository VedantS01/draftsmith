"""Architectural drawing verbs built on the tooling layer.

Higher-level operations an agent uses to draw buildings: walls with
openings, doors with swings, windows, room labels. Geometry conventions:
coordinates in millimetres, angles in degrees counter-clockwise from +X.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from draftsmith.toolkit import Point, Sketch, ToolError, _pt


def _unit(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, tuple[float, float], tuple[float, float]]:
    """Length, unit direction vector, and left-hand unit normal of start->end."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ToolError(f"wall has zero length: start == end == {start}")
    u = (dx / length, dy / length)
    n = (-u[1], u[0])
    return length, u, n


def add_wall(
    sketch: Sketch,
    start: Point,
    end: Point,
    thickness: float = 230,
    openings: Sequence[dict[str, Any]] | None = None,
    layer: str = "WALLS",
) -> list[str]:
    """Draw a straight wall as closed rectangles centred on the
    start->end centerline.

    ``openings`` punches gaps (for doors/windows): each is a dict
    ``{"offset": <mm from wall start>, "width": <mm>}``. Openings must lie
    within the wall and must not overlap. Returns the handles of the wall
    segment polylines.
    """
    s, e = _pt(start, "start"), _pt(end, "end")
    if thickness <= 0:
        raise ToolError(f"wall thickness must be positive, got {thickness}")
    length, u, n = _unit(s, e)

    parsed: list[tuple[float, float]] = []
    for i, o in enumerate(openings or ()):
        try:
            off, w = float(o["offset"]), float(o["width"])
        except (KeyError, TypeError, ValueError):
            raise ToolError(
                f"openings[{i}] must look like {{'offset': mm, 'width': mm}}, got {o!r}"
            ) from None
        if w <= 0:
            raise ToolError(f"openings[{i}] width must be positive, got {w}")
        if off < 0:
            raise ToolError(f"openings[{i}] offset must be >= 0, got {off}")
        if off + w > length + 1e-9:
            raise ToolError(
                f"openings[{i}] extends to {off + w} mm but the wall is only "
                f"{length:.0f} mm long"
            )
        parsed.append((off, w))
    parsed.sort()

    cursor = 0.0
    spans: list[tuple[float, float]] = []
    for off, w in parsed:
        if off < cursor - 1e-9:
            raise ToolError(
                f"opening at offset {off} overlaps the previous opening "
                f"(which ends at {cursor})"
            )
        if off > cursor:
            spans.append((cursor, off))
        cursor = off + w
    if cursor < length:
        spans.append((cursor, length))
    if not spans:
        raise ToolError("openings cover the entire wall; nothing left to draw")

    half = thickness / 2
    handles = []
    for a, b in spans:
        pa = (s[0] + u[0] * a, s[1] + u[1] * a)
        pb = (s[0] + u[0] * b, s[1] + u[1] * b)
        handles.append(
            sketch.add_polyline(
                [
                    (pa[0] - n[0] * half, pa[1] - n[1] * half),
                    (pb[0] - n[0] * half, pb[1] - n[1] * half),
                    (pb[0] + n[0] * half, pb[1] + n[1] * half),
                    (pa[0] + n[0] * half, pa[1] + n[1] * half),
                ],
                closed=True,
                layer=layer,
            )
        )
    return handles


def add_door(
    sketch: Sketch,
    hinge: Point,
    width: float = 900,
    angle: float = 0,
    swing: str = "left",
    layer: str = "DOORS",
) -> list[str]:
    """Standard plan-view door symbol: the leaf drawn in its open position
    plus a quarter-circle swing arc.

    ``angle`` is the direction (degrees CCW from +X) from the hinge to the
    latch when the door is closed; ``swing`` is which way it opens relative
    to that direction ("left" = counter-clockwise). Returns
    [leaf_handle, arc_handle].
    """
    h = _pt(hinge, "hinge")
    if width <= 0:
        raise ToolError(f"door width must be positive, got {width}")
    if swing not in ("left", "right"):
        raise ToolError(f"swing must be 'left' or 'right', got {swing!r}")

    open_angle = angle + 90 if swing == "left" else angle - 90
    rad = math.radians(open_angle)
    leaf_end = (h[0] + width * math.cos(rad), h[1] + width * math.sin(rad))
    leaf = sketch.add_line(h, leaf_end, layer=layer)
    start_angle, end_angle = (
        (angle, open_angle) if swing == "left" else (open_angle, angle)
    )
    arc = sketch.add_arc(h, width, start_angle, end_angle, layer=layer)
    return [leaf, arc]


def add_window(
    sketch: Sketch,
    start: Point,
    end: Point,
    thickness: float = 230,
    layer: str = "WINDOWS",
) -> list[str]:
    """Plan-view window symbol: three parallel lines (faces + glazing)
    across the opening from start to end, spanning the wall thickness.
    start/end lie on the wall centerline."""
    s, e = _pt(start, "start"), _pt(end, "end")
    if thickness <= 0:
        raise ToolError(f"window thickness must be positive, got {thickness}")
    _, _, n = _unit(s, e)
    half = thickness / 2
    handles = []
    for f in (-half, 0, half):
        handles.append(
            sketch.add_line(
                (s[0] + n[0] * f, s[1] + n[1] * f),
                (e[0] + n[0] * f, e[1] + n[1] * f),
                layer=layer,
            )
        )
    return handles


def add_room_label(
    sketch: Sketch,
    text: str,
    position: Point,
    height: float = 250,
    layer: str = "TEXT",
) -> str:
    return sketch.add_text(text, position, height=height, layer=layer)
