"""Action journal: named scene operations, recorded and replayable.

Every mutation of a Scene can be expressed as a named op with JSON args.
A :class:`Recorder` applies ops, appends them to an in-memory (and
optionally on-disk JSONL) journal, and can rebuild the identical scene by
replay — the basis for undo, session persistence, and usage-data
collection in the interactive layer.

This op vocabulary is deliberately the same surface the LLM-agent tools
(M2) will expose: one dispatch layer, two drivers (humans and agents).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from draftsmith.errors import ToolError
from draftsmith.scene import Scene


def _apply(scene: Scene, op: str, args: dict[str, Any]) -> str | None:
    """Apply one op to a scene; returns the created object's id, if any."""
    try:
        if op == "add_wall":
            return scene.add_wall(
                tuple(args["start"]), tuple(args["end"]),
                thickness=args.get("thickness", 230),
            ).id
        if op == "add_door":
            return scene.add_door(
                args["wall"], args["offset"],
                width=args.get("width", 900),
                hinge=args.get("hinge", "near"),
                swing=args.get("swing", "left"),
                style=args.get("style"),
            ).id
        if op == "add_window":
            return scene.add_window(
                args["wall"], args["offset"], args["width"],
                style=args.get("style"),
            ).id
        if op == "add_label":
            return scene.add_label(
                args["text"], tuple(args["position"]), style=args.get("style")
            ).id
        if op == "add_dim":
            return scene.add_dim(
                tuple(args["p1"]), tuple(args["p2"]),
                offset=args.get("offset", -700),
                arrows=args.get("arrows", "default"),
            ).id
        if op == "delete":
            scene.delete(args["id"])
            return None
        if op == "move_opening":
            scene.move_opening(args["id"], args["offset"])
            return None
        if op == "update_dim":
            scene.update_dim(
                args["id"], offset=args.get("offset"), arrows=args.get("arrows")
            )
            return None
        if op == "update_label":
            scene.update_label(
                args["id"], text=args.get("text"),
                position=tuple(args["position"]) if args.get("position") else None,
                style=args.get("style"),
            )
            return None
        if op == "update_opening":
            scene.update_opening(
                args["id"], width=args.get("width"), hinge=args.get("hinge"),
                swing=args.get("swing"), style=args.get("style"),
            )
            return None
        if op == "move_wall":
            scene.translate_wall(args["id"], args["dx"], args["dy"])
            return None
        if op == "move_joint":
            scene.move_joint(tuple(args["at"]), tuple(args["to"]))
            return None
        if op == "set_style":
            scene.set_style(args["slot"], args["name"])
            return None
    except KeyError as missing:
        raise ToolError(f"op {op!r} is missing required arg {missing}") from None
    raise ToolError(f"unknown op {op!r}; valid: {sorted(OPS)}")


OPS = {
    "add_wall", "add_door", "add_window", "add_label", "add_dim",
    "delete", "move_opening", "update_dim", "update_label", "update_opening",
    "move_wall", "move_joint", "set_style", "load",
}


def replay(entries: list[dict[str, Any]]) -> Scene:
    """Rebuild a scene from journal entries."""
    from draftsmith.dsl import parse

    scene = Scene()
    for entry in entries:
        if entry["op"] == "load":
            scene = parse(entry["args"]["fp"])
        else:
            _apply(scene, entry["op"], entry["args"])
    return scene


class Recorder:
    """A Scene plus its construction history.

    ``apply()`` mutates the scene and journals the op; ``undo()`` rebuilds
    from all-but-the-last entry. With ``journal_path`` set, entries are
    appended to a JSONL file as they happen (and the file is rewritten on
    undo); an existing file is replayed on startup, resuming the session.
    """

    def __init__(self, journal_path: str | Path | None = None) -> None:
        self.path = Path(journal_path) if journal_path else None
        self.entries: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []
        if self.path and self.path.exists():
            self.entries = [
                json.loads(line)
                for line in self.path.read_text().splitlines()
                if line.strip()
            ]
        self.scene = replay(self.entries)

    def apply(self, op: str, **args: Any) -> str | None:
        if op == "load":
            from draftsmith.dsl import parse

            new_scene = parse(args["fp"])  # validate before committing
            result = None
        elif op in OPS:
            result = _apply(self.scene, op, args)
        else:
            raise ToolError(f"unknown op {op!r}; valid: {sorted(OPS)}")

        entry = {
            "seq": len(self.entries) + 1,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "op": op,
            "args": args,
            "result": result,
        }
        if op == "load":
            self.scene = new_scene
        self.entries.append(entry)
        self.redo_stack.clear()  # a fresh edit invalidates the redo branch
        if self.path:
            with self.path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        return result

    def _rewrite(self) -> None:
        if self.path:
            self.path.write_text(
                "".join(json.dumps(e) + "\n" for e in self.entries)
            )

    def undo(self) -> None:
        if not self.entries:
            raise ToolError("nothing to undo")
        self.redo_stack.append(self.entries[-1])
        self.entries = self.entries[:-1]
        self.scene = replay(self.entries)
        self._rewrite()

    def redo(self) -> None:
        if not self.redo_stack:
            raise ToolError("nothing to redo")
        entry = self.redo_stack.pop()
        self.entries.append(entry)
        self.scene = replay(self.entries)
        self._rewrite()
