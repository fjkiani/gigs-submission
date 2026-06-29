"""Tests for escalation_triggers.evaluate_triggers.

Cover: each of 7 trigger kinds fires on its matching context; first-match
wins ordering is preserved; no trigger fires on a clean context; the
HandoffReason mapping is the documented collapsed set (six values, not
seven).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from task1_audit import (
    GroundingReport,
    GroundingVerdict,
    HandoffReason,
)
from task2_cashcard.escalation_triggers import (
    WRITE_INTENTS,
    Trigger,
    TriggerKind,
    evaluate_triggers,
)
from task2_cashcard.tests.fixtures import (
    NOW,
    make_config,
    make_context,
    make_invoice,
    make_porting_declined,
    make_subscription,
    make_usage,
)


def _grounding_grounded() -> GroundingReport:
    return GroundingReport(
        verdict=GroundingVerdict.GROUNDED,
        claims=(),
        reason="all claims supported",
    )


def _grounding_ungrounded() -> GroundingReport:
    return GroundingReport(
        verdict=GroundingVerdict.UNGROUNDED,
        claims=(),
        reason="1 unsupported claim",
        ungrounded_claims=("the agent claimed X without citing",),
    )


def _grounding_refused() -> GroundingReport:
    return GroundingReport(
        verdict=GroundingVerdict.REFUSED,
        claims=(),
        reason="agent refused",
    )


# ---- happy: no trigger fires when context is clean ---------------------------


class TestHappyPath:
    def test_grounded_clean_context_returns_none(self) -> None:
        ctx = make_context()
        cfg = make_config()
        result = evaluate_triggers(
            ctx=ctx,
            config=cfg,
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None

    def test_grounded_no_intent_still_returns_none(self) -> None:
        ctx = make_context()
        cfg = make_config()
        result = evaluate_triggers(
            ctx=ctx, config=cfg, grounding=_grounding_grounded(), now=NOW
        )
        assert result is None


# ---- each trigger fires on its matching context -----------------------------


class TestLowConfidence:
    def test_ungrounded_fires_low_confidence(self) -> None:
        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(),
            grounding=_grounding_ungrounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.LOW_CONFIDENCE
        assert result.handoff_reason == HandoffReason.LOW_CONFIDENCE

    def test_refused_fires_low_confidence(self) -> None:
        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(),
            grounding=_grounding_refused(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.LOW_CONFIDENCE


class TestWriteRequested:
    @pytest.mark.parametrize("intent", sorted(WRITE_INTENTS))
    def test_every_write_intent_fires(self, intent: str) -> None:
        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(),
            grounding=_grounding_grounded(),
            intent=intent,
        )
        # Note: out_of_scope check comes AFTER write_requested, so unknown
        # write intents still hit write_requested first.
        assert result is not None
        assert result.kind == TriggerKind.WRITE_REQUESTED
        assert result.handoff_reason == HandoffReason.WRITE_REQUIRES_HUMAN

    def test_write_does_not_fire_when_guardrails_disabled(self) -> None:
        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(read_only_writes=False),
            grounding=_grounding_grounded(),
            intent="cancel_subscription",
            now=NOW,
        )
        # No restriction, no porting decline, no stale usage, no invoice failure.
        # cancel_subscription IS NOT a known routing intent in the test config,
        # so it should fall through to OUT_OF_PRODUCT_SCOPE.
        assert result is not None
        assert result.kind == TriggerKind.OUT_OF_PRODUCT_SCOPE


class TestRestrictedSubscription:
    def test_restricted_sub_fires(self) -> None:
        ctx = make_context(
            subscription=make_subscription(
                status="restricted",
                restriction_reason="payment_overdue",
            )
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.RESTRICTED_SUBSCRIPTION
        assert result.handoff_reason == HandoffReason.POLICY_REFUSAL
        assert "payment_overdue" in result.detail

    def test_active_sub_does_not_fire(self) -> None:
        ctx = make_context(subscription=make_subscription(status="active"))
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None


class TestPortingDeclined:
    def test_declined_with_code_fires(self) -> None:
        ctx = make_context(
            porting_history=[
                make_porting_declined(code="portingPinIncorrect"),
            ]
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.PORTING_DECLINED
        assert result.handoff_reason == HandoffReason.WRITE_REQUIRES_HUMAN
        assert "portingPinIncorrect" in result.detail

    def test_no_porting_history_does_not_fire(self) -> None:
        ctx = make_context()
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None


class TestStaleUsage:
    def test_stale_usage_fires(self) -> None:
        old = NOW - timedelta(hours=2)  # ceiling is 1h
        ctx = make_context(usage=make_usage(updated_at=old))
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.STALE_USAGE
        assert result.handoff_reason == HandoffReason.TOOL_FAILURE

    def test_fresh_usage_does_not_fire(self) -> None:
        fresh = NOW - timedelta(minutes=10)
        ctx = make_context(usage=make_usage(updated_at=fresh))
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None

    def test_no_usage_record_does_not_fire(self) -> None:
        ctx = make_context(no_usage=True)
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None


class TestOutOfProductScope:
    def test_unknown_intent_fires(self) -> None:
        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="ask_about_weather",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.OUT_OF_PRODUCT_SCOPE
        assert result.handoff_reason == HandoffReason.OUT_OF_SCOPE

    def test_known_intent_does_not_fire(self) -> None:
        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None


class TestInvoicePaymentFailed:
    def test_finalized_unpaid_invoice_fires(self) -> None:
        ctx = make_context(
            invoice=make_invoice(status="finalized", amount_due_cents=2999, paid_at=None)
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.INVOICE_PAYMENT_FAILED
        assert result.handoff_reason == HandoffReason.WRITE_REQUIRES_HUMAN

    def test_paid_invoice_does_not_fire(self) -> None:
        ctx = make_context(invoice=make_invoice(status="paid", amount_due_cents=0))
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None

    def test_voided_invoice_does_not_fire(self) -> None:
        ctx = make_context(invoice=make_invoice(status="voided", amount_due_cents=0))
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is None


# ---- first-match-wins ordering ------------------------------------------------


class TestPriorityOrdering:
    def test_low_confidence_beats_restricted(self) -> None:
        """If grounding is ungrounded AND sub is restricted, low_confidence wins."""
        ctx = make_context(
            subscription=make_subscription(status="restricted", restriction_reason="r")
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_ungrounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.LOW_CONFIDENCE

    def test_write_beats_restricted(self) -> None:
        """Write-intent fires before restriction check."""
        ctx = make_context(
            subscription=make_subscription(status="restricted", restriction_reason="r")
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="cancel_subscription",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.WRITE_REQUESTED

    def test_restricted_beats_porting_declined(self) -> None:
        ctx = make_context(
            subscription=make_subscription(status="restricted", restriction_reason="r"),
            porting_history=[make_porting_declined()],
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.RESTRICTED_SUBSCRIPTION

    def test_porting_beats_stale_usage(self) -> None:
        ctx = make_context(
            porting_history=[make_porting_declined()],
            usage=make_usage(updated_at=NOW - timedelta(hours=10)),
        )
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="plan_info",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.PORTING_DECLINED

    def test_stale_usage_beats_out_of_scope(self) -> None:
        ctx = make_context(usage=make_usage(updated_at=NOW - timedelta(hours=10)))
        result = evaluate_triggers(
            ctx=ctx,
            config=make_config(),
            grounding=_grounding_grounded(),
            intent="ask_about_weather",
            now=NOW,
        )
        assert result is not None
        assert result.kind == TriggerKind.STALE_USAGE


# ---- Trigger dataclass behaviour ---------------------------------------------


class TestTriggerDataclass:
    def test_trigger_is_frozen(self) -> None:
        import dataclasses

        result = evaluate_triggers(
            ctx=make_context(),
            config=make_config(),
            grounding=_grounding_ungrounded(),
            intent="plan_info",
            now=NOW,
        )
        assert isinstance(result, Trigger)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.detail = "tampered"  # type: ignore[misc]


# ---- write_intents constant sanity -------------------------------------------


class TestWriteIntents:
    def test_known_write_intents_present(self) -> None:
        for expected in (
            "cancel_subscription",
            "switch_plan",
            "request_refund",
            "request_new_esim",
        ):
            assert expected in WRITE_INTENTS

    def test_read_intent_not_in_write_set(self) -> None:
        for read_intent in ("plan_info", "install_esim", "device_compat"):
            assert read_intent not in WRITE_INTENTS
