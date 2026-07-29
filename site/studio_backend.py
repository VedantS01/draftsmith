"""In-browser backend for the studio demo (runs inside Pyodide).

Mirrors the JSON routes of ``draftsmith.ui.server`` so the unmodified
studio frontend works on a static host: ``site/studio-shim.js``
intercepts ``fetch('/api/...')`` calls and dispatches them here. Chat
model calls stay in JavaScript (browser ``fetch`` — Pyodide has no
sockets); this module supplies the prompt building, reply validation,
and scene application around them, reusing the real engine code.
"""

from __future__ import annotations

import json

from draftsmith.agent import check
from draftsmith.compiler import compile_scene
from draftsmith.dsl import serialize
from draftsmith.errors import ToolError
from draftsmith.journal import Recorder
from draftsmith.ui.chat import ChatSession, _strip_fp
from draftsmith.ui.display import display_model

recorder = Recorder()
chat = ChatSession(runner=lambda p: "")  # prompt building + history only


def _state() -> dict:
    model = display_model(recorder.scene)
    model["undo_depth"] = len(recorder.entries)
    model["redo_depth"] = len(recorder.redo_stack)
    return model


def handle(route: str, payload_json: str = "") -> str:
    """Dispatch one JSON route; always returns a JSON string.

    Errors come back as ``{"__error__": ..., "__code__": ...}`` so the
    JS shim can build a matching HTTP-style Response.
    """
    try:
        payload = json.loads(payload_json) if payload_json else {}
        if route == "state":
            return json.dumps(_state())
        if route == "op":
            recorder.apply(payload["op"], **payload.get("args", {}))
            return json.dumps(_state())
        if route == "undo":
            recorder.undo()
            return json.dumps(_state())
        if route == "redo":
            recorder.redo()
            return json.dumps(_state())
        if route == "fp":
            recorder.apply("load", fp=payload["fp"])
            return json.dumps(_state())
        return json.dumps({"__error__": f"no route {route}", "__code__": 404})
    except ToolError as err:
        return json.dumps({"__error__": str(err), "__code__": 400})
    except KeyError as missing:
        return json.dumps({"__error__": f"missing field {missing}", "__code__": 400})
    except Exception as err:  # engine failures surface in the UI, not the console
        return json.dumps({"__error__": f"{type(err).__name__}: {err}", "__code__": 500})


def export(fmt: str) -> bytes:
    """Compile the scene and return plan.<fmt> bytes (dxf/png/svg)."""
    path = f"/tmp/plan.{fmt}"
    sk = compile_scene(recorder.scene)
    if fmt == "dxf":
        sk.save(path)
    else:
        sk.render(path)
    with open(path, "rb") as fh:
        return fh.read()


def system_prompt() -> str:
    from draftsmith.agent import PROMPT_PATH

    return PROMPT_PATH.read_text()


def build_prompt(message: str) -> str:
    return chat._build_prompt(recorder, message)


def chat_reply(reply: str, reasoning: str = "") -> str:
    """Validate one model reply, apply it if valid; returns turn JSON."""
    turns = []
    if reasoning.strip():
        turns.append({"role": "reasoning", "text": _strip_fp(reasoning)})
    turns.append({"role": "assistant", "text": _strip_fp(reply)})
    scene, report = check(reply)
    applied = False
    if scene is not None:
        recorder.apply("load", fp=serialize(scene))
        applied = True
    turns.append({"role": "engine", "text": report})
    return json.dumps({"turns": turns, "applied": applied, "report": report})


def chat_record(message: str, last_reply: str) -> None:
    """Store the finished exchange in the rolling chat history."""
    chat.history.append({"role": "user", "text": message})
    chat.history.append({"role": "assistant", "text": _strip_fp(last_reply)})
