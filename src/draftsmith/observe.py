"""The observation layer: engine answers to agent queries about a scene.

The drafting protocol is toolless text (M2), so "tool calls" are query
lines — a reply made of lines starting with ``?`` is answered by
:func:`answer` instead of being parsed as a plan.  The same functions
will back native MCP tools later; the protocol is the text.

Everything here is read-only and derived — walls as drawn, the joint
graph (which walls meet where, and which ends dangle), the room graph
(what connects to what, how deep from outside), and per-entity detail
(lengths, alignments, thickness, areas, shapes, entry/exit situation).
"""

from __future__ import annotations

import math

from shapely.geometry import Point as SPoint

from draftsmith.evaluate import AccessGraph, _mrr_sides, room_type
from draftsmith.geometry import (
    EXTERIOR,
    TOL,
    Room,
    connections,
    rooms,
    wall_polygon,
)
from draftsmith.scene import Door, Scene

# Probe reach (mm) beyond a wall face when asking which rooms flank it.
SIDE_PROBE = 60.0


def _align(wall) -> str:
    dx = wall.end[0] - wall.start[0]
    dy = wall.end[1] - wall.start[1]
    if abs(dy) < 1e-6:
        return "H"
    if abs(dx) < 1e-6:
        return "V"
    return f"{math.degrees(math.atan2(dy, dx)) % 180:.0f}deg"


def _fmt_pt(p) -> str:
    return f"{p[0]:.0f},{p[1]:.0f}"


def _room_name(r: Room) -> str:
    return f"{r.id}({r.label})" if r.label else r.id


def _bodies(scene: Scene) -> dict:
    """Wall id -> slightly buffered body polygon (joins are body overlaps,
    not shared endpoints, so all connectivity questions use these)."""
    return {w.id: wall_polygon(w).buffer(2 * TOL) for w in scene.walls}


def _touching(scene: Scene, wall, point, bodies=None) -> list[str]:
    """Walls joined to ``point`` (excluding ``wall`` itself): body covers
    the point, or lies within the mate's half-thickness of it — the same
    reach the geometry layer uses to close corner notches."""
    bodies = bodies or _bodies(scene)
    p = SPoint(point)
    return [
        wid for wid, poly in bodies.items()
        if wid != wall.id
        and poly.distance(p) <= scene.get(wid).thickness / 2 + 2 * TOL
    ]


def _wall_sides(scene: Scene, wall, room_list: list[Room]) -> list[str]:
    """Rooms (or EXT) flanking a wall, one entry per side."""
    nx, ny = wall.normal
    h = wall.thickness / 2 + SIDE_PROBE
    out = []
    for sign in (1, -1):
        probe = wall_polygon(wall).buffer(0)
        # shift a copy of the wall body sideways to sample one side
        from shapely import affinity

        shifted = affinity.translate(probe, xoff=sign * nx * h, yoff=sign * ny * h)
        touched = [r for r in room_list if r.polygon.intersects(shifted)]
        out.append(_room_name(touched[0]) if touched else EXTERIOR)
    return out


# ---------------------------------------------------------------------------
# Tables (the ?walls / ?joints / ?rooms / ?graph answers).


def walls_table(scene: Scene) -> str:
    if not scene.walls:
        return "no walls"
    lines = [f"walls ({len(scene.walls)}):"]
    for w in scene.walls:
        ops = [o.id for o in scene.openings_on(w.id)]
        lines.append(
            f"  {w.id} {_fmt_pt(w.start)} -> {_fmt_pt(w.end)}  "
            f"len {w.length:.0f} t{w.thickness:.0f} {_align(w)}"
            + (f"  openings: {','.join(ops)}" if ops else "")
        )
    dangling = _free_ends(scene)
    if dangling:
        lines.append("free ends (connect these to close loops): "
                     + "; ".join(dangling))
    return "\n".join(lines)


def _free_ends(scene: Scene) -> list[str]:
    bodies = _bodies(scene)
    out = []
    for w in scene.walls:
        for end in ("start", "end"):
            if not _touching(scene, w, getattr(w, end), bodies):
                out.append(f"{w.id}.{end} @{_fmt_pt(getattr(w, end))}")
    return out


def wall_detail(scene: Scene, wall_id: str) -> str:
    w = scene.get(wall_id)
    room_list = rooms(scene)
    lines = [
        f"{w.id} {_fmt_pt(w.start)} -> {_fmt_pt(w.end)}  "
        f"len {w.length:.0f} t{w.thickness:.0f} {_align(w)}"
    ]
    bodies = _bodies(scene)
    for end in ("start", "end"):
        mates = _touching(scene, w, getattr(w, end), bodies)
        names = ", ".join(mates) or "free end"
        lines.append(f"  {end} @{_fmt_pt(getattr(w, end))}: {names}")
    ops = scene.openings_on(w.id)
    for o in ops:
        kind = "door" if isinstance(o, Door) else "window"
        lines.append(f"  {o.id} {kind} @{o.offset:.0f} w{o.width:.0f}")
    if not ops:
        lines.append("  no openings")
    a, b = _wall_sides(scene, w, room_list)
    lines.append(f"  separates: {a} | {b}")
    return "\n".join(lines)


