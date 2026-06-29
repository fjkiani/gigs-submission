"""EscalationContext — the structured handoff packet between Operator and a human.

When the agent decides it cannot answer (or shouldn't), it produces an instance of
EscalationContext and hands that to the ticketing system. The packet is the
single source of truth a Technical Support Engineer reads to skip the
"tell me what happened" round-trip — every field maps to a Gigs API field they
would have looked up themselves.

Design constraints (all grounded in research/00_gigs_facts.md):

  1. Tenant model = Gigs project. `project` is a top-level field, not buried.
  2. PII redaction happens at the boundary. We never put raw email, phone, or
     full name into an escalation packet — only masked forms. The original
     user/subscription IDs are kept so a human can re-fetch from Gigs if needed.
  3. Carrier-lagged usage is always carried with its freshness, never as a
     bare number. UsageSnapshot enforces this.
  4. Subscription restriction state and the most recent porting transition
     are first-class fields — both are the highest-signal "why is this
     ticket here" facts.
  5. The packet is a *self-contained* JSON-serializable artifact. A human
     opens it, sees everything, and can reproduce the agent's view.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enum-ish literals matching Gigs API exactly
# ---------------------------------------------------------------------------

SubscriptionStatus = Literal[
    "pending", "initiated", "active", "restricted", "ended"
]
"""Subscription.status per https://developers.gigs.com/api/latest/core/subscriptions."""

SimStatus = Literal["inactive", "active", "retired"]
"""SIM.status per https://developers.gigs.com/api/latest/core/sims."""

SimType = Literal["eSIM", "pSIM"]

EsimProfileStatus = Literal[
    "deleted", "disabled", "enabled", "installed", "unknown"
]
"""eSimProfile.status. `unknown` when provider isn't p3/p14/p15 OR no events yet."""

PortingStatus = Literal[
    "draft",
    "initiated",
    "pending",
    "informationRequired",
    "requested",
    "declined",
    "completed",
    "canceled",
    "expired",
    "failed",
]
"""Porting.status, 10 values, per /api/latest/core/portings."""

InvoiceStatus = Literal["draft", "finalized", "paid", "voided"]
"""Invoice.status per /docs/billing/billing-users."""


class HandoffReason(StrEnum):
    """Why the agent gave up. These are the only legal reasons.

    Keep this list small on purpose — every value here is a *category*
    a Technical Support Engineer can route on. New reasons should require
    a code review.
    """

    LOW_CONFIDENCE = "low_confidence"
    """Retrieval grounding was below threshold; agent refused to guess."""

    OUT_OF_SCOPE = "out_of_scope"
    """Question wasn't about Gigs/connectivity; agent declined politely."""

    POLICY_REFUSAL = "policy_refusal"
    """Action would require PII the agent isn't allowed to handle."""

    TOOL_FAILURE = "tool_failure"
    """A Gigs API call failed (4xx/5xx) and there's no graceful recovery."""

    WRITE_REQUIRES_HUMAN = "write_requires_human"
    """The fix needs a state-changing action gated to humans (e.g. cancel)."""

    USER_REQUESTED_HUMAN = "user_requested_human"
    """End-user explicitly asked for a person; honor it immediately."""


# ---------------------------------------------------------------------------
# PII redaction helpers — applied at construction time, never undone
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"\+\d{6,15}")  # E.164-ish


def mask_email(email: str | None) -> str | None:
    """Mask an email to first-char + ***@domain. Idempotent. None passes through."""
    if email is None:
        return None
    m = _EMAIL_RE.fullmatch(email.strip())
    if not m:
        # Unrecognized format; mask aggressively rather than leak.
        return "***"
    local, domain = m.group(1), m.group(2)
    return f"{local[0]}***@{domain}"


def mask_phone(phone: str | None) -> str | None:
    """Mask an E.164 phone to country code + ***last4. None passes through."""
    if phone is None:
        return None
    if not _PHONE_RE.fullmatch(phone):
        return "***"
    return f"{phone[:3]}***{phone[-4:]}"


def mask_full_name(name: str | None) -> str | None:
    """Replace inner characters of each token with stars, keep first letter."""
    if name is None or not name.strip():
        return None
    parts = name.split()
    return " ".join((p[0] + "***") if p else p for p in parts)


# ---------------------------------------------------------------------------
# Nested submodels
# ---------------------------------------------------------------------------


