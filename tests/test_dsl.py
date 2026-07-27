import pytest

from draftsmith.dsl import encoding_stats, parse, serialize, to_json
from draftsmith.errors import ToolError
from draftsmith.samples import build_sample_scene


def test_roundtrip_is_exact():
    text = serialize(build_sample_scene())
    assert serialize(parse(text)) == text


def test_sample_serialization_shape():
    text = serialize(build_sample_scene())
    lines = text.strip().splitlines()
    assert lines[0] == "FP1 mm"
    assert lines[1] == "W1 0,115 8000,115 t230"
    assert "D1 W5@0 w900 hinge=far" in lines  # swing=left is default: omitted
    assert 'L1 2500,2500 "LIVING ROOM"' in lines
    assert "M1 0,0 8000,0 d-700" in lines


def test_defaults_omitted_and_restored():
    sc = parse("FP1 mm\nW1 0,0 5000,0 t230\nD1 W1@100 w900\n")
    d = sc.get("D1")
    assert (d.hinge, d.swing, d.style) == ("near", "left", None)
    sc2 = parse(
        "FP1 mm\n!S door=sliding\nW1 0,0 5000,0 t230\n"
        "D1 W1@100 w900 hinge=far swing=right style=double\n"
    )
    d2 = sc2.get("D1")
    assert (d2.hinge, d2.swing, d2.style) == ("far", "right", "double")
    assert sc2.styles == {"door": "sliding"}
    assert "hinge=far swing=right style=double" in serialize(sc2)


def test_comments_and_blanks_ignored():
    sc = parse("# a plan\nFP1 mm\n\nW1 0,0 1000,0 t100\n# done\n")
    assert len(sc.walls) == 1


@pytest.mark.parametrize(
    "text,match",
    [
        ("", "empty"),
        ("FP2 mm\n", "header"),
        ("FP1 mm\nW1 0,0 0,0 t100\n", "line 2"),
        ("FP1 mm\nX1 0,0\n", "cannot parse"),
        ("FP1 mm\nD1 W1@0 w900\n", "line 2"),  # missing wall
        ("FP1 mm\nW1 0,0 1000,0 t100\nD1 W1@0 w900 wing=left\n", "unknown field"),
        ("FP1 mm\n!S roof=tin\n", "unknown field"),
        ("FP1 mm\nW1 0,0 1000,0 t100\nW1 0,50 1000,50 t100\n", "duplicate"),
    ],
)
def test_parse_errors(text, match):
    with pytest.raises(ToolError, match=match):
        parse(text)


def test_float_coordinates_survive():
    sc = parse("FP1 mm\nW1 0,115.5 8000,115.5 t230\n")
    assert sc.get("W1").start == (0, 115.5)
    assert "0,115.5" in serialize(sc)


def test_to_json_matches_scene():
    js = to_json(build_sample_scene())
    assert js["format"] == "FP1"
    assert len(js["walls"]) == 5
    assert js["doors"][0]["wall"] == "W5"
    assert js["labels"][0]["text"] == "LIVING ROOM"


def test_fp1_is_denser_than_json():
    stats = encoding_stats(build_sample_scene())
    assert stats["ratio"] > 2.5


def test_dim_arrows_roundtrip():
    sc = parse("FP1 mm\nM1 0,0 5000,0 d-700 a=tick\nM2 0,0 0,3000 d500\n")
    assert sc.get("M1").arrows == "tick"
    assert sc.get("M2").arrows == "default"
    text = serialize(sc)
    assert "M1 0,0 5000,0 d-700 a=tick" in text
    assert "M2 0,0 0,3000 d500\n" in text  # default omitted
    assert serialize(parse(text)) == text
