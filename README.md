# draftsmith

**Natural language → DWG/DXF drawings, via LLM agents and a CAD tooling layer.**

draftsmith is a long-term research project exploring how far LLM agents can go
at producing real, high-level CAD deliverables (floorplans, kitchen layouts,
architectural drawings) from plain text — not by generating images, but by
driving a structured 2D/3D DXF tooling layer through tool calls.

See [ROADMAP.md](ROADMAP.md) for the full research plan.

## Current status: Step 1 — DXF renderer

A 2D renderer built on [ezdxf](https://ezdxf.mozman.at/)'s drawing add-on
(matplotlib backend), plus a programmatic sample-drawing generator. This is
the foundation the agent tooling layer (step 2) will build on: agents need to
*see* what they drew.

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
