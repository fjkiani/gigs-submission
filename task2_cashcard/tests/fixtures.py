"""Shared fixtures for Task 2 tests — EscalationContext / config builders.

Centralised here so individual test modules stay short. The builders
default to a "happy path" CashCard customer; tests override per-test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from task1_audit import (
    EscalationContext,
    HandoffReason,
    UsageSnapshot,
    UserSnapshot,
)
from task1_audit.escalation_context import (
    ConversationTurn,
    InvoiceSnapshot,
    PortingTransition,
    SimSnapshot,
    SubscriptionSnapshot,
)
from task2_cashcard.cashcard_config import (
    ContextVarSpec,
    Guardrails,
    InstanceConfig,
    IntentHandler,
    RoutingRule,
    TriggerKindSpec,
    TriggerSpec,
    TwoHopEscalation,
)

# Local email-literal workaround.
AT = "@"

# A fixed reference time tests can pin staleness against.
NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)


def make_user(
    *,
    user_id: str = "usr_cashcard_demo",
    email_masked: str | None = f"j***{AT}cashcard.example",
    status: Literal["active", "blocked", "deleted"] = "active",
) -> UserSnapshot:
    return UserSnapshot(
        user_id=user_id,
        email_masked=email_masked,
        full_name_masked="J*** D***",
        preferred_locale="en-US",
        status=status,
    )


def make_subscription(
    *,
    status: Literal["pending", "initiated", "active", "restricted", "ended"] = "active",
    restriction_reason: str | None = None,
    phone_masked: str | None = "+1 (***) ***-1234",
) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        subscription_id="sub_demo_001",
        plan_id="pln_unlimited_us",
        status=status,
        activated_at=datetime(2026, 6, 1, tzinfo=UTC),
        restriction_reason=restriction_reason,
        restricted_at=datetime(2026, 6, 20, tzinfo=UTC) if status == "restricted" else None,
        phone_number_masked=phone_masked,
    )


def make_sim(
    *,
    provider: str = "p3",
    sim_id: str = "sim_demo_001",
) -> SimSnapshot:
    lifecycle = provider in {"p3", "p14", "p15"}
    return SimSnapshot(
        sim_id=sim_id,
        iccid_last4="1234",
        provider=provider,
        sim_status="active",
        sim_type="eSIM",
        esim_profile_status="installed" if lifecycle else "unknown",
        esim_lifecycle_supported=lifecycle,
    )


def make_usage(
    *,
    updated_at: datetime | None = None,
) -> UsageSnapshot:
    """Build a UsageSnapshot.

    `updated_at` defaults to `NOW` (the pinned reference time). Tests that
    don't pass `now=NOW` to `evaluate_triggers` should override to a time
    relative to the actual wall clock instead.
    """
    return UsageSnapshot(
        period_start=datetime(2026, 6, 1, tzinfo=UTC),
        period_end=datetime(2026, 7, 30, tzinfo=UTC),
        data_bytes_used=1_000_000_000,
        voice_seconds_used=0,
        sms_count_used=0,
        plan_data_bytes_allowance=-1,
        plan_voice_seconds_allowance=-1,
        plan_sms_allowance=-1,
        usage_updated_at=updated_at if updated_at is not None else NOW,
    )


def make_invoice(
    *,
    status: Literal["draft", "finalized", "paid", "voided"] = "paid",
    amount_due_cents: int = 0,
    paid_at: datetime | None = NOW,
) -> InvoiceSnapshot:
    return InvoiceSnapshot(
        invoice_id="inv_demo_001",
        status=status,
        amount_due_cents=amount_due_cents,
        currency="USD",
        finalized_at=NOW,
        paid_at=paid_at,
    )


def make_porting_declined(
    *,
    code: str = "portingPhoneNumberPortProtected",
) -> PortingTransition:
    return PortingTransition(
        porting_id="port_demo_001",
        status="declined",
        donor_provider_name="AT&T",
        declined_code=code,
        declined_message="Port protection enabled at donor",
        observed_at=NOW,
    )


def make_conversation() -> list[ConversationTurn]:
    """A minimal one-turn conversation that satisfies the min_length=1 rule."""
    return [
        ConversationTurn(
            role="user",
            text="Hi, my eSIM isn't working.",
            sent_at=NOW,
        ),
    ]


def make_context(
    *,
    reason: HandoffReason = HandoffReason.LOW_CONFIDENCE,
    subscription: SubscriptionSnapshot | None = None,
    sim: SimSnapshot | None = None,
    usage: UsageSnapshot | None = None,
    invoice: InvoiceSnapshot | None = None,
    porting_history: list[PortingTransition] | None = None,
    user: UserSnapshot | None = None,
    no_subscription: bool = False,
    no_sim: bool = False,
    no_usage: bool = False,
    no_invoice: bool = False,
) -> EscalationContext:
    """Build an EscalationContext with sensible defaults; nulls via flags.

    Pass ``no_*=True`` to *explicitly* set a snapshot field to None (the
    bare keyword-arg defaults to "use a sensible non-None default").
    """
    return EscalationContext(
        escalation_id="esc_demo_001",
        created_at=NOW,
        project_id="proj_cashcard",
        customer_brand="CashCard",
        reason=reason,
        confidence=0.5,
        user=user or make_user(),
        subscription=None if no_subscription else (subscription or make_subscription()),
        sim=None if no_sim else (sim or make_sim()),
        usage=None if no_usage else (usage or make_usage()),
        invoice=None if no_invoice else (invoice if invoice is not None else make_invoice()),
        porting_history=porting_history or [],
        recent_events=[],
        retrieved_chunks=[],
        conversation=make_conversation(),
    )


def make_config(
    *,
    read_only_writes: bool = True,
    staleness_ceiling_seconds: int = 3600,
) -> InstanceConfig:
    return InstanceConfig(
        tenant_id="proj_cashcard",
        country="US",
        sim_types=("eSIM",),
        providers=("p3",),
        contact_mix_prior={
            "esim_activation": 0.35,
            "plan_questions": 0.25,
            "devices": 0.15,
            "roaming": 0.10,
            "port_in": 0.10,
            "other": 0.05,
        },
        routing_rules=(
            RoutingRule(intent="install_esim", handler=IntentHandler.AGENT, bucket="esim_activation"),
            RoutingRule(intent="plan_info", handler=IntentHandler.AGENT, bucket="plan_questions"),
            RoutingRule(intent="device_compat", handler=IntentHandler.AGENT, bucket="devices"),
            RoutingRule(intent="roaming_info", handler=IntentHandler.AGENT, bucket="roaming"),
            RoutingRule(intent="submit_porting", handler=IntentHandler.TIER1_HUMAN, bucket="port_in"),
            RoutingRule(intent="other", handler=IntentHandler.TIER1_HUMAN, bucket="other"),
        ),
        context_variables=(
            ContextVarSpec(name="subscription_id", required=True, source="session.subscription_id"),
            ContextVarSpec(name="sim_id", required=True, source="session.sim_id"),
            ContextVarSpec(name="user_id", required=True, source="session.user_id"),
        ),
        guardrails=Guardrails(
            read_only_writes=read_only_writes,
            staleness_ceiling_seconds=staleness_ceiling_seconds,
        ),
        escalation_triggers=(
            TriggerSpec(kind=TriggerKindSpec.LOW_CONFIDENCE, priority=1),
            TriggerSpec(kind=TriggerKindSpec.WRITE_REQUESTED, priority=2),
            TriggerSpec(kind=TriggerKindSpec.RESTRICTED_SUBSCRIPTION, priority=3),
            TriggerSpec(kind=TriggerKindSpec.PORTING_DECLINED, priority=4),
            TriggerSpec(kind=TriggerKindSpec.STALE_USAGE, priority=5),
            TriggerSpec(kind=TriggerKindSpec.OUT_OF_PRODUCT_SCOPE, priority=6),
            TriggerSpec(kind=TriggerKindSpec.INVOICE_PAYMENT_FAILED, priority=7),
        ),
        two_hop=TwoHopEscalation(
            tier1_target=f"tier1{AT}cashcard.example",
            tier2_target=f"tier2{AT}gigs.example",
        ),
    )
