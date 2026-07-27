"""Render DXF documents to raster/vector images.

Step 1 of the draftsmith roadmap: a 2D renderer built on ezdxf's drawing
add-on with a matplotlib backend. Supports PNG, SVG, and PDF output.

3D DXF content (meshes, 3D faces, extruded entities) is drawn as a flat
top-down projection for now; a true 3D viewport is planned for the web
viewer in step 3.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import matplotlib

matplotlib.use("Agg")  # headless: must be set before pyplot is imported

import matplotlib.pyplot as plt
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.document import Drawing

SUPPORTED_FORMATS = {".png", ".svg", ".pdf"}


def render_doc(
    doc: Drawing,
    out_path: str | Path,
    *,
    dpi: int = 300,
    dark: bool = False,
) -> Path:
    """Render the modelspace of an in-memory DXF document to an image file.

    The output format is inferred from the file extension of ``out_path``
    (one of .png, .svg, .pdf).
    """
    out_path = Path(out_path)
    if out_path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported output format {out_path.suffix!r}; "
            f"expected one of {sorted(SUPPORTED_FORMATS)}"
        )

    msp = doc.modelspace()
    fig = plt.figure()
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    policy = BackgroundPolicy.BLACK if dark else BackgroundPolicy.WHITE
    config = Configuration(background_policy=policy)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend, config=config).draw_layout(msp, finalize=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi, facecolor=ax.get_facecolor())
    plt.close(fig)
    return out_path


def render_dxf(
    dxf_path: str | Path,
    out_path: str | Path,
    *,
    dpi: int = 300,
    dark: bool = False,
) -> Path:
    """Load a DXF file and render its modelspace to an image file."""
    doc = ezdxf.readfile(str(dxf_path))
    return render_doc(doc, out_path, dpi=dpi, dark=dark)
