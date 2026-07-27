"""Programmatically built sample DXF documents.

Built with the step-2 tooling layer (Sketch + architectural verbs), so the
sample doubles as an end-to-end exercise of the exact API that LLM agents
will drive in step 4.
"""

from __future__ import annotations

from ezdxf.document import Drawing

from draftsmith.arch import add_door, add_room_label, add_wall, add_window
from draftsmith.toolkit import Sketch

# All coordinates in millimetres.
WALL_THICKNESS = 230
INNER_WALL_THICKNESS = 120

LAYERS = {
    "WALLS": 7,
    "DOORS": 30,
    "WINDOWS": 5,
    "TEXT": 7,
    "DIMS": 8,
}


def build_sample_sketch() -> Sketch:
    """An 8m x 5m two-room unit: walls, a door with swing, windows, labels
    and one linear dimension."""
    sk = Sketch()
    for name, color in LAYERS.items():
        sk.add_layer(name, color=color)

    t = WALL_THICKNESS
    half = t / 2
    # Outer walls on centerlines; south/north run full width, west/east butt
    # against them so corners join cleanly.
    windows = [(1500, 2700), (5800, 7000)]
    add_wall(
        sk,
        (0, half),
        (8000, half),
        thickness=t,
        openings=[{"offset": x1, "width": x2 - x1} for x1, x2 in windows],
    )
    add_wall(sk, (0, 5000 - half), (8000, 5000 - half), thickness=t)
    add_wall(sk, (half, t), (half, 5000 - t), thickness=t)
    add_wall(sk, (8000 - half, t), (8000 - half, 5000 - t), thickness=t)

    # Interior wall at x=5000 with a 900mm door opening at its south end.
    add_wall(
        sk,
        (5000, t),
        (5000, 5000 - t),
        thickness=INNER_WALL_THICKNESS,
        openings=[{"offset": 0, "width": 900}],
    )

    # Door: hinged at the top of the opening, closed leaf pointing south,
    # swinging open into the bedroom.
    add_door(sk, (5000, t + 900), width=900, angle=270, swing="left")

    # Windows in the south wall.
    for x1, x2 in windows:
        add_window(sk, (x1, half), (x2, half), thickness=t)

    add_room_label(sk, "LIVING ROOM", (2500, 2500))
    add_room_label(sk, "BEDROOM", (6450, 2500))

    # Overall width dimension below the plan.
    sk.add_aligned_dim((0, 0), (8000, 0), offset=-700, layer="DIMS")

    return sk


def build_sample_floorplan() -> Drawing:
    return build_sample_sketch().doc


def build_sample_scene():
    """The same two-room unit as a semantic Scene (walls as centerlines,
    openings hosted on walls). Rooms and adjacency are derived, not stored."""
    from draftsmith.scene import Scene

    sc = Scene()
    t = WALL_THICKNESS
    half = t / 2
    sc.add_wall((0, half), (8000, half), t)                # W1 south
    sc.add_wall((0, 5000 - half), (8000, 5000 - half), t)  # W2 north
    sc.add_wall((half, t), (half, 5000 - t), t)            # W3 west
    sc.add_wall((8000 - half, t), (8000 - half, 5000 - t), t)  # W4 east
    sc.add_wall((5000, t), (5000, 5000 - t), INNER_WALL_THICKNESS)  # W5 interior

    # Hinged at the top of the opening, swinging open into the bedroom.
    sc.add_door("W5", 0, 900, hinge="far", swing="left")
    sc.add_window("W1", 1500, 1200)
    sc.add_window("W1", 5800, 1200)
    sc.add_label("LIVING ROOM", (2500, 2500))
    sc.add_label("BEDROOM", (6450, 2500))
    sc.add_dim((0, 0), (8000, 0), offset=-700)
    return sc
