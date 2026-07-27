from pathlib import Path

import pytest

from draftsmith.renderer import render_doc, render_dxf
from draftsmith.samples import build_sample_floorplan


@pytest.fixture(scope="module")
def sample_doc():
    return build_sample_floorplan()


def test_sample_floorplan_layers(sample_doc):
    layer_names = {layer.dxf.name for layer in sample_doc.layers}
    assert {"WALLS", "DOORS", "WINDOWS", "TEXT", "DIMS"} <= layer_names


def test_sample_floorplan_entities(sample_doc):
    msp = sample_doc.modelspace()
    # 3 south-wall segments (2 window openings) + north + west + east + interior
    assert len(msp.query("LWPOLYLINE[layer=='WALLS']")) == 7
    assert len(msp.query("ARC[layer=='DOORS']")) == 1
    assert len(msp.query("LINE[layer=='WINDOWS']")) == 6
    assert len(msp.query("TEXT[layer=='TEXT']")) == 2
    assert len(msp.query("DIMENSION")) == 1


@pytest.mark.parametrize("ext", [".png", ".svg", ".pdf"])
def test_render_doc_formats(sample_doc, tmp_path, ext):
    out = render_doc(sample_doc, tmp_path / f"plan{ext}")
    assert out.exists()
    assert out.stat().st_size > 1000


def test_render_dxf_roundtrip(sample_doc, tmp_path):
    dxf_path = tmp_path / "plan.dxf"
    sample_doc.saveas(dxf_path)
    out = render_dxf(dxf_path, tmp_path / "plan.png")
    assert out.exists()
    assert out.stat().st_size > 1000


def test_render_rejects_unknown_format(sample_doc, tmp_path):
    with pytest.raises(ValueError, match="Unsupported output format"):
        render_doc(sample_doc, tmp_path / "plan.bmp")


def test_render_dark_background(sample_doc, tmp_path):
    out = render_doc(sample_doc, tmp_path / "dark.png", dark=True)
    assert out.exists()
