"""M4 evaluation: deterministic scoring of a floorplan scene.

Three layers, reported as a (correctness, compliance, soundness) tuple —
never collapsed to a single number (decision: docs/research_notes.md
RN-5, design: docs/evaluation.md):

- **feasibility** (brief-independent hard checks): every room reachable
  from outside, door economy, opening/junction clearance, code minimums
  (areas, widths, ventilation).  Sources for thresholds: NBC India /
  IRC / Neufert — see ``docs/evaluation.md``.
- **compliance** (needs a :class:`Brief`): required rooms, area targets,
  adjacency/connection demands.
- **soundness** (graded, brief-independent): space-syntax depth and
  integration with a privacy-gradient check, proportion and compactness,
  circulation share, style-usage diversity.

Everything is derived from the scene graph via :mod:`draftsmith.geometry`;
nothing here mutates the scene.  The LLM/VLM judge axis (beauty, novelty,
creativity) is *not* here — its rubric lives in docs/evaluation.md and
its transport in a future runner; this module is the part that must be
exactly reproducible.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from draftsmith.geometry import EXTERIOR, Room, connections, rooms
from draftsmith.scene import Door, Scene, Window

# ---------------------------------------------------------------------------
# Room typing: free-text labels -> canonical types the threshold tables key on.

ROOM_TYPES: dict[str, tuple[str, ...]] = {
    # canonical type -> label substrings (lowercase) that map to it
    "bedroom": ("bed", "master", "kids", "guest room"),
    "living": ("living", "lounge", "drawing", "family"),
    "dining": ("dining",),
    "kitchen": ("kitchen", "kitchenette", "pantry"),
    "bath": ("bath", "washroom", "shower"),
    "wc": ("wc", "toilet", "powder"),
    "circulation": ("passage", "corridor", "lobby", "foyer", "hallway"),
    "utility": ("utility", "laundry", "store", "storage"),
    "balcony": ("balcony", "verandah", "veranda", "terrace", "deck", "sitout",
                "sit-out", "porch"),
    "study": ("study", "office", "den"),
    "stair": ("stair",),
}

# Types where people dwell — these get area/width/ventilation demands.
HABITABLE = {"bedroom", "living", "dining", "kitchen", "study"}


def room_type(label: str | None) -> str | None:
    """Canonical type for a room label, or None if unrecognised."""
    if not label:
        return None
    text = label.lower()
    for typ, keys in ROOM_TYPES.items():
        if any(k in text for k in keys):
            return typ
    return None


# ---------------------------------------------------------------------------
# Threshold tables.  Values and sources are catalogued in docs/evaluation.md;
# keep this the only place numbers live.

@dataclass(frozen=True)
class RoomStandard:
    min_area_m2: float          # minimum floor area
    min_side_mm: float          # minimum horizontal dimension


# NBC India 2016 Part 3 / Model Building Bye-Laws 2016 ch.4, with IRC and
# Neufert cross-checks (sources + caveats: docs/evaluation.md §feasibility).
ROOM_STANDARDS: dict[str, RoomStandard] = {
    "bedroom": RoomStandard(7.5, 2100),   # NBC second habitable room
    "living": RoomStandard(9.5, 2400),    # NBC first habitable room
    "dining": RoomStandard(6.0, 2100),    # benchmark-defined (NBC has no solo)
    "kitchen": RoomStandard(5.0, 1800),   # NBC kitchen w/ separate dining
    "bath": RoomStandard(1.8, 1100),      # NBC bath
    "wc": RoomStandard(1.1, 900),         # NBC WC
    "circulation": RoomStandard(0.0, 900),  # MBBL corridor width floor
    "study": RoomStandard(6.5, 2100),     # IRC habitable 70 ft2
}

# Door width minimums, mm.  Entrance/habitable: NBC 900; bath/WC: NBC 750;
# generic interior 800 is benchmark-defined between IRC 813mm clear and
# NBC's 900 leaf (docs/evaluation.md).
DOOR_MIN_WIDTH = {"entrance": 900.0, "interior": 800.0, "bath": 750.0}

# An opening edge closer than this to a wall junction is bad practice
# (frame/trimmer conflict) — RN-4 item 3.  Benchmark-defined.
JUNCTION_CLEARANCE_MM = 100.0

# Aspect-ratio scoring for habitable rooms: full marks to 1.5, decaying to
# zero at 2.5.  Code-anchored (NBC min-width clauses imply <=1.65 at
# minimum size; IRC implies <=1.43) but the band itself is benchmark-defined.
ASPECT_FULL = 1.5
ASPECT_ZERO = 2.5

# Rooms squarer than this fraction of their min rotated rectangle read as
# clean rectilinear shapes (floorplan-analysis convention).
RECTANGULARITY_OK = 0.85

# Circulation share of interior area: 5-15% full marks, industry practice
# puts multi-unit circulation at 11-15% (<=20% max); within-unit target is
# a rule of thumb — see docs/evaluation.md.
CIRCULATION_BAND = (0.05, 0.15)

# MBBL: openable window+ventilator area >= 1/10 of floor area for habitable
# rooms.  Plans are 2D, so glazing area assumes a standard window height.
GLAZING_MIN_RATIO = 0.10
WINDOW_HEIGHT_MM = 1200.0


# ---------------------------------------------------------------------------
# Access graph (rooms + EXT as nodes, doors as edges).


@dataclass
class AccessGraph:
    nodes: list[str]                       # room ids + EXTERIOR
    edges: list[tuple[str, str, str]]      # (room, room, door id)
    adj: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, scene: Scene, room_list: list[Room],
              conns: list[dict]) -> "AccessGraph":
        nodes = [r.id for r in room_list] + [EXTERIOR]
        edges = [
            (c["rooms"][0], c["rooms"][1], c["opening"])
            for c in conns
            if c["kind"] == "door" and c["rooms"][0] != c["rooms"][1]
        ]
        g = cls(nodes, edges)
        g.adj = {n: set() for n in nodes}
        for a, b, _ in edges:
            if a in g.adj and b in g.adj:
                g.adj[a].add(b)
                g.adj[b].add(a)
        return g

    def depths_from(self, root: str,
                    blocked: Iterable[str] = ()) -> dict[str, int]:
        """BFS shortest-path depth from ``root``; ``blocked`` nodes are
        impassable (but still get a depth if directly adjacent)."""
        blocked = set(blocked) - {root}
        depth = {root: 0}
        queue = deque([root])
        while queue:
            cur = queue.popleft()
            if cur in blocked:
                continue
            for nxt in self.adj.get(cur, ()):
                if nxt not in depth:
                    depth[nxt] = depth[cur] + 1
                    queue.append(nxt)
        return depth

    def cycles(self) -> int:
        """Independent cycles (rings) in the graph: E - V + components."""
        seen: set[str] = set()
        comps = 0
        for n in self.nodes:
            if n in seen:
                continue
            comps += 1
            queue = deque([n])
            seen.add(n)
            while queue:
                cur = queue.popleft()
                for nxt in self.adj.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
        return len(self.edges) - len(self.nodes) + comps


def _mean_depth(depths: dict[str, int], root: str) -> float | None:
    others = [d for n, d in depths.items() if n != root]
    return sum(others) / len(others) if others else None


def relative_asymmetry(md: float, k: int) -> float | None:
    """Hillier & Hanson RA = 2(MD-1)/(k-2); k = node count incl. root."""
    if k <= 2:
        return None
    return 2.0 * (md - 1.0) / (k - 2.0)


def d_value(k: int) -> float | None:
    """Diamond-value normalisation for RRA (Hillier & Hanson, 1984)."""
    if k <= 3:
        return None
    return (2.0 * (k * (math.log2((k + 2.0) / 3.0) - 1.0) + 1.0)
            / ((k - 1.0) * (k - 2.0)))


# ---------------------------------------------------------------------------
# Result containers.


@dataclass
class Finding:
    """One scored observation.  ``score`` in [0,1]; hard failures are 0."""
    metric: str
    score: float
    value: object = None
    detail: str = ""

    def to_dict(self) -> dict:
        d = {"metric": self.metric, "score": round(self.score, 3)}
        if self.value is not None:
            d["value"] = self.value
        if self.detail:
            d["detail"] = self.detail
        return d


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _band_score(x: float, lo: float, hi: float, falloff: float) -> float:
    """1.0 inside [lo, hi], linear falloff to 0 over ``falloff`` outside."""
    if lo <= x <= hi:
        return 1.0
    gap = (lo - x) if x < lo else (x - hi)
    return _clamp(1.0 - gap / falloff)


# ---------------------------------------------------------------------------
# Layer 1 — feasibility.


def feasibility_findings(scene: Scene, room_list: list[Room],
                         conns: list[dict], graph: AccessGraph) -> list[Finding]:
    out: list[Finding] = []
    typed = {r.id: room_type(r.label) for r in room_list}
    interior = [r for r in room_list if typed[r.id] != "balcony"]

    # -- reachability: every room reachable from outside (RN-4 item 2)
    depths = graph.depths_from(EXTERIOR)
    unreachable = [r.id for r in room_list if r.id not in depths]
    out.append(Finding(
        "reachability",
        0.0 if unreachable else 1.0,
        {"unreachable": unreachable},
        "every room must be reachable from EXT through doors"
        if unreachable else "",
    ))

    # -- an entrance exists at all
    has_entrance = any(EXTERIOR in (a, b) for a, b, _ in graph.edges)
    out.append(Finding("entrance", 1.0 if has_entrance else 0.0,
                       has_entrance,
                       "" if has_entrance else "no door connects to EXT"))

    # -- common bath/wc not trapped behind a bedroom (RN-4 item 2)
    baths = [r.id for r in room_list if typed[r.id] in ("bath", "wc")]
    if baths and not unreachable and has_entrance:
        bedrooms = {r.id for r in room_list if typed[r.id] == "bedroom"}
        open_depths = graph.depths_from(EXTERIOR, blocked=bedrooms)
        common = [b for b in baths if b in open_depths]
        out.append(Finding(
            "common_bath_access",
            1.0 if common else 0.0,
            {"reachable_without_bedroom": common},
            "" if common else
            "no bath/wc is reachable without passing through a bedroom",
        ))

    # -- WC/bath must not open into the kitchen (NBC prohibition)
    kitchens = {r.id for r in room_list if typed[r.id] == "kitchen"}
    sanitary = {r.id for r in room_list if typed[r.id] in ("bath", "wc")}
    bad_pairs = [
        d for a, b, d in graph.edges
        if {a, b} & kitchens and {a, b} & sanitary
    ]
    out.append(Finding(
        "wc_off_kitchen", 0.0 if bad_pairs else 1.0, {"doors": bad_pairs},
        "bath/WC door opens directly into the kitchen" if bad_pairs else "",
    ))

    # -- door economy (RN-4 item 4)
    pair_count: dict[frozenset, int] = {}
    for a, b, _ in graph.edges:
        pair_count[frozenset((a, b))] = pair_count.get(frozenset((a, b)), 0) + 1
    dupes = sum(n - 1 for n in pair_count.values() if n > 1)
    n_doors = len(graph.edges)
    n_rooms = max(len(room_list), 1)
    ratio = n_doors / n_rooms
    out.append(Finding(
        "door_economy",
        _clamp(1.0 - 0.5 * dupes) * _band_score(ratio, 0.6, 1.3, 0.7),
        {"doors": n_doors, "rooms": len(room_list), "duplicate_pairs": dupes},
        "duplicate doors between the same room pair" if dupes else "",
    ))

    # -- opening vs junction clearance (RN-4 item 3)
    tight = _junction_conflicts(scene)
    out.append(Finding(
        "junction_clearance",
        _clamp(1.0 - 0.25 * len(tight)),
        {"openings": tight},
        f"opening edge within {JUNCTION_CLEARANCE_MM:.0f}mm of a wall "
        "junction" if tight else "",
    ))

    # -- code minimums per typed room
    small: list[str] = []
    narrow: list[str] = []
    for r in room_list:
        std = ROOM_STANDARDS.get(typed[r.id] or "")
        if std is None:
            continue
        if std.min_area_m2 and r.area_m2 < std.min_area_m2:
            small.append(f"{r.id}({r.label}) {r.area_m2:.1f}<{std.min_area_m2}m2")
        w = _min_side_mm(r)
        if std.min_side_mm and w < std.min_side_mm:
            narrow.append(f"{r.id}({r.label}) {w:.0f}<{std.min_side_mm:.0f}mm")
    checked = sum(1 for r in room_list if (typed[r.id] or "") in ROOM_STANDARDS)
    violations = len(small) + len(narrow)
    out.append(Finding(
        "room_minimums",
        _clamp(1.0 - violations / max(checked, 1)),
        {"under_area": small, "under_width": narrow},
        "rooms below NBC/Neufert minimums" if violations else "",
    ))

    # -- door widths
    thin: list[str] = []
    for a, b, did in graph.edges:
        door = scene.get(did)
        if EXTERIOR in (a, b):
            need = DOOR_MIN_WIDTH["entrance"]
        elif any(typed.get(x) in ("bath", "wc") for x in (a, b)):
            need = DOOR_MIN_WIDTH["bath"]
        else:
            need = DOOR_MIN_WIDTH["interior"]
        if door.width < need:
            thin.append(f"{did} {door.width:.0f}<{need:.0f}mm")
    out.append(Finding(
        "door_widths", _clamp(1.0 - 0.34 * len(thin)), {"under": thin},
        "doors below minimum clear width" if thin else "",
    ))

    # -- bedroom privacy: no bedroom only reachable through another bedroom
    bedrooms = {r.id for r in room_list if typed[r.id] == "bedroom"}
    if len(bedrooms) > 1 and not unreachable and has_entrance:
        trapped = []
        for b in bedrooms:
            reach = graph.depths_from(EXTERIOR, blocked=bedrooms - {b})
            if b not in reach:
                trapped.append(b)
        out.append(Finding(
            "bedroom_privacy", 0.0 if trapped else 1.0, {"through": trapped},
            "bedroom only accessible through another bedroom"
            if trapped else "",
        ))

    # -- ventilation: habitable rooms need an exterior opening
    ext_rooms = {
        c["rooms"][0] if c["rooms"][1] == EXTERIOR else c["rooms"][1]
        for c in conns if EXTERIOR in c["rooms"]
    }
    dark = [
        f"{r.id}({r.label})" for r in interior
        if typed[r.id] in HABITABLE and r.id not in ext_rooms
    ]
    out.append(Finding(
        "habitable_ventilation", _clamp(1.0 - 0.5 * len(dark)), {"dark": dark},
        "habitable rooms with no window/exterior door" if dark else "",
    ))

    # -- glazing ratio: MBBL 1/10 of floor area, with an assumed standard
    # window height (plans are 2D; assumption documented in the tables)
    ratios: dict[str, float] = {}
    for r in interior:
        if typed[r.id] not in HABITABLE:
            continue
        w_mm = sum(
            scene.get(c["opening"]).width
            for c in conns
            if c["kind"] == "window" and r.id in c["rooms"]
            and EXTERIOR in c["rooms"]
        )
        ratios[f"{r.id}({r.label})"] = round(
            (w_mm * WINDOW_HEIGHT_MM) / (r.area_m2 * 1e6), 3
        ) if r.area_m2 else 0.0
    if ratios:
        out.append(Finding(
            "glazing_ratio",
            _mean([_clamp(v / GLAZING_MIN_RATIO) for v in ratios.values()]),
            ratios,
            f"window area (assumed {WINDOW_HEIGHT_MM:.0f}mm high) should be "
            f">={GLAZING_MIN_RATIO:.0%} of floor area",
        ))
    return out


def _mrr_sides(room: Room) -> tuple[float, float]:
    """(short, long) side of the minimum rotated bounding rectangle.
    numpy warnings suppressed: shapely's oriented_envelope divides by zero
    on axis-aligned inputs but still returns the right envelope."""
    import numpy as np

    with np.errstate(divide="ignore", invalid="ignore"):
        mrr = room.polygon.minimum_rotated_rectangle
    xs, ys = mrr.exterior.coords.xy
    a = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
    b = math.hypot(xs[2] - xs[1], ys[2] - ys[1])
    lo, hi = sorted((a, b))
    return lo, hi


def _min_side_mm(room: Room) -> float:
    return _mrr_sides(room)[0]


def _junction_conflicts(scene: Scene) -> list[str]:
    """Openings whose edge sits within JUNCTION_CLEARANCE_MM of a point
    where another wall meets the host wall (endpoint or T-joint)."""
    hits: list[str] = []
    for opening in scene:
        if not isinstance(opening, (Door, Window)):
            continue
        wall = scene.get(opening.wall)
        length = wall.length
        stations: list[float] = []
        for other in scene.walls:
            if other.id == wall.id:
                continue
            for end in (other.start, other.end):
                t = _project_mm(wall, end)
                if t is None:
                    continue
                stations.append(t)
        # wall's own endpoints joined to other walls count too
        for t, p in ((0.0, wall.start), (length, wall.end)):
            if scene.walls_at(p, exclude=wall.id):
                stations.append(t)
        lo = opening.offset - JUNCTION_CLEARANCE_MM
        hi = opening.end_offset + JUNCTION_CLEARANCE_MM
        if any(lo < s < hi for s in stations):
            hits.append(opening.id)
    return hits


def _project_mm(wall, point) -> float | None:
    """Arc-length of ``point`` projected onto the wall centerline, if the
    point lies on the wall body (within half thickness); else None."""
    ux, uy = wall.direction
    dx, dy = point[0] - wall.start[0], point[1] - wall.start[1]
    t = dx * ux + dy * uy
    if t < -1.0 or t > wall.length + 1.0:
        return None
    off = abs(-dx * uy + dy * ux)
    return t if off <= wall.thickness / 2 + 1.0 else None


# ---------------------------------------------------------------------------
# Layer 2 — brief compliance.


@dataclass
class Brief:
    """Machine-readable demands extracted from a natural-language brief.

    ``rooms``: canonical type or label substring -> required count (exact)
    ``areas``: room selector -> (min_m2, max_m2); None = unbounded
    ``adjacent``: pairs of selectors that must share a door
    ``total_area``: (min_m2, max_m2) for summed interior area, optional
    """
    rooms: dict[str, int] = field(default_factory=dict)
    areas: dict[str, tuple[float | None, float | None]] = field(
        default_factory=dict)
    adjacent: list[tuple[str, str]] = field(default_factory=list)
    total_area: tuple[float | None, float | None] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Brief":
        return cls(
            rooms={k: int(v) for k, v in data.get("rooms", {}).items()},
            areas={k: (v[0], v[1]) for k, v in data.get("areas", {}).items()},
            adjacent=[tuple(p) for p in data.get("adjacent", [])],
            total_area=tuple(data["total_area"]) if data.get("total_area")
            else None,
        )


def _select(selector: str, room_list: list[Room]) -> list[Room]:
    """Rooms matching a selector: canonical type name, else label substring."""
    sel = selector.lower()
    if sel in ROOM_TYPES:
        return [r for r in room_list if room_type(r.label) == sel]
    return [r for r in room_list if r.label and sel in r.label.lower()]


def compliance_findings(brief: Brief, room_list: list[Room],
                        graph: AccessGraph) -> list[Finding]:
    out: list[Finding] = []
    for selector, want in brief.rooms.items():
        got = len(_select(selector, room_list))
        out.append(Finding(
            f"rooms:{selector}", 1.0 if got == want else 0.0,
            {"want": want, "got": got},
        ))
    for selector, (lo, hi) in brief.areas.items():
        matches = _select(selector, room_list)
        if not matches:
            out.append(Finding(f"area:{selector}", 0.0, "no matching room"))
            continue
        scores = [
            _band_score(r.area_m2, lo or 0.0, hi if hi is not None else 1e9,
                        falloff=max((lo or r.area_m2) * 0.5, 1.0))
            for r in matches
        ]
        out.append(Finding(
            f"area:{selector}", sum(scores) / len(scores),
            {r.id: round(r.area_m2, 2) for r in matches},
        ))
    for sel_a, sel_b in brief.adjacent:
        ids_a = {r.id for r in _select(sel_a, room_list)}
        ids_b = {r.id for r in _select(sel_b, room_list)}
        ok = any(
            (a in ids_a and b in ids_b) or (a in ids_b and b in ids_a)
            for a, b, _ in graph.edges
        )
        out.append(Finding(f"adjacent:{sel_a}<->{sel_b}",
                           1.0 if ok else 0.0, ok))
    if brief.total_area:
        lo, hi = brief.total_area
        total = sum(r.area_m2 for r in room_list
                    if room_type(r.label) != "balcony")
        out.append(Finding(
            "total_area",
            _band_score(total, lo or 0.0, hi if hi is not None else 1e9,
                        falloff=max((lo or total) * 0.25, 1.0)),
            round(total, 1),
        ))
    return out


# ---------------------------------------------------------------------------
# Layer 3 — architectural soundness (graded).


def soundness_findings(scene: Scene, room_list: list[Room],
                       conns: list[dict], graph: AccessGraph) -> list[Finding]:
    out: list[Finding] = []
    typed = {r.id: room_type(r.label) for r in room_list}
    depths = graph.depths_from(EXTERIOR)
    k = len(graph.nodes)

    # -- space syntax: mean depth + integration from the entrance
    md = _mean_depth(depths, EXTERIOR) if len(depths) == k else None
    if md is not None:
        ra = relative_asymmetry(md, k)
        dk = d_value(k)
        rra = (ra / dk) if (ra is not None and dk) else None
        out.append(Finding(
            "syntax_depth", _band_score(md, 1.5, 3.0, 2.0),
            {"mean_depth": round(md, 2),
             "RA": round(ra, 3) if ra is not None else None,
             "RRA": round(rra, 3) if rra is not None else None},
            "very deep (labyrinthine) or very shallow (no hierarchy) plans "
            "score lower",
        ))

    # -- privacy genotype (Hanson 1998; Alexander #127): canonical depth
    # order living/dining < kitchen/study < bedroom < bath/wc, scored as
    # the fraction of type-pair inequalities the plan satisfies.
    GENOTYPE_RANK = {"living": 0, "dining": 0, "kitchen": 1, "study": 1,
                     "bedroom": 2, "bath": 3, "wc": 3}
    mean_depth_by_type: dict[str, float] = {}
    for typ in set(GENOTYPE_RANK):
        ds = [depths[r.id] for r in room_list
              if typed[r.id] == typ and r.id in depths]
        if ds:
            mean_depth_by_type[typ] = sum(ds) / len(ds)
    pairs = [
        (a, b) for a in mean_depth_by_type for b in mean_depth_by_type
        if GENOTYPE_RANK[a] < GENOTYPE_RANK[b]
    ]
    if pairs:
        pts = sum(
            1.0 if mean_depth_by_type[a] < mean_depth_by_type[b]
            else (0.5 if mean_depth_by_type[a] == mean_depth_by_type[b]
                  else 0.0)
            for a, b in pairs
        )
        out.append(Finding(
            "privacy_genotype", pts / len(pairs),
            {t: round(d, 2) for t, d in sorted(mean_depth_by_type.items())},
            "canonical order: living < kitchen < bedroom < bath by depth "
            "from the entrance",
        ))

    # -- distributedness: space link ratio (E+1)/V; 1.0 = pure tree,
    # >1 = circulation rings (Hillier & Hanson)
    e, v = len(graph.edges), len(graph.nodes)
    slr = (e + 1) / v if v else 0.0
    rings = graph.cycles()
    out.append(Finding(
        "ringiness", _clamp(0.6 + 0.4 * min(rings, 1)),
        {"rings": rings, "space_link_ratio": round(slr, 2)},
        "a pure access tree has no circulation loop" if rings == 0 else "",
    ))

    # -- proportion: habitable aspect ratios, full marks to 1:1.5,
    # zero at 1:2.5 (code-anchored band, see threshold table)
    aspects = {}
    scores = []
    for r in room_list:
        if typed[r.id] not in HABITABLE:
            continue
        a = _aspect(r)
        aspects[f"{r.id}({r.label})"] = round(a, 2)
        scores.append(
            _band_score(a, 1.0, ASPECT_FULL, ASPECT_ZERO - ASPECT_FULL))
    if scores:
        out.append(Finding("proportion", _mean(scores), aspects))

    # -- rectangularity: room area / min-rotated-rectangle area.  >=0.85
    # reads as clean rectilinear; lower may be sloppy OR deliberately
    # carved — the judge axis arbitrates, this just reports and nudges.
    rects = []
    for r in room_list:
        if typed[r.id] in (None, "balcony"):
            continue
        lo, hi = _mrr_sides(r)
        if lo * hi:
            rects.append(r.polygon.area / (lo * hi))
    if rects:
        out.append(Finding(
            "rectangularity",
            _mean([_clamp(x / RECTANGULARITY_OK) for x in rects]),
            round(_mean(rects), 3),
        ))

    # -- light on two sides (Alexander #159): habitable rooms with
    # exterior windows on >=2 differently-oriented walls
    orient: dict[str, set[int]] = {}
    for c in conns:
        if c["kind"] != "window" or EXTERIOR not in c["rooms"]:
            continue
        rid = c["rooms"][0] if c["rooms"][1] == EXTERIOR else c["rooms"][1]
        wall = scene.get(scene.get(c["opening"]).wall)
        ang = round(math.degrees(math.atan2(*wall.direction[::-1]))) % 180
        orient.setdefault(rid, set()).add(ang)
    lit = [
        1.0 if len(orient.get(r.id, ())) >= 2
        else (0.5 if orient.get(r.id) else 0.0)
        for r in room_list if typed[r.id] in HABITABLE
    ]
    if lit:
        out.append(Finding(
            "light_two_sides", _mean(lit),
            {"two_sided": sum(1 for x in lit if x == 1.0),
             "habitable": len(lit)},
            "rooms with daylight from two directions read better "
            "(Alexander #159)",
        ))

    # -- footprint articulation: perimeter²/(16·area), 1.0 for a square.
    # Modestly articulated outlines (L/T/U shapes) score best; both a
    # featureless box and a wildly jagged outline drift down.
    body_rooms = [r for r in room_list if typed[r.id] != "balcony"]
    if body_rooms:
        from shapely.ops import unary_union

        merged = unary_union([r.polygon.buffer(200) for r in body_rooms])
        art = (merged.length ** 2) / (16.0 * merged.area) if merged.area else 1.0
        out.append(Finding(
            "articulation", _band_score(art, 1.02, 1.6, 1.0),
            round(art, 3),
            "1.0 = perfect square footprint; higher = more shaped",
        ))

    # -- style diversity: entropy over door + window styles actually used
    styles = [
        (o.style or scene.styles.get(
            "door" if isinstance(o, Door) else "window") or "default")
        for o in scene if isinstance(o, (Door, Window))
    ]
    out.append(Finding("style_diversity", _entropy_score(styles),
                       {"used": sorted(set(styles))}))

    # -- circulation share
    total = sum(r.area_m2 for r in room_list if typed[r.id] != "balcony")
    circ = sum(r.area_m2 for r in room_list if typed[r.id] == "circulation")
    if total:
        share = circ / total
        out.append(Finding(
            "circulation_share",
            _band_score(share, *CIRCULATION_BAND, falloff=0.15),
            round(share, 3),
            "share of interior area spent on corridors/passages",
        ))
    return out


def _aspect(room: Room) -> float:
    lo, hi = _mrr_sides(room)
    return hi / lo if lo else float("inf")


def _entropy_score(items: list[str]) -> float:
    """Normalised Shannon entropy in [0,1]; one lone item scores 0.3
    (a single door can't be diverse, but shouldn't zero the plan)."""
    if not items:
        return 0.0
    if len(items) == 1:
        return 0.3
    counts: dict[str, int] = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    n = len(items)
    h = -sum((c / n) * math.log2(c / n) for c in counts.values())
    hmax = math.log2(min(len(items), 4))  # 4 = rough catalog size today
    return _clamp(h / hmax) if hmax else 0.0


# ---------------------------------------------------------------------------
# Report.


@dataclass
class Report:
    feasibility: list[Finding]
    compliance: list[Finding]
    soundness: list[Finding]

    @property
    def scores(self) -> tuple[float, float | None, float]:
        """(correctness, compliance, soundness), each in [0,1].
        Compliance is None when no brief was supplied."""
        return (
            _mean([f.score for f in self.feasibility]),
            _mean([f.score for f in self.compliance])
            if self.compliance else None,
            _mean([f.score for f in self.soundness]),
        )

    @property
    def hard_failures(self) -> list[Finding]:
        return [f for f in self.feasibility if f.score == 0.0]

    def to_dict(self) -> dict:
        c, b, s = self.scores
        return {
            "scores": {"correctness": round(c, 3),
                       "compliance": round(b, 3) if b is not None else None,
                       "soundness": round(s, 3)},
            "feasibility": [f.to_dict() for f in self.feasibility],
            "compliance": [f.to_dict() for f in self.compliance],
            "soundness": [f.to_dict() for f in self.soundness],
        }

    def render_text(self) -> str:
        c, b, s = self.scores
        lines = [
            "scores: correctness {:.2f} | compliance {} | soundness {:.2f}"
            .format(c, f"{b:.2f}" if b is not None else "n/a", s)
        ]
        for name, findings in (("feasibility", self.feasibility),
                               ("compliance", self.compliance),
                               ("soundness", self.soundness)):
            if not findings:
                continue
            lines.append(f"{name}:")
            for f in findings:
                mark = "x" if f.score == 0 else ("!" if f.score < 1 else "+")
                extra = f"  {f.detail}" if f.detail and f.score < 1 else ""
                lines.append(f"  {mark} {f.metric:<24} {f.score:4.2f}{extra}")
        return "\n".join(lines)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def evaluate(scene: Scene, brief: Brief | None = None) -> Report:
    """Score a scene; deterministic, engine-derived only."""
    room_list = rooms(scene)
    conns = connections(scene, room_list)
    graph = AccessGraph.build(scene, room_list, conns)
    return Report(
        feasibility=feasibility_findings(scene, room_list, conns, graph),
        compliance=compliance_findings(brief, room_list, graph)
        if brief else [],
        soundness=soundness_findings(scene, room_list, conns, graph),
    )
