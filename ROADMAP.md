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
- **Zero-cost public showcase + shared LLM gateway** (2026-07-29):
  GitHub Pages demo live at vedants01.github.io/draftsmith — landing
  page + the full studio in-browser via Pyodide (Shapely, matplotlib,
  ezdxf; no app server). Hosted chat is served by the shared
  multi-project **ai-gateway** Cloudflare Worker
  (github.com/VedantS01/ai-gateway; draftsmith is the pilot project,
  pinned gemini-3.5-flash), with BYOK fallback — a Gemini or OpenRouter
  key pasted in the browser calls the provider directly (CORS verified)
  — and canned demo mode for key-less visitors. Decision record:
  docs/llm_providers.md.

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
- **M4 — Benchmark v0** (NL brief → DXF by tool-using agent): metric
  framework designed and deterministic layers shipped (2026-07-29) —
  `evaluate.py` + `draftsmith evaluate` score (correctness, compliance,
  soundness) tuples: feasibility hard checks (reachability, trapped
  bath/bedroom, WC-off-kitchen, door economy, junction clearance,
  NBC/IRC minimums, glazing), Brief-JSON compliance, and space-syntax /
  proportion / Alexander-pattern soundness measures. Full metric
  catalog, judge rubric (pairwise VLM vs anchors, architect-rubric
  axes), thresholds with citations: **docs/evaluation.md**. Remaining:
  brief suites + runner; Tell2Design room-box export (micro/macro IoU)
  for external comparability; judge runner + human-agreement
  validation; isovist zoning + daylight-depth metrics (deferred,
  engine backlog).
- **M2b — Iterative drafting loop** ✅ v0 (2026-07-30): `loop.py` +
  `draftsmith loop` — plan (program JSON validated against the Brief
  before geometry) → perimeter-first → rooms carved one per turn →
  refine, with rework rounds and phase-gated findings
  (findings-not-scores; judge held out — design: **docs/agent_loop.md**).
  **Observation layer** `observe.py`: `?`-query protocol (walls/joints/
  free-ends, room graph + depths, per-wall and per-room detail) wired
  into the loop, the studio chat, and the agent prompt — the toolless
  precursor of the MCP tool surface. Domain doctrine shipped as
  `design_guidelines.md` (`draftsmith prompt --design`). Remaining:
  run the loop-vs-single-shot experiment (M5); journal-op recording of
  loop sessions; streaming progress in the studio.
- **M5 — Agent research**: first experiment: baseline single-shot vs
  plan-first vs full iterative loop on the M4 tuple (docs/agent_loop.md);
  then self-inspection vs domain-skill prompting (`--design` on/off);
  feedback-modality ablation (pushed warnings vs geometric queries vs
  render-to-VLM); IR-representation ablation (FP1 vs JSON vs prose).
  Paper target lives here.
- **M6 — Recognition track**: rule-based DXF → scene lifting (import real
  DXFs); recognizer-as-judge integration; later: train NN models
  (png→scene) on the M3 synthetic data, evaluate on
  CubiCasa5k/FloorplanCAD.
- **M7b — Studio v1**: ~~chat panel over the agent surface~~ ✅ (local
  `claude` CLI backend, auto-retry, journal-recorded); ~~cloud API
  transport~~ ✅ (`ApiRunner`: any OpenAI-compatible endpoint via
  `DRAFTSMITH_API_*` env vars; provider picks + zero-cost showcase plan
  in docs/llm_providers.md); remaining: multi-label room handling;
  streaming chat responses; Pyodide/GitHub-Pages showcase build
  (docs/llm_providers.md §showcase).
- **M8 — SDK/plugin**: stable public facade + adapters for third-party
  design tools (e.g. Infurnia); DXF in/out, JSON interchange.

## Engine backlog (rolling)

- ~~Agent-feedback checks from RN-4~~ ✅ implemented in `evaluate.py`
  (2026-07-29); remaining: surface the feasibility layer's findings in
  `warnings_for` so the chat auto-retry loop sees them too
- Isovist / visibility-graph zoning metric + daylight-depth metric
  (docs/evaluation.md "deferred"); calibrate on RPLAN/Swiss Dwellings

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
