"""Tests for task3_eval_expansion.q3_commit.

The point of these tests is to pin the *structure* of the pushback —
specifically: there must be exactly 3 monotonically-increasing milestones,
the metric must be locked in advance, and the explicit non-commits must
include the auth-blocked tracks and the bare 90% number.

If anyone "fixes" the commit document later by quietly removing a
non-commit or shifting a milestone's metric, these tests catch it.
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError

import pytest

from task3_eval_expansion.q3_commit import (
    CommitTier,
    HeadlineMetric,
    Milestone,
    NonCommit,
    Q3Commit,
    recommended_q3_commit,
    render_commit_table,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_milestone(
    tier: CommitTier = CommitTier.DEFENDABLE,
    pct: float = 86.0,
    levers: tuple[str, ...] = ("L1",),
) -> Milestone:
    return Milestone(
        tier=tier,
        name="m",
        week_window="weeks 1-2",
        target_metric=HeadlineMetric.REFUSAL_AWARE_DEFLECTION,
        target_value_pct=pct,
        gate="g",
        observable="o",
        primary_levers=levers,
        risk_if_skipped="r",
    )


# ---------------------------------------------------------------------------
# 1. Milestone validation
# ---------------------------------------------------------------------------


class TestMilestoneValidation:
    @pytest.mark.parametrize("pct", [-1.0, -0.1, 100.1, 150.0])
    def test_out_of_range_pct_rejected(self, pct: float) -> None:
        with pytest.raises(ValueError, match="target_value_pct"):
            _valid_milestone(pct=pct)

    @pytest.mark.parametrize("pct", [0.0, 50.0, 100.0])
    def test_in_range_pct_legal(self, pct: float) -> None:
        m = _valid_milestone(pct=pct)
        assert m.target_value_pct == pct

    def test_empty_levers_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one primary lever"):
            _valid_milestone(levers=())

    def test_frozen(self) -> None:
        m = _valid_milestone()
        with pytest.raises(FrozenInstanceError):
            m.target_value_pct = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Q3Commit validation
# ---------------------------------------------------------------------------


def _three_milestones(
    pct_d: float = 86.0, pct_p: float = 92.0, pct_s: float = 96.0
) -> tuple[Milestone, ...]:
    return (
        _valid_milestone(tier=CommitTier.DEFENDABLE, pct=pct_d),
        _valid_milestone(tier=CommitTier.PRODUCT, pct=pct_p, levers=("L2",)),
        _valid_milestone(tier=CommitTier.STRETCH, pct=pct_s, levers=("L3",)),
    )


def _commit_with(milestones: tuple[Milestone, ...]) -> Q3Commit:
    return Q3Commit(
        headline="h",
        milestones=milestones,
        measurement_discipline="md",
        non_commits=(NonCommit(item="x", reason="r", earliest_reasonable_quarter="Q4"),),
    )


class TestQ3CommitValidation:
    def test_construction_succeeds_on_canonical_order(self) -> None:
        c = _commit_with(_three_milestones())
        assert c.defendable.tier == CommitTier.DEFENDABLE
        assert c.product.tier == CommitTier.PRODUCT
        assert c.stretch.tier == CommitTier.STRETCH

    def test_two_milestones_rejected(self) -> None:
        ms = _three_milestones()[:2]  # only 2
        with pytest.raises(ValueError, match="exactly 3 milestones"):
            _commit_with(ms)

    def test_four_milestones_rejected(self) -> None:
        ms = (*_three_milestones(), _valid_milestone(tier=CommitTier.STRETCH, pct=97.0))
        with pytest.raises(ValueError, match="exactly 3 milestones"):
            _commit_with(ms)

    def test_wrong_tier_order_rejected(self) -> None:
        # Stretch before defendable.
        ms = (
            _valid_milestone(tier=CommitTier.STRETCH, pct=80.0),
            _valid_milestone(tier=CommitTier.PRODUCT, pct=85.0, levers=("L2",)),
            _valid_milestone(tier=CommitTier.DEFENDABLE, pct=90.0, levers=("L1",)),
        )
        with pytest.raises(ValueError, match="must be in order"):
            _commit_with(ms)

    def test_non_monotonic_target_values_rejected(self) -> None:
        ms = _three_milestones(pct_d=92.0, pct_p=86.0, pct_s=96.0)
        with pytest.raises(ValueError, match="monotonically non-decreasing"):
            _commit_with(ms)

    def test_equal_target_values_legal(self) -> None:
        # Monotonic NON-DECREASING — equal values are fine.
        ms = _three_milestones(pct_d=90.0, pct_p=90.0, pct_s=92.0)
        c = _commit_with(ms)
        assert c.product.target_value_pct == 90.0

    def test_frozen(self) -> None:
        c = _commit_with(_three_milestones())
        with pytest.raises(FrozenInstanceError):
            c.headline = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. The recommended Q3 commit
# ---------------------------------------------------------------------------


class TestRecommendedQ3Commit:
    def test_construction_succeeds(self) -> None:
        c = recommended_q3_commit()
        assert len(c.milestones) == 3

    def test_three_tiers_in_order(self) -> None:
        c = recommended_q3_commit()
        assert [m.tier for m in c.milestones] == [
            CommitTier.DEFENDABLE,
            CommitTier.PRODUCT,
            CommitTier.STRETCH,
        ]

    def test_all_milestones_use_refusal_aware_metric(self) -> None:
        # The audit prose's measurement-discipline section pins the metric.
        # If a future edit silently switches one to raw deflection, this
        # test catches the regression.
        c = recommended_q3_commit()
        for m in c.milestones:
            assert m.target_metric == HeadlineMetric.REFUSAL_AWARE_DEFLECTION

    def test_target_values_match_audit_prose(self) -> None:
        # 86 / 92 / 96 — these numbers appear in the audit prose's §3.
        # Pin them so the doc and code stay in sync.
        c = recommended_q3_commit()
        assert c.defendable.target_value_pct == 86.0
        assert c.product.target_value_pct == 92.0
        assert c.stretch.target_value_pct == 96.0

    def test_defendable_uses_l1_only(self) -> None:
        # Free lift first.
        c = recommended_q3_commit()
        assert c.defendable.primary_levers == ("L1",)

    def test_product_includes_l2(self) -> None:
        # The largest product lever drives the product tier.
        c = recommended_q3_commit()
        assert "L2" in c.product.primary_levers

    def test_stretch_includes_l5_guardrail(self) -> None:
        c = recommended_q3_commit()
        assert "L5" in c.stretch.primary_levers

    def test_each_milestone_declares_gate_and_observable(self) -> None:
        c = recommended_q3_commit()
        for m in c.milestones:
            assert m.gate, f"empty gate on tier {m.tier.value}"
            assert m.observable, f"empty observable on tier {m.tier.value}"
            assert m.risk_if_skipped, f"empty risk on tier {m.tier.value}"

    def test_measurement_discipline_mentions_refusal_aware(self) -> None:
        c = recommended_q3_commit()
        assert "refusal-aware" in c.measurement_discipline.lower()


# ---------------------------------------------------------------------------
# 4. Non-commits — the pushback's substance
# ---------------------------------------------------------------------------


class TestNonCommits:
    def test_three_non_commits(self) -> None:
        c = recommended_q3_commit()
        assert len(c.non_commits) == 3

    def test_explicitly_refuses_single_90_number(self) -> None:
        """The pushback's headline claim: don't commit to one 90% number.
        That must appear as an explicit non-commit; if a future edit
        quietly removes it, the pushback collapses."""
        c = recommended_q3_commit()
        items = [nc.item.lower() for nc in c.non_commits]
        assert any("90" in item for item in items), (
            "The non-commits must include the explicit refusal of a single "
            "90% number — that's the pushback's substance."
        )

    def test_excludes_auth_blocked_tracks(self) -> None:
        """Track 4 (partner widget) and Track 3b (partner-facing devices)
        share the auth blocker — they MUST be in the Q3 non-commits."""
        c = recommended_q3_commit()
        all_text = " ".join(nc.item + " " + nc.reason for nc in c.non_commits).lower()
        assert "partner" in all_text
        assert "auth" in all_text

    def test_excludes_async_email(self) -> None:
        c = recommended_q3_commit()
        all_text = " ".join(nc.item.lower() for nc in c.non_commits)
        assert "email" in all_text

    def test_every_non_commit_has_reason_and_earliest_quarter(self) -> None:
        c = recommended_q3_commit()
        for nc in c.non_commits:
            assert nc.reason, f"empty reason for {nc.item!r}"
            assert (
                nc.earliest_reasonable_quarter
            ), f"empty earliest_reasonable_quarter for {nc.item!r}"

    def test_frozen(self) -> None:
        nc = NonCommit(item="x", reason="r", earliest_reasonable_quarter="Q4")
        with pytest.raises(FrozenInstanceError):
            nc.item = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. render_commit_table
# ---------------------------------------------------------------------------


class TestRenderCommitTable:
    def test_includes_all_section_headers(self) -> None:
        out = render_commit_table(recommended_q3_commit())
        assert "### Headline" in out
        assert "### Staged milestones" in out
        assert "### Measurement discipline" in out
        assert "### Explicit non-commits" in out

    def test_table_has_three_milestone_rows(self) -> None:
        out = render_commit_table(recommended_q3_commit())
        # Look at the staged-milestones section: count rows after the
        # separator (`|---|...`) and before the next section header.
        lines = out.split("\n")
        in_milestones_table = False
        rows = 0
        for line in lines:
            if line.startswith("|---|"):
                in_milestones_table = True
                continue
            if in_milestones_table:
                if not line.startswith("|"):
                    break
                rows += 1
        assert rows == 3, f"expected 3 milestone rows, got {rows}"

    def test_all_three_tier_names_appear(self) -> None:
        out = render_commit_table(recommended_q3_commit())
        for tier in CommitTier:
            assert f"`{tier.value}`" in out

    def test_milestone_rows_are_well_formed(self) -> None:
        out = render_commit_table(recommended_q3_commit())
        # Pull just the milestone rows.
        lines = out.split("\n")
        ms_rows = [
            line
            for line in lines
            if line.startswith("| `") and any(t.value in line for t in CommitTier)
        ]
        assert len(ms_rows) == 3
        # 6 columns (Tier | Week | Target | Metric | Levers | Gate) → 7 pipes.
        for row in ms_rows:
            pipes = re.findall(r"\|", row)
            assert len(pipes) == 7, f"bad row: {row!r}"


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_q3_commit_pct_monotonic_across_tiers() -> None:
    """The audit prose argues escalation. If a future edit accidentally
    sets STRETCH below PRODUCT, the constructor's monotonic check fires —
    but pin the property directly too."""
    c = recommended_q3_commit()
    assert (
        c.defendable.target_value_pct
        <= c.product.target_value_pct
        <= c.stretch.target_value_pct
    )


def test_q3_commit_target_metrics_strenum_value_stable() -> None:
    # The render uses `.value` directly.
    assert HeadlineMetric.RAW_DEFLECTION.value == "raw_deflection"
    assert HeadlineMetric.REFUSAL_AWARE_DEFLECTION.value == "refusal_aware_deflection"


def test_commit_tier_strenum_values_stable() -> None:
    assert CommitTier.DEFENDABLE.value == "defendable"
    assert CommitTier.PRODUCT.value == "product"
    assert CommitTier.STRETCH.value == "stretch"
