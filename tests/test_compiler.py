import pytest

from draftsmith.compiler import compile_scene
from draftsmith.errors import ToolError
from draftsmith.samples import build_sample_scene
from draftsmith.scene import Scene


def _door_scene(style=None, **styles):
    sc = Scene()
    sc.styles.update(styles)
    sc.add_wall((0, 0), (5000, 0), 230)
    sc.add_door("W1", 2000, 900, style=style)
    return sc


def test_compile_sample_layers_and_counts():
    sk = compile_scene(build_sample_scene())
    s = sk.summary()
    assert s["by_layer"]["TEXT"] == 2
    assert s["by_type"]["DIMENSION"] == 1
    assert s["by_layer"]["WINDOWS"] == 6  # 2 windows x triple style
    assert s["by_layer"]["DOORS"] == 2  # leaf + arc
    walls = compile_scene(build_sample_scene()).entities(layer="WALLS")
    assert len(walls) >= 2 and all(w["closed"] for w in walls)


def test_compile_sample_renders(tmp_path):
    out = compile_scene(build_sample_scene()).render(tmp_path / "plan.png")
    assert out.stat().st_size > 1000


def test_door_style_variants():
    arc = compile_scene(_door_scene()).summary()["by_type"]
    assert arc.get("ARC") == 1 and arc.get("LINE") == 1

    double = compile_scene(_door_scene(style="double")).summary()["by_type"]
    assert double.get("ARC") == 2 and double.get("LINE") == 2

    sliding = compile_scene(_door_scene(style="sliding")).summary()
    assert "ARC" not in sliding["by_type"]
    assert sliding["by_layer"]["DOORS"] == 2  # two panel rectangles


def test_scene_style_header_applies():
    sk = compile_scene(_door_scene(door="sliding"))
    assert "ARC" not in sk.summary()["by_type"]


def test_object_style_overrides_header():
    sk = compile_scene(_door_scene(style="arc", door="sliding"))
    assert sk.summary()["by_type"].get("ARC") == 1


def test_window_style_variants():
    sc = Scene()
    sc.add_wall((0, 0), (5000, 0), 230)
    sc.add_window("W1", 1000, 1200)
    assert compile_scene(sc).summary()["by_layer"]["WINDOWS"] == 3

    sc2 = Scene()
    sc2.add_wall((0, 0), (5000, 0), 230)
    sc2.add_window("W1", 1000, 1200, style="frame")
    by_type = compile_scene(sc2).summary()["by_type"]
    assert by_type.get("LWPOLYLINE", 0) >= 2  # wall rings + frame rect


def test_label_style():
    sc = Scene()
    sc.styles["label"] = "title"
    sc.add_wall((0, 0), (5000, 0), 230)
    sc.add_label("LIVING ROOM", (2500, 500))
    sk = compile_scene(sc)
    texts = [e for e in sk.entities() if e["type"] == "TEXT"]
    assert texts[0]["text"] == "Living Room"


def test_unknown_style_is_agent_feedback():
    with pytest.raises(ToolError, match="available"):
        compile_scene(_door_scene(style="revolving"))


def test_jambs_are_capped():
    """Subtracting an opening leaves the wall body closed (jamb edges),
    so a wall with a door still compiles to closed polylines."""
    sk = compile_scene(_door_scene())
    walls = [e for e in sk.entities(layer="WALLS")]
    assert len(walls) == 2  # wall split into two capped segments
    assert all(w["closed"] for w in walls)
