# Evaluation framework — scoring model-drafted floorplans (M4)

Decision record + metric catalog for the draftsmith benchmark. Follows
up docs/research_notes.md RN-4/RN-5; deterministic layers are
implemented in `src/draftsmith/evaluate.py` (`draftsmith evaluate`).

## Scoring philosophy (decided)

1. **Scores are tuples, never one number**: `(correctness, compliance,
   soundness)` from the deterministic layers, plus a separate judge
   profile. Precedent: HELM refuses single aggregates (Liang et al.
   2022); the RFP-A metric study (2025) found different floorplan
   generators win different axes with none dominating — collapsing axes
   destroys exactly the signal we want to study.
2. **Hard gates before graded scores**: an unparseable document, or a
   plan whose rooms aren't reachable, isn't "a low score" — it fails.
   Precedent: the floorplan-RLVR paper (arXiv 2605.14117) zeroes reward
   on invalid JSON / overlapping polygons.
3. **Deterministic before judged**: everything a formula can catch is
   scored by the engine, reproducibly; the LLM/VLM judge is reserved for
   what formulas can't reach (beauty, novelty, creativity) and is
   validated against human ratings before its numbers are trusted.
4. **Every threshold carries a source tag**: `[NBC]`-style cited code
   values, or `[BM]` benchmark-defined (our choice, defensible but
   ours). Unverified rules of thumb stay out of hard checks.

## The layers

| layer | axis | nature | lives in |
|---|---|---|---|
| L0 | validity | gate: FP1 parses, geometry derives | `agent.check` (M2, done) |
| L1 | feasibility | hard + graded checks, brief-independent | `evaluate.feasibility_findings` |
| L2 | brief compliance | scored against a machine-readable `Brief` | `evaluate.compliance_findings` |
| L3 | architectural soundness | graded, brief-independent | `evaluate.soundness_findings` |
| L4 | design quality | LLM/VLM judge, rubric below | future runner |

`correctness` = mean of L1 findings (hard failures also listed
separately — a plan with any is reported as failed regardless of the
mean). `compliance` = mean of L2 (None without a brief). `soundness` =
mean of L3.

## L1 — feasibility

| metric | rule | source |
|---|---|---|
| `reachability` | every room reachable from EXT via doors (BFS on the access graph) — **hard** | RN-4 |
| `entrance` | ≥1 door to EXT — **hard** | — |
| `common_bath_access` | ≥1 bath/WC reachable without passing through a bedroom — **hard** | adjacency doctrine (Time-Saver-style matrices); RN-4's inaccessible common bath |
| `bedroom_privacy` | no bedroom whose only access is through another bedroom — **hard** | space-syntax residential genotype ("sleeping spaces terminal or off circulation") |
| `wc_off_kitchen` | no bath/WC door directly into a kitchen — **hard** | NBC 2016 Part 9 in substance (clause no. unverified) |
| `door_economy` | no duplicate doors per room pair; door/room ratio in [0.6, 1.3] `[BM]` | RN-4 (16 doors / 13 rooms failure) |
| `junction_clearance` | opening edges ≥100mm `[BM]` from wall junctions | RN-4 |
| `room_minimums` | per-type area/width floors (table below) | NBC/MBBL 2016, IRC cross-check |
| `door_widths` | entrance ≥900 [NBC], bath ≥750 [NBC], other interior ≥800 `[BM]` (between IRC 813 clear and NBC 900 leaf) | NBC; IRC R311.2 |
| `habitable_ventilation` | habitable rooms have ≥1 exterior opening | IRC R303; MBBL |
| `glazing_ratio` | window area ≥ 1/10 floor area per habitable room, assuming 1200mm window height (2D plan; assumption explicit) | MBBL ch.4 (IRC: 8% glazing/4% openable) |

