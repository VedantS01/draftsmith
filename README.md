# draftsmith

**Natural language → DWG/DXF drawings, via LLM agents and a CAD tooling layer.**

draftsmith is a long-term research project exploring how far LLM agents can go
at producing real, high-level CAD deliverables (floorplans, kitchen layouts,
architectural drawings) from plain text — not by generating images, but by
driving a structured 2D/3D DXF tooling layer through tool calls.

See [ROADMAP.md](ROADMAP.md) for the full research plan.

## Current status: Step 2 — agent tooling layer

- **Step 1 — renderer**: any DXF → PNG/SVG/PDF via
  [ezdxf](https://ezdxf.mozman.at/)'s drawing add-on (matplotlib backend).
  The render loop is the agent's visual feedback channel.
- **Step 2 — tooling layer**: `Sketch`, a validated draw/edit/inspect API
  (the agent's "hands"), plus architectural verbs: walls with openings,
  doors with swings, windows, labels.

```python
from draftsmith import Sketch
from draftsmith.arch import add_door, add_wall

sk = Sketch()  # millimetres
add_wall(sk, (0, 0), (5000, 0), thickness=230,
         openings=[{"offset": 2000, "width": 900}])
add_door(sk, (2900, 0), width=900, angle=180, swing="right")
sk.add_aligned_dim((0, 0), (5000, 0), offset=-700)

sk.summary()   # {'entities': ..., 'by_layer': {'WALLS': 2, ...}, 'extents': ...}
sk.render("wall.png")
sk.save("wall.dxf")
```

Every operation validates its inputs and raises `ToolError` with a message
written to be read by an LLM agent; every mutation returns entity handles the
agent can `describe()`, `translate()` or `delete()` later.

The sample floorplan below is built entirely through this API
(`src/draftsmith/samples.py`):

![Sample floorplan](docs/floorplan.png)

## Quickstart

```bash
uv sync

# Generate the sample floorplan DXF and render it to PNG + SVG
uv run draftsmith demo -d demo/

# Render any DXF file
uv run draftsmith render path/to/drawing.dxf -o out.png
uv run draftsmith render path/to/drawing.dxf -o out.svg --dark

# Run tests
uv run pytest
```

## Design notes

- **Why DXF, not images?** DXF is a structured, layered, semantically
  meaningful format — the native language of CAD. It gives agents an
  editable scene graph rather than pixels, and gives evaluation (step 5) a
  ground truth to diff against.
- **Why a renderer first?** The render loop is the agent's feedback channel:
  draw → render → inspect → correct. Everything downstream depends on it.
- 3D DXF content currently renders as a flat projection; a true 3D viewport
  arrives with the web viewer in step 3.
