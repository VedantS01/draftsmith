"""FP1 — draftsmith's token-efficient floorplan text format.

The canonical serialization of a :class:`~draftsmith.scene.Scene`,
designed to live inside LLM context windows: one object per line, typed
sequential IDs, positional syntax for the host relation (``D1 W5@0``),
defaults omitted, integer millimetres.

    FP1 mm
    !S door=arc window=triple
    W1 0,115 8000,115 t230
    D1 W5@0 w900 hinge=far
    N1 W1@1500 w1200
    L1 2500,2500 "LIVING ROOM"
    M1 0,0 8000,0 d-700

Guarantees:
- ``parse(serialize(scene))`` reproduces the scene exactly;
- ``serialize`` is canonical (fixed ordering/formatting), so line diffs
  are meaningful.

JSON (:func:`to_json`) is the schema-friendly *interchange view* for
SDKs, UIs and dataset labels; FP1 is the source of truth in agent
contexts. ``FP1`` is a format version tag — syntax changes bump it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from draftsmith.errors import ToolError
from draftsmith.scene import (
    DEFAULT_HINGE,
    DEFAULT_SWING,
    Dim,
    Door,
    Label,
    Scene,
    Wall,
    Window,
)

VERSION = "FP1"

_NUM = r"-?\d+(?:\.\d+)?"
_RE_WALL = re.compile(rf"^W(\d+) ({_NUM}),({_NUM}) ({_NUM}),({_NUM}) t({_NUM})$")
_RE_OPENING = re.compile(rf"^([DN])(\d+) W(\d+)@({_NUM}) w({_NUM})((?: \w+=\S+)*)$")
_RE_LABEL = re.compile(rf'^L(\d+) ({_NUM}),({_NUM}) "(.*)"((?: \w+=\S+)*)$')
_RE_DIM = re.compile(
    rf"^M(\d+) ({_NUM}),({_NUM}) ({_NUM}),({_NUM}) d({_NUM})((?: \w+=\S+)*)$"
)


def _n(x: float) -> str:
    """Format a millimetre value: integer when whole, else 1 decimal."""
    r = round(x)
    if abs(x - r) < 1e-6:
        return str(int(r))
    return f"{x:.1f}"


def _num_key(obj: Any) -> int:
    return int(obj.id[1:])


def serialize(scene: Scene) -> str:
    lines = [f"{VERSION} {scene.units}"]
    style_items = {k: v for k, v in sorted(scene.styles.items()) if v}
    if style_items:
        lines.append("!S " + " ".join(f"{k}={v}" for k, v in style_items.items()))
    for w in sorted(scene.walls, key=_num_key):
        lines.append(
            f"{w.id} {_n(w.start[0])},{_n(w.start[1])} "
            f"{_n(w.end[0])},{_n(w.end[1])} t{_n(w.thickness)}"
        )
    for d in sorted(scene.doors, key=_num_key):
        extras = ""
        if d.hinge != DEFAULT_HINGE:
            extras += f" hinge={d.hinge}"
        if d.swing != DEFAULT_SWING:
            extras += f" swing={d.swing}"
        if d.style:
            extras += f" style={d.style}"
        lines.append(f"{d.id} {d.wall}@{_n(d.offset)} w{_n(d.width)}{extras}")
    for n in sorted(scene.windows, key=_num_key):
        extras = f" style={n.style}" if n.style else ""
        lines.append(f"{n.id} {n.wall}@{_n(n.offset)} w{_n(n.width)}{extras}")
    for lb in sorted(scene.labels, key=_num_key):
        extras = f" style={lb.style}" if lb.style else ""
        lines.append(
            f'{lb.id} {_n(lb.position[0])},{_n(lb.position[1])} "{lb.text}"{extras}'
        )
    for m in sorted(scene.dims, key=_num_key):
        extras = f" a={m.arrows}" if m.arrows != "default" else ""
        lines.append(
            f"{m.id} {_n(m.p1[0])},{_n(m.p1[1])} "
            f"{_n(m.p2[0])},{_n(m.p2[1])} d{_n(m.offset)}{extras}"
        )
    return "\n".join(lines) + "\n"


def _extras(blob: str, line_no: int, allowed: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in blob.split():
        key, _, value = token.partition("=")
        if key not in allowed:
            raise ToolError(
                f"line {line_no}: unknown field {key!r}; allowed: {sorted(allowed)}"
            )
        out[key] = value
    return out


def parse(text: str) -> Scene:
    lines = text.splitlines()
    content = [
        (i + 1, ln.strip())
        for i, ln in enumerate(lines)
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not content:
        raise ToolError("empty FP document")

    line_no, header = content[0]
    parts = header.split()
    if len(parts) != 2 or parts[0] != VERSION:
        raise ToolError(
            f"line {line_no}: expected header '{VERSION} <units>', got {header!r}"
        )
    scene = Scene(units=parts[1])

    for line_no, ln in content[1:]:
        try:
            if ln.startswith("!S"):
                scene.styles.update(
                    _extras(ln[2:].strip(), line_no,
                            {"wall", "door", "window", "label"})
                )
            elif m := _RE_WALL.match(ln):
                num, x1, y1, x2, y2, t = m.groups()
                scene.add_wall(
                    (float(x1), float(y1)), (float(x2), float(y2)),
                    thickness=float(t), id=f"W{num}",
                )
            elif m := _RE_OPENING.match(ln):
                kind, num, wall_num, off, w, blob = m.groups()
                if kind == "D":
                    ex = _extras(blob, line_no, {"hinge", "swing", "style"})
                    scene.add_door(
                        f"W{wall_num}", float(off), float(w),
                        hinge=ex.get("hinge", DEFAULT_HINGE),
                        swing=ex.get("swing", DEFAULT_SWING),
                        style=ex.get("style"), id=f"D{num}",
                    )
                else:
                    ex = _extras(blob, line_no, {"style"})
                    scene.add_window(
                        f"W{wall_num}", float(off), float(w),
                        style=ex.get("style"), id=f"N{num}",
                    )
            elif m := _RE_LABEL.match(ln):
                num, x, y, text_val, blob = m.groups()
                ex = _extras(blob, line_no, {"style"})
                scene.add_label(
                    text_val, (float(x), float(y)),
                    style=ex.get("style"), id=f"L{num}",
                )
            elif m := _RE_DIM.match(ln):
                num, x1, y1, x2, y2, off, blob = m.groups()
                ex = _extras(blob, line_no, {"a"})
                scene.add_dim(
                    (float(x1), float(y1)), (float(x2), float(y2)),
                    offset=float(off), arrows=ex.get("a", "default"),
                    id=f"M{num}",
                )
            else:
                raise ToolError(f"line {line_no}: cannot parse {ln!r}")
        except ToolError as err:
            if str(err).startswith("line "):
                raise
            raise ToolError(f"line {line_no}: {err}") from None
    return scene


# ---------------------------------------------------------------- interchange


def to_json(scene: Scene) -> dict[str, Any]:
    """Schema-friendly interchange view (SDKs, UIs, dataset labels).
    Mechanically derived from the scene; FP1 remains the canonical text."""
    return {
        "format": VERSION,
        "units": scene.units,
        "styles": dict(scene.styles),
        "walls": [
            {"id": w.id, "start": list(w.start), "end": list(w.end),
             "thickness": w.thickness}
            for w in sorted(scene.walls, key=_num_key)
        ],
        "doors": [
            {"id": d.id, "wall": d.wall, "offset": d.offset, "width": d.width,
             "hinge": d.hinge, "swing": d.swing, "style": d.style}
            for d in sorted(scene.doors, key=_num_key)
        ],
        "windows": [
            {"id": n.id, "wall": n.wall, "offset": n.offset, "width": n.width,
             "style": n.style}
            for n in sorted(scene.windows, key=_num_key)
        ],
        "labels": [
            {"id": lb.id, "position": list(lb.position), "text": lb.text,
             "style": lb.style}
            for lb in sorted(scene.labels, key=_num_key)
        ],
        "dims": [
            {"id": m.id, "p1": list(m.p1), "p2": list(m.p2), "offset": m.offset,
             "arrows": m.arrows}
            for m in sorted(scene.dims, key=_num_key)
        ],
    }


def encoding_stats(scene: Scene) -> dict[str, Any]:
    """Rough size comparison of FP1 vs JSON for this scene (chars and a
    chars/4 token approximation — replace with a real tokenizer count in
    the eval harness)."""
    fp = serialize(scene)
    js = json.dumps(to_json(scene))
    return {
        "fp1_chars": len(fp),
        "json_chars": len(js),
        "fp1_tokens_approx": len(fp) // 4,
        "json_tokens_approx": len(js) // 4,
        "ratio": round(len(js) / len(fp), 2),
    }
