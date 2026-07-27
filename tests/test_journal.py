import pytest

from draftsmith.dsl import serialize
from draftsmith.errors import ToolError
from draftsmith.journal import Recorder, replay
from draftsmith.samples import build_sample_scene


def _build(rec: Recorder) -> None:
    rec.apply("add_wall", start=[0, 0], end=[5000, 0], thickness=230)
    rec.apply("add_wall", start=[0, 0], end=[0, 4000])  # default thickness
    rec.apply("add_door", wall="W1", offset=1000, hinge="far")
    rec.apply("add_window", wall="W1", offset=3000, width=1200)
    rec.apply("add_label", text="KITCHEN", position=[2500, 2000])
    rec.apply("add_dim", p1=[0, 0], p2=[5000, 0])
    rec.apply("set_style", slot="door", name="sliding")


def test_replay_reproduces_scene():
    rec = Recorder()
    _build(rec)
    assert serialize(replay(rec.entries)) == serialize(rec.scene)


def test_apply_returns_ids_and_records():
    rec = Recorder()
    assert rec.apply("add_wall", start=[0, 0], end=[1000, 0]) == "W1"
    assert rec.entries[0]["op"] == "add_wall"
    assert rec.entries[0]["result"] == "W1"
    assert rec.entries[0]["seq"] == 1


def test_undo():
    rec = Recorder()
    _build(rec)
    fp_before = serialize(rec.scene)
    rec.apply("add_label", text="OOPS", position=[100, 100])
    rec.undo()
    assert serialize(rec.scene) == fp_before
    # the id L2 stays retired even after undo replay? Replay rebuilds from
    # entries, so counters reflect only surviving entries: next label is L2.
    assert rec.apply("add_label", text="PANTRY", position=[4000, 500]) == "L2"


def test_undo_empty():
    with pytest.raises(ToolError, match="nothing to undo"):
        Recorder().undo()


def test_journal_file_persist_and_resume(tmp_path):
    path = tmp_path / "session.jsonl"
    rec = Recorder(path)
    _build(rec)
    fp = serialize(rec.scene)

    resumed = Recorder(path)  # replays the file
    assert serialize(resumed.scene) == fp
    resumed.apply("delete", id="N1")
    assert len(Recorder(path).entries) == 8


def test_undo_rewrites_file(tmp_path):
    path = tmp_path / "session.jsonl"
    rec = Recorder(path)
    _build(rec)
    rec.undo()
    assert len(path.read_text().splitlines()) == 6
    assert serialize(Recorder(path).scene) == serialize(rec.scene)


def test_load_op():
    rec = Recorder()
    rec.apply("load", fp=serialize(build_sample_scene()))
    assert len(rec.scene.walls) == 5
    assert serialize(replay(rec.entries)) == serialize(rec.scene)


def test_bad_ops_do_not_journal():
    rec = Recorder()
    with pytest.raises(ToolError, match="unknown op"):
        rec.apply("explode")
    with pytest.raises(ToolError, match="missing required arg"):
        rec.apply("add_wall", start=[0, 0])
    with pytest.raises(ToolError, match="unknown style slot"):
        rec.apply("set_style", slot="roof", name="tin")
    with pytest.raises(ToolError):
        rec.apply("load", fp="not a floorplan")
    assert rec.entries == []


def test_failed_op_leaves_scene_intact():
    rec = Recorder()
    rec.apply("add_wall", start=[0, 0], end=[5000, 0])
    with pytest.raises(ToolError):
        rec.apply("add_door", wall="W9", offset=0)
    assert len(rec.entries) == 1
    assert serialize(replay(rec.entries)) == serialize(rec.scene)


def test_redo_stack():
    rec = Recorder()
    _build(rec)
    fp_full = serialize(rec.scene)
    rec.undo()
    rec.undo()
    rec.redo()
    rec.redo()
    assert serialize(rec.scene) == fp_full
    with pytest.raises(ToolError, match="nothing to redo"):
        rec.redo()


def test_new_op_clears_redo():
    rec = Recorder()
    _build(rec)
    rec.undo()
    rec.apply("add_label", text="NEW", position=[1, 1])
    with pytest.raises(ToolError, match="nothing to redo"):
        rec.redo()


def test_update_dim_op():
    rec = Recorder()
    rec.apply("add_dim", p1=[0, 0], p2=[4000, 0], arrows="arrow")
    rec.apply("update_dim", id="M1", offset=950, arrows="tick")
    assert rec.scene.get("M1").offset == 950
    assert serialize(replay(rec.entries)) == serialize(rec.scene)
