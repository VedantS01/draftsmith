import pytest

from draftsmith.journal import Recorder
from draftsmith.ui.chat import ChatSession

VALID_FP = """FP1 mm
W1 0,115 4000,115 t230
W2 0,2885 4000,2885 t230
W3 115,230 115,2770 t230
W4 3885,230 3885,2770 t230
L1 2000,1500 "STUDY"
M1 0,0 4000,0 d-700
"""


def scripted(replies):
    replies = list(replies)
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return replies.pop(0)

    runner.calls = calls
    return runner


def test_valid_reply_is_applied():
    rec = Recorder()
    chat = ChatSession(runner=scripted([f"Here you go.\n```fp\n{VALID_FP}```\nDone."]))
    result = chat.turn(rec, "draw a study")
    assert result["applied"] is True
    assert [t["role"] for t in result["turns"]] == ["assistant", "engine"]
    assert result["turns"][1]["text"].startswith("OK: 4 walls")
    assert len(rec.scene.walls) == 4
    assert rec.entries[-1]["op"] == "load"
    # fp block stripped from the chat-visible text and stored history
    assert "W1" not in result["turns"][0]["text"]
    assert chat.history[-1]["role"] == "assistant"


def test_invalid_then_valid_retries():
    bad = "```fp\nFP1 mm\nD1 W9@0 w900\n```"
    good = f"```fp\n{VALID_FP}```"
    runner = scripted([bad, good])
    rec = Recorder()
    result = ChatSession(runner=runner).turn(rec, "draw a study")
    assert result["applied"] is True
    roles = [t["role"] for t in result["turns"]]
    assert roles == ["assistant", "engine", "assistant", "engine"]
    assert result["turns"][1]["text"].startswith("ERROR")
    assert "Fix exactly this error" in runner.calls[1]
    assert len(rec.scene.walls) == 4


def test_gives_up_after_max_rounds():
    bad = "no plan here, sorry"
    rec = Recorder()
    result = ChatSession(runner=scripted([bad, bad, bad])).turn(rec, "draw")
    assert result["applied"] is False
    assert len(rec.scene.walls) == 0
    assert sum(1 for t in result["turns"] if t["role"] == "assistant") == 3


def test_prompt_includes_current_plan_and_history():
    rec = Recorder()
    rec.apply("add_wall", start=[0, 0], end=[5000, 0])
    runner = scripted([f"```fp\n{VALID_FP}```", f"```fp\n{VALID_FP}```"])
    chat = ChatSession(runner=runner)
    chat.turn(rec, "replace this with a study")
    first = runner.calls[0]
    assert "Current plan" in first and "W1 0,0 5000,0 t230" in first
    assert "USER REQUEST: replace this with a study" in first
    chat.turn(rec, "make it bigger")
    assert "Conversation so far:" in runner.calls[1]
    assert "USER: replace this with a study" in runner.calls[1]


def test_empty_canvas_prompt():
    runner = scripted([f"```fp\n{VALID_FP}```"])
    ChatSession(runner=runner).turn(Recorder(), "draw a study")
    assert "canvas is currently empty" in runner.calls[0]


