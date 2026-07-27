import pytest

from draftsmith.agent import check, extract_fp, feedback, system_prompt, warnings_for
from draftsmith.dsl import serialize
from draftsmith.errors import ToolError
from draftsmith.samples import build_sample_scene
from draftsmith.scene import Scene


def test_system_prompt_covers_fp1():
    prompt = system_prompt()
    for token in ["FP1 mm", "W<n>", "hinge", "swing", "```fp", "OK:", "ERROR"]:
        assert token in prompt


def test_extract_fp_variants():
    fp = "FP1 mm\nW1 0,0 1000,0 t230\n"
    assert extract_fp(fp) == fp
    chat = f"Here is the plan:\n```fp\n{fp}```\nDone."
    assert extract_fp(chat) == fp
    untagged = f"```\n{fp}```"
    assert extract_fp(untagged) == fp
    with pytest.raises(ToolError, match="no FP1 document"):
        extract_fp("hello there")


def test_feedback_sample():
    report = feedback(build_sample_scene())
    assert "OK: 5 walls, 1 doors, 2 windows, 2 labels, 1 dims" in report
    assert 'R1 "LIVING ROOM"' in report and "21.38 m2" in report
    assert "D1 door" in report and "R1 <-> R2" in report
    assert "N1 window" in report and "EXT" in report
    assert "warnings:" not in report


def test_check_roundtrip_and_errors():
    scene, report = check(f"```fp\n{serialize(build_sample_scene())}```")
    assert scene is not None and report.startswith("OK:")

    scene, report = check("```fp\nFP1 mm\nD1 W9@0 w900\n```")
    assert scene is None
    assert report.startswith("ERROR") and "line 2" in report


def test_warnings_open_walls_and_labels():
    sc = Scene()
    sc.add_wall((0, 0), (5000, 0))
    sc.add_wall((0, 1000), (5000, 1000))  # parallel, no loop
    warns = warnings_for(sc)
    assert any("no enclosed rooms" in w for w in warns)
    assert any("no dimensions" in w for w in warns)


def test_warnings_label_placement():
    sc = build_sample_scene()
    sc.add_label("OUTSIDE", (20000, 20000))
    sc.add_label("EXTRA", (2000, 2000))  # second label in living room
    warns = warnings_for(sc)
    assert any('L3 "OUTSIDE" is not inside any room' in w for w in warns)
    assert any("multiple labels" in w for w in warns)


def test_warning_interior_window():
    sc = build_sample_scene()
    sc.add_window("W5", 2000, 900)  # interior wall
    warns = warnings_for(sc)
    assert any("interior wall" in w for w in warns)


def test_cli_check_and_prompt(tmp_path, capsys):
    from draftsmith.cli import main

    fp_file = tmp_path / "plan.fp"
    fp_file.write_text(serialize(build_sample_scene()))
    out_png = tmp_path / "plan.png"
    main(["check", str(fp_file), "--render", str(out_png)])
    out = capsys.readouterr().out
    assert out.startswith("OK:") and out_png.exists()

    bad = tmp_path / "bad.fp"
    bad.write_text("FP1 mm\nW1 0,0 0,0 t230\n")
    with pytest.raises(SystemExit):
        main(["check", str(bad)])
    assert capsys.readouterr().out.startswith("ERROR")

    main(["prompt"])
    assert "drafting agent" in capsys.readouterr().out


def test_warning_dim_inside_building():
    sc = build_sample_scene()
    # vertical dim south->north with negative offset = inside the plan
    sc.add_dim((0, 0), (0, 5000), offset=-700)
    warns = warnings_for(sc)
    assert any("M2 runs inside the building" in w for w in warns)
    # the correctly-placed original M1 is not flagged
    assert not any("M1 runs inside" in w for w in warns)
