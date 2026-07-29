"""Studio chatbot backend: one drafting turn per user message.

Each user message becomes one drafting turn: the model receives the
current plan, the engine's feedback for it, recent conversation, and the
user's request; it replies with a full FP1 block, which is validated and
— if valid — applied to the live scene through the action journal
(recorded as a ``load`` op, so chat edits are undoable like any other).
Invalid replies are retried automatically with the error as feedback, up
to ``MAX_ROUNDS``.

Two built-in transports, both toolless text-in/text-out:

- :class:`ApiRunner` — any OpenAI-compatible chat-completions endpoint
  (Gemini, Mistral, NVIDIA NIM, OpenRouter, Groq, ...), selected when
  the ``DRAFTSMITH_API_*`` environment variables are set.
- the local ``claude`` CLI in print mode (the original M2 setup),
  used as the fallback when no API is configured.

The model runner stays injectable, so tests (and future transports:
MCP, remote endpoints) swap it without touching the loop.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Callable

from draftsmith.agent import PROMPT_PATH, check, feedback
from draftsmith.dsl import serialize
from draftsmith.errors import ToolError
from draftsmith.journal import Recorder

MAX_ROUNDS = 3
HISTORY_TURNS = 8
TIMEOUT_S = 240


class ApiRunner:
    """Toolless runner over an OpenAI-compatible chat-completions API.

    Works against any provider exposing the ``POST {base}/chat/completions``
    shape — e.g. Gemini (``https://generativelanguage.googleapis.com/v1beta/openai``),
    Mistral (``https://api.mistral.ai/v1``), NVIDIA NIM
    (``https://integrate.api.nvidia.com/v1``), OpenRouter
    (``https://openrouter.ai/api/v1``). Stdlib-only, like the rest of
    the studio.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = TIMEOUT_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.system = PROMPT_PATH.read_text()

    def __call__(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")[:400]
            raise ToolError(f"LLM API returned {err.code}: {detail}") from err
        except OSError as err:  # URLError, timeouts, DNS failures
            raise ToolError(f"LLM API request failed: {err}") from err
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as err:
            raise ToolError(
                f"unexpected LLM API response shape: {str(data)[:200]}"
            ) from err


def api_runner_from_env() -> ApiRunner | None:
    """Build an :class:`ApiRunner` from the environment, if configured.

    Reads ``DRAFTSMITH_API_BASE`` (endpoint base URL, without the
    ``/chat/completions`` suffix), ``DRAFTSMITH_API_KEY``, and
    ``DRAFTSMITH_API_MODEL``. Returns ``None`` unless both the base URL
    and the model are set, so the CLI fallback keeps working untouched.
    """
    base = os.environ.get("DRAFTSMITH_API_BASE")
    model = os.environ.get("DRAFTSMITH_API_MODEL")
    if not (base and model):
        return None
    return ApiRunner(base, os.environ.get("DRAFTSMITH_API_KEY", ""), model)


def _strip_fp(text: str) -> str:
    return re.sub(r"```(?:fp)?\n.*?```", "[fp block]", text, flags=re.DOTALL).strip()


class ChatSession:
    def __init__(
        self,
        model: str = "sonnet",
        runner: Callable[[str], str] | None = None,
        effort: str = "low",
    ) -> None:
        self.model = model
        self.effort = effort
        self.runner = runner or api_runner_from_env() or self._run_claude
        self.history: list[dict[str, str]] = []  # {"role": user|assistant, "text"}

    # ------------------------------------------------------------- transport

    def _run_claude(self, prompt: str) -> str:
        binary = shutil.which("claude")
        if binary is None:
            raise ToolError(
                "the 'claude' CLI was not found on PATH - install Claude Code "
                "or start the studio with a different chat backend"
            )
        # Measured on-device: default effort + available tools pushed simple
        # briefs past 240s; effort low + no tools + no session persistence
        # brings them to ~4-6s (sonnet). Complex briefs still take ~2min of
        # pure generation.
        result = subprocess.run(
            [binary, "-p", "--model", self.model,
             "--effort", self.effort,
             "--disallowedTools", "*",
             "--no-session-persistence",
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
