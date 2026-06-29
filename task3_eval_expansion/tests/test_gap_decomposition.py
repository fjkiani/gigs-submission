"""Tests for task3_eval_expansion.gap_decomposition.

Covers:

1. Construction validation — non-negativity, exhaustiveness, individual bounds
2. Derived metrics — gap_size, raw vs refusal-aware deflection percentages
3. The illustrated worked example matches the audit prose's framing
4. ``render_decomposition_table`` shape

The point is that the 4-bucket model is a *partition* — every failing
question is in exactly one bucket. The partition invariant is what makes
the audit prose's lift math sound; without it, the buckets could
double-count and the projected lifts would be incoherent.
"""

from __future__ import annotations

import math
import re
from dataclasses import FrozenInstanceError

import pytest

from task3_eval_expansion.gap_decomposition import (
    GapBucket,
    GapDecomposition,
    illustrated_decomposition_for_raw_80,
    render_decomposition_table,
)

# ---------------------------------------------------------------------------
# 1. Construction validation
# ---------------------------------------------------------------------------


def _balanced(
    *,
    total: int = 50,
    passing: int = 40,
    rm: int = 4,
    ua: int = 2,
    crcf: int = 3,
    wafp: int = 1,
) -> GapDecomposition:
    return GapDecomposition(
        total_questions=total,
        passing=passing,
        retrieval_miss=rm,
        ungrounded_answer=ua,
        correct_refusal_counted_as_fail=crcf,
        wrong_answer_false_positive=wafp,
    )


class TestValidation:
    def test_balanced_construction(self) -> None:
        d = _balanced()
        assert d.total_questions == 50

    def test_zero_total_rejected(self) -> None:
        with pytest.raises(ValueError, match="total_questions must be positive"):
            GapDecomposition(
                total_questions=0,
                passing=0,
                retrieval_miss=0,
                ungrounded_answer=0,
                correct_refusal_counted_as_fail=0,
                wrong_answer_false_positive=0,
            )

    def test_negative_total_rejected(self) -> None:
        with pytest.raises(ValueError, match="total_questions must be positive"):
            GapDecomposition(
                total_questions=-1,
                passing=0,
                retrieval_miss=0,
                ungrounded_answer=0,
                correct_refusal_counted_as_fail=0,
                wrong_answer_false_positive=0,
            )

    @pytest.mark.parametrize(
        "bucket_field",
        [
            "passing",
            "retrieval_miss",
            "ungrounded_answer",
            "correct_refusal_counted_as_fail",
            "wrong_answer_false_positive",
        ],
    )
    def test_any_negative_count_rejected(self, bucket_field: str) -> None:
        # Start from a balanced decomposition then mutate one field to -1.
        kwargs = {
            "total_questions": 50,
            "passing": 40,
            "retrieval_miss": 4,
            "ungrounded_answer": 2,
            "correct_refusal_counted_as_fail": 3,
            "wrong_answer_false_positive": 1,
        }
        kwargs[bucket_field] = -1
        # Need to also shrink another bucket so totals balance — but
        # we want to test the negative check fires first.
        with pytest.raises(ValueError, match="must be non-negative"):
            GapDecomposition(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "bucket_field",
        [
            "passing",
            "retrieval_miss",
            "ungrounded_answer",
            "correct_refusal_counted_as_fail",
            "wrong_answer_false_positive",
        ],
    )
    def test_count_cannot_exceed_total(self, bucket_field: str) -> None:
        kwargs = {
            "total_questions": 50,
            "passing": 0,
            "retrieval_miss": 0,
            "ungrounded_answer": 0,
            "correct_refusal_counted_as_fail": 0,
            "wrong_answer_false_positive": 0,
        }
        kwargs[bucket_field] = 51
        with pytest.raises(ValueError, match="cannot exceed total_questions"):
            GapDecomposition(**kwargs)  # type: ignore[arg-type]

    def test_buckets_must_partition_gold_set(self) -> None:
        # 40 + 4 + 2 + 3 + 1 = 50, but we shrink to make it 49.
        with pytest.raises(ValueError, match="buckets do not partition gold set"):
            GapDecomposition(
                total_questions=50,
                passing=40,
                retrieval_miss=4,
                ungrounded_answer=2,
                correct_refusal_counted_as_fail=2,  # was 3
                wrong_answer_false_positive=1,
            )

    def test_overshoot_partition_rejected(self) -> None:
        with pytest.raises(ValueError, match="buckets do not partition gold set"):
            GapDecomposition(
                total_questions=50,
                passing=40,
                retrieval_miss=5,  # was 4
                ungrounded_answer=2,
                correct_refusal_counted_as_fail=3,
                wrong_answer_false_positive=1,
            )

    def test_all_passing_is_legal(self) -> None:
        # A degenerate but legal state: 100% pass, zero gap.
        d = GapDecomposition(
            total_questions=10,
            passing=10,
            retrieval_miss=0,
            ungrounded_answer=0,
            correct_refusal_counted_as_fail=0,
            wrong_answer_false_positive=0,
        )
        assert d.gap_size == 0
        assert d.raw_deflection_pct == 100.0

    def test_all_failing_is_legal(self) -> None:
        # The other degenerate state.
        d = GapDecomposition(
            total_questions=4,
            passing=0,
            retrieval_miss=1,
            ungrounded_answer=1,
            correct_refusal_counted_as_fail=1,
            wrong_answer_false_positive=1,
        )
        assert d.gap_size == 4
        assert d.raw_deflection_pct == 0.0

    def test_frozen(self) -> None:
        d = _balanced()
        with pytest.raises(FrozenInstanceError):
            d.passing = 41  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Derived metrics
