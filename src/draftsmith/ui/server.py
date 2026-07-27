"""draftsmith studio server — stdlib-only local web app.

Serves the single-page frontend and a small JSON API. Every mutation goes
through the :class:`~draftsmith.journal.Recorder`, so the full session is
recorded and reproducible (and optionally persisted to a JSONL journal).
"""

from __future__ import annotations

import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from draftsmith.compiler import compile_scene
from draftsmith.errors import ToolError
from draftsmith.journal import Recorder
from draftsmith.ui.display import display_model

INDEX = Path(__file__).parent / "index.html"


def make_handler(recorder: Recorder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def _state(self, code: int = 200) -> None:
            self._json(code, display_model(recorder.scene))

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._state()
            elif self.path == "/api/fp":
                from draftsmith.dsl import serialize

                self._send(200, serialize(recorder.scene).encode(), "text/plain")
            elif self.path == "/api/export.dxf":
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "plan.dxf"
                    compile_scene(recorder.scene).save(path)
                    body = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/dxf")
                self.send_header(
                    "Content-Disposition", "attachment; filename=plan.dxf"
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(404, {"error": f"no route {self.path}"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON body"})
                return
            try:
                if self.path == "/api/op":
                    recorder.apply(payload["op"], **payload.get("args", {}))
                    self._state()
                elif self.path == "/api/undo":
                    recorder.undo()
                    self._state()
                elif self.path == "/api/fp":
                    recorder.apply("load", fp=payload["fp"])
                    self._state()
                else:
                    self._json(404, {"error": f"no route {self.path}"})
            except ToolError as err:
                self._json(400, {"error": str(err)})
            except KeyError as missing:
                self._json(400, {"error": f"missing field {missing}"})

    return Handler


def serve(
    port: int = 8765,
    journal_path: str | Path | None = None,
    fp_path: str | Path | None = None,
) -> ThreadingHTTPServer:
    """Build the server (call ``serve_forever()`` on the result)."""
    recorder = Recorder(journal_path)
    if fp_path:
        recorder.apply("load", fp=Path(fp_path).read_text())
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(recorder))
    server.recorder = recorder  # exposed for tests
    return server
