"""Build the display model the studio frontend renders.

The *drawing* (styled primitives) comes straight from the compiler, so
the browser shows exactly what the DXF will contain; *hit shapes* for
selection come from the scene's semantic objects, so clicking maps back
to IDs. Labels and dimensions are sent as semantic data (the frontend
draws them, keeping text crisp and selectable).
"""

from __future__ import annotations

import math
from typing import Any

from draftsmith.compiler import (
    DOOR_STYLES,
    LABEL_STYLES,
    WINDOW_STYLES,
    compile_scene,
)
from draftsmith.dsl import serialize
from draftsmith.geometry import (
    connections,
    joints,
    opening_polygon,
    rooms,
    wall_polygon,
)
from draftsmith.scene import DEFAULT_STYLES, Door, Scene


def _ring(coords) -> list[list[float]]:
    return [[round(x, 1), round(y, 1)] for x, y in coords]


def display_model(scene: Scene) -> dict[str, Any]:
    sk = compile_scene(scene)
    drawing = [
        e for e in sk.entities() if e["layer"] in ("WALLS", "DOORS", "WINDOWS")
    ]
    room_list = rooms(scene)
    label_fmt = LABEL_STYLES[scene.style_for("label")]
    return {
        "drawing": drawing,
        "walls": [
            {
                "id": w.id,
                "start": list(w.start),
                "end": list(w.end),
                "thickness": w.thickness,
                "length": round(w.length, 1),
                "polygon": _ring(wall_polygon(w).exterior.coords[:-1]),
            }
            for w in scene.walls
        ],
        "openings": [
            {
                "id": o.id,
                "kind": "door" if isinstance(o, Door) else "window",
                "wall": o.wall,
                "offset": o.offset,
                "width": o.width,
                "style": o.style,
                **({"hinge": o.hinge, "swing": o.swing} if isinstance(o, Door) else {}),
                "polygon": _ring(opening_polygon(scene, o).exterior.coords[:-1]),
            }
            for o in scene
            if hasattr(o, "wall")
        ],
        "labels": [
            {
                "id": lb.id,
                "position": list(lb.position),
                "text": label_fmt(lb.text),
                "raw_text": lb.text,
            }
            for lb in scene.labels
        ],
        "dims": [
            {
                "id": m.id,
                "p1": list(m.p1),
                "p2": list(m.p2),
                "offset": m.offset,
                "arrows": m.arrows,
                "measurement": round(math.dist(m.p1, m.p2)),
            }
            for m in scene.dims
        ],
        "rooms": [
            {
                "id": r.id,
                "label": r.label,
                "area_m2": round(r.area_m2, 2),
                "centroid": [round(v) for v in r.centroid],
                "polygon": _ring(r.polygon.exterior.coords[:-1]),
            }
            for r in room_list
        ],
        "joints": joints(scene),
        "connections": connections(scene, room_list),
        "styles": {slot: scene.style_for(slot) for slot in DEFAULT_STYLES},
        "style_options": {
            "door": sorted(DOOR_STYLES),
            "window": sorted(WINDOW_STYLES),
            "label": sorted(LABEL_STYLES),
        },
        "fp": serialize(scene),
    }
