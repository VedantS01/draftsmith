import math

import pytest

from draftsmith.arch import add_door, add_room_label, add_wall, add_window
from draftsmith.toolkit import Sketch, ToolError


@pytest.fixture
def sk():
    return Sketch()


def test_wall_without_openings(sk):
    handles = add_wall(sk, (0, 0), (1000, 0), thickness=200)
    assert len(handles) == 1
    info = sk.describe(handles[0])
    assert info["layer"] == "WALLS"
    assert info["closed"] is True
    assert sorted(info["points"]) == [
        (0, -100), (0, 100), (1000, -100), (1000, 100),
    ]


def test_wall_with_openings_segments(sk):
    handles = add_wall(
        sk,
        (0, 0),
        (1000, 0),
        thickness=100,
        openings=[{"offset": 200, "width": 100}, {"offset": 600, "width": 150}],
    )
    assert len(handles) == 3
    spans = []
    for h in handles:
        xs = [p[0] for p in sk.describe(h)["points"]]
        spans.append((min(xs), max(xs)))
    assert spans == [(0, 200), (300, 600), (750, 1000)]


def test_wall_opening_at_start_and_end(sk):
    handles = add_wall(
        sk, (0, 0), (1000, 0), thickness=100,
        openings=[{"offset": 0, "width": 100}, {"offset": 900, "width": 100}],
    )
    assert len(handles) == 1


def test_diagonal_wall_geometry(sk):
    (h,) = add_wall(sk, (0, 0), (1000, 1000), thickness=100 * math.sqrt(2))
    corners = sorted((round(p[0]), round(p[1])) for p in sk.describe(h)["points"])
    assert corners == [(-50, 50), (50, -50), (950, 1050), (1050, 950)]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": (0, 0), "end": (0, 0)},
        {"start": (0, 0), "end": (100, 0), "thickness": 0},
        {"start": (0, 0), "end": (100, 0), "openings": [{"offset": 50, "width": 100}]},
        {"start": (0, 0), "end": (100, 0), "openings": [{"width": 10}]},
        {"start": (0, 0), "end": (100, 0), "openings": [{"offset": 10, "width": -5}]},
        {"start": (0, 0), "end": (100, 0), "openings": [{"offset": 0, "width": 100}]},
        {
            "start": (0, 0),
            "end": (1000, 0),
            "openings": [
                {"offset": 100, "width": 300},
                {"offset": 200, "width": 100},
            ],
        },
    ],
)
def test_wall_validation(sk, kwargs):
    with pytest.raises(ToolError):
        add_wall(sk, **kwargs)


def test_door_left_swing(sk):
    leaf, arc = add_door(sk, (0, 0), width=900, angle=0, swing="left")
    leaf_info = sk.describe(leaf)
    assert leaf_info["layer"] == "DOORS"
    assert leaf_info["end"][0] == pytest.approx(0, abs=1e-6)
    assert leaf_info["end"][1] == pytest.approx(900)
    arc_info = sk.describe(arc)
    assert (arc_info["start_angle"], arc_info["end_angle"]) == (0, 90)
    assert arc_info["radius"] == 900


def test_door_right_swing(sk):
    leaf, arc = add_door(sk, (0, 0), width=800, angle=90, swing="right")
    leaf_info = sk.describe(leaf)
    assert leaf_info["end"][0] == pytest.approx(800)
    assert leaf_info["end"][1] == pytest.approx(0, abs=1e-6)
    arc_info = sk.describe(arc)
    assert (arc_info["start_angle"], arc_info["end_angle"]) == (0, 90)


def test_door_validation(sk):
    with pytest.raises(ToolError):
        add_door(sk, (0, 0), width=0)
    with pytest.raises(ToolError):
        add_door(sk, (0, 0), swing="sideways")


def test_window(sk):
    handles = add_window(sk, (100, 0), (500, 0), thickness=200)
    assert len(handles) == 3
    ys = sorted(sk.describe(h)["start"][1] for h in handles)
    assert ys == [-100, 0, 100]


def test_room_label(sk):
    h = add_room_label(sk, "KITCHEN", (100, 100))
    info = sk.describe(h)
    assert info["text"] == "KITCHEN"
    assert info["layer"] == "TEXT"
