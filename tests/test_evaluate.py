import pytest

from draftsmith.evaluate import (
    AccessGraph,
    Brief,
    _entropy_score,
    d_value,
    evaluate,
    relative_asymmetry,
    room_type,
)
from draftsmith.scene import Scene


def two_room_flat() -> Scene:
    """A clean 8x5m flat: living (5x5) + bedroom (3x5), entrance to the
    living room, windows on opposite exterior walls."""
    sc = Scene()
    w_s = sc.add_wall((0, 0), (8000, 0))
    w_e = sc.add_wall((8000, 0), (8000, 5000))
    sc.add_wall((8000, 5000), (0, 5000))
    w_w = sc.add_wall((0, 5000), (0, 0))
    part = sc.add_wall((5000, 0), (5000, 5000))
    sc.add_door(w_s.id, 1000, 900)          # entrance
    sc.add_door(part.id, 2000, 900)         # living <-> bedroom
    sc.add_window(w_w.id, 2000, 1500)       # living
    sc.add_window(w_e.id, 2000, 1500)       # bedroom
    sc.add_label("LIVING ROOM", (2500, 2500))
    sc.add_label("BEDROOM", (6500, 2500))
    return sc


def flat_with_trapped_bath() -> Scene:
    """Living + bedroom + bath, where the bath's only door opens off the
    bedroom — the RN-4 'inaccessible common bathroom' failure."""
    sc = Scene()
    w_s = sc.add_wall((0, 0), (8000, 0))
    w_e = sc.add_wall((8000, 0), (8000, 5000))
    sc.add_wall((8000, 5000), (0, 5000))
    w_w = sc.add_wall((0, 5000), (0, 0))
    part = sc.add_wall((5000, 0), (5000, 5000))
    split = sc.add_wall((5000, 3000), (8000, 3000))
    sc.add_door(w_s.id, 1000, 900)
    sc.add_door(part.id, 500, 900)          # living <-> bedroom
    sc.add_door(split.id, 1000, 750)        # bedroom <-> bath (only way in)
    sc.add_window(w_w.id, 2000, 1500)
    sc.add_window(w_e.id, 500, 1200)
    sc.add_label("LIVING ROOM", (2500, 2500))
    sc.add_label("BEDROOM", (6500, 1500))
    sc.add_label("BATH", (6500, 4000))
    return sc


def test_room_type_mapping():
    assert room_type("MASTER BEDROOM") == "bedroom"
    assert room_type("Kitchen") == "kitchen"
    assert room_type("COMMON BATH") == "bath"
    assert room_type("WC") == "wc"
    assert room_type("Passage") == "circulation"
    assert room_type("Verandah") == "balcony"
    assert room_type(None) is None
    assert room_type("MYSTERY") is None


def test_clean_flat_has_no_hard_failures():
    report = evaluate(two_room_flat())
    assert report.hard_failures == []
    correctness, compliance, soundness = report.scores
    assert correctness > 0.9
    assert compliance is None
    assert 0.0 < soundness <= 1.0
    by_name = {f.metric: f for f in report.feasibility}
    assert by_name["reachability"].score == 1.0
    assert by_name["entrance"].score == 1.0
    assert by_name["door_economy"].score == 1.0
    assert by_name["junction_clearance"].score == 1.0
    assert by_name["room_minimums"].score == 1.0
    assert by_name["door_widths"].score == 1.0


def test_unreachable_room_is_hard_failure():
    sc = two_room_flat()
    # rebuild without the interior door: bedroom becomes unreachable
    trapped = Scene()
    for w in sc.walls:
        trapped.add_wall(w.start, w.end, w.thickness, id=w.id)
    trapped.add_door("W1", 1000, 900)
    for lb in sc.labels:
        trapped.add_label(lb.text, lb.position)
    report = evaluate(trapped)
    fails = {f.metric for f in report.hard_failures}
    assert "reachability" in fails


