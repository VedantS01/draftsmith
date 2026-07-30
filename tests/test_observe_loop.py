import json

import pytest

from draftsmith.dsl import parse
from draftsmith.evaluate import Brief
from draftsmith.loop import DraftingLoop, _extract_plan, _validate_plan
from draftsmith.observe import answer, is_query
from draftsmith.scene import Scene


@pytest.fixture(scope="module")
def flat() -> Scene:
    sc = Scene()
    sc.add_wall((0, 0), (8000, 0))
    sc.add_wall((8000, 0), (8000, 5000))
    sc.add_wall((8000, 5000), (0, 5000))
    sc.add_wall((0, 5000), (0, 0))
    sc.add_wall((5000, 0), (5000, 5000), 115)
    sc.add_door("W1", 1000, 900)
    sc.add_door("W5", 2000, 900)
    sc.add_window("W4", 2000, 1500)
    sc.add_label("LIVING ROOM", (2500, 2500))
    sc.add_label("BEDROOM", (6500, 2500))
    return sc


def test_is_query():
    assert is_query("?walls")
    assert is_query(" ?rooms \n?graph")
    assert not is_query("FP1 mm\nW1 0,0 1,1 t230")
    assert not is_query("?walls\nFP1 mm")
    assert not is_query("")


def test_walls_and_joints_answers(flat):
    walls = answer(flat, "?walls")
    assert "W5" in walls and "t115" in walls and "len 5000" in walls
    assert "free ends" not in walls          # closed plan
    joints = answer(flat, "?joints")
    assert "wall graph" in joints
    assert "W5: W1,W3" in joints             # partition touches top+bottom


def test_dangling_wall_flagged(flat):
    sc = parse(  # same flat, plus a floating wall stub
        "FP1 mm\nW1 0,0 8000,0 t230\nW2 8000,0 8000,5000 t230\n"
        "W3 8000,5000 0,5000 t230\nW4 0,5000 0,0 t230\n"
        "W5 2000,2000 3000,2000 t115\n")
    out = answer(sc, "?walls")
    assert "free ends" in out and "W5" in out.split("free ends")[1]


def test_wall_detail_sides(flat):
    out = answer(flat, "?wall W5")
    assert "separates:" in out
    assert "LIVING ROOM" in out and "BEDROOM" in out


def test_room_detail_and_graph(flat):
    out = answer(flat, "?room bedroom")
    assert "depth from outside: 2" in out
    assert "door D2 -> R1(LIVING ROOM)" in out
    graph = answer(flat, "?graph")
    assert "<-D1-> EXT" in graph or "EXT <-D1->" in graph
    sealed = answer(flat, "?room nosuch")
    assert "no room matching" in sealed


def test_bad_query_gets_help(flat):
    assert "?walls" in answer(flat, "?frobnicate")


# --------------------------------------------------------------------------
# Scripted end-to-end loop run (no API).

PLAN_REPLY = """Here is the program.
```plan
{"rooms": [{"label": "LIVING ROOM", "area_m2": 25},
           {"label": "BEDROOM", "area_m2": 15}],
 "adjacency": [["LIVING ROOM", "BEDROOM"]]}
```"""

PERIMETER_FP = """```fp
FP1 mm
W1 0,0 8000,0 t230
W2 8000,0 8000,5000 t230
W3 8000,5000 0,5000 t230
W4 0,5000 0,0 t230
D1 W1@1000 w900
```"""

ROOMS_FP = """```fp
FP1 mm
W1 0,0 8000,0 t230
W2 8000,0 8000,5000 t230
W3 8000,5000 0,5000 t230
W4 0,5000 0,0 t230
W5 5000,0 5000,5000 t115
D1 W1@1000 w900
D2 W5@2000 w900
L1 2500,2500 "LIVING ROOM"
L2 6500,2500 "BEDROOM"
```"""

REFINE_FP = """```fp
FP1 mm
W1 0,0 8000,0 t230
W2 8000,0 8000,5000 t230
W3 8000,5000 0,5000 t230
W4 0,5000 0,0 t230
W5 5000,0 5000,5000 t115
D1 W1@1000 w900
D2 W5@2000 w900
N1 W4@1500 w1500
N2 W2@1500 w1500
N3 W1@6000 w1200
N4 W3@1000 w1200
L1 2500,2500 "LIVING ROOM"
L2 6500,2500 "BEDROOM"
M1 0,0 8000,0 d-800
M2 0,0 0,5000 d800
```"""


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def two_room_brief() -> Brief:
    return Brief.from_dict({
        "rooms": {"bedroom": 1, "living": 1},
        "adjacent": [["living", "bedroom"]],
        "total_area": [35, 45],
    })


def test_loop_happy_path_with_query():
    runner = Scripted([
        PLAN_REPLY,
        PERIMETER_FP,
        "?rooms\n?graph",      # look before carving — free, not a round
        ROOMS_FP,
        REFINE_FP,
    ])
    loop = DraftingLoop(runner, "a small 1-bed flat", two_room_brief())
    result = loop.run()
    assert [p.name for p in result.phases] == \
        ["plan", "perimeter", "rooms", "refine"]
    assert all(p.ok for p in result.phases), result.summary()
    assert result.phases[2].queries == 1
    assert result.report is not None and result.report.hard_failures == []
    # engine answered the query inside the rooms phase
    engine_texts = [t.text for t in result.transcript if t.role == "engine"]
    assert any("depth from outside" in t or "no enclosed rooms" not in t
               for t in engine_texts)
    # the plan context reached the model
    assert any("AGREED PROGRAM" in p for p in runner.prompts)


def test_loop_plan_rework():
    bad_plan = "```plan\n{\"rooms\": []}\n```"
    runner = Scripted([bad_plan, PLAN_REPLY, PERIMETER_FP,
                       ROOMS_FP, REFINE_FP])
    loop = DraftingLoop(runner, "a small 1-bed flat", two_room_brief())
    result = loop.run()
    assert result.phases[0].ok and result.phases[0].fp_rounds == 2


def test_loop_perimeter_rejects_split_region():
    runner = Scripted([PLAN_REPLY, ROOMS_FP, PERIMETER_FP,
                       ROOMS_FP, REFINE_FP])
    loop = DraftingLoop(runner, "a small 1-bed flat", two_room_brief())
    result = loop.run()
    peri = result.phases[1]
    assert peri.ok and peri.fp_rounds == 2  # first attempt had 2 regions


def test_plan_validation():
    program = _extract_plan(PLAN_REPLY)
    assert _validate_plan(program, two_room_brief()) == []
    stingy = Brief.from_dict({"rooms": {"bedroom": 2}})
    problems = _validate_plan(program, stingy)
    assert problems and "bedroom" in problems[0]


def test_loop_gives_up_without_program():
    runner = Scripted(["nonsense"] * 4)
    loop = DraftingLoop(runner, "flat", two_room_brief())
    result = loop.run()
    assert not result.phases[0].ok
    assert len(result.phases) == 1          # stops after plan fails
    assert result.report is None
