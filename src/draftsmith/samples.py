"""Programmatically built sample DXF documents.

These serve two purposes: end-to-end fixtures for the renderer tests, and
a preview of the kind of geometry the step-2 tooling layer will expose to
LLM agents (walls, openings, symbols, annotation).
"""

from __future__ import annotations

import ezdxf
from ezdxf.document import Drawing

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


def build_sample_floorplan() -> Drawing:
    """An 8m x 5m two-room unit: walls, a door with swing, windows, labels
    and one linear dimension."""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    t = WALL_THICKNESS
    # Outer wall: two closed rectangles (outside face, inside face).
    msp.add_lwpolyline(
        [(0, 0), (8000, 0), (8000, 5000), (0, 5000)],
        close=True,
        dxfattribs={"layer": "WALLS"},
    )
    msp.add_lwpolyline(
        [(t, t), (8000 - t, t), (8000 - t, 5000 - t), (t, 5000 - t)],
        close=True,
        dxfattribs={"layer": "WALLS"},
    )

    # Interior wall at x=5000 with a 900mm door opening at its south end.
    half = INNER_WALL_THICKNESS / 2
    msp.add_lwpolyline(
        [
            (5000 - half, 1130),
            (5000 + half, 1130),
            (5000 + half, 5000 - t),
            (5000 - half, 5000 - t),
        ],
        close=True,
        dxfattribs={"layer": "WALLS"},
    )

    # Door: leaf shown open (perpendicular to the wall) plus swing arc.
    msp.add_line((5000, 1130), (5900, 1130), dxfattribs={"layer": "DOORS"})
    msp.add_arc(
        center=(5000, 1130),
        radius=900,
        start_angle=270,
        end_angle=360,
        dxfattribs={"layer": "DOORS"},
    )

    # Windows in the south wall: three parallel lines across the opening.
    for x1, x2 in [(1500, 2700), (5800, 7000)]:
        for y in (0, t / 2, t):
            msp.add_line((x1, y), (x2, y), dxfattribs={"layer": "WINDOWS"})

    # Room labels.
    for label, x in [("LIVING ROOM", 2500), ("BEDROOM", 6450)]:
        msp.add_text(
            label,
            height=250,
            dxfattribs={"layer": "TEXT"},
        ).set_placement((x, 2500), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # Overall width dimension below the plan.
    dim = msp.add_linear_dim(
        base=(0, -700),
        p1=(0, 0),
        p2=(8000, 0),
        dimstyle="EZDXF",
        override={
            # Scale annotation for a mm-unit drawing; defaults are unreadably small.
            "dimtxt": 250,
            "dimasz": 200,
            "dimexe": 100,
            "dimexo": 100,
            "dimgap": 80,
            "dimdec": 0,
            "dimlfac": 1,  # EZDXF style defaults to a 100x measurement factor
        },
        dxfattribs={"layer": "DIMS"},
    )
    dim.render()

    return doc
