"""Tests for task3_eval_expansion.expansion_track.

The goal isn't 100% line coverage — it's to pin down the verdict-computation
rules and the shape of the 6 recommended reports so a verdict flip in either
direction would have to come with a deliberate test change.

Grouped by concern:

1. ``ReadinessGate`` validation invariants
2. ``TrackReport`` validation invariants
3. ``TrackReport.verdict`` rule table
4. The 6 recommended reports — verdicts, blocker locations, summary shape
5. ``render_verdict_table`` formatting + idempotence
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError

import pytest

from task3_eval_expansion.expansion_track import (
    ReadinessGate,
    ReadinessVerdict,
    SurfaceClass,
    Track,
    TrackReport,
    recommended_track_reports,
    render_verdict_table,
    summarise,
    track_1_same_vertical,
    track_2_local_fintech,
    track_3a_devices_user_facing,
    track_3b_devices_partner_facing,
    track_4_partner_widget,
    track_5_agentic_email,
)

# ---------------------------------------------------------------------------
# 1. ReadinessGate validation
# ---------------------------------------------------------------------------


class TestReadinessGate:
    def test_construction_with_all_fields(self) -> None:
        g = ReadinessGate(
            name="kb_coverage",
            passed=True,
            blocking=False,
            evidence="50 chunks authored",
        )
        assert g.name == "kb_coverage"
        assert g.passed is True
        assert g.blocking is False
        assert g.evidence == "50 chunks authored"

    def test_frozen(self) -> None:
        g = ReadinessGate(name="g", passed=True, blocking=False, evidence="ok")
        with pytest.raises(FrozenInstanceError):
            g.passed = False  # type: ignore[misc]

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name must be non-empty"):
            ReadinessGate(name="", passed=True, blocking=False, evidence="ok")

    def test_empty_evidence_rejected(self) -> None:
        # Every gate must point to an artifact — that's the contract that
        # makes the audit prose auditable.
        with pytest.raises(ValueError, match="evidence must be non-empty"):
            ReadinessGate(name="g", passed=True, blocking=False, evidence="")

    def test_passed_blocking_independent(self) -> None:
        # All 4 combinations are legal at construction time — the verdict
        # rules apply at report level, not gate level.
        for passed in (True, False):
            for blocking in (True, False):
                g = ReadinessGate(
                    name=f"g_{passed}_{blocking}",
                    passed=passed,
                    blocking=blocking,
                    evidence="e",
                )
                assert g.passed is passed
                assert g.blocking is blocking


# ---------------------------------------------------------------------------
# 2. TrackReport validation
# ---------------------------------------------------------------------------


def _track() -> Track:
    return Track(name="T", population="P", surface_class=SurfaceClass.CONSUMER_CHAT)


def _gate(name: str, passed: bool, blocking: bool = False) -> ReadinessGate:
    return ReadinessGate(name=name, passed=passed, blocking=blocking, evidence="e")


class TestTrackReportValidation:
    def test_empty_gates_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one gate"):
            TrackReport(track=_track(), gates=())

    def test_duplicate_gate_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate gate names"):
            TrackReport(
                track=_track(),
                gates=(_gate("g1", True), _gate("g1", False)),
            )

    def test_frozen(self) -> None:
        r = TrackReport(track=_track(), gates=(_gate("g1", True),))
        with pytest.raises(FrozenInstanceError):
            r.summary = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. Verdict derivation rules — the rule table that drives the audit prose
# ---------------------------------------------------------------------------


class TestVerdictRules:
    def test_all_gates_passed_is_ready(self) -> None:
        r = TrackReport(
            track=_track(),
            gates=(
                _gate("a", True, blocking=True),
                _gate("b", True, blocking=False),
            ),
        )
        assert r.verdict == ReadinessVerdict.READY

    def test_any_blocking_failure_is_not_ready(self) -> None:
        r = TrackReport(
            track=_track(),
            gates=(
                _gate("a", True, blocking=False),
                _gate("b", False, blocking=True),  # blocker fails
                _gate("c", True, blocking=False),
            ),
        )
        assert r.verdict == ReadinessVerdict.NOT_READY

    def test_only_non_blocking_failures_is_needs_work(self) -> None:
        r = TrackReport(
            track=_track(),
            gates=(
                _gate("a", True, blocking=True),
                _gate("b", False, blocking=False),
                _gate("c", False, blocking=False),
            ),
        )
        assert r.verdict == ReadinessVerdict.NEEDS_WORK

    def test_blocking_failure_dominates_non_blocking_pass(self) -> None:
        # If a blocking gate fails, verdict is NOT_READY even if other
        # non-blocking gates pass.
        r = TrackReport(
            track=_track(),
            gates=(
                _gate("blocker", False, blocking=True),
                _gate("nice_to_have", True, blocking=False),
            ),
        )
        assert r.verdict == ReadinessVerdict.NOT_READY

    def test_failing_gates_preserves_declaration_order(self) -> None:
        r = TrackReport(
            track=_track(),
            gates=(
                _gate("alpha", False),
                _gate("beta", True),
                _gate("gamma", False),
                _gate("delta", False),
            ),
        )
        names = [g.name for g in r.failing_gates]
        assert names == ["alpha", "gamma", "delta"]

    def test_blocking_failures_is_subset_of_failing_gates(self) -> None:
        r = TrackReport(
            track=_track(),
            gates=(
                _gate("a", False, blocking=True),
                _gate("b", False, blocking=False),
                _gate("c", True, blocking=True),
            ),
        )
        assert [g.name for g in r.blocking_failures] == ["a"]
        # All blocking failures appear in failing_gates.
        for g in r.blocking_failures:
            assert g in r.failing_gates


# ---------------------------------------------------------------------------
# 4. The 6 recommended reports — verdicts, blocker locations, summaries
# ---------------------------------------------------------------------------


class TestRecommendedReports:
    """One test per track verdict, plus aggregate invariants.

    These tests pin the design decisions from the audit prose. Flipping
    any verdict requires editing both the report and the matching test —
    that's the point.
    """

    def test_track_1_is_ready(self) -> None:
        r = track_1_same_vertical()
        assert r.verdict == ReadinessVerdict.READY
        assert len(r.failing_gates) == 0

    def test_track_2_needs_work_no_blocker(self) -> None:
        # Local/fintech: KB thin, no auth gap. Verdict NEEDS_WORK.
        r = track_2_local_fintech()
        assert r.verdict == ReadinessVerdict.NEEDS_WORK
        assert len(r.blocking_failures) == 0
        # KB coverage is the headline non-blocker.
        failing_names = {g.name for g in r.failing_gates}
        assert "kb_coverage_local_fintech" in failing_names

    def test_track_3a_needs_work_no_blocker(self) -> None:
        # Devices user-facing: same surface as live, new content/QA work.
        # NOT a blocker — same auth surface as live tenants.
        r = track_3a_devices_user_facing()
        assert r.verdict == ReadinessVerdict.NEEDS_WORK
        assert len(r.blocking_failures) == 0

    def test_track_3b_not_ready_shares_auth_blocker(self) -> None:
        # Devices partner-facing: shares Track 4's auth-scoping blocker.
        r = track_3b_devices_partner_facing()
        assert r.verdict == ReadinessVerdict.NOT_READY
        blocker_names = {g.name for g in r.blocking_failures}
        # The auth-scoping gate must be one of the blockers.
        assert "middleware_exists_with_scoped_auth" in blocker_names

    def test_track_4_not_ready_with_auth_blocker(self) -> None:
        # Partner-led widget: auth blocker + new surface + new contract.
        r = track_4_partner_widget()
        assert r.verdict == ReadinessVerdict.NOT_READY
        blocker_names = {g.name for g in r.blocking_failures}
        assert "middleware_exists_with_scoped_auth" in blocker_names
        # Must declare more than 1 blocker — the brief says it's the
        # heaviest multi-quarter lift.
        assert len(r.blocking_failures) >= 2

    def test_track_5_needs_work_no_blocker(self) -> None:
        # Agentic email: async surface, but auth model unchanged.
        r = track_5_agentic_email()
        assert r.verdict == ReadinessVerdict.NEEDS_WORK
        assert len(r.blocking_failures) == 0

    def test_track_3b_and_track_4_share_auth_blocker(self) -> None:
        """The audit prose's core Part A claim: 3b and 4 share the same
        auth-scoping blocker. This test pins that — if the blocker is
        renamed or removed from one, the test catches it.
        """
        gate_name = "middleware_exists_with_scoped_auth"
        r3b = track_3b_devices_partner_facing()
        r4 = track_4_partner_widget()
        names_3b = {g.name for g in r3b.blocking_failures}
        names_4 = {g.name for g in r4.blocking_failures}
        assert gate_name in names_3b
        assert gate_name in names_4

    def test_recommended_reports_count_and_order(self) -> None:
        reports = recommended_track_reports()
        # 5 brief tracks, with Track 3 split into 3a + 3b = 6 reports.
        assert len(reports) == 6
        # Verdicts in declared order.
        verdicts = [r.verdict for r in reports]
        assert verdicts == [
            ReadinessVerdict.READY,
            ReadinessVerdict.NEEDS_WORK,
            ReadinessVerdict.NEEDS_WORK,
            ReadinessVerdict.NOT_READY,
            ReadinessVerdict.NOT_READY,
            ReadinessVerdict.NEEDS_WORK,
        ]

    def test_every_recommended_report_has_summary(self) -> None:
        # The summary lands in the markdown table — empty would make
        # the table broken. Pin it.
        for r in recommended_track_reports():
            assert r.summary, f"empty summary on {r.track.name!r}"
            assert len(r.summary) < 200, (
                f"summary too long ({len(r.summary)} chars) on {r.track.name!r}; "
                "table rows should be one line"
            )


# ---------------------------------------------------------------------------
# 5. render_verdict_table — output shape
# ---------------------------------------------------------------------------


class TestRenderVerdictTable:
    def test_default_renders_all_recommended_tracks(self) -> None:
        out = render_verdict_table()
        # One header + one separator + one row per report.
        lines = out.strip().split("\n")
        assert len(lines) == 2 + 6
        # Header has the expected columns.
        assert lines[0].startswith("| Track | Verdict |")

    def test_renders_passed_verdicts_as_code(self) -> None:
        out = render_verdict_table()
        # Each verdict shows as `READY` / `NEEDS_WORK` / `NOT_READY`
        # wrapped in backticks so the markdown renders monospace.
        assert "`READY`" in out
        assert "`NEEDS_WORK`" in out
        assert "`NOT_READY`" in out

    def test_explicit_reports_argument_used(self) -> None:
        # Pass a 1-element list — should render exactly 1 data row.
        out = render_verdict_table((track_1_same_vertical(),))
        lines = out.strip().split("\n")
        assert len(lines) == 3  # header + sep + 1 row

    def test_idempotent(self) -> None:
        # Same inputs → same output. Useful for the audit doc's
        # paste-through workflow.
        assert render_verdict_table() == render_verdict_table()

    def test_summary_appears_in_row(self) -> None:
        # The 6 summaries each show up verbatim in the table output.
        out = render_verdict_table()
        for r in recommended_track_reports():
            assert r.summary in out


class TestSummarise:
    def test_summary_shape_matches_report(self) -> None:
        r = track_3b_devices_partner_facing()
        s = summarise(r)
        assert s.name == r.track.name
        assert s.verdict == r.verdict
        assert s.summary == r.summary
        assert s.failing_gate_count == len(r.failing_gates)
        assert s.blocking_failure_count == len(r.blocking_failures)


# ---------------------------------------------------------------------------
# Light cross-module invariants (no false coupling, just shape)
# ---------------------------------------------------------------------------


def test_surface_class_partner_widget_only_on_partner_tracks() -> None:
    """Partner-widget surface class should only appear on partner tracks.

    Pins that we didn't accidentally classify Track 1 as a partner widget.
    """
    by_name = {r.track.name: r for r in recommended_track_reports()}
    expected_widget = {
        "Devices/retail — partner-facing",
        "Partner-led widget",
    }
    actual_widget = {
        name
        for name, r in by_name.items()
        if r.track.surface_class == SurfaceClass.PARTNER_WIDGET
    }
    assert actual_widget == expected_widget


def test_async_email_surface_only_on_track_5() -> None:
    by_name = {r.track.name: r for r in recommended_track_reports()}
    async_names = {
        name
        for name, r in by_name.items()
        if r.track.surface_class == SurfaceClass.ASYNC_EMAIL
    }
    assert async_names == {"Agentic email channel"}


def test_verdict_strenum_string_values_are_stable() -> None:
    """The markdown table writes verdict.value directly. Pin the strings
    so a careless StrEnum rename can't silently shift the rendered table.
    """
    assert ReadinessVerdict.READY.value == "READY"
    assert ReadinessVerdict.NEEDS_WORK.value == "NEEDS_WORK"
    assert ReadinessVerdict.NOT_READY.value == "NOT_READY"


def test_markdown_table_passes_basic_sanity_regex() -> None:
    # Each row has exactly 5 cell separators.
    out = render_verdict_table()
    for line in out.strip().split("\n")[2:]:  # skip header + sep
        # 5 columns → 6 pipes per row.
        pipes = re.findall(r"\|", line)
        assert len(pipes) == 6, f"bad row: {line!r}"
