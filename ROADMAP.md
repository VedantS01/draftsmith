# draftsmith — research roadmap

Goal: a product/tool that draws high-level DWG/DXF drawings from natural
text, using LLM agents over a 2D/3D DXF tooling layer — and, along the way,
a body of research on agentic CAD generation worth writing up.

## Step 1 — 2D/3D DXF renderer ✅ (2D MVP done)

- [x] Render DXF modelspace to PNG / SVG / PDF (ezdxf drawing add-on + matplotlib)
- [x] Light/dark backgrounds, DPI control, CLI (`draftsmith render`)
- [x] Programmatic sample floorplan + end-to-end tests
- [ ] Layer filtering and viewport/extents control
- [ ] 3D: isometric/axonometric projection of 3D entities; later a real 3D view

## Step 2 — Tooling layer to edit/make a 2D/3D DXF ✅ (core done)

A clean, agent-friendly API over ezdxf: the "hands" of the system
(`draftsmith.toolkit.Sketch` + `draftsmith.arch`).

- [x] Primitive ops: lines, polylines, rects, arcs, circles, text, aligned dimensions, layers
- [x] Higher-level ops: wall with openings, door + swing, window, room label
- [x] Scene inspection ops: entities/describe (JSON-friendly), summary, extents, measure
- [x] Edit ops: delete, translate (by entity handle)
- [x] Validating operations raising `ToolError` with agent-readable messages
- [ ] Blocks (symbol libraries) and hatches
- [ ] Structural grid helper; query-by-region
- [ ] Wall joins/mitres at corners (currently butt joints only)

## Step 3 — UI: interactive tool

- Web viewer (SVG or three.js) with chat alongside the canvas
- Live re-render on each agent edit; version history / undo
- Human-in-the-loop: user can annotate/select entities to ground the next instruction

## Step 4 — Raw LLM agentic surface

- Expose the step-2 tooling layer as tool definitions (likely MCP + direct API)
- General-purpose agent loop: instruction → tool calls → render → visual/textual feedback → iterate
- Baseline: how far does an off-the-shelf agent get with zero customization?
  This baseline is the control for everything after it.

## Step 5a — Evaluation & benchmarking

- Task suite: text prompts → reference drawings, graded by difficulty
  (single shape → dimensioned part → room → full floorplan → kitchen layout)
- Metrics: geometric fidelity (entity/layer diff vs reference), constraint
  satisfaction (dimensions, clearances), instruction adherence, edit-turn count, cost
- LLM-as-judge on renders vs programmatic DXF diffing — measure agreement between the two
- Compare models and (later) harnesses on the same suite

## Step 5 — Customized agentic flow

- Plan mode: layout planning pass before drawing (rooms/zones/adjacency), then execution
- Specialized system prompts; drawing-order strategies (walls → openings → fixtures → annotation)
- Agent harness: self-inspection loop (render + query after each phase), retry policies,
  subagents (e.g. a "checker" agent grading the render against the instruction)
- Measure each intervention against the step-4 baseline on the step-5a suite

## Step 6 — Domain specialization

- Floorplans / kitchens / architectural drawing conventions as skills:
  standard dimensions (counter depths, door widths, clearances), symbol libraries
  (blocks), layer conventions, annotation standards
- Knowledge-augmented prompting vs fine-grained tools vs retrieval — what moves the needle?
- Case studies: full kitchen from a paragraph; apartment plan from a listing description

## Research paper angles

- Ablation story: raw agent → +plan mode → +self-inspection → +domain skills,
  all on one benchmark (steps 4→6 measured by 5a)
- Structured CAD output as an agent benchmark: verifiable, compositional,
  long-horizon, tool-heavy — a nice complement to code benchmarks
- The render-inspect feedback loop: how much does visual feedback help vs
  scene-graph (textual) feedback?

## Conventions

- Python + [ezdxf](https://ezdxf.mozman.at/) + uv; tests with pytest
- GitHub: [VedantS01/draftsmith](https://github.com/VedantS01/draftsmith)
- Each step lands as a working increment on `main` via PRs; benchmarks and
  experiment logs live in-repo for reproducibility