def joints_table(scene: Scene) -> str:
    """Junctions where wall bodies overlap, grouped by location, plus the
    wall adjacency graph.  Catches T-joints mid-wall, not just shared
    endpoints."""
    if not scene.walls:
        return "no joints (no walls)"
    bodies = _bodies(scene)
    spots: dict[tuple[float, float], set[str]] = {}
    order = [w.id for w in scene.walls]
    for i, wa in enumerate(order):
        for wb in order[i + 1:]:
            hit = bodies[wa].intersection(bodies[wb])
            if hit.is_empty:
                continue
            c = hit.centroid
            key = (round(c.x / 50) * 50, round(c.y / 50) * 50)
            spots.setdefault(key, set()).update((wa, wb))
    lines = [f"junctions ({len(spots)}):"]
    for (x, y), ws in sorted(spots.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        kind = {2: "corner/T", 3: "T", 4: "cross"}.get(
            len(ws), f"{len(ws)}-way")
        lines.append(f"  @{x:.0f},{y:.0f}: {','.join(sorted(ws))} ({kind})")
    lines.append("wall graph (wall: walls it touches):")
    for wa in order:
        mates = sorted(
            wb for wb in order
            if wb != wa and bodies[wa].intersects(bodies[wb])
        )
        lines.append(f"  {wa}: {','.join(mates) if mates else '-'}")
    dangling = _free_ends(scene)
    if dangling:
        lines.append("free ends: " + "; ".join(dangling))
    return "\n".join(lines)


def rooms_table(scene: Scene) -> str:
    room_list = rooms(scene)
    if not room_list:
        return "no enclosed rooms"
    lines = [f"rooms ({len(room_list)}):"]
    for r in room_list:
        b = r.polygon.bounds
        w, h = b[2] - b[0], b[3] - b[1]
        aspect = max(w, h) / min(w, h) if min(w, h) else 0
        lines.append(
            f"  {r.id} {r.label or '(unlabelled)':<16} {r.area_m2:6.2f} m2  "
            f"bbox {w:.0f}x{h:.0f}  aspect {aspect:.2f}"
        )
    return "\n".join(lines)


def room_detail(scene: Scene, room_ref: str) -> str:
    room_list = rooms(scene)
    ref = room_ref.strip().lower()
    match = next(
        (r for r in room_list
         if r.id.lower() == ref or (r.label and ref in r.label.lower())),
        None,
    )
    if match is None:
        return (f"no room matching {room_ref!r}; rooms: "
                + ", ".join(_room_name(r) for r in room_list))
    conns = connections(scene, room_list)
    graph = AccessGraph.build(scene, room_list, conns)
    depths = graph.depths_from(EXTERIOR)
    b = match.polygon.bounds
    corners = len(match.polygon.exterior.coords) - 1
    lo, hi = _mrr_sides(match)
    rect = match.polygon.area / (lo * hi) if lo * hi else 0
    lines = [
        f"{_room_name(match)}  type {room_type(match.label) or '?'}",
        f"  area {match.area_m2:.2f} m2  bbox {b[0]:.0f},{b[1]:.0f} -> "
        f"{b[2]:.0f},{b[3]:.0f}",
        f"  shape: {corners} corners, rectangularity {rect:.2f}"
        + (" (rectangle)" if corners == 4 else ""),
    ]
    doors = [c for c in conns
             if c["kind"] == "door" and match.id in c["rooms"]]
    wins = [c for c in conns
            if c["kind"] == "window" and match.id in c["rooms"]]
    names = {r.id: _room_name(r) for r in room_list}
    if doors:
        for c in doors:
            other = [x for x in c["rooms"] if x != match.id][0]
            lines.append(f"  door {c['opening']} -> {names.get(other, other)}")
    else:
        lines.append("  NO DOORS - room is sealed")
    lines.append(f"  windows: {', '.join(c['opening'] for c in wins) or 'none'}")
    d = depths.get(match.id)
    lines.append(
        f"  depth from outside: {d if d is not None else 'UNREACHABLE'}"
    )
    return "\n".join(lines)


def room_graph(scene: Scene) -> str:
    room_list = rooms(scene)
    if not room_list:
        return "no enclosed rooms"
    conns = connections(scene, room_list)
    graph = AccessGraph.build(scene, room_list, conns)
    depths = graph.depths_from(EXTERIOR)
    names = {r.id: _room_name(r) for r in room_list}
    names[EXTERIOR] = EXTERIOR
    lines = ["room graph (door connections):"]
    for a, b, d in graph.edges:
        lines.append(f"  {names.get(a, a)} <-{d}-> {names.get(b, b)}")
    lines.append("depth from outside (doors to cross):")
    for r in room_list:
        d = depths.get(r.id)
        lines.append(
            f"  {names[r.id]}: {d if d is not None else 'UNREACHABLE'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatcher.

HELP = """queries:
  ?walls          all walls: endpoints, length, thickness, alignment, openings
  ?wall W3        one wall: joints, openings, which rooms it separates
  ?joints         joint graph: corners/T/cross, free ends, wall adjacency
  ?rooms          all rooms: area, bbox, aspect
  ?room R2        one room (id or label): shape, doors, windows, depth
  ?graph          room connectivity graph + depth from outside
  ?help           this list"""


def is_query(text: str) -> bool:
    stripped = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return bool(stripped) and all(l.startswith("?") for l in stripped)


def answer(scene: Scene, text: str) -> str:
    """Answer a block of ``?`` query lines against the scene."""
    out = []
    for line in text.strip().splitlines():
        q = line.strip().lstrip("?").strip()
        if not q:
            continue
        parts = q.split(None, 1)
        cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        try:
            if cmd == "walls":
                out.append(walls_table(scene))
            elif cmd == "wall" and arg:
                out.append(wall_detail(scene, arg.upper()))
            elif cmd == "joints":
                out.append(joints_table(scene))
            elif cmd == "rooms":
                out.append(rooms_table(scene))
            elif cmd == "room" and arg:
                out.append(room_detail(scene, arg))
            elif cmd == "graph":
                out.append(room_graph(scene))
            else:
                out.append(HELP)
        except Exception as err:  # bad id etc. — answer, don't crash the loop
            out.append(f"query error ({line.strip()}): {err}")
    return "\n\n".join(out) if out else HELP
