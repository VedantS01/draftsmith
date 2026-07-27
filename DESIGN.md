# draftsmith — design

Mission: a **floorplan scene-graph engine** powering four independent
surfaces — (1) LLM-agent drafting workflows, (2) synthetic dataset
generation for NN training, (3) a human design tool, (4) an SDK/plugin for
third-party design software. Specialized to floorplans by decision: the
agent is expert at *layout facts*, the engine is expert at *geometry and
depiction*.

## Architecture

```
scene.py      Semantic IR: Wall / Door / Window / Label / Dim, typed IDs, validation
dsl.py        FP1: canonical token-efficient text format; JSON as interchange view
geometry.py   Derived truth (Shapely): wall bodies (union joins), rooms, adjacency
compiler.py   Style compiler: scene -> primitives; door/window/label style registries
toolkit.py    Sketch: validated primitive layer over ezdxf (draw/edit/inspect)
renderer.py   DXF -> PNG/SVG/PDF (agent visual feedback)
```

Rules that hold everything together:

1. **Facts, not drawings, in the IR.** The scene stores what is true
   (a 900mm door on W5 at offset 0, hinged far, swinging left). How it is
   drawn is the compiler's job; what it encloses (rooms) is derived.
2. **Semantics compile down; recognition lifts up.** Because the compiler
   generates every primitive from the scene, any compiled drawing carries
   perfect ground truth (scene ↔ DXF ↔ render) — the basis of the dataset
   factory, and eventually the target of recognition models.
3. **Derived geometry is computed, never stored.** Rooms, areas,
   adjacency, wall joins come from `geometry.py` on demand. Nothing can go
   stale; agents query instead of tracking state.
4. **Every drawing is a program.** FP1 is both the document and a
   replayable construction sequence; line diffs are edits.

## FP1 — the IR text format

Designed for LLM context windows (~4x denser than JSON; the sample plan
is ~65 tokens):

```
FP1 mm
!S door=arc window=triple
W1 0,115 8000,115 t230
W5 5000,230 5000,4770 t120
D1 W5@0 w900 hinge=far
N1 W1@1500 w1200
L1 2500,2500 "LIVING ROOM"
M1 0,0 8000,0 d-700
```

Decisions (and why):

- **Typed sequential IDs** (`W5`, `D1`): reliable for LLMs to emit/refer
  to; the host relation is positional syntax (`D1 W5@0` = door on wall 5
  at offset 0 mm).
- **IDs retire forever** on deletion — references in an agent's earlier
  turns never silently rebind.
- **Absolute integer millimetres**, not deltas: every line stays
  independently editable; token cost is close, ambiguity is lower.
- **Defaults omitted; styles set once** in the `!S` header, overridable
  per object (`style=`). Same plan + different header = different drawing:
  that is the dataset variety axis.
- **Canonical serialization** (fixed order/format):
  `parse(serialize(s))` round-trips exactly; diffs are meaningful.
- `FP1` is a version tag; syntax changes bump it. JSON (`dsl.to_json`) is
  the schema-friendly interchange view for SDK/UI/dataset labels.
- Micro-syntax (e.g. `t230` vs `t=230`) is frozen only after tokenizer
  measurement in the eval harness; `encoding_stats()` is the placeholder.

## Geometry

- Walls are centerline + thickness. Bodies are Shapely polygons; the
  **union** resolves mitres/T-joints, opening subtraction leaves capped
  jambs automatically.
- **Rooms** = enclosed faces of the solid wall network (envelope minus
  union, drop outside components), numbered deterministically in reading
  order, labels matched by containment.
- **Connections**: an opening probes 50mm past both wall faces; the rooms
  it touches are what it connects (`EXT` = outside).
- One tolerance constant (`TOL = 1mm`) for all "does it touch" questions.

## Style compiler

`compile_scene(scene) -> Sketch` resolves styles per object → scene `!S`
header → defaults. Registries (`DOOR_STYLES`, `WINDOW_STYLES`,
`LABEL_STYLES`) are the extension point: a style is a small function
emitting primitives; adding one never touches the engine. Current packs:
doors `arc | double | sliding`, windows `triple | frame`, labels
`plain | caps | title`. Growing this catalog (hatch patterns, line
weights, dimension styles, symbol variants) is scheduled work, not
redesign.

## Research program (see ROADMAP.md for milestones)

- **Benchmark**: NL brief → DXF floorplan by a tool-using agent, scored in
  layers: file validity → geometric fidelity (room IoU, wall-graph edit
  distance, opening placement) → brief/constraint satisfaction →
  drafting quality (a pretrained symbol-spotter as automatic judge).
  Survey result (2026): no such benchmark exists; nearest neighbors are
  Tell2Design (NL→room boxes, no CAD output) and 3D text-to-CAD suites.
- **Dataset factory**: sample layout topology, compile under many style
  packs + raster degradation → paired FP1/DXF/SVG/PNG with perfect labels
  (CubiCasa5k/FloorplanCAD-compatible formats). Style variety at fixed
  semantics is the novel axis.
- **Ablations**: feedback modality for drafting agents (render vs
  geometric queries vs recognizer-critic); IR token-efficiency vs agent
  performance (FP1 vs JSON vs prose).
- **External anchors**: Tell2Design (research-only) for text→layout
  comparability; FloorplanCAD/ArchCAD-400K for recognition; Swiss
  Dwellings (CC BY 4.0) as the legally-clean realism reference. Keep the
  engine and synthetic data free of research-only dataset derivatives so
  product uses stay unencumbered.

## Non-goals (deliberate)

- General-purpose CAD kernel, arbitrary-geometry trim/extend/fillet.
- Parametric constraint solving (revisit only if dimension-driven editing
  becomes a product need).
- True DWG output (proprietary; DXF is the interchange standard).
- 3D as a first-class model (walls may gain a height attribute later;
  plan-view semantics stay primary).
