"""Week-1 canaries — named runtime checks for "what could go wrong".

Each canary is a pure function `check(...) -> CanaryHit | None`. They consume
the same `EscalationContext` shape Task 1 ships, plus the agent's actual
answer text, and fire when a documented failure mode is present.

Why these six
-------------
Each maps to a *specific* mechanism in the Gigs stack rather than a generic
"check the answer is good" pattern:

- ``canary_missing_required_var``       — Task 1 audit: customers shipping
  conversations with the first message missing the user id. Most failure
  modes downstream stem from this.
- ``canary_provider_not_supported``     — eSIM lifecycle is only meaningful
  on providers p3/p14/p15 [2]. Agent claiming "your eSIM is installed" on
  any other provider is hallucination.
- ``canary_stale_usage_no_qualifier``   — carrier-lagged usage data MUST
  carry an "as of {timestamp}" qualifier [6].
- ``canary_porting_declined_not_decoded`` — declined ports come with a
  structured `declinedCode`; agent answers about declined ports that don't
  surface it are throwing away the signal [5].
- ``canary_restriction_ignored``        — subscription status "restricted"
  blocks the user's request; agent promising the action will work is wrong.
- ``canary_pii_in_answer``              — Task 1 audit established that
  agent answers must never echo the user's full email/phone back; we
  enforce it post-hoc here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from task1_audit import EscalationContext

# Lifecycle-supporting providers per Gigs docs [2].
_LIFECYCLE_PROVIDERS: frozenset[str] = frozenset({"p3", "p14", "p15"})

# Phrases that indicate the agent is making an install-state claim.
_INSTALL_CLAIM_PHRASES: tuple[str, ...] = (
    "esim is installed",
    "esim is enabled",
    "your esim is set up",
    "your esim is active on your device",
    "profile is installed",
)

# Tokens that, if present together with a usage-style number, would form a
# freshness qualifier. We look for any one within a small window.
_FRESHNESS_HINTS: tuple[str, ...] = (
    "as of",
    "as-of",
    "last reported",
    "last updated",
    "updated at",
    "carrier reported",
    "(stale",
)

# Pattern matching a "balance"-style usage number the agent might emit.
_USAGE_NUMBER_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:gb|mb|gigabytes?|megabytes?|minutes?|texts?|messages?|sms)\b",
    re.IGNORECASE,
)

# Pattern matching a 10-digit phone number (US format only — CashCard).
_PHONE_RE = re.compile(r"\b\d{10}\b")

# Pattern matching a plausible email address.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


@dataclass(frozen=True)
class CanaryHit:
    """A canary that fired. Carries enough detail to alert + reproduce."""

    name: str
    detail: str


def canary_missing_required_var(
    *,
    ctx: EscalationContext,
    required: tuple[str, ...] = ("subscription_id", "sim_id", "user_id"),
) -> CanaryHit | None:
    """Fire if any required identifier is absent from the context.

    The Task 1 audit identified this as the #1 cause of conversations not
    appearing in the data warehouse — the variable was never set on the
    first message. We check by mapping each required name to the obvious
    attribute on the EscalationContext.
    """
    missing: list[str] = []
    if "subscription_id" in required and ctx.subscription is None:
        missing.append("subscription_id")
    if "sim_id" in required and ctx.sim is None:
        missing.append("sim_id")
    if "user_id" in required and not ctx.user.user_id:
        missing.append("user_id")
    if missing:
        return CanaryHit(
            name="missing_required_var",
            detail=f"missing required identifiers: {sorted(missing)!r}",
        )
    return None


def canary_provider_not_supported(
    *, ctx: EscalationContext, answer: str
) -> CanaryHit | None:
    """Fire if the agent claims eSIM install state on an unsupported provider.

    On providers outside {p3, p14, p15} the lifecycle status is always
    `unknown`. The agent must NOT claim it has verified install state.
    """
    if ctx.sim is None or ctx.sim.provider is None:
        return None
    provider = ctx.sim.provider
    if provider in _LIFECYCLE_PROVIDERS:
        return None
    lowered = answer.lower()
    for phrase in _INSTALL_CLAIM_PHRASES:
        if phrase in lowered:
            return CanaryHit(
                name="provider_not_supported",
                detail=(
                    f"answer claims install state ({phrase!r}) but "
                    f"provider={provider!r} returns unknown lifecycle"
                ),
            )
    return None


def canary_stale_usage_no_qualifier(*, answer: str) -> CanaryHit | None:
    """Fire if the answer cites a usage number without a freshness qualifier.

    We require at least one freshness hint in the answer when a usage-style
    number is present. False-positive rate is low because the hints are
    cheap to include ("as of {timestamp}") and the Gigs Usage docs [6]
    explicitly mandate them.
    """
    if not _USAGE_NUMBER_RE.search(answer):
        return None
    lowered = answer.lower()
    for hint in _FRESHNESS_HINTS:
        if hint in lowered:
            return None
    snippet_match = _USAGE_NUMBER_RE.search(answer)
    assert snippet_match is not None  # we just matched above
    return CanaryHit(
        name="stale_usage_no_qualifier",
        detail=(
            f"answer cites usage number {snippet_match.group(0)!r} without "
            "a freshness qualifier"
        ),
    )


def canary_porting_declined_not_decoded(
    *, ctx: EscalationContext, answer: str
) -> CanaryHit | None:
    """Fire if porting is declined but the answer doesn't surface declinedCode."""
    if not ctx.porting_history:
        return None
    latest = ctx.porting_history[0]
    if latest.status != "declined" or not latest.declined_code:
        return None
    if latest.declined_code in answer:
        return None
    return CanaryHit(
        name="porting_declined_not_decoded",
        detail=(
            f"latest porting transition has declinedCode={latest.declined_code!r} "
            "but answer doesn't surface it"
        ),
    )