def test_server_chat_endpoint():
    import json
    import threading
    import urllib.request

    from draftsmith.ui.server import serve

    server = serve(port=0, chat_runner=scripted([f"```fp\n{VALID_FP}```"]))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/chat",
            json.dumps({"message": "draw a study"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
        assert data["applied"] is True
        assert len(data["state"]["walls"]) == 4
        assert data["state"]["rooms"][0]["label"] == "STUDY"
    finally:
        server.shutdown()


# ---------------------------------------------------------------- ApiRunner


def _stub_api(handler_body: bytes, status: int = 200):
    """Minimal OpenAI-compatible /chat/completions stub; returns (server, port)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(handler_body)))
            self.end_headers()
            self.wfile.write(handler_body)

        def do_GET(self):
            requests.append({"path": self.path, "auth": self.headers.get("Authorization")})
            self._reply(handler_body)

        def do_POST(self):
            import json

            length = int(self.headers["Content-Length"])
            requests.append({
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "body": json.loads(self.rfile.read(length)),
            })
            self._reply(handler_body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.requests = requests
    return server, server.server_address[1]


def test_api_runner_round_trip():
    import json

    from draftsmith.ui.chat import ApiRunner

    reply = {"choices": [{"message": {"content": "  hello plan  "}}]}
    server, port = _stub_api(json.dumps(reply).encode())
    try:
        runner = ApiRunner(f"http://127.0.0.1:{port}/v1/", "sk-test", "some-model")
        assert runner("draw a study") == "hello plan"
        req = server.requests[0]
        assert req["path"] == "/v1/chat/completions"
        assert req["auth"] == "Bearer sk-test"
        assert req["body"]["model"] == "some-model"
        roles = [m["role"] for m in req["body"]["messages"]]
        assert roles == ["system", "user"]
        assert "FP1" in req["body"]["messages"][0]["content"]  # system prompt
        assert req["body"]["messages"][1]["content"] == "draw a study"
    finally:
        server.shutdown()


def test_api_runner_http_error_is_tool_error():
    import pytest as _pytest

    from draftsmith.errors import ToolError
    from draftsmith.ui.chat import ApiRunner

    server, port = _stub_api(b'{"error": "rate limited"}', status=429)
    try:
        runner = ApiRunner(f"http://127.0.0.1:{port}", "k", "m")
        with _pytest.raises(ToolError, match="429"):
            runner("draw")
    finally:
        server.shutdown()


def test_api_runner_bad_shape_is_tool_error():
    import pytest as _pytest

    from draftsmith.errors import ToolError
    from draftsmith.ui.chat import ApiRunner

    server, port = _stub_api(b'{"unexpected": true}')
    try:
        runner = ApiRunner(f"http://127.0.0.1:{port}", "k", "m")
        with _pytest.raises(ToolError, match="response shape"):
            runner("draw")
    finally:
        server.shutdown()


def test_api_runner_from_env_selection(monkeypatch):
    from draftsmith.ui.chat import ApiRunner, api_runner_from_env

    monkeypatch.delenv("DRAFTSMITH_API_BASE", raising=False)
    monkeypatch.delenv("DRAFTSMITH_API_MODEL", raising=False)
    monkeypatch.delenv("DRAFTSMITH_API_KEY", raising=False)
    assert api_runner_from_env() is None

    monkeypatch.setenv("DRAFTSMITH_API_BASE", "http://example.test/v1")
    assert api_runner_from_env() is None  # model still missing

    monkeypatch.setenv("DRAFTSMITH_API_MODEL", "m")
    runner = api_runner_from_env()
    assert isinstance(runner, ApiRunner)
    assert runner.api_key == ""  # key optional (some gateways don't need one)

    # ChatSession picks the env-configured API runner over the claude CLI
    chat = ChatSession()
    assert chat.runner is not chat._run_claude
    assert isinstance(chat.runner, ApiRunner)


def test_api_runner_reasoning_field_becomes_turn():
    import json

    reply = {
        "model": "some-model-002",
        "choices": [{"message": {
            "content": f"```fp\n{VALID_FP}```",
            "reasoning_content": "walls first, then the label",
        }}],
    }
    server, port = _stub_api(json.dumps(reply).encode())
    try:
        from draftsmith.ui.chat import ApiRunner

        runner = ApiRunner(f"http://127.0.0.1:{port}", "k", "some-model")
        chat = ChatSession(runner=runner)
        result = chat.turn(Recorder(), "draw a study")
        roles = [t["role"] for t in result["turns"]]
        assert roles == ["reasoning", "assistant", "engine"]
        assert result["turns"][0]["text"] == "walls first, then the label"
        assert runner.last_model == "some-model-002"
    finally:
        server.shutdown()


def test_api_runner_inline_think_block_is_split_out():
    import json

    content = f"<think>plan the walls</think>\n```fp\n{VALID_FP}```"
    reply = {"choices": [{"message": {"content": content}}]}
    server, port = _stub_api(json.dumps(reply).encode())
    try:
        from draftsmith.ui.chat import ApiRunner

        runner = ApiRunner(f"http://127.0.0.1:{port}", "k", "m")
        out = runner("draw")
        assert "<think>" not in out
        assert out.startswith("```fp")
        assert runner.last_reasoning == "plan the walls"
    finally:
        server.shutdown()


def test_api_runner_list_models():
    import json

    body = {"data": [{"id": "b-model"}, {"id": "a-model"}, {"id": ""}]}
    server, port = _stub_api(json.dumps(body).encode())
    try:
        from draftsmith.ui.chat import ApiRunner

        runner = ApiRunner(f"http://127.0.0.1:{port}", "k", "m")
        assert runner.list_models() == ["a-model", "b-model"]
    finally:
        server.shutdown()


def test_chat_session_model_info_and_switch():
    from draftsmith.errors import ToolError
    from draftsmith.ui.chat import ApiRunner

    api = ChatSession(runner=ApiRunner("http://x", "k", "m1"))
    assert api.info() == {"backend": "api", "model": "m1", "served_model": ""}
    api.set_model("m2")
    assert api.runner.model == "m2"

    scripted_chat = ChatSession(runner=scripted([]))
    assert scripted_chat.info()["backend"] == "custom"
    assert scripted_chat.models() == []

    claude_chat = ChatSession.__new__(ChatSession)
    claude_chat.model = "sonnet"
    claude_chat.effort = "low"
    claude_chat.history = []
    claude_chat.runner = claude_chat._run_claude
    assert claude_chat.info() == {
        "backend": "claude", "model": "sonnet", "served_model": ""
    }
    assert claude_chat.models() == ["sonnet", "opus", "haiku"]
    claude_chat.set_model("opus")
    assert claude_chat.model == "opus"

    import pytest as _pytest

    with _pytest.raises(ToolError):
        api.set_model("")


def test_server_chat_info_and_model_endpoints():
    import json
    import threading
    import urllib.request

    from draftsmith.ui.server import serve

    server = serve(port=0, chat_runner=scripted([]))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/chat/info") as res:
            info = json.loads(res.read())
        assert info["backend"] == "custom"
        assert info["models"] == []

        req = urllib.request.Request(
            f"{base}/api/chat/model",
            json.dumps({"model": "haiku"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as res:
            assert json.loads(res.read())["backend"] == "custom"
        assert server.chat.model == "haiku"
    finally:
        server.shutdown()
