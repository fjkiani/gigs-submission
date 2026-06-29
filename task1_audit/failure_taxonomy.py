"""Failure taxonomy for Operator's grounded answers.

Every time the agent goes wrong, the cause falls into one of seven axes — and
each axis points to a specific mechanism in Gigs' stack. This module turns
that into a small typed API the eval harness (Task 3) and the audit doc
(01_TASK1_AUDIT.md §2) both consume.

Why seven and not five or fifteen? Because each axis below corresponds to a
distinct, *observable* fact about a Gigs object (or absence thereof). If we
can't write a deterministic detector for an axis, it doesn't belong here —
it belongs in "OTHER" and needs more thinking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FailureAxis(StrEnum):
    """The 7 axes. Order is meaningful only for stable enum iteration."""

    STALE_KB = "STALE_KB"
    """KB chunk was authored before the latest plan/policy change.

    Detector: chunk.last_updated < plan.updatedAt for any plan the chunk references.
    """

    WRONG_PROVIDER = "WRONG_PROVIDER"
    """Answer assumes p3/p14/p15 eSIM lifecycle on a provider that doesn't expose it.

    Detector: answer claims an eSimProfile.status meaning, but the
    SIM's provider is not in {p3, p14, p15} -> eSimProfile is 'unknown'.
    """

    STALE_USAGE = "STALE_USAGE"
    """Balance/usage answer given without a freshness qualifier.

    Detector: answer mentions a numeric balance or 'GB remaining' without
    referencing usageRecord.updatedAt or a 'as of' clause.
    """

    MISSING_RESTRICTION = "MISSING_RESTRICTION"
    """Agent ignored subscription.status == 'restricted'.

    Detector: subscription.status == 'restricted' AND answer doesn't surface
    restriction reason and doesn't escalate.
    """

    PORTING_DECLINE_NOT_DECODED = "PORTING_DECLINE_NOT_DECODED"
    """Agent didn't surface declinedCode / declinedMessage when porting failed.

    Detector: most recent porting transition has declinedCode != null AND
    the answer doesn't include that code or its declinedMessage text.
    """

    BILLING_AMBIGUITY = "BILLING_AMBIGUITY"
    """Agent collapsed nuanced invoice state into a generic 'payment failed' message.

    Detector: invoice.status in {'draft', 'finalized', 'voided'} AND answer
    says or implies 'your payment failed' without distinguishing the actual state.
    """

    OUT_OF_SCOPE_OVER_REACH = "OUT_OF_SCOPE_OVER_REACH"
    """Agent answered something it shouldn't (off-product question).

    Detector: question intent classifier judged off-Gigs-domain AND the
    answer engaged with the question rather than declining.
    """


@dataclass(frozen=True)
class FailureAnnotation:
    """One axis-tag attached to an evaluated answer.

    Multiple annotations can attach to a single answer (e.g. STALE_USAGE +
    MISSING_RESTRICTION on a 'why is my service slow' question that ignored
    both the restriction state AND gave a stale GB-remaining figure).
    """

    axis: FailureAxis
    detail: str
    """One-line, human-readable explanation. Lands in the escalation packet."""

    evidence: dict[str, Any]
    """Structured evidence the detector used (chunk_id, sim_id, etc.).

    Kept as a plain dict so it serializes cleanly into the eval scorecard.
    """

    def __str__(self) -> str:  # pragma: no cover — cosmetic
        return f"[{self.axis.value}] {self.detail}"


# ---------------------------------------------------------------------------
# Constructors: one per axis, each documents what evidence it requires.
# Use these — never construct FailureAnnotation by hand. The constructors
# enforce that the right evidence is attached, which keeps Task 3's scorecard
# honest.
# ---------------------------------------------------------------------------


def stale_kb(*, chunk_id: str, chunk_updated_at: str, plan_updated_at: str) -> FailureAnnotation:
    """KB chunk older than the plan it references."""
    return FailureAnnotation(
        axis=FailureAxis.STALE_KB,
        detail=(
            f"KB chunk {chunk_id} (updated {chunk_updated_at}) predates a referenced "
            f"plan update at {plan_updated_at}."
        ),
        evidence={
            "chunk_id": chunk_id,
            "chunk_updated_at": chunk_updated_at,
            "plan_updated_at": plan_updated_at,
        },
    )


def wrong_provider(*, sim_id: str, provider: str) -> FailureAnnotation:
    """Lifecycle claim on a provider that doesn't expose lifecycle."""
    if provider in {"p3", "p14", "p15"}:
        # Be paranoid: if the caller mis-classified, fail loud, don't silently
        # mis-tag.
        raise ValueError(
            f"Provider {provider!r} DOES support eSIM lifecycle; "
            "do not tag WRONG_PROVIDER here."
        )
    return FailureAnnotation(
        axis=FailureAxis.WRONG_PROVIDER,
        detail=(
            f"Agent referenced eSIM lifecycle state on SIM {sim_id} whose provider "
            f"{provider!r} does not report it (returns 'unknown')."
        ),
        evidence={"sim_id": sim_id, "provider": provider},
    )


