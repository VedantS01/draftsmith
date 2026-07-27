import pytest

from draftsmith.errors import ToolError
from draftsmith.scene import Scene


@pytest.fixture
def sc():
    return Scene()


@pytest.fixture
def walled(sc):
    sc.add_wall((0, 0), (5000, 0), 230)  # W1
    sc.add_wall((0, 0), (0, 4000), 230)  # W2
    return sc


def test_typed_sequential_ids(walled):
    assert [w.id for w in walled.walls] == ["W1", "W2"]
    d = walled.add_door("W1", 1000)
    n = walled.add_window("W1", 3000, 1200)
    lb = walled.add_label("KITCHEN", (100, 100))
    m = walled.add_dim((0, 0), (5000, 0))
    assert (d.id, n.id, lb.id, m.id) == ("D1", "N1", "L1", "M1")


def test_ids_never_reused(walled):
    d1 = walled.add_door("W1", 1000)
    walled.delete(d1.id)
    d2 = walled.add_door("W1", 1000)
    assert d2.id == "D2"
    with pytest.raises(ToolError, match="never reused"):
        walled.get("D1")


def test_explicit_ids_bump_counter(sc):
    sc.add_wall((0, 0), (100, 0), id="W7")
    assert sc.add_wall((0, 10), (100, 10)).id == "W8"
    with pytest.raises(ToolError, match="duplicate id"):
        sc.add_wall((0, 20), (100, 20), id="W7")
    with pytest.raises(ToolError, match="invalid id"):
        sc.add_wall((0, 30), (100, 30), id="D3")


def test_wall_validation(sc):
    with pytest.raises(ToolError, match="zero length"):
        sc.add_wall((1, 1), (1, 1))
    with pytest.raises(ToolError, match="thickness"):
        sc.add_wall((0, 0), (100, 0), thickness=0)


def test_opening_validation(walled):
    with pytest.raises(ToolError, match="no object"):
        walled.add_door("W9", 0)
    walled.add_label("X", (0, 0))
    with pytest.raises(ToolError, match="not a wall"):
        walled.add_door("L1", 0)
    with pytest.raises(ToolError, match="only"):
        walled.add_door("W1", 4500, 900)  # past the end
    with pytest.raises(ToolError, match="width must be positive"):
        walled.add_window("W1", 0, 0)
    walled.add_door("W1", 1000, 900)
    with pytest.raises(ToolError, match="overlaps D1"):
        walled.add_window("W1", 1500, 600)
    with pytest.raises(ToolError, match="hinge"):
        walled.add_door("W1", 3000, hinge="middle")
    with pytest.raises(ToolError, match="swing"):
        walled.add_door("W1", 3000, swing="up")


def test_delete_wall_with_openings_blocked(walled):
    walled.add_door("W1", 1000)
    with pytest.raises(ToolError, match="D1"):
        walled.delete("W1")
    walled.delete("D1")
    walled.delete("W1")
    assert [w.id for w in walled.walls] == ["W2"]


def test_move_opening(walled):
    d = walled.add_door("W1", 1000)
    walled.add_window("W1", 3000, 1200)
    walled.move_opening(d.id, 500)
    assert walled.get(d.id).offset == 500
    with pytest.raises(ToolError, match="overlaps N1"):
        walled.move_opening(d.id, 2500)
    # moving back onto its own footprint is fine (excluded from overlap check)
    walled.move_opening(d.id, 500)


def test_wall_derived_properties(sc):
    w = sc.add_wall((0, 0), (3000, 4000), 200)
    assert w.length == 5000
    assert w.direction == pytest.approx((0.6, 0.8))
    assert w.normal == pytest.approx((-0.8, 0.6))
    assert w.point_at(2500) == pytest.approx((1500, 2000))


def test_openings_on_sorted(walled):
    walled.add_door("W1", 3000)
    walled.add_window("W1", 500, 600)
    assert [o.id for o in walled.openings_on("W1")] == ["N1", "D1"]


def test_dim_arrows_and_update(sc):
    m = sc.add_dim((0, 0), (5000, 0), arrows="tick")
    assert m.arrows == "tick"
    sc.update_dim(m.id, offset=900, arrows="empty")
    assert (sc.get(m.id).offset, sc.get(m.id).arrows) == (900, "empty")
    with pytest.raises(ToolError, match="arrows"):
        sc.add_dim((0, 0), (100, 0), arrows="harpoon")
    with pytest.raises(ToolError, match="arrows"):
        sc.update_dim(m.id, arrows="harpoon")
    with pytest.raises(ToolError, match="non-zero"):
        sc.update_dim(m.id, offset=0)
    sc.add_wall((0, 0), (1000, 0))
    with pytest.raises(ToolError, match="not a dimension"):
        sc.update_dim("W1", offset=500)
