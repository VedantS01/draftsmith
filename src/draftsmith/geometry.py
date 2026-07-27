"""Derived geometry over the scene graph (Shapely-backed).

Nothing here is stored in the scene: wall bodies, rooms, and adjacency
are always computed from the semantic facts. This is what gives agents
(and metrics) their spatial awareness — "what rooms exist", "what does
this door connect", "how big is the bedroom" — without the IR having to
keep any of it consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point as SPoint
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from draftsmith.scene import Door, Opening, Scene, Wall

# One consistent tolerance for "does it touch" questions, in mm.
TOL = 1.0
# How far an opening probe reaches beyond the wall faces when asking which
# rooms an opening connects.
PROBE = 50.0

EXTERIOR = "EXT"


def wall_polygon(wall: Wall, ext_start: float = 0.0, ext_end: float = 0.0) -> Polygon:
    """The wall's body: its centerline offset by half the thickness.
    ``ext_start``/``ext_end`` lengthen the body past the endpoints — used
    to close the corner notch where walls meet at a joint."""
    ux, uy = wall.direction
    sx, sy = wall.start[0] - ux * ext_start, wall.start[1] - uy * ext_start
    ex, ey = wall.end[0] + ux * ext_end, wall.end[1] + uy * ext_end
    nx, ny = wall.normal
    h = wall.thickness / 2
    return Polygon(
        [
            (sx - nx * h, sy - ny * h),
            (ex - nx * h, ey - ny * h),
            (ex + nx * h, ey + ny * h),
            (sx + nx * h, sy + ny * h),
        ]
    )


def _joint_extensions(scene: Scene, wall: Wall) -> tuple[float, float]:
    """How far to extend each end of a wall so joints close cleanly:
    half the thickest mate meeting at that endpoint (0 at free ends)."""
    exts = []
    for end in ("start", "end"):
        mates = scene.walls_at(getattr(wall, end), exclude=wall.id)
        exts.append(max((m.thickness for m, _ in mates), default=0.0) / 2)
    return exts[0], exts[1]


def joints(scene: Scene) -> list[dict]:
    """Wall endpoints grouped into joints (shared endpoints merge), for
    display/drag handles: [{"at": [x, y], "walls": [ids]}]."""
    groups: dict[tuple[float, float], dict] = {}
    for w in scene.walls:
        for end in ("start", "end"):
            p = getattr(w, end)
            key = (round(p[0], 1), round(p[1], 1))
            g = groups.setdefault(key, {"at": [key[0], key[1]], "walls": []})
            if w.id not in g["walls"]:
                g["walls"].append(w.id)
    return list(groups.values())


def opening_polygon(scene: Scene, opening: Opening, probe: float = 0.0) -> Polygon:
    """The rectangle an opening occupies in its host wall; ``probe`` extends
    it beyond the wall faces (used to ask what lies on either side)."""
    wall = scene.get(opening.wall)
    ux, uy = wall.direction
    nx, ny = wall.normal
    a = wall.point_at(opening.offset)
    b = wall.point_at(opening.end_offset)
    h = wall.thickness / 2 + probe
    return Polygon(
        [
            (a[0] - nx * h, a[1] - ny * h),
            (b[0] - nx * h, b[1] - ny * h),
            (b[0] + nx * h, b[1] + ny * h),
            (a[0] + nx * h, a[1] + ny * h),
        ]
    )


def wall_body(scene: Scene, cut_openings: bool = True):
    """Union of all wall polygons — mitres and T-joints resolve here.
    With ``cut_openings``, door/window gaps are subtracted (the drawn
    form); without, walls are solid (the room-separating form)."""
    polys = [wall_polygon(w, *_joint_extensions(scene, w)) for w in scene.walls]
    if not polys:
        return Polygon()
    body = unary_union(polys)
    if cut_openings:
        cuts = [
            opening_polygon(scene, o, probe=TOL)
            for o in scene
            if isinstance(o, Opening)
        ]
        if cuts:
            body = body.difference(unary_union(cuts))
    return body


@dataclass
class Room:
    id: str
    polygon: Polygon
    label: str | None = None

    @property
    def area_m2(self) -> float:
        return self.polygon.area / 1e6

    @property
    def centroid(self) -> tuple[float, float]:
        c = self.polygon.centroid
        return (c.x, c.y)


def rooms(scene: Scene) -> list[Room]:
    """Enclosed regions of the solid wall network, numbered deterministically
    (reading order: bottom-to-top, then left-to-right), with labels matched
    by containment."""
    solid = wall_body(scene, cut_openings=False)
    if solid.is_empty:
        return []
    minx, miny, maxx, maxy = solid.bounds
    margin = 10 * TOL
    envelope = box(minx - margin, miny - margin, maxx + margin, maxy + margin)
    free = envelope.difference(solid)
    parts = list(free.geoms) if free.geom_type == "MultiPolygon" else [free]
    enclosed = [
        p for p in parts
        if not p.is_empty and p.distance(envelope.exterior) > TOL
    ]
    enclosed.sort(key=lambda p: (round(p.centroid.y), round(p.centroid.x)))

    result = [Room(f"R{i + 1}", p) for i, p in enumerate(enclosed)]
    for label in scene.labels:
        pt = SPoint(label.position)
        for room in result:
            if room.polygon.contains(pt):
                room.label = label.text
                break
    return result


def connections(scene: Scene, room_list: list[Room] | None = None) -> list[dict]:
    """What each opening connects: two room ids, or a room and ``EXT``
    (outside). Windows to the exterior read as [room, EXT] too."""
    room_list = rooms(scene) if room_list is None else room_list
    out = []
    for opening in scene:
        if not isinstance(opening, Opening):
            continue
        probe_poly = opening_polygon(scene, opening, probe=PROBE)
        touched = [r.id for r in room_list if r.polygon.intersects(probe_poly)]
        while len(touched) < 2:
            touched.append(EXTERIOR)
        out.append(
            {
                "opening": opening.id,
                "kind": "door" if isinstance(opening, Door) else "window",
                "rooms": touched[:2],
            }
        )
    return out


def summary(scene: Scene) -> dict:
    """Compact spatial read-back for agents: rooms with areas and labels,
    what connects to what, and totals."""
    room_list = rooms(scene)
    return {
        "walls": len(scene.walls),
        "doors": len(scene.doors),
        "windows": len(scene.windows),
        "rooms": [
            {
                "id": r.id,
                "label": r.label,
                "area_m2": round(r.area_m2, 2),
                "bbox": [round(v) for v in r.polygon.bounds],
            }
            for r in room_list
        ],
        "connections": connections(scene, room_list),
    }