def stale_usage(*, subscription_id: str, hours_old: float) -> FailureAnnotation:
    """Numeric balance answer with no freshness qualifier."""
    return FailureAnnotation(
        axis=FailureAxis.STALE_USAGE,
        detail=(
            f"Subscription {subscription_id} usage report is {hours_old:.1f}h old; "
            "answer didn't qualify with 'as of'."
        ),
        evidence={"subscription_id": subscription_id, "hours_old": hours_old},
    )


def missing_restriction(*, subscription_id: str, restriction_reason: str | None) -> FailureAnnotation:
    """Restricted subscription handled as if active."""
    return FailureAnnotation(
        axis=FailureAxis.MISSING_RESTRICTION,
        detail=(
            f"Subscription {subscription_id} status is 'restricted' "
            f"(reason: {restriction_reason or 'unspecified'}) but the answer "
            "didn't surface that fact."
        ),
        evidence={
            "subscription_id": subscription_id,
            "restriction_reason": restriction_reason,
        },
    )


def porting_decline_not_decoded(
    *, porting_id: str, declined_code: str, declined_message: str
) -> FailureAnnotation:
    """Porting failed for a structured reason the agent didn't surface."""
    return FailureAnnotation(
        axis=FailureAxis.PORTING_DECLINE_NOT_DECODED,
        detail=(
            f"Porting {porting_id} declined with code {declined_code!r} "
            f"('{declined_message}'); answer didn't reference either."
        ),
        evidence={
            "porting_id": porting_id,
            "declined_code": declined_code,
            "declined_message": declined_message,
        },
    )


def billing_ambiguity(*, invoice_id: str, actual_status: str) -> FailureAnnotation:
    """Collapsed invoice state into a generic 'payment failed' message."""
    return FailureAnnotation(
        axis=FailureAxis.BILLING_AMBIGUITY,
        detail=(
            f"Invoice {invoice_id} is in status {actual_status!r}; "
            "answer collapsed that into 'payment failed' or similar."
        ),
        evidence={"invoice_id": invoice_id, "actual_status": actual_status},
    )


def out_of_scope_over_reach(*, intent: str) -> FailureAnnotation:
    """Off-Gigs-domain question that the agent engaged with instead of declining."""
    return FailureAnnotation(
        axis=FailureAxis.OUT_OF_SCOPE_OVER_REACH,
        detail=(
            f"Question intent '{intent}' is outside the connectivity / Gigs "
            "domain; agent should have declined and routed."
        ),
        evidence={"intent": intent},
    )


# ---------------------------------------------------------------------------
# Distribution helper — used by Task 1 §2 and Task 3 scorecard.
# ---------------------------------------------------------------------------


def distribution(annotations: list[FailureAnnotation]) -> dict[str, int]:
    """Count annotations by axis. Used to build the failure-axis pareto chart.

    The output is ordered by descending count, then by axis name, so the
    scorecard is reproducible across runs.
    """
    counts: dict[str, int] = {axis.value: 0 for axis in FailureAxis}
    for a in annotations:
        counts[a.axis.value] += 1
    return dict(
        sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
