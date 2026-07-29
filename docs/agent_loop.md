# The iterative drafting loop (decision record, 2026-07-29)

Direction decided after the M4 evaluation landed: the drafting agent
moves from single-shot emit-and-revise to a **phased loop with the
engine as critic**. This note records why and the design constraints,
before implementation.

## Why a loop

- **Observed failures are feedback-starved, not intelligence-starved.**
  RN-1 (dimension inside the building) was textually valid — no parser
  could catch it, a render or geometric query catches it instantly.
  RN-4's trapped bathroom and 16-doors-for-13-rooms are the same
  shape: the model emits a whole plan blind and errors compound with
  nothing pushing back mid-flight. Single-shot caps quality at
  whatever the model can simulate in its head.
- **Literature agreement.** The strongest systems are rough-to-fine:
  HouseTune/HouseLLM drafts a rough layout then refines; Graph2Plan
  and the House-GAN line pass through a bubble-diagram intermediate;
  the RLVR paper shows deterministic verifiable feedback signals
  improve floorplan generation. Nobody runs it as an *interactive
  engine loop* — that's draftsmith's edge.

## The phases

1. **Plan** (no geometry): brief → the model commits to a program —
   room list, target areas, adjacency graph; essentially authoring the
   `Brief` JSON + bubble diagram. The engine validates the *program*
   against the brief before a wall exists. Catches RN-4's skipped
   passageway at turn one, when it's cheap.
2. **Block-out**: rooms as rough rectangles; feedback restricted to
   reachability / adjacency / areas. Coarse checks only.
3. **Refine**: walls merged/carved, openings placed, styles and
   annotation; full `evaluate()` findings each turn.

## Design constraints

- **Findings are the feedback, scores are the benchmark.** Per-metric
  findings ("bath R7 only reachable through bedroom R4", "door D3
  within 100mm of junction") are actionable; "soundness 0.79" is not.
  The tuple never enters the loop.
- **Phase-gate the feedback.** Junction-clearance complaints during
  block-out are noise. Each phase sees only its layer's findings.
- **Queries vs pushed feedback vs render are different tools — that's
  the M5 ablation, not an assumption.** Pushed warnings (`draftsmith
  check` today) vs on-demand queries ("what's adjacent to R3") vs
  render-to-VLM self-inspection get compared. Prior to test:
  deterministic text feedback carries most correctness gains cheaply;
  the render/VLM channel matters for RN-1-class visual errors and for
  design quality.
- **Goodhart.** An agent iterating against `evaluate.py` will learn to
  satisfy `evaluate.py` — fine for feasibility (real rules), dangerous
  for soundness (metric-shaped plans). The L4 judge stays **out of the
  inner loop**, held-out eval only, at least until human-validated.

## What exists vs what's wiring

The journal op vocabulary is already the tool surface (deferred M2 MCP
work); `evaluate()` is the critic; `design_guidelines.md` is the
domain-skill prompt block. The iterative agent is mostly wiring.

**First experiment worth writing up** (M5): baseline single-shot vs
plan-first vs full iterative loop, scored on the M4 tuple with the
judge held out.
