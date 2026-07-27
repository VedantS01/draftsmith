import pytest

from draftsmith.geometry import connections, rooms, summary, wall_body
from draftsmith.samples import build_sample_scene
from draftsmith.scene import Scene


@pytest.fixture(scope="module")
def sample():
    return build_sample_scene()


def test_two_rooms_with_labels_and_areas(sample):
    rs = rooms(sample)
    assert [r.id for r in rs] == ["R1", "R2"]
    living, bedroom = rs
    assert living.label == "LIVING ROOM"
    assert bedroom.label == "BEDROOM"
    assert living.area_m2 == pytest.approx(21.38, abs=0.05)
    assert bedroom.area_m2 == pytest.approx(12.30, abs=0.05)


def test_connections(sample):
    conns = {c["opening"]: c for c in connections(sample)}
    assert sorted(conns["D1"]["rooms"]) == ["R1", "R2"]
    assert conns["D1"]["kind"] == "door"
    assert sorted(conns["N1"]["rooms"]) == ["EXT", "R1"]
    assert sorted(conns["N2"]["rooms"]) == ["EXT", "R2"]


def test_wall_body_openings_reduce_area(sample):
    solid = wall_body(sample, cut_openings=False)
    cut = wall_body(sample, cut_openings=True)
    assert cut.area < solid.area
    # 2 windows (1200 wide) + 1 door (900) punched through
    punched = solid.area - cut.area
    assert punched == pytest.approx(1200 * 230 * 2 + 900 * 120, rel=0.05)


def test_wall_joins_are_merged(sample):
    solid = wall_body(sample, cut_openings=False)
    # 5 wall rectangles union into a single connected body
    assert solid.geom_type == "Polygon"
    # ...with exactly two holes: the two rooms
    assert len(solid.interiors) == 2


def test_empty_scene():
    assert rooms(Scene()) == []
    assert wall_body(Scene()).is_empty


def test_open_layout_has_no_rooms():
    sc = Scene()
    sc.add_wall((0, 0), (5000, 0), 230)
    sc.add_wall((0, 1000), (5000, 1000), 230)  # parallel walls, open ends
    assert rooms(sc) == []


def test_summary(sample):
    s = summary(sample)
    assert (s["walls"], s["doors"], s["windows"]) == (5, 1, 2)
    assert [r["label"] for r in s["rooms"]] == ["LIVING ROOM", "BEDROOM"]
    assert all(len(c["rooms"]) == 2 for c in s["connections"])


def test_l_joint_is_mitered():
    from shapely.geometry import Point as SPoint

    sc = Scene()
    sc.add_wall((0, 0), (2000, 0), 200)
    sc.add_wall((2000, 0), (2000, 1500), 200)
    body = wall_body(sc, cut_openings=False)
    # outer corner of the L is filled (plain rectangles leave a notch there)
    assert body.contains(SPoint(2090, -90))
    assert body.geom_type == "Polygon"


def test_joints_grouping():
    from draftsmith.geometry import joints

    sc = Scene()
    sc.add_wall((0, 0), (2000, 0))
    sc.add_wall((2000, 0), (2000, 1500))
    js = {tuple(j["at"]): sorted(j["walls"]) for j in joints(sc)}
    assert js[(2000, 0)] == ["W1", "W2"]
    assert js[(0, 0)] == ["W1"]
    assert len(js) == 3
