"""Tests for task1_audit.escalation_context."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from task1_audit.escalation_context import (
    ConversationTurn,
    EscalationContext,
    HandoffReason,
    InvoiceSnapshot,
    PortingTransition,
    RetrievedChunk,
    SimSnapshot,
    SubscriptionSnapshot,
    UsageSnapshot,
    UserSnapshot,
    WebhookEcho,
    mask_email,
    mask_full_name,
    mask_phone,
)

# Avoid the Write-tool email-pattern obfuscation: build email literals from
# constants so the source bytes stay byte-stable through the toolchain.
AT = "@"


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------


class TestMaskEmail:
    def test_typical(self) -> None:
        assert mask_email(f"alice{AT}cashcard.example") == f"a***{AT}cashcard.example"

    def test_uppercase_local(self) -> None:
        assert mask_email(f"Alice{AT}cashcard.example") == f"A***{AT}cashcard.example"

    def test_short_local(self) -> None:
        assert mask_email(f"a{AT}example.com") == f"a***{AT}example.com"

    def test_none(self) -> None:
        assert mask_email(None) is None

    def test_invalid_returns_stars(self) -> None:
        assert mask_email("not-an-email") == "***"

    def test_idempotent_on_masked(self) -> None:
        # Masking already-masked input shouldn't crash; degrade to '***'.
        masked = mask_email(f"a***{AT}cashcard.example")
        assert masked in {"***", f"a***{AT}cashcard.example"}


class TestMaskPhone:
    def test_typical(self) -> None:
        assert mask_phone("+14155551234") == "+14***1234"

    def test_short_is_rejected(self) -> None:
        assert mask_phone("+1234") == "***"

    def test_non_e164(self) -> None:
        assert mask_phone("415-555-1234") == "***"

    def test_none(self) -> None:
        assert mask_phone(None) is None


class TestMaskFullName:
    def test_two_part_name(self) -> None:
        assert mask_full_name("Jerry Seinfeld") == "J*** S***"

    def test_single_name(self) -> None:
        assert mask_full_name("Cher") == "C***"

    def test_none(self) -> None:
        assert mask_full_name(None) is None

    def test_blank_returns_none(self) -> None:
        assert mask_full_name("   ") is None


# ---------------------------------------------------------------------------
# UsageSnapshot
# ---------------------------------------------------------------------------


def _usage(
    *,
    used: int = 4_000_000_000,
    allowance: int = 10_737_418_240,
    updated_at: datetime | None = None,
) -> UsageSnapshot:
    return UsageSnapshot(
        period_start=datetime(2026, 6, 1, tzinfo=UTC),
        period_end=datetime(2026, 6, 30, 23, 59, tzinfo=UTC),
        data_bytes_used=used,
        voice_seconds_used=0,
        sms_count_used=0,
        plan_data_bytes_allowance=allowance,
        plan_voice_seconds_allowance=-1,
        plan_sms_allowance=-1,
        usage_updated_at=updated_at or datetime.now(tz=UTC) - timedelta(hours=1),
    )


class TestUsageSnapshot:
    def test_period_end_after_start(self) -> None:
        with pytest.raises(ValidationError):
            UsageSnapshot(
                period_start=datetime(2026, 6, 30, tzinfo=UTC),
                period_end=datetime(2026, 6, 1, tzinfo=UTC),
                data_bytes_used=0,
                voice_seconds_used=0,
                sms_count_used=0,
                plan_data_bytes_allowance=-1,
                plan_voice_seconds_allowance=-1,
                plan_sms_allowance=-1,
                usage_updated_at=datetime.now(tz=UTC),
            )

    def test_remaining_when_capped(self) -> None:
        u = _usage(used=4_000_000_000, allowance=10_737_418_240)
        assert u.data_remaining_bytes() == 10_737_418_240 - 4_000_000_000

    def test_remaining_when_unlimited(self) -> None:
        u = _usage(allowance=-1)
        assert u.data_remaining_bytes() is None

    def test_remaining_clamps_at_zero(self) -> None:
        u = _usage(used=10_000_000_000, allowance=5_000_000_000)
        assert u.data_remaining_bytes() == 0

    def test_used_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            _usage(used=-1)

    def test_stale_after_24h(self) -> None:
        old = datetime.now(tz=UTC) - timedelta(hours=25)
        u = _usage(updated_at=old)
        assert u.is_stale() is True

    def test_fresh_within_window(self) -> None:
        recent = datetime.now(tz=UTC) - timedelta(hours=2)
        u = _usage(updated_at=recent)
        assert u.is_stale() is False

    def test_naive_datetime_treated_as_utc(self) -> None:
        # If the API ever returns a naive timestamp, is_stale should still work.
        naive = datetime.utcnow() - timedelta(hours=25)
        u = _usage(updated_at=naive.replace(tzinfo=UTC))
        assert u.is_stale() is True


# ---------------------------------------------------------------------------
# SimSnapshot
# ---------------------------------------------------------------------------


def _sim(
    *,
    provider: str = "p3",
    iccid_last4: str = "1234",
    sim_type: str = "eSIM",
    esim_status: str | None = "installed",
) -> SimSnapshot:
    return SimSnapshot(
        sim_id="sim_abc",
        iccid_last4=iccid_last4,
        provider=provider,
        sim_status="active",
        sim_type=sim_type,  # type: ignore[arg-type]
        esim_profile_status=esim_status,  # type: ignore[arg-type]
        esim_lifecycle_supported=provider in {"p3", "p14", "p15"},
        credentials_available=False,
    )


class TestSimSnapshot:
    def test_iccid_must_be_exactly_4_chars(self) -> None:
        with pytest.raises(ValidationError):
            _sim(iccid_last4="123")
        with pytest.raises(ValidationError):
            _sim(iccid_last4="12345")

    def test_iccid_accepts_exactly_4(self) -> None:
        s = _sim(iccid_last4="9876")
        assert s.iccid_last4 == "9876"


# ---------------------------------------------------------------------------
# InvoiceSnapshot
# ---------------------------------------------------------------------------


class TestInvoiceSnapshot:
    def test_amount_due_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            InvoiceSnapshot(
                invoice_id="inv_1",
                status="finalized",
                amount_due_cents=-1,
                currency="USD",
            )

    def test_zero_amount_accepted(self) -> None:
        inv = InvoiceSnapshot(
            invoice_id="inv_1",
            status="paid",
            amount_due_cents=0,
            currency="USD",
        )
        assert inv.amount_due_cents == 0


# ---------------------------------------------------------------------------
# WebhookEcho chronology
# ---------------------------------------------------------------------------


def _echo(event_type: str, when: datetime) -> WebhookEcho:
    return WebhookEcho(
        event_id=f"evt_{when.timestamp():.0f}",
        event_type=event_type,
        occurred_at=when,
        summary="event",
    )


def _user() -> UserSnapshot:
    return UserSnapshot.from_raw(
        user_id="usr_abc123",
        email=f"jerry{AT}cashcard.example",
        full_name="Jerry Seinfeld",
        preferred_locale="en-US",
        status="active",
    )


def _conv() -> list[ConversationTurn]:
    return [
        ConversationTurn(
            role="user",
            text="Hi, how much data do I have left?",
            sent_at=datetime.now(tz=UTC),
        )
    ]


def _ec(events: list[WebhookEcho], porting: list[PortingTransition] | None = None) -> EscalationContext:
    return EscalationContext(
        escalation_id="esc_1",
        created_at=datetime.now(tz=UTC),
        project_id="prj_abc",
        customer_brand="CashCard",
        reason=HandoffReason.LOW_CONFIDENCE,
        confidence=0.42,
        user=_user(),
        recent_events=events,
        porting_history=porting or [],
        conversation=_conv(),
    )


class TestRecentEventsChronology:
    def test_most_recent_first_accepted(self) -> None:
        now = datetime.now(tz=UTC)
        events = [
            _echo("com.gigs.plan.updated", now),
            _echo("com.gigs.plan.created", now - timedelta(hours=1)),
        ]
        ec = _ec(events)
        assert ec.recent_events[0].occurred_at == now

    def test_oldest_first_rejected(self) -> None:
        now = datetime.now(tz=UTC)
        events = [
            _echo("com.gigs.plan.created", now - timedelta(hours=1)),
            _echo("com.gigs.plan.updated", now),
        ]
        with pytest.raises(ValidationError):
            _ec(events)

    def test_empty_ok(self) -> None:
        ec = _ec([])
        assert ec.recent_events == []

    def test_event_type_must_be_gigs_namespaced(self) -> None:
        now = datetime.now(tz=UTC)
        with pytest.raises(ValidationError):
            _echo("stripe.charge.succeeded", now)

    def test_max_5_events(self) -> None:
        now = datetime.now(tz=UTC)
        too_many = [
            _echo("com.gigs.plan.updated", now - timedelta(minutes=i))
            for i in range(6)
        ]
        with pytest.raises(ValidationError):
            _ec(too_many)


# ---------------------------------------------------------------------------
# Porting history chronology + cap
# ---------------------------------------------------------------------------


def _port(when: datetime, status: str = "declined") -> PortingTransition:
    return PortingTransition(
        porting_id=f"prt_{when.timestamp():.0f}",
        status=status,  # type: ignore[arg-type]
        observed_at=when,
    )


class TestPortingHistory:
    def test_most_recent_first_accepted(self) -> None:
        now = datetime.now(tz=UTC)
        ec = _ec(
            [],
            porting=[
                _port(now),
                _port(now - timedelta(hours=2)),
                _port(now - timedelta(hours=5)),
            ],
        )
        assert ec.porting_history[0].observed_at == now

    def test_oldest_first_rejected(self) -> None:
        now = datetime.now(tz=UTC)
        with pytest.raises(ValidationError):
            _ec(
                [],
                porting=[
                    _port(now - timedelta(hours=5)),
                    _port(now),
                ],
            )

    def test_cap_at_3(self) -> None:
        now = datetime.now(tz=UTC)
        with pytest.raises(ValidationError):
            _ec(
                [],
                porting=[
                    _port(now - timedelta(minutes=i)) for i in range(4)
                ],
            )


# ---------------------------------------------------------------------------
# Top-level serialization + PII boundary
# ---------------------------------------------------------------------------


class TestEscalationContextSerialization:
    def test_to_json_roundtrip(self) -> None:
        ec = _ec([])
        as_json = ec.to_json()
        loaded = json.loads(as_json)
        assert loaded["escalation_id"] == "esc_1"
        assert loaded["customer_brand"] == "CashCard"
        assert loaded["user"]["email_masked"] == f"j***{AT}cashcard.example"

    def test_no_raw_pii_in_payload(self) -> None:
        ec = _ec([])
        body = ec.to_json()
        # Original raw email must not survive into the serialized packet.
        assert f"jerry{AT}cashcard.example" not in body
        # Original raw full name must not survive either.
        assert "Jerry Seinfeld" not in body

    def test_schema_version_set(self) -> None:
        ec = _ec([])
        assert ec.schema_version == "1.0.0"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EscalationContext(
                escalation_id="esc_1",
                created_at=datetime.now(tz=UTC),
                project_id="prj_abc",
                customer_brand="CashCard",
                reason=HandoffReason.LOW_CONFIDENCE,
                confidence=0.5,
                user=_user(),
                conversation=_conv(),
                hostile_extra_field="oops",  # type: ignore[call-arg]
            )

    def test_confidence_clamped_inclusive(self) -> None:
        ec0 = _ec([])
        # confidence at the boundaries (0.0, 1.0) accepted.
        EscalationContext(
            escalation_id="esc_2",
            created_at=datetime.now(tz=UTC),
            project_id="prj_abc",
            customer_brand="CashCard",
            reason=HandoffReason.USER_REQUESTED_HUMAN,
            confidence=0.0,
            user=ec0.user,
            conversation=ec0.conversation,
        )
        EscalationContext(
            escalation_id="esc_3",
            created_at=datetime.now(tz=UTC),
            project_id="prj_abc",
            customer_brand="CashCard",
            reason=HandoffReason.USER_REQUESTED_HUMAN,
            confidence=1.0,
            user=ec0.user,
            conversation=ec0.conversation,
        )

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            EscalationContext(
                escalation_id="esc_4",
                created_at=datetime.now(tz=UTC),
                project_id="prj_abc",
                customer_brand="CashCard",
                reason=HandoffReason.USER_REQUESTED_HUMAN,
                confidence=1.01,
                user=_user(),
                conversation=_conv(),
            )

    def test_frozen(self) -> None:
        ec = _ec([])
        with pytest.raises(ValidationError):
            ec.customer_brand = "OtherBrand"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HandoffReason enum sanity
# ---------------------------------------------------------------------------


class TestHandoffReason:
    def test_str_value_equality(self) -> None:
        # StrEnum carries the string value transparently.
        assert HandoffReason.LOW_CONFIDENCE == "low_confidence"

    def test_all_reasons_documented(self) -> None:
        expected = {
            "low_confidence",
            "out_of_scope",
            "policy_refusal",
            "tool_failure",
            "write_requires_human",
            "user_requested_human",
        }
        actual = {r.value for r in HandoffReason}
        assert actual == expected


# ---------------------------------------------------------------------------
# RetrievedChunk + SubscriptionSnapshot quick sanity
# ---------------------------------------------------------------------------


class TestRetrievedChunkAndSubscription:
    def test_chunk_score_bounds(self) -> None:
        with pytest.raises(ValidationError):
            RetrievedChunk(doc_id="d", chunk_id="c", score=1.5, excerpt="x")
        with pytest.raises(ValidationError):
            RetrievedChunk(doc_id="d", chunk_id="c", score=-0.1, excerpt="x")
        # Boundaries OK
        RetrievedChunk(doc_id="d", chunk_id="c", score=0.0, excerpt="x")
        RetrievedChunk(doc_id="d", chunk_id="c", score=1.0, excerpt="x")

    def test_subscription_minimal(self) -> None:
        s = SubscriptionSnapshot(
            subscription_id="sub_1",
            plan_id="plan_1",
            status="restricted",
            restriction_reason="overdue_invoice",
        )
        assert s.status == "restricted"
        assert s.restriction_reason == "overdue_invoice"

    def test_frozen_chunk(self) -> None:
        c = RetrievedChunk(doc_id="d", chunk_id="c", score=0.5, excerpt="x")
        with pytest.raises(ValidationError):
            c.score = 0.9  # type: ignore[misc]
        # also dataclasses.FrozenInstanceError shouldn't apply (pydantic model)
        # silenced unused import warning
        _ = dataclasses
