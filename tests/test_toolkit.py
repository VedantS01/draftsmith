import pytest

from draftsmith.toolkit import Sketch, ToolError


@pytest.fixture
def sk():
    return Sketch()


def test_primitives_return_handles_and_describe(sk):
    h = sk.add_line((0, 0), (100, 0), layer="A")
    info = sk.describe(h)
    assert info["type"] == "LINE"
    assert info["layer"] == "A"
    assert info["start"] == (0, 0)
    assert info["end"] == (100, 0)

    h = sk.add_circle((50, 50), 25)
    assert sk.describe(h)["radius"] == 25

    h = sk.add_rect((0, 0), 200, 100)
    info = sk.describe(h)
    assert info["closed"] is True
    assert len(info["points"]) == 4

    h = sk.add_text("HELLO", (10, 10), height=50)
    assert sk.describe(h)["text"] == "HELLO"

    h = sk.add_aligned_dim((0, 0), (300, 0))
    assert sk.describe(h)["measurement"] == pytest.approx(300)


def test_layers_auto_created(sk):
    sk.add_line((0, 0), (1, 1), layer="NEW_LAYER")
    assert "NEW_LAYER" in [layer["name"] for layer in sk.layers()]


@pytest.mark.parametrize(
    "call",
    [
        lambda sk: sk.add_line((5, 5), (5, 5)),
        lambda sk: sk.add_polyline([(0, 0)]),
        lambda sk: sk.add_rect((0, 0), -10, 10),
        lambda sk: sk.add_circle((0, 0), 0),
        lambda sk: sk.add_arc((0, 0), -1, 0, 90),
        lambda sk: sk.add_text("", (0, 0)),
        lambda sk: sk.add_text("X", (0, 0), align="NOT_AN_ALIGNMENT"),
        lambda sk: sk.add_aligned_dim((1, 1), (1, 1)),
        lambda sk: sk.add_layer(" bad "),
        lambda sk: sk.delete("DEADBEEF"),
        lambda sk: sk.add_line("nope", (1, 1)),
    ],
)
def test_validation_errors(sk, call):
    with pytest.raises(ToolError):
        call(sk)


def test_delete_and_translate(sk):
    h = sk.add_line((0, 0), (100, 0))
    sk.translate(h, 10, 20)
    info = sk.describe(h)
    assert info["start"] == (10, 20)
    assert info["end"] == (110, 20)

    sk.delete(h)
    with pytest.raises(ToolError, match="no modelspace entity"):
        sk.describe(h)
    assert sk.entities() == []


def test_entities_filter_and_summary(sk):
    sk.add_line((0, 0), (100, 0), layer="A")
    sk.add_line((0, 0), (0, 100), layer="B")
    sk.add_circle((0, 0), 10, layer="B")

    assert len(sk.entities()) == 3
    assert len(sk.entities(layer="B")) == 2

    s = sk.summary()
    assert s["entities"] == 3
    assert s["by_type"] == {"LINE": 2, "CIRCLE": 1}
    assert s["by_layer"] == {"A": 1, "B": 2}
    assert s["extents"]["min"] == (-10, -10)
    assert s["extents"]["max"] == (100, 100)


def test_empty_extents(sk):
    assert sk.extents() is None


def test_measure():
    assert Sketch.measure((0, 0), (3, 4)) == 5


def test_save_open_roundtrip(sk, tmp_path):
    sk.add_line((0, 0), (100, 100), layer="A")
    sk.add_circle((50, 50), 10)
    path = sk.save(tmp_path / "out.dxf")

    sk2 = Sketch.open(path)
    assert sk2.summary()["by_type"] == {"LINE": 1, "CIRCLE": 1}


def test_render(sk, tmp_path):
    sk.add_rect((0, 0), 1000, 500)
    out = sk.render(tmp_path / "out.png")
    assert out.exists()