class UserSnapshot(BaseModel):
    """Subset of the Gigs User object — PII masked at the boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(..., description="Gigs user id, e.g. usr_xxx.")
    email_masked: str | None = Field(default=None)
    full_name_masked: str | None = Field(default=None)
    preferred_locale: str | None = Field(default=None, examples=["en-US", "en-GB"])
    status: Literal["active", "blocked", "deleted"]

    @classmethod
    def from_raw(
        cls,
        *,
        user_id: str,
        email: str | None,
        full_name: str | None,
        preferred_locale: str | None,
        status: Literal["active", "blocked", "deleted"],
    ) -> UserSnapshot:
        return cls(
            user_id=user_id,
            email_masked=mask_email(email),
            full_name_masked=mask_full_name(full_name),
            preferred_locale=preferred_locale,
            status=status,
        )


class SimSnapshot(BaseModel):
    """Subset of the SIM object + eSimProfile + credentials availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sim_id: str
    iccid_last4: str = Field(
        ..., min_length=4, max_length=4, description="Last 4 of ICCID; never the full ICCID."
    )
    provider: str = Field(..., examples=["p3", "p14", "p15"])
    sim_status: SimStatus
    sim_type: SimType
    esim_profile_status: EsimProfileStatus | None = Field(
        default=None,
        description=(
            "Profile status; None when sim_type=='pSIM'. "
            "'unknown' is a real status — surface it to the human as 'we don't know'."
        ),
    )
    esim_lifecycle_supported: bool = Field(
        ...,
        description=(
            "True iff provider is in {p3,p14,p15}. If False, esim_profile_status "
            "is meaningless and the agent must not pretend otherwise."
        ),
    )
    credentials_available: bool = Field(
        default=False,
        description=(
            "Whether the agent could fetch /sims/{id}/credentials. The actual "
            "activationCode/qrCodeUrl are NEVER stored in this packet."
        ),
    )


class UsageSnapshot(BaseModel):
    """Subscription usage. Always carries staleness — no bare numbers.

    The Gigs Usage API explicitly states there is a delay in usage data that
    varies between carriers (see /api/latest/core/usage). Any answer the agent
    gives about "remaining balance" is computed and stale; this struct enforces
    that the staleness is always carried with the value.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    period_start: datetime
    period_end: datetime
    data_bytes_used: int = Field(..., ge=0)
    voice_seconds_used: int = Field(..., ge=0)
    sms_count_used: int = Field(..., ge=0)
    plan_data_bytes_allowance: int = Field(
        ..., description="-1 means unlimited per Gigs Plan deprecated-but-live convention."
    )
    plan_voice_seconds_allowance: int = Field(..., description="-1 means unlimited.")
    plan_sms_allowance: int = Field(..., description="-1 means unlimited.")
    usage_updated_at: datetime = Field(
        ...,
        description=(
            "The usageRecord.updatedAt — the time the carrier last reported. "
            "Critical for honesty: 'as of this time, you've used X'."
        ),
    )

    @field_validator("period_end")
    @classmethod
    def _period_end_after_start(cls, v: datetime, info: object) -> datetime:
        # pydantic v2 access pattern for prior fields
        values = getattr(info, "data", {})
        start = values.get("period_start")
        if start is not None and v <= start:
            raise ValueError("period_end must be strictly after period_start")
        return v

    def data_remaining_bytes(self) -> int | None:
        """Remaining = allowance - used. None when allowance is unlimited (-1)."""
        if self.plan_data_bytes_allowance == -1:
            return None
        return max(0, self.plan_data_bytes_allowance - self.data_bytes_used)

    def is_stale(self, *, now: datetime | None = None, max_age_hours: float = 24.0) -> bool:
        """Is the carrier report older than max_age_hours? Default 24h per docs."""
        ref = now or datetime.now(tz=UTC)
        # Normalize to tz-aware for comparison
        updated = self.usage_updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        age_hours = (ref - updated).total_seconds() / 3600.0
        return age_hours > max_age_hours


class SubscriptionSnapshot(BaseModel):
    """Subset of Subscription + key timestamps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subscription_id: str
    plan_id: str
    status: SubscriptionStatus
    activated_at: datetime | None = None
    canceled_at: datetime | None = None
    ended_at: datetime | None = None
    restricted_at: datetime | None = None
    restriction_reason: str | None = Field(
        default=None,
        description="From subscription.restrictionDetails; surfaces 'why service is off'.",
    )
    earliest_end_at: datetime | None = Field(
        default=None,
        description="Earliest cancelable date given plan.validity.minimumPeriods.",
    )
    phone_number_masked: str | None = Field(
        default=None,
        description="E.164 masked to country code + last 4. None for non-voice plans.",
    )


