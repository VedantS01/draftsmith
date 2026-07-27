"""Studio chatbot backend: drives a local toolless Claude session.

Each user message becomes one drafting turn: the model (via the local
``claude`` CLI, print mode, the M2 system prompt) receives the current
plan, the engine's feedback for it, recent conversation, and the user's
request; it replies with a full FP1 block, which is validated and — if
valid — applied to the live scene through the action journal (recorded
as a ``load`` op, so chat edits are undoable like any other). Invalid
replies are retried automatically with the error as feedback, up to
``MAX_ROUNDS``.

The model runner is injectable, so tests (and future transports: API,
MCP, remote endpoints) swap it without touching the loop.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable

from draftsmith.agent import PROMPT_PATH, check, feedback
from draftsmith.dsl import serialize
from draftsmith.errors import ToolError
from draftsmith.journal import Recorder

MAX_ROUNDS = 3
HISTORY_TURNS = 8
TIMEOUT_S = 240


def _strip_fp(text: str) -> str:
    return re.sub(r"```(?:fp)?\n.*?```", "[fp block]", text, flags=re.DOTALL).strip()


class ChatSession:
    def __init__(
        self,
        model: str = "sonnet",
        runner: Callable[[str], str] | None = None,
    ) -> None:
        self.model = model
        self.runner = runner or self._run_claude
        self.history: list[dict[str, str]] = []  # {"role": user|assistant, "text"}

    # ------------------------------------------------------------- transport

    def _run_claude(self, prompt: str) -> str:
        binary = shutil.which("claude")
        if binary is None:
            raise ToolError(
                "the 'claude' CLI was not found on PATH - install Claude Code "
                "or start the studio with a different chat backend"
            )
        result = subprocess.run(
            [binary, "-p", "--model", self.model,
             "--system-prompt-file", str(PROMPT_PATH)],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
        if result.returncode != 0:
            raise ToolError(
                f"claude exited with {result.returncode}: "
                f"{(result.stderr or result.stdout).strip()[:400]}"
            )
        return result.stdout.strip()

    # ----------------------------------------------------------- turn logic

    def _build_prompt(self, recorder: Recorder, message: str) -> str:
        parts: list[str] = []
        scene = recorder.scene
        if len(scene):
            parts.append(
                "Current plan (the user may have edited it graphically):\n"
                f"```fp\n{serialize(scene)}```\n\n"
                f"Engine feedback for the current plan:\n{feedback(scene)}"
            )
        else:
            parts.append("The canvas is currently empty.")
        if self.history:
            recent = self.history[-HISTORY_TURNS:]
            convo = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in recent)
            parts.append(f"Conversation so far:\n{convo}")
        parts.append(
            f"USER REQUEST: {message}\n\n"
            "Reply with the FULL updated FP1 document in a ```fp block "
            "(plus at most 2 sentences)."
        )
        return "\n\n".join(parts)

    def turn(self, recorder: Recorder, message: str) -> dict:
        """One chat turn: model -> validate -> apply -> (retry on error)."""
        turns: list[dict[str, str]] = []
        prompt = self._build_prompt(recorder, message)
        applied = False
        last_reply = ""
        for _ in range(MAX_ROUNDS):
            reply = self.runner(prompt)
            last_reply = reply
            turns.append({"role": "assistant", "text": _strip_fp(reply)})
            scene, report = check(reply)
            if scene is None:
                turns.append({"role": "engine", "text": report})
                prompt = (
                    f"{prompt}\n\nASSISTANT: {reply}\n\nENGINE: {report}\n"
                    "Fix exactly this error and resend the FULL corrected "
                    "fp block."
                )
                continue
            recorder.apply("load", fp=serialize(scene))
            turns.append({"role": "engine", "text": report})
            applied = True
            break
        self.history.append({"role": "user", "text": message})
        self.history.append({"role": "assistant", "text": _strip_fp(last_reply)})
        return {"turns": turns, "applied": applied}
