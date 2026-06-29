"""Task 1 demo — offline replay of three Operator handoffs.

Run via ``python -m task1_audit.demo`` (or ``make demo``).

Each example is a small, realistic Gigs support thread. We feed it through
``check_grounding`` so reviewers see the three verdicts that matter:

    1. UNGROUNDED — agent quoted a stale balance with no freshness qualifier.
    2. GROUNDED   — agent answered with API-state-aware language.
    3. REFUSED    — agent declined and escalated; gate exempts refusals.

No network, no LLM. Pure deterministic dispatch — the same way the eval
harness in Task 3 will exercise this gate in CI.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from task1_audit.grounding_check import (
    GroundingReport,
    GroundingVerdict,
    check_grounding,
)


def _ex_stale_balance_ungrounded() -> tuple[str, GroundingReport]:
    """Agent quotes a hard number with no 'as of' qualifier — gate must refuse."""
    question = "How much data do I have left?"
    answer = "You have 4.3 GB remaining on your plan."
    retrieved_chunks = [
        {
            "chunk_id": "plan/overview#1",
            "text": (
                "Each subscription has a plan that defines its allowances. "
                "Carrier usage is reported with a delay; the API exposes "
                "usageRecord.updatedAt as the as-of timestamp."
            ),
        }
    ]
    api_facts = {
        "subscription.status": "active",
        "usage.data_bytes_used": 6_438_265_318,
        "usage.updated_at": "2026-06-26T22:12:00Z",
    }
    report = check_grounding(
        question=question,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        api_facts=api_facts,
    )
    return ("stale balance, no freshness qualifier", report)


def _ex_freshness_qualifier_grounded() -> tuple[str, GroundingReport]:
    """Same question — answered with an 'as of' qualifier and a state match."""
    question = "How much data do I have left right now?"
    answer = (
        "As of 2026-06-26T22:12:00Z, your subscription is active and your usage "
        "report shows 6438265318 bytes consumed this period."
    )
    retrieved_chunks = [
        {
            "chunk_id": "usage/freshness#1",
            "text": (
                "Always quote usage with the carrier-reported as-of timestamp "
                "(usageRecord.updatedAt). Treat any value older than 24 hours as stale."
            ),
        },
        {
            "chunk_id": "subscription/status#1",
            "text": (
                "Subscription status values include active, pending, initiated, "
                "restricted, and ended. Restricted means service is paused."
            ),
        },
    ]
    api_facts = {
        "subscription.status": "active",
        "usage.data_bytes_used": 6_438_265_318,
        "usage.updated_at": "2026-06-26T22:12:00Z",
    }
    report = check_grounding(
        question=question,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        api_facts=api_facts,
    )
    return ("freshness-qualified balance with state match", report)


def _ex_refusal_grounded() -> tuple[str, GroundingReport]:
    """Agent recognized it couldn't answer and escalated — gate exempts."""
    question = "Can you cancel my line and refund last month?"
    answer = (
        "I'll hand this off to a human teammate — cancellations and refunds "
        "need a person to review your account and confirm the refund window."
    )
    retrieved_chunks = [
        {
            "chunk_id": "policy/handoff#1",
            "text": (
                "Cancellations and refunds always escalate to a human "
                "operator; we do not auto-process state-changing requests."
            ),
        }
    ]
    api_facts: dict[str, object] = {}
    report = check_grounding(
        question=question,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        api_facts=api_facts,
    )
    return ("explicit human handoff", report)


def _verdict_color(v: GroundingVerdict) -> str:
    return {
        GroundingVerdict.GROUNDED: "bold green",
        GroundingVerdict.UNGROUNDED: "bold red",
        GroundingVerdict.REFUSED: "bold yellow",
        GroundingVerdict.EMPTY: "bold red",
    }[v]


def main() -> None:
    examples = [
        _ex_stale_balance_ungrounded(),
        _ex_freshness_qualifier_grounded(),
        _ex_refusal_grounded(),
    ]
    console = Console()
    table = Table(title="Task 1 — grounding gate verdicts (offline)", title_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Scenario")
    table.add_column("Verdict")
    table.add_column("Reason")
    for i, (label, report) in enumerate(examples, start=1):
        table.add_row(
            str(i),
            label,
            f"[{_verdict_color(report.verdict)}]{report.verdict.value}[/]",
            report.reason,
        )
    console.print(table)


if __name__ == "__main__":
    main()