def canary_restriction_ignored(
    *, ctx: EscalationContext, answer: str
) -> CanaryHit | None:
    """Fire if subscription is restricted but the answer promises an action.

    Heuristic: when restricted, the answer should not contain action verbs
    that imply service is working ("activate", "use", "start", "enable").
    """
    sub = ctx.subscription
    if sub is None or sub.status != "restricted":
        return None
    action_verbs = ("activate", "use ", "start ", "enable", "go ahead")
    lowered = answer.lower()
    matched = [v.strip() for v in action_verbs if v in lowered]
    if matched:
        return CanaryHit(
            name="restriction_ignored",
            detail=(
                f"subscription restricted but answer uses action verbs: {matched!r}"
            ),
        )
    return None


def canary_pii_in_answer(
    *, ctx: EscalationContext, answer: str
) -> CanaryHit | None:
    """Fire if the answer echoes user PII verbatim.

    Two checks:

    - If the answer contains *any* full email address at all, flag it. The
      agent is replying to a logged-in user; there is no legitimate reason
      to echo back an email in a support response.

    - If the answer contains a raw 10-digit number AND we have a subscription
      record with a `phone_number_masked` value, flag the digits. The masked
      phone format ``+1 (***) ***-1234`` should never appear in agent text
      reconstructed back to digits.
    """
    user = ctx.user
    bad_substrings: list[str] = []

    if user.email_masked and user.email_masked in answer:
        bad_substrings.append(user.email_masked)

    sub = ctx.subscription
    if sub is not None and sub.phone_number_masked:
        digits = _PHONE_RE.search(answer)
        if digits is not None:
            bad_substrings.append(digits.group(0))

    detected_email = _EMAIL_RE.search(answer)
    if detected_email and detected_email.group(0) not in bad_substrings:
        bad_substrings.append(detected_email.group(0))

    if bad_substrings:
        return CanaryHit(
            name="pii_in_answer",
            detail=f"PII-like tokens present in answer: {bad_substrings!r}",
        )
    return None


def run_all(
    *, ctx: EscalationContext, answer: str, now: datetime | None = None
) -> list[CanaryHit]:
    """Convenience: run every canary and return all hits (not just first)."""
    _ = now if now is not None else datetime.now(UTC)
    hits: list[CanaryHit] = []
    for canary in (
        canary_missing_required_var(ctx=ctx),
        canary_provider_not_supported(ctx=ctx, answer=answer),
        canary_stale_usage_no_qualifier(answer=answer),
        canary_porting_declined_not_decoded(ctx=ctx, answer=answer),
        canary_restriction_ignored(ctx=ctx, answer=answer),
        canary_pii_in_answer(ctx=ctx, answer=answer),
    ):
        if canary is not None:
            hits.append(canary)
    return hits


__all__ = [
    "CanaryHit",
    "canary_missing_required_var",
    "canary_pii_in_answer",
    "canary_porting_declined_not_decoded",
    "canary_provider_not_supported",
    "canary_restriction_ignored",
    "canary_stale_usage_no_qualifier",
    "run_all",
]
