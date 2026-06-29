"""CashCard instance configuration — routing, context vars, guardrails, triggers.

This is the *static* configuration a Gigs tenant is launched with. It lives
next to the agent runtime, not in the KB. Every field here is one CashCard
ops-team decision the audit prose (`02_TASK2_CASHCARD.md` §2) walks through.

Design notes
------------
- Pydantic v2, frozen models. The config is read once at session start; any
  change is a deploy, not a runtime mutation.
- Validators enforce hard facts from research/00_gigs_facts.md:
  * sim_types must be ("eSIM",) for CashCard (US/eSIM-only customer).
  * providers must be subset of {p3, p14, p15} — only those expose eSIM
    lifecycle ([2]).
  * country must be "US" — CashCard scope.
  * contact_mix_prior must sum to 1.0 ± 0.01.
  * routing_rules must cover every intent that has a matching KB topic.
- The `Guardrails` defaults are the *read-only day 1* posture chosen in
  the plan. The 60/90-day write-action ramp flips these via a config diff,
  not a code change.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Mix tolerance — anything within ±1% is treated as "sums to 1.0".
_MIX_TOLERANCE = 0.01

# Providers that expose meaningful eSIM lifecycle state per Gigs docs [2].
SUPPORTED_PROVIDERS: tuple[str, ...] = ("p3", "p14", "p15")

# Contact-mix bucket names — keep aligned with kb_skeleton/ topic folder names.
CONTACT_BUCKETS: tuple[str, ...] = (
    "esim_activation",
    "plan_questions",
    "devices",
    "roaming",
    "port_in",
    "other",
)


class IntentHandler(StrEnum):
    """Where an intent gets routed."""

    AGENT = "agent"
    TIER1_HUMAN = "tier1_human"
    TIER2_HUMAN = "tier2_human"


class TriggerKindSpec(StrEnum):
    """Names of escalation triggers the config declares.

    These match the `TriggerKind` enum in escalation_triggers.py 1:1. We keep
    them as strings in the config to avoid a circular import.
    """

    LOW_CONFIDENCE = "low_confidence"
    WRITE_REQUESTED = "write_requested"
    RESTRICTED_SUBSCRIPTION = "restricted_subscription"
    PORTING_DECLINED = "porting_declined"
    STALE_USAGE = "stale_usage"
    OUT_OF_PRODUCT_SCOPE = "out_of_product_scope"
    INVOICE_PAYMENT_FAILED = "invoice_payment_failed"


class RoutingRule(BaseModel):
    """One intent → handler mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: str = Field(..., min_length=1)
    handler: IntentHandler
    # Optional bucket the intent maps to — used by the gap analyzer to assert
    # every bucket has at least one agent-handled intent.
    bucket: str | None = None


class ContextVarSpec(BaseModel):
    """A Gigs API field resolved at session start and passed to the agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., min_length=1)
    required: bool
    # Gigs API endpoint or field path this is sourced from (e.g.
    # "GET /projects/{p}/users/{u}.id" or "session.subscription_id").
    source: str = Field(..., min_length=1)


class Guardrails(BaseModel):
    """Day-1 safety posture.

    Defaults are the read-only-day-1 stance from the approved plan. Flipping
    any of these is a deliberate, audited config change.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    read_only_writes: bool = True
    refuse_pii_writes: bool = True
    refuse_irreversible_actions: bool = True
    # Treat usage older than this as stale and require an "as of" qualifier.
    staleness_ceiling_seconds: int = Field(default=3600, ge=60)


class TriggerSpec(BaseModel):
    """One escalation-trigger declaration, in priority order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TriggerKindSpec
    # 1 is highest priority; first-match wins by ascending priority.
    priority: int = Field(..., ge=1)


class TwoHopEscalation(BaseModel):
    """First hop = agent → CashCard Tier 1. Second hop = Tier 1 → Gigs Tier 2.

    The plan stipulates: first hop has code, second hop has schema only. So
    this carries the addresses for both; the runtime only acts on `tier1`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tier1_target: str = Field(..., min_length=3)
    tier2_target: str = Field(..., min_length=3)


