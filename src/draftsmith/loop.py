"""The phased drafting loop (M2b) — engine as inner-loop critic.

Implements docs/agent_loop.md: instead of emitting a whole plan blind,
the agent moves through gated phases, each with rework rounds and the
observation-query protocol (:mod:`draftsmith.observe`) available:

1. **plan** — commit to a program (room list, target areas, adjacency)
   as JSON; validated against the ``Brief`` before any geometry exists.
2. **perimeter** — outer walls + main entrance only; checked for a
   single closed region and total-area sanity.
3. **rooms** — interior rooms one per turn (walls + door + label);
   feedback is the room table plus the reachability/adjacency/minimum
   findings only — no drafting nitpicks yet.
4. **refine** — windows, dimensions, styles; full ``evaluate()``
   findings until no hard failures remain (or rounds run out).

Feedback is always the *findings*, never the score tuple — scores are
for the benchmark, not the loop (Goodhart guard, docs/agent_loop.md).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from draftsmith.agent import check, warnings_for
from draftsmith.dsl import serialize
from draftsmith.errors import ToolError
from draftsmith.evaluate import (
    ROOM_TYPES,
    Brief,
    Report,
    evaluate,
    room_type,
)
from draftsmith.geometry import rooms
from draftsmith.observe import answer, is_query
from draftsmith.scene import Scene

PROTOCOL = (
    "Reply with EITHER the FULL FP1 document in a ```fp block (plus at "
    "most 2 sentences) OR only engine-query lines starting with '?' "
    "(?walls ?wall W3 ?joints ?rooms ?room R2 ?graph ?help)."
)

# Findings the rooms phase is allowed to nag about; everything else
# (junction clearance, glazing, widths, soundness) waits for refine.
ROOMS_GATE = {
    "reachability", "entrance", "common_bath_access", "bedroom_privacy",
    "wc_off_kitchen", "room_minimums", "door_economy",
}
# Circulation allowance when the brief gives no total: planned rooms sum
# plus this fraction.
CIRC_ALLOWANCE = 0.12
AREA_TOL = 0.25


@dataclass
class Turn:
    phase: str
    role: str  # instruction | assistant | engine
    text: str


@dataclass
class PhaseLog:
    name: str
    ok: bool = False
    fp_rounds: int = 0
    queries: int = 0
    note: str = ""


@dataclass
class LoopResult:
    scene: Scene | None
    program: dict | None
    phases: list[PhaseLog]
    transcript: list[Turn]
    report: Report | None

    def summary(self) -> str:
        lines = []
        for p in self.phases:
            lines.append(
                f"{p.name:<10} {'ok' if p.ok else 'INCOMPLETE'}  "
                f"rounds {p.fp_rounds}  queries {p.queries}"
                + (f"  ({p.note})" if p.note else "")
            )
        return "\n".join(lines)


def _findings_text(report: Report, gate: set[str] | None = None,
                   layers: tuple[str, ...] = ("feasibility", "compliance"),
                   only_imperfect: bool = False) -> str:
    lines = []
    for layer in layers:
        for f in getattr(report, layer):
            if gate is not None and f.metric not in gate \
                    and layer == "feasibility":
                continue
            if only_imperfect and f.score >= 1.0:
                continue
            mark = "FAIL" if f.score == 0 else f"{f.score:.2f}"
            extra = f"  {f.detail}" if f.detail else ""
            val = f"  {f.value}" if f.value not in (None, {}, []) \
                and f.score < 1 else ""
            lines.append(f"  [{mark}] {f.metric}{val}{extra}")
    return "\n".join(lines) if lines else "  (all checks pass)"


def _match(selector: str, label: str | None) -> bool:
    sel = selector.lower()
    if sel in ROOM_TYPES:
        return room_type(label) == sel
    return bool(label) and sel in label.lower()


class DraftingLoop:
    """Drives one brief through the phased loop with a text runner.

    ``runner`` is any ``prompt -> reply`` callable (e.g. ``ApiRunner``
    with its system prompt already set); the loop owns the per-turn
    context construction, validation, and phase gating.
    """

    def __init__(
        self,
        runner: Callable[[str], str],
        request: str,
        brief: Brief | None = None,
        rounds_per_phase: int = 4,
        query_budget: int = 8,
        max_calls: int = 40,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.runner = runner
        self.request = request
        self.brief = brief
        self.rounds_per_phase = rounds_per_phase
        self.query_budget = query_budget
        self.max_calls = max_calls
        self.progress = progress or (lambda s: None)
        self.calls = 0
        self.transcript: list[Turn] = []
        self.scene: Scene | None = None
        self.program: dict | None = None
        self._last_error = ""

    # ----------------------------------------------------------- plumbing

    def _say(self, phase: str, role: str, text: str) -> None:
        self.transcript.append(Turn(phase, role, text))

    def _model(self, phase: str, prompt: str) -> str:
        if self.calls >= self.max_calls:
            raise ToolError(f"loop exceeded {self.max_calls} model calls")
        self.calls += 1
        reply = self.runner(prompt)
        self._say(phase, "assistant", reply)
        return reply

    def _context(self, phase: str, instruction: str,
                 feedback: str | None = None) -> str:
        parts = [f"BRIEF: {self.request}"]
        if self.program:
            parts.append("AGREED PROGRAM:\n"
                         + json.dumps(self.program, indent=1))
        if self.scene is not None and len(self.scene):
            parts.append("CURRENT PLAN:\n```fp\n"
                         + serialize(self.scene) + "```")
        if feedback:
            parts.append(f"ENGINE FEEDBACK:\n{feedback}")
        parts.append(f"PHASE {phase.upper()}: {instruction}")
        parts.append(PROTOCOL if phase != "plan" else instruction_plan_reply())
        return "\n\n".join(parts)

    def _fp_turn(self, phase: str, log: PhaseLog, instruction: str,
                 feedback: str | None) -> Scene | None:
        """One drafting exchange: queries are answered without consuming
        a round; an invalid document returns None with error feedback
        recorded for the caller."""
        prompt = self._context(phase, instruction, feedback)
        while True:
            reply = self._model(phase, prompt)
            if is_query(reply):
                if log.queries >= self.query_budget:
                    ans = "query budget exhausted - send the fp block now"
                else:
                    ans = answer(self.scene or Scene(), reply)
                log.queries += 1
                self._say(phase, "engine", ans)
                prompt = f"{prompt}\n\nASSISTANT:\n{reply}\n\nENGINE:\n{ans}"
                continue
            log.fp_rounds += 1
            scene, report = check(reply)
            if scene is None:
                self._say(phase, "engine", report)
                self._last_error = report
                return None
            return scene

    # ------------------------------------------------------------- phases

    def run(self) -> LoopResult:
        logs = []
        for phase_fn in (self._phase_plan, self._phase_perimeter,
                         self._phase_rooms, self._phase_refine):
            log = phase_fn()
            logs.append(log)
            self.progress(f"[{log.name}] "
                          + ("ok" if log.ok else f"incomplete: {log.note}")
                          + f" (rounds {log.fp_rounds}, queries {log.queries})")
            if not log.ok and log.name in ("plan", "perimeter"):
                break  # nothing downstream can work without these
        report = None
        if self.scene is not None and rooms(self.scene):
            report = evaluate(self.scene, self.brief)
        return LoopResult(self.scene, self.program, logs,
                          self.transcript, report)

    def _phase_plan(self) -> PhaseLog:
        log = PhaseLog("plan")
        instruction = (
            "No drawing yet. Commit to a program for this brief: every "
            "room with a target area, plus which rooms need direct door "
            "connections. Include circulation (passage/hall) if the "
            "layout needs it."
        )
        feedback = None
        for _ in range(self.rounds_per_phase):
            prompt = self._context("plan", instruction, feedback)
            reply = self._model("plan", prompt)
            try:
                program = _extract_plan(reply)
                problems = _validate_plan(program, self.brief)
            except ToolError as err:
                feedback = str(err)
                self._say("plan", "engine", feedback)
                log.fp_rounds += 1
                continue
            log.fp_rounds += 1
            if problems:
                feedback = "program does not satisfy the brief:\n- " \
                    + "\n- ".join(problems)
                self._say("plan", "engine", feedback)
                continue
            self.program = program
            self._say("plan", "engine", "program accepted")
            log.ok = True
            return log
        log.note = "no acceptable program"
        return log

    def _phase_perimeter(self) -> PhaseLog:
        log = PhaseLog("perimeter")
        target = self._target_area()
        instruction = (
            "Draw ONLY the outer perimeter walls (closed loop, thickness "
            "230) and the main entrance door. No interior walls, labels "
            f"or windows yet. Target enclosed area ~{target:.0f} m2."
        )
        feedback = None
        for _ in range(self.rounds_per_phase):
            scene = self._fp_turn("perimeter", log, instruction, feedback)
            if scene is None:
                feedback = self._last_error
                continue
            derived = rooms(scene)
            problems = []
            if len(derived) != 1:
                problems.append(
                    f"expected one enclosed region, got {len(derived)} - "
                    "perimeter must be a single closed loop with no "
                    "interior walls")
            if not scene.doors:
                problems.append("add the main entrance door")
            if derived:
                area = sum(r.area_m2 for r in derived)
                if abs(area - target) > AREA_TOL * target:
                    problems.append(
                        f"enclosed {area:.0f} m2 but the program needs "
                        f"~{target:.0f} m2 (+-{AREA_TOL:.0%})")
            if problems:
                feedback = "- " + "\n- ".join(problems)
                self._say("perimeter", "engine", feedback)
                continue
            self.scene = scene
            self._say("perimeter", "engine",
                      f"perimeter accepted ({sum(r.area_m2 for r in derived):.0f} m2)")
            log.ok = True
            return log
        log.note = "no valid perimeter"
        return log

    def _phase_rooms(self) -> PhaseLog:
        log = PhaseLog("rooms")
        planned = [r["label"] for r in self.program["rooms"]]
        budget = 2 * len(planned) + 2
        feedback = None
        for _ in range(budget):
            placed, missing = self._placed(planned)
            if not missing:
                log.ok = True
                return log
            instruction = (
                "Carve the interior one room per turn: add the walls, the "
                "door(s), and the label for the NEXT room, keeping every "
                f"already-placed room intact. Placed: "
                f"{', '.join(placed) or 'none'}. Still to place: "
                f"{', '.join(missing)}. Resend the FULL document."
            )
            scene = self._fp_turn("rooms", log, instruction, feedback)
            if scene is None:
                feedback = self._last_error
                continue
            self.scene = scene
            feedback = self._rooms_feedback(scene)
            self._say("rooms", "engine", feedback)
        placed, missing = self._placed(planned)
        log.ok = not missing
        if missing:
            log.note = f"unplaced: {', '.join(missing)}"
        return log

    def _phase_refine(self) -> PhaseLog:
        log = PhaseLog("refine")
        feedback = None
        for i in range(self.rounds_per_phase):
            report = evaluate(self.scene, self.brief)
            clean = (not report.hard_failures
                     and all(f.score >= 0.75 for f in report.feasibility))
            if i > 0 and clean:
                log.ok = True
                return log
            instruction = (
                "Finish the drawing: windows for every habitable room "
                "(two sides where possible), overall dimensions OUTSIDE "
                "the building, door swings and styles chosen with intent "
                "(sliding/double where they serve). Then fix every "
                "finding listed. Resend the FULL document."
            )
            findings = _findings_text(
                report, layers=("feasibility", "compliance", "soundness"),
                only_imperfect=True)
            warns = warnings_for(self.scene)
            fb = "findings to fix:\n" + findings
            if warns:
                fb += "\nwarnings:\n" + "\n".join(f"  - {w}" for w in warns)
            if feedback:
                fb = f"{feedback}\n{fb}"
            scene = self._fp_turn("refine", log, instruction, fb)
            feedback = None
            if scene is None:
                feedback = self._last_error
                continue
            self.scene = scene
        report = evaluate(self.scene, self.brief)
        log.ok = not report.hard_failures
        if not log.ok:
            log.note = ", ".join(f.metric for f in report.hard_failures)
        return log

    # ------------------------------------------------------------ helpers

    def _target_area(self) -> float:
        if self.brief and self.brief.total_area and self.brief.total_area[0]:
            lo, hi = self.brief.total_area
            return (lo + (hi or lo)) / 2
        total = sum(float(r.get("area_m2", 0))
                    for r in self.program["rooms"])
        return total * (1 + CIRC_ALLOWANCE)

    def _placed(self, planned: list[str]) -> tuple[list[str], list[str]]:
        labels = [r.label for r in rooms(self.scene) if r.label]
        placed, missing = [], []
        for want in planned:
            if any(want.lower() == have.lower() for have in labels):
                placed.append(want)
            else:
                missing.append(want)
        return placed, missing

    def _rooms_feedback(self, scene: Scene) -> str:
        from draftsmith.observe import rooms_table

        report = evaluate(scene, self.brief)
        targets = {r["label"].lower(): float(r.get("area_m2", 0))
                   for r in self.program["rooms"]}
        deltas = []
        for r in rooms(scene):
            want = targets.get((r.label or "").lower())
            if want:
                off = (r.area_m2 - want) / want
                if abs(off) > AREA_TOL:
                    deltas.append(
                        f"  {r.label}: {r.area_m2:.1f} m2 vs planned "
                        f"{want:.1f} ({off:+.0%})")
        fb = rooms_table(scene) + "\nchecks:\n" \
            + _findings_text(report, gate=ROOMS_GATE)
        if deltas:
            fb += "\narea drift vs program:\n" + "\n".join(deltas)
        return fb


# ---------------------------------------------------------------------------
# Plan-block parsing.


def instruction_plan_reply() -> str:
    return (
        'Reply with ONLY a fenced block tagged `plan` containing JSON: '
        '{"rooms": [{"label": "MASTER BEDROOM", "area_m2": 14}, ...], '
        '"adjacency": [["KITCHEN", "DINING"], ...]} — labels exactly as '
        "they will appear on the drawing."
    )


def _extract_plan(text: str) -> dict:
    m = re.search(r"```(?:plan|json)\n(.*?)```", text, re.DOTALL)
    raw = m.group(1) if m else text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ToolError(
            f"could not parse the plan JSON ({err}); reply with a "
            "```plan fenced block of valid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("rooms"), list) \
            or not data["rooms"]:
        raise ToolError('plan JSON needs a non-empty "rooms" list')
    for i, r in enumerate(data["rooms"]):
        if not isinstance(r, dict) or not r.get("label"):
            raise ToolError(f'rooms[{i}] needs a "label"')
    data.setdefault("adjacency", [])
    return data


def _validate_plan(program: dict, brief: Brief | None) -> list[str]:
    if brief is None:
        return []
    problems = []
    labels = [r["label"] for r in program["rooms"]]
    for selector, want in brief.rooms.items():
        got = sum(1 for lb in labels if _match(selector, lb))
        if got != want:
            problems.append(f"brief needs {want} x {selector}, program "
                            f"has {got}")
    if brief.total_area and brief.total_area[0]:
        total = sum(float(r.get("area_m2", 0)) for r in program["rooms"])
        lo, hi = brief.total_area
        if total < lo * (1 - AREA_TOL) or (hi and total > hi * (1 + AREA_TOL)):
            problems.append(
                f"planned areas sum to {total:.0f} m2; brief wants "
                f"{lo:.0f}-{hi or lo:.0f} m2 (leave ~10% for walls/"
                "circulation)")
    pairs = [tuple(sorted(p)) for p in program.get("adjacency", [])]
    for a, b in brief.adjacent:
        hit = any(
            (_match(a, p[0]) and _match(b, p[1]))
            or (_match(a, p[1]) and _match(b, p[0]))
            for p in pairs
        )
        if not hit:
            problems.append(f"brief requires {a} adjacent to {b}; add the "
                            "pair to adjacency")
    return problems