# ---------------------------------------------------------------------------


class TestDerivedMetrics:
    def test_gap_size(self) -> None:
        d = _balanced()
        # 50 total, 40 passing → gap of 10.
        assert d.gap_size == 10

    def test_raw_deflection_pct(self) -> None:
        d = _balanced()
        # 40/50 = 80.0%
        assert math.isclose(d.raw_deflection_pct, 80.0)

    def test_refusal_aware_reclaims_correct_refusals(self) -> None:
        d = _balanced()
        # raw: 40/50 = 80%; refusal-aware: 43/50 = 86%.
        assert math.isclose(d.refusal_aware_deflection_pct, 86.0)
        # The gap between raw and refusal-aware equals correct_refusal
        # bucket as percentage points.
        delta = d.refusal_aware_deflection_pct - d.raw_deflection_pct
        bucket_pct = 100.0 * d.correct_refusal_counted_as_fail / d.total_questions
        assert math.isclose(delta, bucket_pct)

    def test_percentage_points_per_bucket(self) -> None:
        d = _balanced()
        pcts = d.percentage_points_per_bucket()
        # 4 / 50 = 8.0%
        assert math.isclose(pcts[GapBucket.RETRIEVAL_MISS], 8.0)
        assert math.isclose(pcts[GapBucket.UNGROUNDED_ANSWER], 4.0)
        assert math.isclose(pcts[GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL], 6.0)
        assert math.isclose(pcts[GapBucket.WRONG_ANSWER_FALSE_POSITIVE], 2.0)

    def test_percentage_points_sum_to_gap_size(self) -> None:
        d = _balanced()
        pcts = d.percentage_points_per_bucket()
        total = sum(pcts.values())
        # 4 buckets summing to gap = 20% (10/50)
        assert math.isclose(total, 20.0)
        # And gap as pct of total agrees.
        assert math.isclose(total, 100.0 * d.gap_size / d.total_questions)

    def test_count_lookup_matches_fields(self) -> None:
        d = _balanced()
        assert d.count(GapBucket.RETRIEVAL_MISS) == d.retrieval_miss
        assert d.count(GapBucket.UNGROUNDED_ANSWER) == d.ungrounded_answer
        assert (
            d.count(GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL)
            == d.correct_refusal_counted_as_fail
        )
        assert (
            d.count(GapBucket.WRONG_ANSWER_FALSE_POSITIVE)
            == d.wrong_answer_false_positive
        )


