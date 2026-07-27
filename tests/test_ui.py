import json
import threading
import urllib.error
import urllib.request

import pytest

from draftsmith.dsl import serialize
from draftsmith.samples import build_sample_scene
from draftsmith.ui.display import display_model
from draftsmith.ui.server import serve


def test_display_model_shape():
    model = display_model(build_sample_scene())
    assert {e["type"] for e in model["drawing"]} >= {"LINE", "LWPOLYLINE", "ARC"}
    assert all(e["layer"] in ("WALLS", "DOORS", "WINDOWS") for e in model["drawing"])
    assert [w["id"] for w in model["walls"]] == ["W1", "W2", "W3", "W4", "W5"]
    assert model["openings"][0]["kind"] == "door"
    assert model["openings"][0]["hinge"] == "far"
    assert len(model["openings"][0]["polygon"]) == 4
    assert [r["id"] for r in model["rooms"]] == ["R1", "R2"]
    assert model["labels"][0]["text"] == "LIVING ROOM"
    assert model["dims"][0]["measurement"] == 8000
    assert model["styles"]["door"] == "arc"
    assert "sliding" in model["style_options"]["door"]
    assert model["fp"].startswith("FP1 mm")


def test_display_model_applies_label_style():
    sc = build_sample_scene()
    sc.styles["label"] = "title"
    model = display_model(sc)
    assert model["labels"][0]["text"] == "Living Room"
    assert model["labels"][0]["raw_text"] == "LIVING ROOM"


@pytest.fixture()
def studio():
    server = serve(port=0)  # ephemeral port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as res:
        return res.status, res.read()


def _post(url, payload):
    req = urllib.request.Request(
        url, json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        return res.status, json.loads(res.read())


def test_server_roundtrip(studio):
    status, html = _get(studio + "/")
    assert status == 200 and b"draftsmith studio" in html

    status, state = _post(studio + "/api/op",
                          {"op": "add_wall", "args": {"start": [0, 0], "end": [5000, 0]}})
    assert status == 200
    assert state["walls"][0]["id"] == "W1"

    _post(studio + "/api/op",
          {"op": "add_door", "args": {"wall": "W1", "offset": 1000}})
    status, fp = _get(studio + "/api/fp")
    assert b"D1 W1@1000 w900" in fp

    status, state = _post(studio + "/api/undo", {})
    assert state["openings"] == []

    status, dxf = _get(studio + "/api/export.dxf")
    assert status == 200 and len(dxf) > 1000

    fp_text = serialize(build_sample_scene())
    status, state = _post(studio + "/api/fp", {"fp": fp_text})
    assert len(state["rooms"]) == 2


def test_server_error_is_agent_readable(studio):
    req = urllib.request.Request(
        studio + "/api/op",
        json.dumps({"op": "add_door", "args": {"wall": "W99", "offset": 0}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 400
    assert "no object" in json.loads(err.value.read())["error"]


def test_display_model_joints():
    model = display_model(build_sample_scene())
    assert any(len(j["walls"]) >= 1 for j in model["joints"])
    assert len(model["joints"]) == 10  # 5 walls, butt layout: no shared endpoints


def test_export_formats(studio):
    for fmt, magic in [("png", b"\x89PNG"), ("svg", b"<?xml")]:
        status, body = _get(studio + f"/api/export.{fmt}")
        assert status == 200
        assert body[:5].startswith(magic[:4])
