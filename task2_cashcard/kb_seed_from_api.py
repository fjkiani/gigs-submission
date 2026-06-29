"""API-derived KB chunks — the drift-resistant half of the CashCard KB.

Three deterministic derivers, each consuming a frozen JSON snapshot of the
relevant Gigs API resource and emitting structured chunks. Body text is
templated, not hand-authored, so when the underlying API changes the chunks
regenerate cleanly.

In production these run on a cron AND in response to `com.gigs.plan.updated`,
`com.gigs.networkAvailability.updated`, etc. (the 10 event types listed in
Task 1's `KB_INVALIDATING_EVENT_TYPES`). Here we ship the pure derivers and
demonstrate them against the fixture in `fixtures/cashcard_project.json`.

Sources
-------
- Plan schema: developers.gigs.com/api/latest/core/plans [4]
- SIM + eSIM endpoints: /api/latest/core/sims [2]
- Porting schema (US-specific required fields): /api/latest/core/portings [5]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Default freshness — derived chunks are good for 24h before a re-derive
# should be considered stale. The freshness watcher invalidates sooner on
# real events.
_DEFAULT_TTL_SECONDS = 24 * 3600

# Providers exposing eSIM lifecycle status [2]; everything else returns
# `eSimProfile.status = "unknown"`.
_LIFECYCLE_PROVIDERS: frozenset[str] = frozenset({"p3", "p14", "p15"})

# US porting required fields per Porting docs [5]. These are the fields
# CashCard agents will see denied port-ins for if absent.
US_PORTING_REQUIRED_FIELDS: tuple[str, ...] = (
    "accountNumber",
    "accountPin",
    "ssnLast4",
    "zipCode",
    "phoneNumber",
    "donorProvider",
)

# Subset of US donor decline codes the agent must surface verbatim. Names come
# from Porting docs [5].
US_PORTING_DECLINE_CODES: tuple[tuple[str, str], ...] = (
    (
        "portingPhoneNumberPortProtected",
        "The number has port protection enabled at the donor provider; the user "
        "must disable it in the donor's portal before retrying.",
    ),
    (
        "portingAccountNumberMismatch",
        "The account number the user supplied does not match the donor's "
        "records; ask the user to verify on the donor's most recent bill.",
    ),
    (
        "portingPinIncorrect",
        "The account PIN (transfer/port-out PIN) is wrong; on most US carriers "
        "the user can regenerate it from the donor app or by calling support.",
    ),
    (
        "portingZipCodeMismatch",
        "The ZIP code on file at the donor differs from what the user supplied; "
        "verify the billing ZIP, not the service-address ZIP.",
    ),
    (
        "portingSsnLast4Mismatch",
        "The last 4 digits of the SSN don't match the donor's records; this is "
        "often because the donor account is in a household member's name.",
    ),
    (
        "portingNumberNotPortable",
        "The donor confirms the number is not portable (e.g. VoIP, prepaid "
        "with no port window). Offer the user a new number instead.",
    ),
)


@dataclass(frozen=True)
class SeededChunk:
    """An API-derived KB chunk.

    Body is rendered text. Source fields are kept so a reader (or the agent
    via the citation gate) can verify which API path the chunk came from.
    """

    chunk_id: str
    topic: str
    body: str
    source_endpoint: str
    source_field_path: str
    derived_at: datetime
    ttl_seconds: int


def _now() -> datetime:
    return datetime.now(UTC)


def derive_plan_chunks(plan: dict[str, Any]) -> list[SeededChunk]:
    """Emit one chunk describing a Plan's allowances, limits, simTypes, validity.

    Schema reference: /api/latest/core/plans [4]. We touch only the documented
    public fields — `id`, `name`, `allowances`, `limits`, `simTypes`,
    `validity`, `description`, `coverage`.
    """
    if not isinstance(plan, dict):
        raise TypeError(f"plan must be dict, got {type(plan).__name__}")
    pid = plan.get("id")
    if not pid:
        raise ValueError("plan must have 'id'")

    name = plan.get("name") or pid
    allowances = plan.get("allowances") or []
    limits = plan.get("limits") or []
    sim_types = plan.get("simTypes") or []
    validity = plan.get("validity") or {}
    coverage = plan.get("coverage") or {}

    parts: list[str] = [f"Plan **{name}** (`{pid}`)."]

    if allowances:
        allowance_lines: list[str] = []
        for a in allowances:
            if isinstance(a, dict):
                amount = a.get("amount")
                unit = a.get("unit") or ""
                kind = a.get("type") or "unknown"
                if amount is not None:
                    allowance_lines.append(f"- {kind}: {amount} {unit}".rstrip())
        if allowance_lines:
            parts.append("Allowances:\n" + "\n".join(allowance_lines))

    if limits:
        limit_lines: list[str] = []
        for limit in limits:
            if isinstance(limit, dict):
                kind = limit.get("type") or "unknown"
                value = limit.get("value")
                limit_lines.append(f"- {kind}: {value}")
        if limit_lines:
            parts.append("Limits:\n" + "\n".join(limit_lines))

    if sim_types:
        parts.append(f"SIM types supported: {', '.join(sorted(sim_types))}.")

    if validity:
        v_amt = validity.get("amount")
        v_unit = validity.get("unit")
        if v_amt is not None and v_unit:
            parts.append(f"Validity: {v_amt} {v_unit}.")

    if coverage:
        countries = coverage.get("countries") or []
        if countries:
            parts.append(f"Coverage: {', '.join(sorted(countries))}.")

    parts.append(f"Source: GET /projects/{{p}}/plans/{pid}")
    body = "\n\n".join(parts)

    return [
        SeededChunk(
            chunk_id=f"plan.{pid}",
            topic="plan_questions",
            body=body,
            source_endpoint=f"/projects/{{p}}/plans/{pid}",
            source_field_path="plan",
            derived_at=_now(),
            ttl_seconds=_DEFAULT_TTL_SECONDS,
        )
    ]


def derive_porting_required_fields(country: str = "US") -> list[SeededChunk]:
    """Emit chunks describing porting required fields and decline-code meanings.

    For US, returns one chunk for the required-field list plus one chunk per
    documented decline code. Source: /api/latest/core/portings [5].
    """
    if country != "US":
        # CashCard is US-only by config; we keep the function gated to make
        # the assumption explicit.
        raise NotImplementedError(
            f"porting derivers ship for country='US' only, got {country!r}"
        )

    chunks: list[SeededChunk] = []
    field_list = "\n".join(f"- `{f}`" for f in US_PORTING_REQUIRED_FIELDS)
    chunks.append(
        SeededChunk(
            chunk_id="porting.us.required_fields",
            topic="port_in",
            body=(
                "Before submitting a US port-in, every Gigs port request must "
                f"carry these fields:\n\n{field_list}\n\n"
                "All six are donor-provider-checked — a single mismatch causes "
                "the port to land in `status=\"declined\"` with a structured "
                "`declinedCode`.\n\n"
                "Source: POST /projects/{p}/portings, donorProvider.required[]"
            ),
            source_endpoint="/projects/{p}/portings",
            source_field_path="donorProvider.required",
            derived_at=_now(),
            ttl_seconds=_DEFAULT_TTL_SECONDS,
        )
    )

    for code, explanation in US_PORTING_DECLINE_CODES:
        chunks.append(
            SeededChunk(
                chunk_id=f"porting.decline.{code}",
                topic="port_in",
                body=(
                    f"Decline code **`{code}`**.\n\n{explanation}\n\n"
                    f"When the agent sees `porting.declinedCode == \"{code}\"`, "
                    "it must surface this exact code in the answer so the user "
                    "(or the Tier 1 human) can act on it.\n\n"
                    "Source: porting.declinedCode + porting.declinedMessage"
                ),
                source_endpoint="/projects/{p}/portings/{port_id}",
                source_field_path="declinedCode",
                derived_at=_now(),
                ttl_seconds=_DEFAULT_TTL_SECONDS,
            )
        )

    return chunks


def derive_esim_eligibility(provider: str) -> list[SeededChunk]:
    """Emit a chunk describing whether eSIM lifecycle state is meaningful.

    Hard fact from Gigs docs [2]: eSimProfile.status is meaningful only on
    providers in `{p3, p14, p15}`. Everything else returns `"unknown"`, and
    the agent must NOT claim to verify install state.
    """
    if not provider:
        raise ValueError("provider must be a non-empty string")

    if provider in _LIFECYCLE_PROVIDERS:
        body = (
            f"On provider `{provider}`, the SIM's `eSimProfile.status` is "
            "meaningful and takes values `installed`, `enabled`, `disabled`, "
            "or `deleted`. The agent can rely on this field to answer "
            "\"is my eSIM installed?\" questions, with an \"as of "
            "`{updatedAt}`\" qualifier.\n\n"
            "Source: GET /projects/{p}/sims/{s}.eSimProfile.status"
        )
    else:
        body = (
            f"On provider `{provider}`, `eSimProfile.status` returns "
            "`unknown` — the carrier does not expose lifecycle state. The "
            "agent must NOT claim to have verified the eSIM is installed; "
            "it must instead ask the user to confirm visually or escalate.\n\n"
            "Source: GET /projects/{p}/sims/{s}.eSimProfile.status (always "
            f"`unknown` on `{provider}`)"
        )

    return [
        SeededChunk(
            chunk_id=f"esim.lifecycle.{provider}",
            topic="esim_activation",
            body=body,
            source_endpoint="/projects/{p}/sims/{s}",
            source_field_path="eSimProfile.status",
            derived_at=_now(),
            ttl_seconds=_DEFAULT_TTL_SECONDS,
        )
    ]


__all__ = [
    "US_PORTING_DECLINE_CODES",
    "US_PORTING_REQUIRED_FIELDS",
    "SeededChunk",
    "derive_esim_eligibility",
    "derive_plan_chunks",
    "derive_porting_required_fields",
]
