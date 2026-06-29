"""4-bucket decomposition of the "80 → 90%" gap.

The brief asks: how would you get the agent from 80% to 90% deflection?
You don't answer that by guessing — you answer it by decomposing the 20%
gap into *named* failure modes, and then per bucket you point to the
intervention that closes it.

Buckets — these are the four ways a question in the gold set can fail to
register as a passing answered turn:

1. **retrieval_miss** — the gap-analysis tool returns "no chunk above
   threshold". The KB doesn't have the answer. Lever: author chunks
   targeted at the top failure axes from Task 1's taxonomy.

2. **ungrounded_answer** — a chunk was retrieved but the agent's answer
   didn't ground. Either the grounding threshold is too loose or the
   chunk doesn't actually contain the fact. Lever: tighten threshold OR
   improve chunk quality.

3. **correct_refusal_counted_as_fail** — the agent correctly refused
   (out-of-scope / restricted / billing-ambiguity) but the *raw* metric
   counts it as a failure. The refusal-aware metric counts it as a
   success. Lever: switch the headline metric — pure measurement fix,
   buys points without any product change.

4. **wrong_answer_false_positive** — the agent confidently answered
   something incorrect AND the answer ended up grounded against a chunk
   that didn't actually support it. This is the highest-stakes bucket
   because it's the one a user can be hurt by. Lever: tightened grounding
   threshold + escalation triggers from Task 2.

The buckets are mutually exclusive and exhaustive — every failing question
falls into exactly one. We enforce that as a runtime invariant.

This module is the typed substrate for §2.2 of the audit prose. It doesn't
*run* the decomposition (we don't have a real 50-question failure trace
for a tenant). It models the decomposition as a typed object so the prose
can argue numbers from named, immutable data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GapBucket(StrEnum):
    """The 4 buckets every failed question falls into.

    Mutually exclusive (a question is in exactly one bucket) and exhaustive
    (every failure must be in some bucket).
    """

    RETRIEVAL_MISS = "retrieval_miss"
    UNGROUNDED_ANSWER = "ungrounded_answer"
    CORRECT_REFUSAL_COUNTED_AS_FAIL = "correct_refusal_counted_as_fail"
    WRONG_ANSWER_FALSE_POSITIVE = "wrong_answer_false_positive"


@dataclass(frozen=True)
class GapDecomposition:
    """The 4-bucket attribution of the gap.

    All four bucket counts are absolute — number of questions in that
    bucket, not percentages. We compute percentages on the fly so we can
    sanity-check the input.

    `total_questions` is the size of the gold set the decomposition is
    against (typically 50 for the live tenants from Task 2). `passing` is
    questions that already pass under the *current* metric. The 4 buckets
    sum to `total_questions - passing`.

    Why not just take "the gap"? Two reasons. (1) The "gap" depends on the
    metric — refusal-aware and raw disagree by 32 points on the same data.
    (2) We need to validate that the buckets actually sum to a coherent
    number; otherwise the decomposition is decorative.
    """

    total_questions: int
    passing: int
    retrieval_miss: int
    ungrounded_answer: int
    correct_refusal_counted_as_fail: int
    wrong_answer_false_positive: int

    def __post_init__(self) -> None:
        if self.total_questions <= 0:
            raise ValueError(
                f"total_questions must be positive, got {self.total_questions}"
            )
        for field_name in (
            "passing",
            "retrieval_miss",
            "ungrounded_answer",
            "correct_refusal_counted_as_fail",
            "wrong_answer_false_positive",
        ):
            v = getattr(self, field_name)
            if v < 0:
                raise ValueError(f"{field_name} must be non-negative, got {v}")
            if v > self.total_questions:
                raise ValueError(
                    f"{field_name}={v} cannot exceed total_questions="
                    f"{self.total_questions}"
                )
        # Exhaustiveness invariant: passing + 4 buckets == total.
        accounted = (
            self.passing
            + self.retrieval_miss
            + self.ungrounded_answer
            + self.correct_refusal_counted_as_fail
            + self.wrong_answer_false_positive
        )
        if accounted != self.total_questions:
            raise ValueError(
                f"buckets do not partition gold set: passing({self.passing}) + "
                f"retrieval_miss({self.retrieval_miss}) + ungrounded_answer("
                f"{self.ungrounded_answer}) + correct_refusal_counted_as_fail("
                f"{self.correct_refusal_counted_as_fail}) + "
                f"wrong_answer_false_positive({self.wrong_answer_false_positive}) "
                f"= {accounted}, expected {self.total_questions}"
            )

    @property
    def gap_size(self) -> int:
        """Number of failing questions = sum of 4 buckets."""
        return self.total_questions - self.passing

    @property
    def raw_deflection_pct(self) -> float:
        """Raw % = passing / total. Bucket 3 is implicitly counted against us."""
        return 100.0 * self.passing / self.total_questions

    @property
    def refusal_aware_deflection_pct(self) -> float:
        """% under refusal-aware metric — bucket 3 moves to "passing"."""
        return (
            100.0
            * (self.passing + self.correct_refusal_counted_as_fail)
            / self.total_questions
        )

    def percentage_points_per_bucket(self) -> dict[GapBucket, float]:
        """Map each bucket to its size in percentage points of the gold set.

        These are the headline numbers in the audit prose's §2.2. A bucket
        of 6 questions out of 50 is "12 points of the gap" — that's what
        this returns.
        """
        n = self.total_questions
        return {
            GapBucket.RETRIEVAL_MISS: 100.0 * self.retrieval_miss / n,
            GapBucket.UNGROUNDED_ANSWER: 100.0 * self.ungrounded_answer / n,
            GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL: (
                100.0 * self.correct_refusal_counted_as_fail / n
            ),
            GapBucket.WRONG_ANSWER_FALSE_POSITIVE: (
                100.0 * self.wrong_answer_false_positive / n
            ),
        }

    def count(self, bucket: GapBucket) -> int:
        """Lookup the absolute count for a given bucket."""
        match bucket:
            case GapBucket.RETRIEVAL_MISS:
                return self.retrieval_miss
            case GapBucket.UNGROUNDED_ANSWER:
                return self.ungrounded_answer
            case GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL:
                return self.correct_refusal_counted_as_fail
            case GapBucket.WRONG_ANSWER_FALSE_POSITIVE:
                return self.wrong_answer_false_positive


# ---------------------------------------------------------------------------
# A worked example that powers the audit prose's §2.2 narrative.
#
# This is one *plausible* decomposition. The audit prose says explicitly:
# "without a real failure trace for a live tenant, these numbers are an
# illustrated argument, not a measurement." The numbers are conservative
# and consistent with the Task 2 final scorecard (50 questions, 50 pass
# refusal-aware, 34 pass raw — so the "raw gap" is 16 questions = 32%).
# ---------------------------------------------------------------------------


def illustrated_decomposition_for_raw_80() -> GapDecomposition:
    """Worked example: a tenant at ~80% raw deflection.

    The brief's framing assumes the agent is "at 80% deflection". We model
    that as a 50-question gold set with 40 passing under raw metric. The 10
    failing questions distribute across the 4 buckets in the proportions
    the audit prose argues:

    - 3 questions in correct_refusal_counted_as_fail (=> refusal-aware
      metric immediately reclaims them — "free" 6 points).
    - 4 questions in retrieval_miss (clusters around top Task 1 axes:
      STALE_KB / WRONG_PROVIDER / STALE_USAGE).
    - 2 questions in ungrounded_answer (chunk retrieved, threshold too
      loose to count it as grounded — tighten threshold OR rewrite chunk).
    - 1 question in wrong_answer_false_positive (highest stakes; partial
      grounding against an outdated chunk — needs Task 2 escalation hop).

    These are not measurements. They're the seed numbers the lever
    simulator (lever_simulator.py) consumes to project lifts.
    """
    return GapDecomposition(
        total_questions=50,
        passing=40,
        retrieval_miss=4,
        ungrounded_answer=2,
        correct_refusal_counted_as_fail=3,
        wrong_answer_false_positive=1,
    )


# ---------------------------------------------------------------------------
# Renderer — used by the audit doc to embed the bucket table.
# ---------------------------------------------------------------------------


def render_decomposition_table(d: GapDecomposition) -> str:
    """Render the 4-bucket decomposition as a markdown table.

    Output shape:
        | Bucket | Count | % of gold set | Lever |
        |---|---|---|---|
        | retrieval_miss | 4 | 8.0% | L2: KB delta on top-3 axes |
        | ...
    """
    pcts = d.percentage_points_per_bucket()
    lines = [
        "| Bucket | Count | % of gold set | Primary lever |",
        "|---|---|---|---|",
    ]
    rows: tuple[tuple[GapBucket, str], ...] = (
        (GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL, "L1 — switch to refusal-aware metric"),
        (GapBucket.RETRIEVAL_MISS, "L2 — KB delta on top-3 taxonomy axes"),
        (GapBucket.UNGROUNDED_ANSWER, "L3 — tighten grounding threshold"),
        (GapBucket.WRONG_ANSWER_FALSE_POSITIVE, "L4 — per-tenant escalation triggers"),
    )
    for bucket, lever in rows:
        lines.append(
            f"| `{bucket.value}` | {d.count(bucket)} | "
            f"{pcts[bucket]:.1f}% | {lever} |"
        )
    return "\n".join(lines)


__all__ = [
    "GapBucket",
    "GapDecomposition",
    "illustrated_decomposition_for_raw_80",
    "render_decomposition_table",
]
