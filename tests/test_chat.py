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
