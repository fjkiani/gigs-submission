"""Tests for task1_audit.failure_taxonomy."""

from __future__ import annotations

import dataclasses

import pytest

from task1_audit.failure_taxonomy import (
    FailureAnnotation,
    FailureAxis,
    billing_ambiguity,
    distribution,
    missing_restriction,
    out_of_scope_over_reach,
    porting_decline_not_decoded,
    stale_kb,
    stale_usage,
    wrong_provider,
)

# ---------------------------------------------------------------------------
# Enum surface
# ---------------------------------------------------------------------------


class TestFailureAxis:
    def test_exactly_seven_axes(self) -> None:
        assert len(list(FailureAxis)) == 7

    def test_all_seven_present(self) -> None:
        expected = {
            "STALE_KB",
            "WRONG_PROVIDER",
            "STALE_USAGE",
            "MISSING_RESTRICTION",
            "PORTING_DECLINE_NOT_DECODED",
            "BILLING_AMBIGUITY",
            "OUT_OF_SCOPE_OVER_REACH",
        }
        actual = {a.value for a in FailureAxis}
        assert actual == expected

    def test_str_value_equality(self) -> None:
        # StrEnum lets the value compare as a string transparently.
        assert FailureAxis.STALE_KB == "STALE_KB"


# ---------------------------------------------------------------------------
# Per-constructor smoke tests
# ---------------------------------------------------------------------------


class TestStaleKb:
    def test_smoke(self) -> None:
        a = stale_kb(
            chunk_id="esim/install#2.1",
            chunk_updated_at="2026-04-01T00:00:00Z",
            plan_updated_at="2026-05-15T00:00:00Z",
        )
        assert a.axis is FailureAxis.STALE_KB
        assert a.evidence["chunk_id"] == "esim/install#2.1"
        assert "predates" in a.detail


class TestWrongProvider:
    @pytest.mark.parametrize("provider", ["p3", "p14", "p15"])
    def test_raises_on_lifecycle_capable_provider(self, provider: str) -> None:
        # Asking for WRONG_PROVIDER on a provider that DOES support lifecycle
        # is a caller bug — must raise loudly, not silently mis-tag.
        with pytest.raises(ValueError, match="DOES support"):
            wrong_provider(sim_id="sim_x", provider=provider)

    @pytest.mark.parametrize("provider", ["p1", "p99", "TMUS", ""])
    def test_accepts_non_lifecycle_provider(self, provider: str) -> None:
        a = wrong_provider(sim_id="sim_x", provider=provider)
        assert a.axis is FailureAxis.WRONG_PROVIDER
        assert a.evidence["provider"] == provider
        assert a.evidence["sim_id"] == "sim_x"


class TestStaleUsage:
    def test_smoke(self) -> None:
        a = stale_usage(subscription_id="sub_q", hours_old=8.3)
        assert a.axis is FailureAxis.STALE_USAGE
        assert a.evidence["hours_old"] == 8.3
        assert "8.3h old" in a.detail


class TestMissingRestriction:
    def test_with_reason(self) -> None:
        a = missing_restriction(subscription_id="sub_r", restriction_reason="overdue_invoice")
        assert a.axis is FailureAxis.MISSING_RESTRICTION
        assert "overdue_invoice" in a.detail

    def test_without_reason(self) -> None:
        a = missing_restriction(subscription_id="sub_r", restriction_reason=None)
        assert "unspecified" in a.detail


class TestPortingDeclineNotDecoded:
    def test_smoke(self) -> None:
        a = porting_decline_not_decoded(
            porting_id="prt_1",
            declined_code="portingPhoneNumberPortProtected",
            declined_message="The number is port-protected by the donor.",
        )
        assert a.axis is FailureAxis.PORTING_DECLINE_NOT_DECODED
        assert "portingPhoneNumberPortProtected" in a.detail
        assert "port-protected" in a.detail


class TestBillingAmbiguity:
    def test_smoke(self) -> None:
        a = billing_ambiguity(invoice_id="inv_42", actual_status="finalized")
        assert a.axis is FailureAxis.BILLING_AMBIGUITY
        assert "'finalized'" in a.detail


class TestOutOfScopeOverReach:
    def test_smoke(self) -> None:
        a = out_of_scope_over_reach(intent="ask_for_stock_picks")
        assert a.axis is FailureAxis.OUT_OF_SCOPE_OVER_REACH
        assert "ask_for_stock_picks" in a.detail


# ---------------------------------------------------------------------------
# Frozen-ness
# ---------------------------------------------------------------------------


class TestFailureAnnotationFrozen:
    def test_annotation_is_frozen(self) -> None:
        ann = stale_usage(subscription_id="sub_q", hours_old=10.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ann.detail = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


class TestDistribution:
    def test_empty_input_lists_all_axes(self) -> None:
        d = distribution([])
        assert set(d.keys()) == {a.value for a in FailureAxis}
        assert all(v == 0 for v in d.values())

    def test_counts_per_axis(self) -> None:
        anns = [
            stale_usage(subscription_id="s", hours_old=5),
            stale_usage(subscription_id="s", hours_old=6),
            missing_restriction(subscription_id="s", restriction_reason=None),
            out_of_scope_over_reach(intent="i"),
        ]
        d = distribution(anns)
        assert d["STALE_USAGE"] == 2
        assert d["MISSING_RESTRICTION"] == 1
        assert d["OUT_OF_SCOPE_OVER_REACH"] == 1
        assert d["STALE_KB"] == 0
        assert d["WRONG_PROVIDER"] == 0

    def test_ordering_is_descending_count_then_axis_name(self) -> None:
        anns = [
            stale_usage(subscription_id="s", hours_old=5),
            stale_usage(subscription_id="s", hours_old=6),
            missing_restriction(subscription_id="s", restriction_reason=None),
        ]
        d = distribution(anns)
        keys = list(d.keys())
        # STALE_USAGE (2) first; MISSING_RESTRICTION (1) second.
        assert keys[0] == "STALE_USAGE"
        assert keys[1] == "MISSING_RESTRICTION"
        # Then the zero-count axes in alphabetical order.
        zero_axes = keys[2:]
        assert zero_axes == sorted(zero_axes)


# ---------------------------------------------------------------------------
# Direct construction sanity (we don't *want* this, but it must work for tests)
# ---------------------------------------------------------------------------


class TestDirectConstruction:
    def test_manual_construction(self) -> None:
        ann = FailureAnnotation(
            axis=FailureAxis.STALE_KB,
            detail="explicit",
            evidence={"chunk_id": "x"},
        )
        assert ann.axis is FailureAxis.STALE_KB
        assert ann.evidence == {"chunk_id": "x"}
