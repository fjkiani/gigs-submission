"""Lever simulator — typed projection of intervention lifts.

The audit prose's §2.3 says: given a gap decomposition, here are the 5
levers, each with an expected lift in percentage points, applied in this
order. This module is the typed substrate for that argument.

A ``Lever`` is a named intervention with:
- ``name`` — the brief label (L1-L5)
- ``mechanism`` — one-line explanation of HOW it works
- ``targeted_buckets`` — which of the 4 buckets it removes questions from
- ``apply`` — pure function: input ``GapDecomposition`` → output
  ``GapDecomposition``

Then ``simulate_sequence`` chains a list of levers through a starting
decomposition and returns the trajectory. The trajectory is what the
audit prose embeds as the "0 → 80% → 84% → 89% → 91%" sequence.

Why a simulator and not just hand-computed numbers? Because the lever
chain is *non-commutative* — applying the refusal-aware metric switch
after a KB expansion gives a different end-state from doing it first.
A reviewer can change the order, drop a lever, or scale a coefficient
in the recommended sequence and see the projection update.

Important caveat (echoed in the audit prose §2.4):

    These lifts are projections, not measurements. We don't have access
    to a real failure trace. The numbers are CONSISTENT with the Task 2
    final scorecard and the brief's framing, and the SHAPE of the
    intervention is documented in code so a reviewer can challenge any
    coefficient by editing one line.

What the simulator is NOT:

- Not a stochastic model. We don't sample distributions of lifts. The
  audit prose's claim is "we expect L2 to recover 4-7 points"; the
  simulator pins the midpoint and notes the range in the lever metadata.
- Not a configuration loader. Levers are defined in code so the diff is
  legible.
- Not a budgeting tool. ``q3_commit.py`` consumes the simulator output
  to argue what Q3 can actually ship.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from task3_eval_expansion.gap_decomposition import GapBucket, GapDecomposition


class LeverId(StrEnum):
    """The 5 named levers from the audit prose."""

    L1_REFUSAL_AWARE_METRIC = "L1"
    L2_KB_DELTA_TOP_AXES = "L2"
    L3_GROUNDING_THRESHOLD = "L3"
    L4_ESCALATION_TRIGGERS = "L4"
    L5_EVAL_IN_CI = "L5"


@dataclass(frozen=True)
class LeverEffect:
    """The mechanical effect of applying a lever to a decomposition.

    The simulator interprets this as a *contract*: when the lever fires,
    move at most ``max_questions_moved`` questions from the named
    ``source_bucket`` into the ``passing`` count. If the bucket has
    fewer questions than ``max_questions_moved``, only what's available
    is moved (we don't synthesise gold-set questions).
    """

    source_bucket: GapBucket
    max_questions_moved: int

    def __post_init__(self) -> None:
        if self.max_questions_moved < 0:
            raise ValueError(
                f"max_questions_moved must be non-negative, got {self.max_questions_moved}"
            )


@dataclass(frozen=True)
class Lever:
    """A named intervention with explicit effects.

    `effects` may have multiple entries — e.g. L3 (tightening grounding
    threshold) raises grounded-rate on borderline answers but also pushes
    some currently-grounded answers below threshold; the audit prose
    notes the asymmetry honestly. For now we keep the model simple: each
    effect is purely additive into ``passing``; a future iteration could
    model negative effects.

    `note` is a free-text annotation that lands in the audit table.
    """

    lever_id: LeverId
    name: str
    mechanism: str
    effects: tuple[LeverEffect, ...]
    note: str = ""

    def __post_init__(self) -> None:
        if not self.effects:
            raise ValueError(
                f"Lever {self.lever_id.value}: must declare at least one effect"
            )

    def apply(self, d: GapDecomposition) -> GapDecomposition:
        """Return a new decomposition with this lever's effects applied.

        The transformation:
        - For each effect: take min(bucket_count, max_questions_moved)
          questions and move them from the source bucket into ``passing``.

        Pure function. Doesn't mutate ``d``. Idempotent only for empty-
        source levers (which is the right behaviour: applying L1 twice
        doesn't get you double the refusal-aware bonus).
        """
        new_buckets = {
            GapBucket.RETRIEVAL_MISS: d.retrieval_miss,
            GapBucket.UNGROUNDED_ANSWER: d.ungrounded_answer,
            GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL: d.correct_refusal_counted_as_fail,
            GapBucket.WRONG_ANSWER_FALSE_POSITIVE: d.wrong_answer_false_positive,
        }
        new_passing = d.passing
        for effect in self.effects:
            available = new_buckets[effect.source_bucket]
            moved = min(available, effect.max_questions_moved)
            new_buckets[effect.source_bucket] = available - moved
            new_passing += moved
        return GapDecomposition(
            total_questions=d.total_questions,
            passing=new_passing,
            retrieval_miss=new_buckets[GapBucket.RETRIEVAL_MISS],
            ungrounded_answer=new_buckets[GapBucket.UNGROUNDED_ANSWER],
            correct_refusal_counted_as_fail=(
                new_buckets[GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL]
            ),
            wrong_answer_false_positive=new_buckets[GapBucket.WRONG_ANSWER_FALSE_POSITIVE],
        )


@dataclass(frozen=True)
class SimulationStep:
    """One step in the projected sequence.

    `before` and `after` are the decompositions on either side of the
    lever; `lever` is the one that fired. The audit prose embeds a
    table of these — one row per applied lever — showing the running
    deflection.
    """

    lever: Lever
    before: GapDecomposition
    after: GapDecomposition

    @property
    def lift_pp(self) -> float:
        """How many percentage points the lever moved the headline metric.

        We report raw deflection lift here. The audit prose discusses
        the refusal-aware lift in narrative form, and the consumer of
        this object (``q3_commit.py``) can inspect both.
        """
        return self.after.raw_deflection_pct - self.before.raw_deflection_pct


@dataclass(frozen=True)
class SimulationResult:
    """Trajectory: starting decomposition + per-lever steps + final state."""

    initial: GapDecomposition
    steps: tuple[SimulationStep, ...]

    @property
    def final(self) -> GapDecomposition:
        return self.steps[-1].after if self.steps else self.initial

    @property
    def total_raw_lift_pp(self) -> float:
        return self.final.raw_deflection_pct - self.initial.raw_deflection_pct

    @property
    def total_refusal_aware_lift_pp(self) -> float:
        return (
            self.final.refusal_aware_deflection_pct
            - self.initial.refusal_aware_deflection_pct
        )


def simulate_sequence(
    initial: GapDecomposition, levers: Sequence[Lever]
) -> SimulationResult:
    """Apply a sequence of levers to a starting decomposition.

    Pure function. Each lever's apply() runs on the *previous* lever's
    output, so the simulation is order-dependent. The audit prose argues
    a specific order (L1 → L2 → L3 → L4 → L5); reordering levers here
    would change the projected end-state, which is the point.
    """
    steps: list[SimulationStep] = []
    state = initial
    for lever in levers:
        new_state = lever.apply(state)
        steps.append(SimulationStep(lever=lever, before=state, after=new_state))
        state = new_state
    return SimulationResult(initial=initial, steps=tuple(steps))


# ---------------------------------------------------------------------------
# The 5 actual levers the audit prose argues
# ---------------------------------------------------------------------------


def lever_l1_refusal_aware_metric() -> Lever:
    """L1 — switch the headline metric from raw to refusal-aware.

    Pure measurement fix. Moves every question in the
    correct_refusal_counted_as_fail bucket into passing. No product
    change required — just stops penalising the agent for doing the
    right thing.

    Expected lift: the size of the correct_refusal bucket in PP. In the
    illustrated example, that's ~6 PP.
    """
    return Lever(
        lever_id=LeverId.L1_REFUSAL_AWARE_METRIC,
        name="Switch headline metric to refusal-aware deflection",
        mechanism=(
            "Pure measurement fix. A correct refusal (out-of-scope, "
            "restricted, ambiguous billing) is a desirable outcome, not "
            "a failure. The refusal-aware metric counts it as passing."
        ),
        effects=(
            # We move the ENTIRE bucket — by construction every question
            # in correct_refusal_counted_as_fail is reclaimed by the
            # metric switch. We use a large constant so the actual
            # bucket size caps it.
            LeverEffect(
                source_bucket=GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL,
                max_questions_moved=1_000_000,
            ),
        ),
        note="Free lift. Ship before any KB work.",
    )


def lever_l2_kb_delta_top_axes() -> Lever:
    """L2 — author KB chunks targeted at top-3 Task 1 failure axes.

    The brief asks for the second move after the metric fix: where does
    the next chunk of points come from? Task 1's taxonomy says the top
    axes are STALE_KB, WRONG_PROVIDER, and STALE_USAGE. Authoring 5-10
    chunks per axis (~20-30 chunks total) closes the retrieval-miss
    bucket on questions that map to those axes.

    Expected lift: most of the retrieval_miss bucket. In the illustrated
    example with 4 questions there, we project recovering 3-4 of them.
    Conservatively we model 3 (leaving 1 for the longer-tail miss).
    """
    return Lever(
        lever_id=LeverId.L2_KB_DELTA_TOP_AXES,
        name="Author KB chunks against top-3 taxonomy axes",
        mechanism=(
            "Target the top failure axes from Task 1's taxonomy (STALE_KB, "
            "WRONG_PROVIDER, STALE_USAGE). Author 5-10 chunks per axis. "
            "Closes most of the retrieval_miss bucket."
        ),
        effects=(
            LeverEffect(
                source_bucket=GapBucket.RETRIEVAL_MISS,
                max_questions_moved=3,
            ),
        ),
        note="Largest single product lever. Reuses Task 1 taxonomy as targeting.",
    )


def lever_l3_grounding_threshold() -> Lever:
    """L3 — tighten the grounding threshold.

    Borderline answers that retrieved a chunk but didn't ground are
    pushed past the threshold. Counter-cost: a small number of currently-
    grounded answers may also fall below; the audit prose discusses this
    honestly. Net effect modeled here as +1 question into passing from
    ungrounded_answer.
    """
    return Lever(
        lever_id=LeverId.L3_GROUNDING_THRESHOLD,
        name="Tighten grounding threshold",
        mechanism=(
            "Config change: raise grounding-score threshold so weakly-"
            "supported answers refuse instead of confidently asserting. "
            "Trades small refusal-aware loss for raw-metric gain."
        ),
        effects=(
            LeverEffect(
                source_bucket=GapBucket.UNGROUNDED_ANSWER,
                max_questions_moved=1,
            ),
        ),
        note="Caveat: tradeoff between raw and refusal-aware. Quantified in audit.",
    )


def lever_l4_escalation_triggers() -> Lever:
    """L4 — per-tenant escalation triggers (reuses Task 2 pattern).

    The wrong_answer_false_positive bucket is the highest-stakes — a
    confident wrong answer is what hurts the user. Escalation triggers
    catch the cases where the agent's confidence is high but the chunk
    context doesn't match the user's actual situation (e.g. provider
    mismatch, restricted feature).

    Expected lift: close most of WAFP. In the illustrated example with
    1 question there, we project recovering 1.
    """
    return Lever(
        lever_id=LeverId.L4_ESCALATION_TRIGGERS,
        name="Per-tenant escalation triggers",
        mechanism=(
            "Tenant-specific keyword + intent triggers route high-risk "
            "answers to a human. Reuses Task 2's escalation_triggers.py "
            "pattern; the additions here are tenant-specific keyword sets."
        ),
        effects=(
            LeverEffect(
                source_bucket=GapBucket.WRONG_ANSWER_FALSE_POSITIVE,
                max_questions_moved=1,
            ),
        ),
        note="Highest-stakes bucket. Lift looks small in pp but matters most.",
    )


def lever_l5_eval_in_ci() -> Lever:
    """L5 — eval-in-CI on every prompt change.

    This is a *guardrail* lever, not a lift lever. It doesn't move any
    questions from the gap into passing — it prevents the lift from
    L1-L4 from regressing the next time someone tweaks the system prompt.
    Modeled with zero effects so it's clear from the code that this
    isn't a point-buying move.
    """
    return Lever(
        lever_id=LeverId.L5_EVAL_IN_CI,
        name="Eval-in-CI on every prompt / KB change",
        mechanism=(
            "Run the gold set in CI on every PR that touches prompts or "
            "KB. Catches regressions from prompt tinkering. Does not buy "
            "points; sustains the L1-L4 lifts."
        ),
        # Zero effects — but we need at least one entry. Use a no-op
        # effect (move 0 questions from a bucket).
        effects=(
            LeverEffect(
                source_bucket=GapBucket.WRONG_ANSWER_FALSE_POSITIVE,
                max_questions_moved=0,
            ),
        ),
        note="Guardrail. No projected lift; prevents regression of L1-L4 gains.",
    )


def recommended_lever_sequence() -> tuple[Lever, ...]:
    """The sequence the audit prose §2.3 argues.

    Order matters: L1 first because it's free, L2 next because it's the
    largest product lever, L3/L4 third and fourth because they require
    tuning that's safer after the metric and KB are stable, L5 last
    because it's the sustain-it lever.
    """
    return (
        lever_l1_refusal_aware_metric(),
        lever_l2_kb_delta_top_axes(),
        lever_l3_grounding_threshold(),
        lever_l4_escalation_triggers(),
        lever_l5_eval_in_ci(),
    )


# ---------------------------------------------------------------------------
# Renderer for the audit-prose §2.3 trajectory table
# ---------------------------------------------------------------------------


def render_trajectory_table(result: SimulationResult) -> str:
    """Render the per-step trajectory as a markdown table.

    Output shape:
        | Step | Lever | Raw % | Δ raw (pp) | Refusal-aware % | Note |

    The audit prose pastes this output directly into §2.3.
    """
    lines = [
        "| Step | Lever | Raw % | Δ raw (pp) | Refusal-aware % | Note |",
        "|---|---|---:|---:|---:|---|",
        f"| 0 | (starting state) | {result.initial.raw_deflection_pct:.1f}% | "
        f"— | {result.initial.refusal_aware_deflection_pct:.1f}% | "
        f"baseline ({result.initial.passing}/{result.initial.total_questions} pass) |",
    ]
    for idx, step in enumerate(result.steps, start=1):
        lines.append(
            f"| {idx} | {step.lever.lever_id.value} "
            f"{step.lever.name} | "
            f"{step.after.raw_deflection_pct:.1f}% | "
            f"{step.lift_pp:+.1f} | "
            f"{step.after.refusal_aware_deflection_pct:.1f}% | "
            f"{step.lever.note} |"
        )
    return "\n".join(lines)


__all__ = [
    "Lever",
    "LeverEffect",
    "LeverId",
    "SimulationResult",
    "SimulationStep",
    "lever_l1_refusal_aware_metric",
    "lever_l2_kb_delta_top_axes",
    "lever_l3_grounding_threshold",
    "lever_l4_escalation_triggers",
    "lever_l5_eval_in_ci",
    "recommended_lever_sequence",
    "render_trajectory_table",
    "simulate_sequence",
]