Room minimums (`ROOM_STANDARDS`), mm/m², NBC 2016 Part 3 / MBBL 2016
ch. 4 unless tagged: bedroom 7.5 m²·2.1 m (NBC second-room clause;
first habitable room 9.5·2.4 applied to living); kitchen 5.0·1.8; bath
1.8·1.1; WC 1.1·0.9; corridor width 0.9; study 6.5 m² (IRC 70 ft²);
dining 6.0 `[BM]`. UK NDSS 2015 (single 7.5 m²/2.15 m, double 11.5 m²)
corroborates the band. Neufert furniture-clearance figures (bed-side
750mm etc.) are deferred until we model furniture.

## L2 — brief compliance

A `Brief` is the machine-readable half of each benchmark brief, written
when the brief is authored (no NL parsing at eval time):

```json
{"rooms": {"bedroom": 4, "bath": 2, "kitchen": 1},
 "areas": {"master bedroom": [14, null], "kitchen": [5, 12]},
 "adjacent": [["kitchen", "dining"]],
 "total_area": [90, 140]}
```

Scoring conventions follow DStruct2Design (arXiv 2407.15723), the most
complete constraint scorecard in the literature: exact match for
counts/identity, band-with-linear-falloff for areas (they use raw %
error; our falloff is the tolerance-band variant), graph checks for
adjacency. Their split of **self-consistency** (internal coherence)
vs **prompt-consistency** (brief adherence) maps to our L0/L1 vs L2.
Planned extension: precision/recall over required room sets (partial
credit for 3 of 4 bedrooms) instead of per-selector exact match.

## L3 — architectural soundness (graded)

Space syntax is computed on the **justified permeability graph**: nodes
= rooms + the exterior carrier, edges = doors (Hillier & Hanson 1984,
*The Social Logic of Space*; Hanson 1998, *Decoding Homes and Houses*).

| metric | definition | source |
|---|---|---|
| `syntax_depth` | mean depth MD from EXT; reported with RA = 2(MD−1)/(k−2) and RRA = RA/D_k, D_k = 2{k[log₂((k+2)/3)−1]+1}/[(k−1)(k−2)]. Scored full in MD ∈ [1.5, 3.0] `[BM]` — absolute published bands don't exist, the ordinal genotype below is the citable claim | Hillier & Hanson 1984 |
| `privacy_genotype` | fraction of satisfied depth-order pairs, canonical order living/dining < kitchen/study < bedroom < bath/WC | Hanson 1998; replications (Erbil 2010, npj Herit. Sci. 2025); = Alexander #127 "Intimacy Gradient" — two independent literatures, same check |
| `ringiness` | independent cycles (E−V+components) and space link ratio (E+1)/V; any ring scores full, pure tree 0.6 `[BM]` | Hillier & Hanson (distributedness) |
| `proportion` | habitable-room aspect (min rotated rect): full ≤1.5, zero at 2.5. Code-anchored (NBC width floors imply ≤1.65 at min size; IRC ≤1.43) but band `[BM]` | trade guidance is unverified-RoT; anchor is code |
| `rectangularity` | room area / min-rotated-rect area, full ≥0.85 `[BM]`; low = sloppy **or** deliberately carved — reported, gently scored, judge arbitrates | floorplan-analysis convention; ResPlan 2025 uses Polsby-Popper compactness similarly |
| `articulation` | footprint P²/16A (1.0 = square): full in [1.02, 1.6] `[BM]` — both featureless boxes and jagged outlines drift down | RN-5 "not a boring grid" proxy |
| `light_two_sides` | habitable rooms with exterior windows on ≥2 differently-oriented walls (full/half/zero per room) | Alexander #159 |
| `style_diversity` | normalized Shannon entropy over door/window styles used | RN-5; trivially computable in our IR |
| `circulation_share` | corridor/passage area ÷ interior area, full in [5%, 15%] | 11–15% (≤20%) multi-unit practice; within-unit target unverified-RoT, so `[BM]` band |