# ---------------------------------------------------------------------------
# 3. Illustrated worked example
# ---------------------------------------------------------------------------


class TestIllustratedExample:
    def test_construction_succeeds(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        assert d.total_questions == 50

    def test_passes_partition_invariant(self) -> None:
        # If this passes, the constructor's partition check passed too —
        # but we double-check the sums explicitly so a careless edit
        # to the function gets caught.
        d = illustrated_decomposition_for_raw_80()
        assert (
            d.passing
            + d.retrieval_miss
            + d.ungrounded_answer
            + d.correct_refusal_counted_as_fail
            + d.wrong_answer_false_positive
            == d.total_questions
        )

    def test_starts_at_raw_80_percent(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        # This is the brief's framing: agent is at ~80% deflection.
        assert math.isclose(d.raw_deflection_pct, 80.0)

    def test_refusal_aware_above_raw(self) -> None:
        # The "free 6 points" claim in the audit prose needs this to hold.
        d = illustrated_decomposition_for_raw_80()
        assert d.refusal_aware_deflection_pct > d.raw_deflection_pct

    def test_correct_refusal_bucket_drives_metric_gap(self) -> None:
        # The audit prose says: bucket #3 (correct refusal counted as
        # fail) is the bucket that the refusal-aware metric reclaims.
        d = illustrated_decomposition_for_raw_80()
        delta_pp = d.refusal_aware_deflection_pct - d.raw_deflection_pct
        crcf_pp = 100.0 * d.correct_refusal_counted_as_fail / d.total_questions
        assert math.isclose(delta_pp, crcf_pp)

    def test_wrong_answer_false_positive_is_smallest(self) -> None:
        # The highest-stakes bucket should be the smallest bucket in
        # the audit prose's illustrated example. If it isn't, the prose
        # is misleading and a reviewer should catch the mismatch.
        d = illustrated_decomposition_for_raw_80()
        # WAFP <= every other bucket
        assert d.wrong_answer_false_positive <= d.retrieval_miss
        assert d.wrong_answer_false_positive <= d.ungrounded_answer
        assert d.wrong_answer_false_positive <= d.correct_refusal_counted_as_fail


# ---------------------------------------------------------------------------
# 4. Render
# ---------------------------------------------------------------------------


class TestRenderDecompositionTable:
    def test_basic_shape(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        out = render_decomposition_table(d)
        lines = out.strip().split("\n")
        # Header + sep + 4 buckets = 6 lines.
        assert len(lines) == 6
        assert "Bucket" in lines[0]
        assert "Count" in lines[0]
        assert "Primary lever" in lines[0]

    def test_all_four_buckets_appear(self) -> None:
        out = render_decomposition_table(illustrated_decomposition_for_raw_80())
        for bucket in GapBucket:
            assert bucket.value in out

    def test_lever_names_in_output(self) -> None:
        # Each row lists the matching primary lever (L1-L4).
        out = render_decomposition_table(illustrated_decomposition_for_raw_80())
        assert "L1" in out
        assert "L2" in out
        assert "L3" in out
        assert "L4" in out

    def test_table_is_markdown_well_formed(self) -> None:
        out = render_decomposition_table(illustrated_decomposition_for_raw_80())
        # 4 columns (Bucket | Count | % of gold set | Primary lever) →
        # 5 pipes per row.
        for line in out.strip().split("\n")[2:]:
            pipes = re.findall(r"\|", line)
            assert len(pipes) == 5, f"bad row: {line!r}"


# ---------------------------------------------------------------------------
# Cross-cutting: every GapBucket enum value is reachable by count()
# ---------------------------------------------------------------------------


def test_count_handles_every_enum_value() -> None:
    d = illustrated_decomposition_for_raw_80()
    # Make sure no enum addition slips past count()'s match.
    for bucket in GapBucket:
        d.count(bucket)  # would raise on missing case
