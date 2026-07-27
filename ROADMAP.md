# draftsmith — roadmap

Goal: a floorplan scene-graph engine with four surfaces — LLM-agent
drafting, synthetic dataset generation, a human design tool, and an
SDK/plugin for third-party design software — plus a research program
(agentic floorplan drafting benchmark + ablations) built on it.
Architecture and decisions live in [DESIGN.md](DESIGN.md).

## Done

- **M0 — Rendering + primitive toolkit** (was steps 1–2): DXF →
  PNG/SVG/PDF renderer; `Sketch` validated draw/edit/inspect layer over
  ezdxf; CLI (`render`, `demo`).
- **M1 — Scene-graph core**: semantic IR
  (walls/doors/windows/labels/dims, typed retiring IDs, validation);
  **FP1** token-efficient canonical format + JSON interchange; derived
  geometry (wall-join union, rooms, adjacency, summaries); style
  compiler with first variety packs (doors: arc/double/sliding, windows:
  triple/frame, labels: plain/caps/title); CLI `compile`.
- **M7a — Studio v0** (pulled forward; potential standalone product):
  local web app (`draftsmith ui`) — graphical wall/door/window/label/dim
  editing, selection, undo, live rooms/areas, two-way FP1 panel, DXF
  export; **action journal** (`journal.py`): every graphical or
  programmatic edit recorded as a named op, replayable to the identical
  scene, persistable as JSONL (future usage-data collection). The op
  vocabulary doubles as the M2 agent tool surface.

## Next

- **M2 — Agent surface** ✅ (toolless text protocol done): system prompt
  teaching FP1 + conventions (`draftsmith prompt`); engine feedback
  channel — `draftsmith check` validates chat output and returns rooms/
  areas/connections/warnings or precise errors (`agent.py`). Verified
  end-to-end with a toolless Claude Sonnet session (first-shot valid
  plan; see docs/agent_example.md). Deferred: MCP server / native tool
  schemas over the journal ops — transport decision pending.
- **M3 — Style catalog + dataset factory v0**: hatch patterns, line
  weights, dimension styles, more door/window/label variants; layout
  samplers (procedural first, RPLAN/Swiss-Dwellings-informed later);
  raster degradation (blur, noise, scan artifacts); paired
  FP1/DXF/SVG/PNG + masks/junction labels in CubiCasa5k- and
  FloorplanCAD-compatible formats.
- **M4 — Benchmark v0** (NL brief → DXF by tool-using agent): brief
  suites (terse → dimensioned), layered metrics: file validity →
  geometric fidelity (room IoU, wall-graph edit distance, opening
  placement error) → constraint satisfaction (areas, adjacency, swing
  directions) → drafting quality (pretrained symbol-spotter as judge)
  → **design quality** (see docs/research_notes.md RN-5: space-syntax
  integration/depth, isovist zoning, proportion & style-diversity
  measures, judge rubric). Scores are (correctness, compliance,
  design-quality) tuples, not a single number. Also: export adapter to
  Tell2Design room-box format for external comparability.
- **M5 — Agent research**: baseline vs plan-mode vs self-inspection vs
  domain-skill prompting; feedback-modality ablation (render vs geometric
  queries vs recognizer-critic); IR-representation ablation (FP1 vs JSON
  vs prose). Paper target lives here.
- **M6 — Recognition track**: rule-based DXF → scene lifting (import real
  DXFs); recognizer-as-judge integration; later: train NN models
  (png→scene) on the M3 synthetic data, evaluate on
  CubiCasa5k/FloorplanCAD.
- **M7b — Studio v1**: ~~chat panel over the agent surface~~ ✅ (local
  `claude` CLI backend, auto-retry, journal-recorded); remaining:
  multi-label room handling; streaming chat responses; hosted deployment
  packaging (if floated as a product).
- **M8 — SDK/plugin**: stable public facade + adapters for third-party
  design tools (e.g. Infurnia); DXF in/out, JSON interchange.

## Engine backlog (rolling)

- Agent-feedback checks from RN-4: room reachability from entrance
  (accessibility graph), opening-vs-junction clearance, door economy
  (duplicate room-pair doors, door/room ratio)

- Curved walls (arc centerlines); wall endcap styles
- Blocks/symbol library (fixtures, furniture) + placement semantics
- Dimension chains, leader annotations; label auto-placement
- Query-by-region, nearest-entity, snap suggestions for the agent surface
- Tokenizer-measured FP1 micro-syntax freeze (see DESIGN.md)
- Layer filtering & viewport control in the renderer; 3D height attribute
  + axonometric render (much later)

## External anchors

Tell2Design (text→layout eval, research-only) · FloorplanCAD +
ArchCAD-400K (vector recognition) · CubiCasa5k (raster parsing) · Swiss
Dwellings CC BY 4.0 (realism calibration) · MSD (multi-unit constraints).
Full survey and licensing notes: DESIGN.md.