**Deliberately deferred** (engine backlog, needs new machinery):
isovist/visibility-graph zoning legibility (Benedikt 1979; Turner et
al. 2001 — clustering-coefficient fields would quantify RN-5's "sofa
and dining zones without a wall"; no published thresholds, so it needs
calibration against RPLAN/Swiss Dwellings first); daylight-depth (room
area within 2.5× window-head-height of a window, CIBSE RoT); control
values per room; Hanson's difference factor (is there *any* privacy
structure); route directness. Swiss Dwellings ships space-syntax-
flavoured centrality columns — calibration data for all of these.

## L4 — design quality (judge)

What formulas can't reach: beauty, novelty, creativity, zoning
legibility, "would an architect nod". Design, following the judge
literature:

- **Rubric axes**: functionality, circulation/flow, overall layout —
  lifted from FloorPlan-LLaMa's ArchiMetricsNet (ACL 2025; 24k
  architect ratings back exactly these three) — plus draftsmith's
  novelty/creativity axis (RN-5), which their data doesn't cover.
- **Pairwise, not absolute**: VLM judges track humans well in pairwise
  comparison and poorly in absolute scoring (MLLM-as-a-Judge, ICML
  2024). Protocol: pairwise comparisons against a fixed anchor set of
  reference plans per brief, positions swapped (MT-Bench position-bias
  mitigation, Zheng et al. 2023), ties allowed, Bradley-Terry
  aggregation to a per-axis scale.
- **Inputs**: the render (PNG) **and** the engine summary (rooms,
  areas, connections) — the judge sees both modalities; which one it
  needs is itself an M5 ablation.
- **Validation before trust**: a small human-rated set (draftsmith
  studio sessions make collection cheap — the journal already records
  everything); report judge–human agreement alongside any judge scores.
  No agreement number, no leaderboard use.

## Benchmark protocol (M4 runner, next)

- Brief suites from terse ("a 2BHK") to dimensioned (areas, adjacency,
  orientations), each shipping its `Brief` JSON. Indian-idiom briefs
  score against the NBC profile; a `CodeProfile` switch (NBC/IRC) is
  planned for others.
- Per-model report: hard-failure rate, then mean (correctness,
  compliance, soundness) over passing plans, then judge profile. Axes
  stay separate; no headline scalar.
- External comparability: Tell2Design room-box export + micro/macro
  IoU (roadmap M4 item) so draftsmith agents can be compared to that
  literature; GED-vs-brief-adjacency (House-GAN's compatibility) falls
  out of L2's adjacency checks.

## Research positioning

The survey found no published work using space-syntax integration or
isovist measures as *automatic* metrics for generated floorplans (one
2026 preprint uses syntax rewards for post-training — arXiv
2602.22507). A benchmark whose soundness axis is grounded in Hillier &
Hanson + Alexander, validated against architect ratings, is a real
gap — and the natural first write-up out of draftsmith: metric suite +
judge validation + feedback-modality ablation (M5) on top.

## Sources

Hillier & Hanson 1984 *The Social Logic of Space*; Hanson 1998
*Decoding Homes and Houses*; Alexander et al. 1977 *A Pattern
Language* (#112/127/132/159); Benedikt 1979; Turner et al. 2001; NBC
India 2016 Part 3/8/9 + Model Building Bye-Laws 2016 ch.4; IRC
2021 R303–R311; UK NDSS 2015; Neufert *Architects' Data* 4e (flagged
where OCR-unverified); DStruct2Design arXiv 2407.15723; floorplan RLVR
arXiv 2605.14117; FloorPlan-LLaMa ACL 2025; Tell2Design ACL 2023;
House-GAN++ CVPR 2021; HouseDiffusion CVPR 2023; ResPlan arXiv
2508.14006; RFP-A metrics study 2025; MLLM-as-a-Judge ICML 2024; Zheng
et al. NeurIPS 2023 (MT-Bench); HELM arXiv 2211.09110; Swiss Dwellings
Zenodo 7070952. Flagged-unverified items: NBC kitchen–WC clause
number, within-unit circulation %, aspect-ratio trade bands, absolute
RRA ranges, Neufert exact wording.
