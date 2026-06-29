"""Tests for task3_eval_expansion.lever_simulator.

Covers:

1. ``LeverEffect`` / ``Lever`` validation
2. ``Lever.apply`` semantics — moves at-most N questions from named bucket
3. ``simulate_sequence`` chains levers; trajectory is order-dependent
4. The 5 recommended levers — each does what its mechanism claims
5. The recommended sequence on the illustrated 80% example lands at the
   numbers the audit prose argues (80% → 96% raw, 86% → 96% refusal-aware)
6. ``render_trajectory_table`` shape

Important property tested: the simulator NEVER violates the gap_decomp
partition invariant — every intermediate state is itself a valid
``GapDecomposition``. That's an emergent guarantee from ``Lever.apply``
constructing a fresh decomposition each step (which triggers the
constructor's validation).
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from task3_eval_expansion.gap_decomposition import (
    GapBucket,
    GapDecomposition,
    illustrated_decomposition_for_raw_80,
)
from task3_eval_expansion.lever_simulator import (
    Lever,
    LeverEffect,
    LeverId,
    SimulationResult,
    SimulationStep,
    lever_l1_refusal_aware_metric,
    lever_l2_kb_delta_top_axes,
    lever_l3_grounding_threshold,
    lever_l4_escalation_triggers,
    lever_l5_eval_in_ci,
    recommended_lever_sequence,
    render_trajectory_table,
    simulate_sequence,
)

# ---------------------------------------------------------------------------
# 1. LeverEffect + Lever validation
# ---------------------------------------------------------------------------


class TestLeverEffect:
    def test_construction(self) -> None:
        e = LeverEffect(
            source_bucket=GapBucket.RETRIEVAL_MISS, max_questions_moved=3
        )
        assert e.source_bucket == GapBucket.RETRIEVAL_MISS
        assert e.max_questions_moved == 3

    def test_zero_max_is_legal(self) -> None:
        # L5 (eval-in-CI) uses a 0-max effect because it's a guardrail.
        e = LeverEffect(
            source_bucket=GapBucket.WRONG_ANSWER_FALSE_POSITIVE,
            max_questions_moved=0,
        )
        assert e.max_questions_moved == 0

    def test_negative_max_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            LeverEffect(
                source_bucket=GapBucket.RETRIEVAL_MISS,
                max_questions_moved=-1,
            )

    def test_frozen(self) -> None:
        e = LeverEffect(
            source_bucket=GapBucket.RETRIEVAL_MISS, max_questions_moved=1
        )
        with pytest.raises(FrozenInstanceError):
            e.max_questions_moved = 2  # type: ignore[misc]


class TestLeverValidation:
    def test_must_declare_at_least_one_effect(self) -> None:
        with pytest.raises(ValueError, match="at least one effect"):
            Lever(
                lever_id=LeverId.L1_REFUSAL_AWARE_METRIC,
                name="x",
                mechanism="m",
                effects=(),
            )

    def test_frozen(self) -> None:
        lever = lever_l1_refusal_aware_metric()
        with pytest.raises(FrozenInstanceError):
            lever.name = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Lever.apply semantics
# ---------------------------------------------------------------------------


def _start_decomp(
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


class TestApplySemantics:
    def test_apply_moves_questions_from_source_to_passing(self) -> None:
        d = _start_decomp()
        lever = Lever(
            lever_id=LeverId.L2_KB_DELTA_TOP_AXES,
            name="test",
            mechanism="m",
            effects=(
                LeverEffect(
                    source_bucket=GapBucket.RETRIEVAL_MISS,
                    max_questions_moved=2,
                ),
            ),
        )
        d2 = lever.apply(d)
        assert d2.retrieval_miss == d.retrieval_miss - 2
        assert d2.passing == d.passing + 2

    def test_apply_clamps_at_bucket_size(self) -> None:
        # Lever wants to move 100 questions from a bucket with only 4.
        # Should clamp at 4 — we don't synthesise questions.
        d = _start_decomp()
        lever = Lever(
            lever_id=LeverId.L2_KB_DELTA_TOP_AXES,
            name="test",
            mechanism="m",
            effects=(
                LeverEffect(
                    source_bucket=GapBucket.RETRIEVAL_MISS,
                    max_questions_moved=100,
                ),
            ),
        )
        d2 = lever.apply(d)
        assert d2.retrieval_miss == 0
        assert d2.passing == d.passing + 4  # not + 100

    def test_apply_with_zero_effect_is_identity(self) -> None:
        d = _start_decomp()
        lever = lever_l5_eval_in_ci()
        d2 = lever.apply(d)
        assert d2.passing == d.passing
        assert d2.wrong_answer_false_positive == d.wrong_answer_false_positive

    def test_apply_does_not_mutate_input(self) -> None:
        d = _start_decomp()
        before_passing = d.passing
        before_rm = d.retrieval_miss
        _ = lever_l2_kb_delta_top_axes().apply(d)
        assert d.passing == before_passing
        assert d.retrieval_miss == before_rm

    def test_apply_preserves_total_questions(self) -> None:
        d = _start_decomp()
        for lever_fn in (
            lever_l1_refusal_aware_metric,
            lever_l2_kb_delta_top_axes,
            lever_l3_grounding_threshold,
            lever_l4_escalation_triggers,
            lever_l5_eval_in_ci,
        ):
            d2 = lever_fn().apply(d)
            assert d2.total_questions == d.total_questions

    def test_apply_result_passes_partition_invariant(self) -> None:
        # Implicit — if apply produced an unbalanced decomposition,
        # the GapDecomposition constructor would raise.
        d = _start_decomp()
        for lever_fn in (
            lever_l1_refusal_aware_metric,
            lever_l2_kb_delta_top_axes,
            lever_l3_grounding_threshold,
            lever_l4_escalation_triggers,
            lever_l5_eval_in_ci,
        ):
            d2 = lever_fn().apply(d)  # would raise if partition broken
            assert isinstance(d2, GapDecomposition)


# ---------------------------------------------------------------------------
# 3. simulate_sequence
# ---------------------------------------------------------------------------


class TestSimulateSequence:
    def test_empty_sequence_returns_initial_only(self) -> None:
        d = _start_decomp()
        r = simulate_sequence(d, ())
        assert r.initial == d
        assert r.final == d
        assert r.steps == ()

    def test_single_lever(self) -> None:
        d = _start_decomp()
        r = simulate_sequence(d, (lever_l1_refusal_aware_metric(),))
        assert len(r.steps) == 1
        assert r.steps[0].before == d
        assert r.steps[0].after.correct_refusal_counted_as_fail == 0

    def test_chained_state_propagates(self) -> None:
        d = _start_decomp()
        levers = (
            lever_l1_refusal_aware_metric(),
            lever_l2_kb_delta_top_axes(),
        )
        r = simulate_sequence(d, levers)
        # Step 2's "before" must equal step 1's "after".
        assert r.steps[1].before == r.steps[0].after

    def test_total_lift_matches_difference(self) -> None:
        d = _start_decomp()
        r = simulate_sequence(d, recommended_lever_sequence())
        expected = r.final.raw_deflection_pct - d.raw_deflection_pct
        assert math.isclose(r.total_raw_lift_pp, expected)

    def test_order_is_commutative_for_disjoint_levers(self) -> None:
        # The 5 recommended levers act on DISJOINT buckets — so the
        # final state is invariant under reordering. The audit prose
        # argues a specific order for *product* reasons (free lift first,
        # ship the cheap thing first, guardrail last) — NOT for
        # arithmetic reasons. Pin both halves of that claim.
        d = _start_decomp()
        forward = simulate_sequence(d, recommended_lever_sequence()).final
        reverse_levers = tuple(reversed(recommended_lever_sequence()))
        reverse = simulate_sequence(d, reverse_levers).final
        # Disjoint buckets → final state identical regardless of order.
        assert forward.passing == reverse.passing
        # Sanity: verify the 5 levers really do target distinct buckets.
        targets = {
            effect.source_bucket
            for lever in recommended_lever_sequence()
            for effect in lever.effects
            if effect.max_questions_moved > 0
        }
        # L1 → CRCF, L2 → RM, L3 → UA, L4 → WAFP. L5 has zero-move only.
        assert len(targets) == 4

    def test_per_step_lift_pp(self) -> None:
        d = _start_decomp()
        r = simulate_sequence(d, recommended_lever_sequence())
        lifts = [s.lift_pp for s in r.steps]
        # L1 reclaims 3 questions from a 50-question gold set → 6pp.
        assert math.isclose(lifts[0], 6.0)
        # L2 reclaims 3 questions → 6pp.
        assert math.isclose(lifts[1], 6.0)
        # L3 reclaims 1 question → 2pp.
        assert math.isclose(lifts[2], 2.0)
        # L4 reclaims 1 question → 2pp.
        assert math.isclose(lifts[3], 2.0)
        # L5 is a guardrail.
        assert math.isclose(lifts[4], 0.0)


# ---------------------------------------------------------------------------
# 4. The 5 recommended levers
# ---------------------------------------------------------------------------


class TestRecommendedLevers:
    def test_l1_targets_correct_refusal_bucket(self) -> None:
        lever = lever_l1_refusal_aware_metric()
        assert lever.lever_id == LeverId.L1_REFUSAL_AWARE_METRIC
        sources = {e.source_bucket for e in lever.effects}
        assert sources == {GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL}

    def test_l2_targets_retrieval_miss(self) -> None:
        lever = lever_l2_kb_delta_top_axes()
        sources = {e.source_bucket for e in lever.effects}
        assert sources == {GapBucket.RETRIEVAL_MISS}

    def test_l3_targets_ungrounded_answer(self) -> None:
        lever = lever_l3_grounding_threshold()
        sources = {e.source_bucket for e in lever.effects}
        assert sources == {GapBucket.UNGROUNDED_ANSWER}

    def test_l4_targets_wrong_answer_false_positive(self) -> None:
        lever = lever_l4_escalation_triggers()
        sources = {e.source_bucket for e in lever.effects}
        assert sources == {GapBucket.WRONG_ANSWER_FALSE_POSITIVE}

    def test_l5_is_guardrail_with_zero_max(self) -> None:
        lever = lever_l5_eval_in_ci()
        # All effects must have max_questions_moved == 0.
        for effect in lever.effects:
            assert effect.max_questions_moved == 0

    def test_recommended_sequence_has_five_levers(self) -> None:
        assert len(recommended_lever_sequence()) == 5

    def test_recommended_sequence_lever_ids_in_order(self) -> None:
        ids = [lever.lever_id for lever in recommended_lever_sequence()]
        assert ids == [
            LeverId.L1_REFUSAL_AWARE_METRIC,
            LeverId.L2_KB_DELTA_TOP_AXES,
            LeverId.L3_GROUNDING_THRESHOLD,
            LeverId.L4_ESCALATION_TRIGGERS,
            LeverId.L5_EVAL_IN_CI,
        ]


# ---------------------------------------------------------------------------
# 5. End-to-end illustrated example — the audit prose's headline numbers
# ---------------------------------------------------------------------------


class TestIllustrated80PercentTrajectory:
    """These tests pin the headline numbers in the audit prose's §2.3.

    Starting from 80% raw / 86% refusal-aware, applying L1-L5 in order,
    we should end at 96% raw / 96% refusal-aware. If any coefficient
    in a lever changes, these tests fail and the audit prose must
    be updated to match (or the lever was wrong).
    """

    def test_starting_state(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        assert math.isclose(d.raw_deflection_pct, 80.0)
        assert math.isclose(d.refusal_aware_deflection_pct, 86.0)

    def test_end_state_raw_deflection(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        # 40 + 3 + 3 + 1 + 1 + 0 = 48 passing out of 50 = 96.0%
        assert math.isclose(result.final.raw_deflection_pct, 96.0)

    def test_end_state_refusal_aware(self) -> None:
        # Refusal-aware collapses to raw once L1 has reclaimed the
        # correct-refusal bucket (because that bucket goes to zero).
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        assert math.isclose(
            result.final.refusal_aware_deflection_pct, 96.0
        )

    def test_l1_immediate_lift_is_six_pp(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        after_l1 = lever_l1_refusal_aware_metric().apply(d)
        # 40 + 3 = 43 passing out of 50 = 86%.
        assert math.isclose(after_l1.raw_deflection_pct, 86.0)
        # The refusal-aware was already at 86% — they meet.
        assert math.isclose(
            after_l1.raw_deflection_pct,
            d.refusal_aware_deflection_pct,
        )

    def test_total_raw_lift_is_16_pp(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        assert math.isclose(result.total_raw_lift_pp, 16.0)

    def test_l5_step_has_zero_lift(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        # Last step is L5.
        assert math.isclose(result.steps[-1].lift_pp, 0.0)


# ---------------------------------------------------------------------------
# 6. render_trajectory_table
# ---------------------------------------------------------------------------


class TestRenderTrajectoryTable:
    def test_includes_baseline_row(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        out = render_trajectory_table(result)
        assert "(starting state)" in out
        assert "baseline" in out

    def test_one_row_per_step_plus_baseline(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        out = render_trajectory_table(result)
        lines = out.strip().split("\n")
        # Header + sep + baseline + 5 steps = 8 lines.
        assert len(lines) == 8

    def test_all_lever_ids_appear(self) -> None:
        d = illustrated_decomposition_for_raw_80()
        result = simulate_sequence(d, recommended_lever_sequence())
        out = render_trajectory_table(result)
        for lid in LeverId:
            assert lid.value in out


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_simulation_step_lift_pp() -> None:
    d = _start_decomp()
    lever = lever_l1_refusal_aware_metric()
    after = lever.apply(d)
    step = SimulationStep(lever=lever, before=d, after=after)
    expected = after.raw_deflection_pct - d.raw_deflection_pct
    assert math.isclose(step.lift_pp, expected)


def test_simulation_result_handles_empty_steps() -> None:
    d = _start_decomp()
    result = SimulationResult(initial=d, steps=())
    assert result.final == d
    assert math.isclose(result.total_raw_lift_pp, 0.0)