class InstanceConfig(BaseModel):
    """Top-level CashCard instance configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(..., min_length=1)
    country: Literal["US"]
    sim_types: tuple[Literal["eSIM"], ...]
    providers: tuple[str, ...]
    contact_mix_prior: dict[str, float]
    routing_rules: tuple[RoutingRule, ...]
    context_variables: tuple[ContextVarSpec, ...]
    guardrails: Guardrails
    escalation_triggers: tuple[TriggerSpec, ...]
    two_hop: TwoHopEscalation

    # ---- validators ----

    @field_validator("sim_types")
    @classmethod
    def _esim_only(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if v != ("eSIM",):
            raise ValueError("CashCard is eSIM-only; sim_types must equal ('eSIM',)")
        return v

    @field_validator("providers")
    @classmethod
    def _providers_supported(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("providers must be non-empty")
        bad = [p for p in v if p not in SUPPORTED_PROVIDERS]
        if bad:
            raise ValueError(
                f"providers {bad!r} not in supported eSIM-lifecycle set "
                f"{SUPPORTED_PROVIDERS!r}"
            )
        return v

    @field_validator("contact_mix_prior")
    @classmethod
    def _mix_sums_to_one(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("contact_mix_prior must be non-empty")
        for bucket in v:
            if bucket not in CONTACT_BUCKETS:
                raise ValueError(
                    f"contact_mix bucket {bucket!r} not in known buckets "
                    f"{CONTACT_BUCKETS!r}"
                )
            if v[bucket] < 0:
                raise ValueError(f"contact_mix weight for {bucket!r} is negative")
        total = sum(v.values())
        if abs(total - 1.0) > _MIX_TOLERANCE:
            raise ValueError(
                f"contact_mix_prior must sum to 1.0 ± {_MIX_TOLERANCE}, got {total:.4f}"
            )
        return v

    @field_validator("escalation_triggers")
    @classmethod
    def _trigger_priorities_unique(
        cls, v: tuple[TriggerSpec, ...]
    ) -> tuple[TriggerSpec, ...]:
        seen: set[int] = set()
        for t in v:
            if t.priority in seen:
                raise ValueError(f"duplicate trigger priority: {t.priority}")
            seen.add(t.priority)
        return v

    @model_validator(mode="after")
    def _routing_covers_buckets(self) -> InstanceConfig:
        """Every bucket in contact_mix_prior with weight > 0 must have at least
        one routing rule whose `bucket` field matches it.

        This is the day-1 coverage check — if eSIM activation is 35% of volume
        but no rule routes to AGENT for that bucket, the config is broken.
        """
        weighted_buckets = {b for b, w in self.contact_mix_prior.items() if w > 0}
        covered = {r.bucket for r in self.routing_rules if r.bucket is not None}
        missing = weighted_buckets - covered
        if missing:
            raise ValueError(
                f"contact-mix buckets with no routing rule: {sorted(missing)!r}"
            )
        return self

    @model_validator(mode="after")
    def _required_vars_present(self) -> InstanceConfig:
        """The escalation context needs at least subscription_id, sim_id, user_id
        to be useful. Refuse a config that doesn't pass them in.
        """
        required_names = {"subscription_id", "sim_id", "user_id"}
        present_required = {
            v.name for v in self.context_variables if v.required
        }
        missing = required_names - present_required
        if missing:
            raise ValueError(
                f"required context variables missing: {sorted(missing)!r}"
            )
        return self


__all__ = [
    "CONTACT_BUCKETS",
    "SUPPORTED_PROVIDERS",
    "ContextVarSpec",
    "Guardrails",
    "InstanceConfig",
    "IntentHandler",
    "RoutingRule",
    "TriggerKindSpec",
    "TriggerSpec",
    "TwoHopEscalation",
]
