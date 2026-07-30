"""The agent surface: FP1 in, engine feedback out.

M2 of the roadmap, shaped for a *toolless* chat workflow: the LLM emits
an FP1 document (its system prompt is ``agent_prompt.md``), the engine
validates and derives geometry, and :func:`feedback` renders the result
as compact text to paste back into the chat. The same function will feed
tool-calling/MCP agents later — the protocol is the text, not the
transport.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from draftsmith.dsl import parse
from draftsmith.errors import ToolError
from draftsmith.geometry import EXTERIOR, connections, rooms, wall_body
from draftsmith.scene import Scene
from shapely.geometry import Point as SPoint

PROMPT_PATH = Path(__file__).parent / "agent_prompt.md"
GUIDELINES_PATH = Path(__file__).parent / "design_guidelines.md"


def system_prompt(design: bool = False) -> str:
    """The drafting-agent system prompt; ``design=True`` appends the
    design-quality doctrine (``design_guidelines.md``).  Kept separate
    so the M5 domain-skill-prompting ablation can toggle it."""
    text = PROMPT_PATH.read_text()
    if design:
        text = f"{text.rstrip()}\n\n{GUIDELINES_PATH.read_text()}"
    return text


def design_guidelines() -> str:
    return GUIDELINES_PATH.read_text()


def extract_fp(text: str) -> str:
    """Pull an FP1 document out of chat text: a ```fp fenced block, any
    fenced block starting with 'FP1', or raw FP1 text."""
    for m in re.finditer(r"```(\w*)\n(.*?)```", text, re.DOTALL):
        tag, body = m.group(1), m.group(2)
        if tag == "fp" or body.lstrip().startswith("FP1"):
            return body
    if text.lstrip().startswith("FP1"):
        return text
    raise ToolError("no FP1 document found (expected a ```fp fenced block)")


def warnings_for(scene: Scene, room_list=None) -> list[str]:
    """Agent-facing sanity warnings about derived geometry."""
    room_list = rooms(scene) if room_list is None else room_list
    warns: list[str] = []
    if scene.walls and not room_list:
        warns.append(
            "no enclosed rooms detected - walls do not close a loop "
            "(check that connecting walls share endpoints)"
        )
    for room in room_list:
        if room.label is None:
            warns.append(f"room {room.id} has no label inside it")
    labels_by_room: dict[str, list[str]] = {}
    for lb in scene.labels:
        for room in room_list:
            if room.polygon.contains(SPoint(lb.position)):
                labels_by_room.setdefault(room.id, []).append(lb.id)
                break
        else:
            if room_list:
                warns.append(f'label {lb.id} "{lb.text}" is not inside any room')
    for rid, lbs in labels_by_room.items():
        if len(lbs) > 1:
            warns.append(f"room {rid} contains multiple labels: {', '.join(lbs)}")
    conns = connections(scene, room_list)
    for c in conns:
        if c["kind"] == "door" and c["rooms"].count(EXTERIOR) == 2:
            warns.append(f"door {c['opening']} connects nothing (EXT <-> EXT)")
        if c["kind"] == "window" and EXTERIOR not in c["rooms"]:
            warns.append(
                f"window {c['opening']} is in an interior wall "
                f"({c['rooms'][0]} <-> {c['rooms'][1]})"
            )
    if not scene.dims and scene.walls:
        warns.append("no dimensions - add at least overall width and height")
    body = wall_body(scene, cut_openings=False)
    if not body.is_empty:
        for m in scene.dims:
            dx, dy = m.p2[0] - m.p1[0], m.p2[1] - m.p1[1]
            length = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / length, dx / length
            mid = SPoint(
                (m.p1[0] + m.p2[0]) / 2 + nx * m.offset,
                (m.p1[1] + m.p2[1]) / 2 + ny * m.offset,
            )
            if body.contains(mid) or any(
                r.polygon.contains(mid) for r in room_list
            ):
                warns.append(
                    f"dimension {m.id} runs inside the building - flip the "
                    f"sign of its d offset (or swap its points)"
                )
    return warns


def feedback(scene: Scene) -> str:
    """The engine's textual read-back for an agent turn."""
    room_list = rooms(scene)
    lines = [
        f"OK: {len(scene.walls)} walls, {len(scene.doors)} doors, "
        f"{len(scene.windows)} windows, {len(scene.labels)} labels, "
        f"{len(scene.dims)} dims"
    ]
    if room_list:
        lines.append("rooms:")
        for r in room_list:
            b = r.polygon.bounds
            label = f'"{r.label}"' if r.label else "(unlabelled)"
            lines.append(
                f"  {r.id} {label:<16} {r.area_m2:6.2f} m2  "
                f"bbox {b[0]:.0f},{b[1]:.0f} -> {b[2]:.0f},{b[3]:.0f}"
            )
    conns = connections(scene, room_list)
    if conns:
        lines.append("connections:")
        for c in conns:
            lines.append(
                f"  {c['opening']} {c['kind']:<6} {c['rooms'][0]} <-> {c['rooms'][1]}"
            )
    warns = warnings_for(scene, room_list)
    if warns:
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in warns)
    body = wall_body(scene, cut_openings=False)
    if not body.is_empty:
        b = body.bounds
        lines.append(f"extents: {b[0]:.0f},{b[1]:.0f} -> {b[2]:.0f},{b[3]:.0f}")
    return "\n".join(lines)


def check(text: str) -> tuple[Scene | None, str]:
    """Validate chat text containing FP1; returns (scene, feedback) —
    scene is None and feedback is the error message when invalid."""
    try:
        scene = parse(extract_fp(text))
    except ToolError as err:
        return None, f"ERROR {err}"
    return scene, feedback(scene)
