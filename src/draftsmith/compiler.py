"""Style compiler: scene graph -> drawn primitives.

Separates floorplan *facts* from their *depiction*. Each door/window
style is a small function emitting primitives into a
:class:`~draftsmith.toolkit.Sketch`; registering a new style never
touches the engine. Style resolution order: per-object override, then
the scene's ``!S`` style header, then defaults.

This separation is the dataset factory's variety axis: the same scene
compiled under different style packs yields visually distinct but
semantically identical drawings — with the scene itself as perfect
ground truth.
"""

from __future__ import annotations

import math
from typing import Callable

from draftsmith.errors import ToolError
from draftsmith.geometry import wall_body
from draftsmith.scene import Door, Scene, Window
from draftsmith.toolkit import Sketch

LAYERS = {
    "WALLS": 7,
    "DOORS": 30,
    "WINDOWS": 5,
    "TEXT": 7,
    "DIMS": 8,
}

SLIDING_PANEL_THICKNESS = 40


def _door_frame(scene: Scene, door: Door):
    """Hinge point, closed-leaf angle (deg) and opening angle span for a door."""
    wall = scene.get(door.wall)
    a = wall.point_at(door.offset)
    b = wall.point_at(door.end_offset)
    ux, uy = wall.direction
    if door.hinge == "near":
        hinge, closed = a, math.degrees(math.atan2(uy, ux))
    else:
        hinge, closed = b, math.degrees(math.atan2(-uy, -ux))
    return hinge, closed


def _leaf_and_arc(sk: Sketch, hinge, closed: float, swing: str, width: float) -> None:
    open_angle = closed + 90 if swing == "left" else closed - 90
    rad = math.radians(open_angle)
    leaf_end = (hinge[0] + width * math.cos(rad), hinge[1] + width * math.sin(rad))
    sk.add_line(hinge, leaf_end, layer="DOORS")
    start, end = (closed, open_angle) if swing == "left" else (open_angle, closed)
    sk.add_arc(hinge, width, start, end, layer="DOORS")


def _door_arc(sk: Sketch, scene: Scene, door: Door) -> None:
    """Single swing leaf + quarter arc."""
    hinge, closed = _door_frame(scene, door)
    _leaf_and_arc(sk, hinge, closed, door.swing, door.width)


def _door_double(sk: Sketch, scene: Scene, door: Door) -> None:
    """Two half-width leaves hinged at both jambs, meeting mid-opening."""
    wall = scene.get(door.wall)
    ux, uy = wall.direction
    a = wall.point_at(door.offset)
    b = wall.point_at(door.end_offset)
    half = door.width / 2
    angle_ab = math.degrees(math.atan2(uy, ux))
    angle_ba = math.degrees(math.atan2(-uy, -ux))
    # The two leaves mirror each other, so their swings are opposite-handed.
    other = "right" if door.swing == "left" else "left"
    _leaf_and_arc(sk, a, angle_ab, door.swing, half)
    _leaf_and_arc(sk, b, angle_ba, other, half)


def _door_sliding(sk: Sketch, scene: Scene, door: Door) -> None:
    """Two overlapping panels on either side of the wall centerline."""
    wall = scene.get(door.wall)
    ux, uy = wall.direction
    nx, ny = wall.normal
    panel_len = door.width / 2 + 50
    side = 1 if door.swing == "left" else -1
    for i, start_off in enumerate([door.offset, door.end_offset - panel_len]):
        shift = side * (SLIDING_PANEL_THICKNESS if i == 0 else -SLIDING_PANEL_THICKNESS)
        p0 = wall.point_at(start_off)
        corners = []
        for da, dn in [(0, 0), (panel_len, 0),
                       (panel_len, shift), (0, shift)]:
            corners.append(
                (p0[0] + ux * da + nx * dn, p0[1] + uy * da + ny * dn)
            )
        sk.add_polyline(corners, closed=True, layer="DOORS")


def _window_triple(sk: Sketch, scene: Scene, window: Window) -> None:
    """Three parallel lines across the opening (faces + glazing)."""
    wall = scene.get(window.wall)
    nx, ny = wall.normal
    a = wall.point_at(window.offset)
    b = wall.point_at(window.end_offset)
    h = wall.thickness / 2
    for f in (-h, 0, h):
        sk.add_line(
            (a[0] + nx * f, a[1] + ny * f),
            (b[0] + nx * f, b[1] + ny * f),
            layer="WINDOWS",
        )


def _window_frame(sk: Sketch, scene: Scene, window: Window) -> None:
    """Frame rectangle filling the opening, with a centerline glazing line."""
    wall = scene.get(window.wall)
    nx, ny = wall.normal
    a = wall.point_at(window.offset)
    b = wall.point_at(window.end_offset)
    h = wall.thickness / 2
    sk.add_polyline(
        [
            (a[0] - nx * h, a[1] - ny * h),
            (b[0] - nx * h, b[1] - ny * h),
            (b[0] + nx * h, b[1] + ny * h),
            (a[0] + nx * h, a[1] + ny * h),
        ],
        closed=True,
        layer="WINDOWS",
    )
    sk.add_line(a, b, layer="WINDOWS")


DOOR_STYLES: dict[str, Callable[[Sketch, Scene, Door], None]] = {
    "arc": _door_arc,
    "double": _door_double,
    "sliding": _door_sliding,
}

WINDOW_STYLES: dict[str, Callable[[Sketch, Scene, Window], None]] = {
    "triple": _window_triple,
    "frame": _window_frame,
}

# Label styles are pure text transforms; the catalog lives in styles.py.
from draftsmith.styles import LABEL_FORMATS as LABEL_STYLES  # noqa: E402


def _resolve(styles: dict, name: str, kind: str):
    fn = styles.get(name)
    if fn is None:
        raise ToolError(
            f"unknown {kind} style {name!r}; available: {sorted(styles)}"
        )
    return fn


def compile_scene(scene: Scene) -> Sketch:
    """Compile the scene into drawn primitives (a Sketch), ready to
    ``save()`` as DXF or ``render()`` to PNG/SVG/PDF."""
    sk = Sketch()
    for name, color in LAYERS.items():
        sk.add_layer(name, color=color)

    # Walls: union of bodies with openings cut; ring boundaries include the
    # jamb edges at every opening.
    body = wall_body(scene, cut_openings=True)
    polys = list(body.geoms) if body.geom_type == "MultiPolygon" else [body]
    for poly in polys:
        if poly.is_empty:
            continue
        for ring in [poly.exterior, *poly.interiors]:
            pts = [(round(x, 1), round(y, 1)) for x, y in ring.coords[:-1]]
            if len(pts) >= 2:
                sk.add_polyline(pts, closed=True, layer="WALLS")

    for door in scene.doors:
        style = scene.style_for("door", door.style)
        _resolve(DOOR_STYLES, style, "door")(sk, scene, door)

    for window in scene.windows:
        style = scene.style_for("window", window.style)
        _resolve(WINDOW_STYLES, style, "window")(sk, scene, window)

    for label in scene.labels:
        fmt = _resolve(LABEL_STYLES, scene.style_for("label", label.style), "label")
        sk.add_text(fmt(label.text), label.position, layer="TEXT")

    for dim in scene.dims:
        sk.add_aligned_dim(
            dim.p1, dim.p2, offset=dim.offset, arrows=dim.arrows, layer="DIMS"
        )

    return sk
