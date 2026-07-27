# Research notes — agent failure observations

Running log of drafting-agent mistakes seen in real sessions. Each entry
feeds the M4 benchmark's scoring rules and the M5 feedback-modality
study; "resolution" records which layer of the system was changed.

## RN-1 · Dimension drawn inside the building (recurring, 3 sightings)

- **Sightings**: M2 example exchange (10×6 apartment, height dim);
  4BHK first run (height dim); live studio session 2026-07-28 (4BHK,
  `M2 0,0 0,11200 d-700` — dimension line at x=+700, slicing through
  verandah and master bedroom).
- **Mechanism**: the sign of `d` is direction-relative (positive = left
  of p1→p2). The model learns `d-700` works for the south edge
  (west→east, negative = below = outside) and reuses the same sign for
  the vertical dimension written south→north, where negative = east =
  *inside*. A copied local pattern, not a geometric judgment.
- **Why it matters for research**: the plan stays textually valid — no
  parser or geometry error — so pure-text feedback never flags it, while
  it is instantly obvious in the render. Prime evidence for the
  feedback-modality ablation (text vs render), and a candidate scored
  check in the benchmark.
- **Resolution** (three layers, same day):
  1. engine: `warnings_for()` now tests the dimension line's midpoint
     against the wall body and room polygons → warning
     `dimension M2 runs inside the building`, so text feedback + the
     chat auto-retry can catch it;
  2. system prompt: explicit side rule ("building interior on the LEFT
     of p1→p2, then negative d is outside") with the west-edge example;
  3. this note.
- **Open question**: does the prompt rule alone fix it, or only the
  engine warning? Worth an A/B when the benchmark runner exists.

## RN-2 · Label collisions (cosmetic, frequent)

Adjacent room labels overlap when rooms are narrow (e.g. "KIDS
BEDROOM"/"COMMON BATH" in the 4BHK). Textually invisible; benchmark
should score label legibility or the engine should warn on
label-bbox overlap. Not yet addressed.

## RN-3 · Interior-wall window (caught by engine)

4BHK first run placed one window in an interior wall; the
`warnings_for` interior-window check flagged it — evidence the
warning channel works when the check exists.

## RN-4 · Multi-turn error series in the live 4BHK chat session (user-observed)

Over successive turns of one session the model: (1) **skipped the
passageway** entirely; (2) made the **common bathroom inaccessible**
except through the kids' bedroom; (3) placed **doors overlapping the
T-joints** where interior walls meet; (4) converged on **far too many
doors** (final plan: 16 doors for 13 rooms, incl. three separate
living↔passage doors).

Key insight: most of these are NOT purely "model intelligence" gaps —
they are **engine-checkable** and belong in `warnings_for` / benchmark
scoring:

- *Accessibility*: build the room-connectivity graph from `connections`
  and check every room is reachable from the entrance (EXT) without
  passing through private rooms (bedrooms/baths). (2) becomes a warning.
- *Door–junction clearance*: an opening whose span overlaps a wall
  junction (within, say, 100mm) is bad practice and geometrically
  detectable. (3) becomes a warning.
- *Door economy*: >1 door between the same room pair, or door count far
  above room count, is countable. (4) becomes a warning or a score.
- (1) is a brief-compliance check — "passageways" was in the program —
  i.e. an M4 per-brief expectation, not a generic warning.

None of these are implemented yet — logged as engine backlog.

## RN-5 · Quality beyond correctness: uniqueness, creativity, beauty (user-observed)

The 4BHK converged on a boring grid of rectangles. Concretely missed
opportunities: space *carving* instead of grid partitioning; a sliding
door for the balcony; a double door from living room to passage; a
shaped living room that separates sofa and dining zones **without a
wall** (distinct areas by geometry, not partitions).

Direction: model output quality must be scored on (at least) two axes —
**correctness** (validity, brief compliance, drafting sanity) and
**design quality** (variety of styles actually used, non-grid layout
character, zoning legibility, proportion). How to score the second
mathematically is open. Leads to mine before inventing our own:

- **Space syntax** (Hillier & Hanson): justified access graphs — depth,
  integration, connectivity per room; quantifies circulation quality and
  privacy gradients (would catch RN-4's inaccessible bath *and* reward
  good passage design).
- **Isovist / visibility-graph analysis** (Benedikt; Turner): area,
  occlusivity, drift of view fields — quantifies "distinct zones without
  walls" (the sofa/dining separation is literally an isovist property).
- Proportion/regularity measures: room aspect-ratio distributions,
  alignment entropy, footprint articulation (perimeter²/area vs pure
  rectangle) — cheap proxies for "not a boring grid".
- Style-usage diversity: entropy over door/window/label styles used —
  trivially computable in our IR.
- Neufert-style standards for minimum widths/areas per room type
  (correctness-adjacent, textbook-quantified).
- Where formulas run out: LLM/VLM judge with an architect rubric,
  validated against human ratings on a small set.

Status: **noted for M4 metric design** — the benchmark's score should be
(correctness, compliance, design-quality) tuples, not a single number.
Solving generation quality itself is deliberately deferred (too
ambitious now); measuring it comes first.
