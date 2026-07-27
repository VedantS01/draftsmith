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