class PortingTransition(BaseModel):
    """One observed state of a Porting object; we keep the last few."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    porting_id: str
    status: PortingStatus
    donor_provider_name: str | None = Field(
        default=None, examples=["AT&T", "T-Mobile", "Verizon Wireless"]
    )
    declined_code: str | None = Field(
        default=None, examples=["portingPhoneNumberPortProtected"]
    )
    declined_message: str | None = Field(
        default=None,
        description="Human-readable decline reason; safe to show to end-user.",
    )
    last_requested_at: datetime | None = None
    observed_at: datetime


class InvoiceSnapshot(BaseModel):
    """Most recent invoice — billing-side of 'why isn't my service working'."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invoice_id: str
    status: InvoiceStatus
    amount_due_cents: int = Field(..., ge=0)
    currency: str = Field(..., examples=["USD", "GBP", "EUR"])
    finalized_at: datetime | None = None
    paid_at: datetime | None = None
    voided_at: datetime | None = None


class WebhookEcho(BaseModel):
    """One recent com.gigs.* event the agent observed for this subscription/user."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    event_type: str = Field(
        ...,
        pattern=r"^com\.gigs\.",
        description="Must start with 'com.gigs.' per Svix CloudEvents convention.",
    )
    occurred_at: datetime
    summary: str = Field(..., max_length=240, description="Short human readable summary.")


class ConversationTurn(BaseModel):
    """One turn of the user/assistant conversation that led to escalation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    text: str = Field(..., max_length=4000)
    sent_at: datetime


class RetrievedChunk(BaseModel):
    """One KB chunk the agent retrieved before its final (failed) attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    chunk_id: str = Field(..., description="Stable id of the chunk, e.g. 'esim/install#2.1'.")
    score: float = Field(..., ge=0.0, le=1.0)
    excerpt: str = Field(..., max_length=600)


# ---------------------------------------------------------------------------
# Top-level packet
# ---------------------------------------------------------------------------


class EscalationContext(BaseModel):
    """Self-contained handoff packet emitted when the agent escalates.

    Required reading for the human: this is the *single* artifact they get.
    They don't need to dig in dashboards before triaging.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Routing
    schema_version: str = Field(default="1.0.0", description="SemVer for this packet shape.")
    escalation_id: str = Field(..., description="Stable id for this handoff.")
    created_at: datetime
    project_id: str = Field(
        ..., description="Gigs project id — the tenant boundary in our system."
    )
    customer_brand: str = Field(
        ..., description="Human-readable brand name, e.g. 'CashCard', 'Tide', 'Revolut'."
    )
    reason: HandoffReason
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Agent's self-reported confidence at the moment of escalation.",
    )

    # State the human will want to read first
    user: UserSnapshot
    subscription: SubscriptionSnapshot | None = None
    sim: SimSnapshot | None = None
    usage: UsageSnapshot | None = None
    invoice: InvoiceSnapshot | None = None
    porting_history: list[PortingTransition] = Field(
        default_factory=list,
        description="Most recent first; cap at 3 transitions.",
        max_length=3,
    )
    recent_events: list[WebhookEcho] = Field(
        default_factory=list,
        description="Most recent 'com.gigs.*' events observed for this entity.",
        max_length=5,
    )

    # What the agent actually saw and said
    conversation: list[ConversationTurn] = Field(..., min_length=1)
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    proposed_answer: str | None = Field(
        default=None,
        description="The answer the agent considered but didn't send.",
        max_length=4000,
    )
    failure_tags: list[str] = Field(
        default_factory=list,
        description=(
            "Tags from failure_taxonomy.py, e.g. ['STALE_USAGE', 'WRONG_PROVIDER']. "
            "Helpful for routing and for the eval scorecard."
        ),
    )

    # Honesty surface
    notes_for_human: str = Field(
        default="",
        description=(
            "Free-text the agent leaves for the human: what it tried, what it "
            "couldn't verify, anything unusual. Keep brief; this is signal."
        ),
        max_length=1000,
    )

    @field_validator("recent_events")
    @classmethod
    def _events_chronological(cls, v: list[WebhookEcho]) -> list[WebhookEcho]:
        if v and any(v[i].occurred_at < v[i + 1].occurred_at for i in range(len(v) - 1)):
            raise ValueError("recent_events must be sorted most-recent-first")
        return v

    @field_validator("porting_history")
    @classmethod
    def _porting_chronological(cls, v: list[PortingTransition]) -> list[PortingTransition]:
        if v and any(v[i].observed_at < v[i + 1].observed_at for i in range(len(v) - 1)):
            raise ValueError("porting_history must be sorted most-recent-first")
        return v

    def to_json(self) -> str:
        """Serialize to JSON — what gets written into the ticketing system."""
        return self.model_dump_json(indent=2)
