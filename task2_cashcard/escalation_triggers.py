"""Escalation trigger rules engine.

Takes (EscalationContext, InstanceConfig, GroundingReport) and returns the
first matching `Trigger` or None. Pure function — no side effects, easy to
test, easy to replay against historical conversations.

Trigger types (priority order — first match wins):

1. ``LOW_CONFIDENCE``         — grounding verdict is UNGROUNDED or REFUSED
2. ``WRITE_REQUESTED``        — intent maps to a write endpoint while
                                guardrails.read_only_writes is True
3. ``RESTRICTED_SUBSCRIPTION``— subscription.status == "restricted"
4. ``PORTING_DECLINED``       — most-recent porting transition is "declined"
                                with a declinedCode
5. ``STALE_USAGE``            — usage older than guardrails.staleness_ceiling
6. ``OUT_OF_PRODUCT_SCOPE``   — intent has no routing rule
7. ``INVOICE_PAYMENT_FAILED`` — latest invoice status ∈ {open, uncollectible}

Each trigger carries a `HandoffReason` from Task 1's enum so the downstream
ticket gets a clean reason code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from task1_audit import (
    EscalationContext,
    GroundingReport,
    GroundingVerdict,
    HandoffReason,
)
from task2_cashcard.cashcard_config import InstanceConfig

# Intents that hit Gigs write endpoints. The agent's intent classifier is
# upstream of this engine; we only need to recognise the *labels* it emits.
WRITE_INTENTS: frozenset[str] = frozenset(
    {
        "cancel_subscription",
        "switch_plan",
        "request_refund",
        "update_payment_method",
        "delete_account",
        "request_new_esim",
        "submit_porting",
        "cancel_porting",
    }
)


class TriggerKind(StrEnum):
    """One per escalation trigger.

    Mirrored 1:1 by ``cashcard_config.TriggerKindSpec`` to avoid a circular
    import on the config side.
    """

    LOW_CONFIDENCE = "low_confidence"
    WRITE_REQUESTED = "write_requested"
    RESTRICTED_SUBSCRIPTION = "restricted_subscription"
    PORTING_DECLINED = "porting_declined"
    STALE_USAGE = "stale_usage"
    OUT_OF_PRODUCT_SCOPE = "out_of_product_scope"
    INVOICE_PAYMENT_FAILED = "invoice_payment_failed"


@dataclass(frozen=True)
class Trigger:
    """A fired trigger, ready to be attached to the escalation packet."""

    kind: TriggerKind
    handoff_reason: HandoffReason
    detail: str


# Mapping from trigger kind to the Task 1 HandoffReason enum.
#
# Task 1's HandoffReason set is deliberately small (six routing categories)
# so this engine collapses its richer 7-axis trigger space into them. The
# specific kind is preserved in the Trigger itself for analytics; the
# HandoffReason is what the ticketing system routes on.
_TRIGGER_TO_REASON: dict[TriggerKind, HandoffReason] = {
    TriggerKind.LOW_CONFIDENCE: HandoffReason.LOW_CONFIDENCE,
    TriggerKind.WRITE_REQUESTED: HandoffReason.WRITE_REQUIRES_HUMAN,
    # A restricted subscription means the agent cannot complete the user's
    # request without a policy action; treat as policy refusal.
    TriggerKind.RESTRICTED_SUBSCRIPTION: HandoffReason.POLICY_REFUSAL,
    # A declined port requires a state-changing fix (retry with new info,
    # contact donor, choose a new number); needs a human.
    TriggerKind.PORTING_DECLINED: HandoffReason.WRITE_REQUIRES_HUMAN,
    # Stale usage means the underlying API state can't ground the answer.
    TriggerKind.STALE_USAGE: HandoffReason.TOOL_FAILURE,
    TriggerKind.OUT_OF_PRODUCT_SCOPE: HandoffReason.OUT_OF_SCOPE,
    # Failed invoice -> a billing action is needed; the agent doesn't act
    # on payments in the day-1 read-only posture.
    TriggerKind.INVOICE_PAYMENT_FAILED: HandoffReason.WRITE_REQUIRES_HUMAN,
}


def _check_low_confidence(grounding: GroundingReport) -> Trigger | None:
    if grounding.verdict in (GroundingVerdict.UNGROUNDED, GroundingVerdict.REFUSED):
        return Trigger(
            kind=TriggerKind.LOW_CONFIDENCE,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.LOW_CONFIDENCE],
            detail=f"grounding verdict = {grounding.verdict.value}",
        )
    return None


def _check_write_requested(
    intent: str | None, config: InstanceConfig
) -> Trigger | None:
    if (
        intent
        and intent in WRITE_INTENTS
        and config.guardrails.read_only_writes
    ):
        return Trigger(
            kind=TriggerKind.WRITE_REQUESTED,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.WRITE_REQUESTED],
            detail=f"intent {intent!r} is a write and read_only_writes=True",
        )
    return None


def _check_restricted_subscription(ctx: EscalationContext) -> Trigger | None:
    sub = ctx.subscription
    if sub is not None and sub.status == "restricted":
        return Trigger(
            kind=TriggerKind.RESTRICTED_SUBSCRIPTION,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.RESTRICTED_SUBSCRIPTION],
            detail=(
                f"subscription {sub.subscription_id!r} is restricted: "
                f"{sub.restriction_reason or 'no reason given'}"
            ),
        )
    return None


def _check_porting_declined(ctx: EscalationContext) -> Trigger | None:
    if not ctx.porting_history:
        return None
    latest = ctx.porting_history[0]
    if latest.status == "declined" and latest.declined_code:
        return Trigger(
            kind=TriggerKind.PORTING_DECLINED,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.PORTING_DECLINED],
            detail=f"declinedCode={latest.declined_code!r}",
        )
    return None


def _check_stale_usage(
    ctx: EscalationContext, config: InstanceConfig, *, now: datetime | None = None
) -> Trigger | None:
    """Fire if usage age exceeds the configured staleness ceiling.

    `now` is injectable so tests can pin staleness deterministically without
    monkeypatching `datetime.now()`.
    """
    usage = ctx.usage
    if usage is None:
        return None
    current = now if now is not None else datetime.now(UTC)
    age_seconds = (current - usage.usage_updated_at).total_seconds()
    if age_seconds > config.guardrails.staleness_ceiling_seconds:
        hours_stale = age_seconds / 3600
        ceiling_hours = config.guardrails.staleness_ceiling_seconds / 3600
        return Trigger(
            kind=TriggerKind.STALE_USAGE,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.STALE_USAGE],
            detail=(
                f"usage is {hours_stale:.1f}h old; ceiling is {ceiling_hours:.1f}h"
            ),
        )
    return None


def _check_out_of_scope(
    intent: str | None, config: InstanceConfig
) -> Trigger | None:
    if intent is None:
        return None
    known = {r.intent for r in config.routing_rules}
    if intent not in known:
        return Trigger(
            kind=TriggerKind.OUT_OF_PRODUCT_SCOPE,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.OUT_OF_PRODUCT_SCOPE],
            detail=f"intent {intent!r} has no routing rule",
        )
    return None


def _check_invoice_payment_failed(ctx: EscalationContext) -> Trigger | None:
    """Fire when an invoice is finalized with a non-zero balance and unpaid.

    Per Gigs' invoice lifecycle (draft → finalized → paid | voided), a
    'finalized' invoice with amount due > 0 and no `paid_at` is the closest
    analog to "payment failed". Free / fully-discounted invoices auto-paid
    will have `status == "paid"` and won't trigger.
    """
    invoice = ctx.invoice
    if invoice is None:
        return None
    is_unpaid_finalized = (
        invoice.status == "finalized"
        and invoice.amount_due_cents > 0
        and invoice.paid_at is None
    )
    if is_unpaid_finalized:
        return Trigger(
            kind=TriggerKind.INVOICE_PAYMENT_FAILED,
            handoff_reason=_TRIGGER_TO_REASON[TriggerKind.INVOICE_PAYMENT_FAILED],
            detail=(
                f"invoice {invoice.invoice_id!r} finalized + unpaid "
                f"({invoice.amount_due_cents} {invoice.currency})"
            ),
        )
    return None


def evaluate_triggers(
    *,
    ctx: EscalationContext,
    config: InstanceConfig,
    grounding: GroundingReport,
    intent: str | None = None,
    now: datetime | None = None,
) -> Trigger | None:
    """Return the first matching trigger, or None if the agent should answer.

    Priority order matches the order checks are listed at the top of this
    module — first non-None wins. Pure function; safe to replay.

    `now` is injectable so tests pin staleness deterministically.
    """
    # The order here is the canonical priority order. Tests pin it.
    for trigger in (
        _check_low_confidence(grounding),
        _check_write_requested(intent, config),
        _check_restricted_subscription(ctx),
        _check_porting_declined(ctx),
        _check_stale_usage(ctx, config, now=now),
        _check_out_of_scope(intent, config),
        _check_invoice_payment_failed(ctx),
    ):
        if trigger is not None:
            return trigger
    return None


__all__ = [
    "WRITE_INTENTS",
    "Trigger",
    "TriggerKind",
    "evaluate_triggers",
]