def test_trapped_bath_flagged():
    report = evaluate(flat_with_trapped_bath())
    by_name = {f.metric: f for f in report.feasibility}
    assert by_name["common_bath_access"].score == 0.0
    assert by_name["reachability"].score == 1.0   # reachable, just badly


def test_duplicate_doors_hurt_economy():
    sc = two_room_flat()
    part = [w for w in sc.walls if w.start == (5000.0, 0.0)][0]
    sc.add_door(part.id, 3500, 900)   # second living<->bedroom door
    report = evaluate(sc)
    econ = {f.metric: f for f in report.feasibility}["door_economy"]
    assert econ.score < 1.0
    assert econ.value["duplicate_pairs"] == 1


def test_door_at_junction_flagged():
    sc = two_room_flat()
    w_s = sc.walls[0]
    sc.add_door(w_s.id, 4800, 900)    # spans the T-joint at x=5000
    report = evaluate(sc)
    jc = {f.metric: f for f in report.feasibility}["junction_clearance"]
    assert jc.score < 1.0


def test_narrow_door_flagged():
    sc = two_room_flat()
    part = [w for w in sc.walls if w.start == (5000.0, 0.0)][0]
    sc.add_door(part.id, 4000, 600)   # below any minimum
    widths = {f.metric: f for f in evaluate(sc).feasibility}["door_widths"]
    assert widths.score < 1.0


def test_brief_compliance():
    brief = Brief.from_dict({
        "rooms": {"bedroom": 1, "living": 1, "kitchen": 1},
        "areas": {"bedroom": [9, 20]},
        "adjacent": [["living", "bedroom"]],
        "total_area": [30, 50],
    })
    report = evaluate(two_room_flat(), brief)
    by_name = {f.metric: f for f in report.compliance}
    assert by_name["rooms:bedroom"].score == 1.0
    assert by_name["rooms:kitchen"].score == 0.0     # no kitchen drawn
    assert by_name["area:bedroom"].score == 1.0      # 15 m2 in [9, 20]
    assert by_name["adjacent:living<->bedroom"].score == 1.0
    assert by_name["total_area"].score == 1.0        # 40 m2
    _, compliance, _ = report.scores
    assert compliance == pytest.approx(5 / 6)


def test_privacy_genotype_ordering():
    report = evaluate(flat_with_trapped_bath())
    geno = {f.metric: f for f in report.soundness}["privacy_genotype"]
    # living(1) < bedroom(2) < bath(3): fully canonical order
    assert geno.score == 1.0


def test_space_syntax_formulas():
    # chain root-a-b: depths 0,1,2 -> MD = 1.5, RA = 2(0.5)/1 = 1.0
    g = AccessGraph(nodes=["r", "a", "b"],
                    edges=[("r", "a", "d1"), ("a", "b", "d2")])
    g.adj = {"r": {"a"}, "a": {"r", "b"}, "b": {"a"}}
    depths = g.depths_from("r")
    assert depths == {"r": 0, "a": 1, "b": 2}
    assert relative_asymmetry(1.5, 3) == pytest.approx(1.0)
    assert d_value(3) is None            # undefined below k=4
    assert d_value(5) == pytest.approx(0.352, abs=0.001)   # published table
    assert d_value(10) == pytest.approx(0.306, abs=0.001)
    assert g.cycles() == 0
    g.edges.append(("r", "b", "d3"))
    g.adj["r"].add("b")
    g.adj["b"].add("r")
    assert g.cycles() == 1


def test_entropy_score():
    assert _entropy_score([]) == 0.0
    assert _entropy_score(["arc"]) == 0.3           # lone door: neutral-ish
    assert _entropy_score(["arc", "arc", "arc"]) == 0.0
    assert _entropy_score(["arc", "sliding"]) > 0.5


def test_report_serialises():
    report = evaluate(two_room_flat())
    d = report.to_dict()
    assert set(d["scores"]) == {"correctness", "compliance", "soundness"}
    assert d["compliance"] == []
    text = report.render_text()
    assert "correctness" in text and "soundness" in text
