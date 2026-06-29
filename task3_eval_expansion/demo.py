"""Task 3 demo — expansion verdicts + 80→90% trajectory + Q3 commit in one screen.

Run via ``python -m task3_eval_expansion.demo`` (or ``make demo-task3``).

Four blocks, deterministic, no network, no LLM:

    1. Expansion verdicts — six tracks (Track 3 split into 3a/3b), each
                             with verdict and gate-failure counts.
    2. Gap decomposition  — the four mutually-exclusive buckets that
                             account for the 20-point gap, with each
                             bucket's primary lever named.
    3. Lever trajectory   — L1 through L5 applied in order on the
                             illustrated 80% decomposition, showing how
                             the headline metric moves.
    4. Q3 commit          — three staged tiers with explicit gates, plus
                             the three explicit Q3 non-commits.

The point of the demo is to show a reviewer in 60 seconds that:

- The expansion claims are typed (six verdicts, each with named gates).
- The 80→90% argument decomposes into a partition (no double-counting).
- The Q3 commit has named gates and explicit non-commits — no single
  90% number with quiet denominator drift.

If any of the four blocks shows a regression (a verdict flips, a bucket
sum doesn't balance, the trajectory lands at a different endpoint, or a
non-commit drops), the demo's output changes and the test suite catches it.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from task3_eval_expansion.expansion_track import (
    ReadinessVerdict,
    recommended_track_reports,
)
from task3_eval_expansion.gap_decomposition import (
    GapBucket,
    illustrated_decomposition_for_raw_80,
)
from task3_eval_expansion.lever_simulator import (
    recommended_lever_sequence,
    simulate_sequence,
)
from task3_eval_expansion.q3_commit import recommended_q3_commit

_VERDICT_STYLE = {
    ReadinessVerdict.READY: "bold green",
    ReadinessVerdict.NEEDS_WORK: "bold yellow",
    ReadinessVerdict.NOT_READY: "bold red",
}


def _section_1_verdicts(console: Console) -> None:
    console.print(
        Panel(
            "[bold]Part A — expansion readiness[/bold]\n"
            "Six tracks (Track 3 split into user-facing / partner-facing). "
            "Verdicts are computed from per-track typed gates, not declared.",
            border_style="cyan",
        )
    )
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Track")
    table.add_column("Verdict", justify="center")
    table.add_column("Failing gates", justify="right")
    table.add_column("Blocking?", justify="right")
    table.add_column("Summary")
    for r in recommended_track_reports():
        style = _VERDICT_STYLE.get(r.verdict, "white")
        table.add_row(
            r.track.name,
            f"[{style}]{r.verdict.value}[/{style}]",
            str(len(r.failing_gates)),
            str(len(r.blocking_failures)),
            r.summary,
        )
    console.print(table)
    console.print()


def _section_2_decomposition(console: Console) -> None:
    console.print(
        Panel(
            "[bold]Part B step 1 — decomposing the 20% gap[/bold]\n"
            "Every failing question is in EXACTLY one of four buckets. "
            "The partition invariant is enforced at construction time.",
            border_style="cyan",
        )
    )
    d = illustrated_decomposition_for_raw_80()
    pcts = d.percentage_points_per_bucket()

    summary_table = Table(show_header=True, header_style="bold cyan")
    summary_table.add_column("Bucket")
    summary_table.add_column("Count", justify="right")
    summary_table.add_column("% of gold set", justify="right")
    summary_table.add_column("Primary lever")
    rows = (
        (
            GapBucket.CORRECT_REFUSAL_COUNTED_AS_FAIL,
            "L1 — switch to refusal-aware metric",
        ),
        (GapBucket.RETRIEVAL_MISS, "L2 — KB delta on top-3 taxonomy axes"),
        (GapBucket.UNGROUNDED_ANSWER, "L3 — tighten grounding threshold"),
        (
            GapBucket.WRONG_ANSWER_FALSE_POSITIVE,
            "L4 — per-tenant escalation triggers",
        ),
    )
    for bucket, lever in rows:
        summary_table.add_row(
            bucket.value,
            str(d.count(bucket)),
            f"{pcts[bucket]:.1f}%",
            lever,
        )
    console.print(summary_table)
    console.print(
        f"  [dim]Total: {d.total_questions}q, "
        f"raw deflection {d.raw_deflection_pct:.1f}%, "
        f"refusal-aware {d.refusal_aware_deflection_pct:.1f}%[/dim]"
    )
    console.print()


def _section_3_trajectory(console: Console) -> None:
    console.print(
        Panel(
            "[bold]Part B step 2 — applying the five levers[/bold]\n"
            "Pure function: GapDecomposition + Lever → GapDecomposition. "
            "Each step shows the running raw and refusal-aware deflection.",
            border_style="cyan",
        )
    )
    initial = illustrated_decomposition_for_raw_80()
    result = simulate_sequence(initial, recommended_lever_sequence())

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Step", justify="right")
    table.add_column("Lever")
    table.add_column("Raw %", justify="right")
    table.add_column("Δ raw (pp)", justify="right")
    table.add_column("Refusal-aware %", justify="right")
    table.add_column("Note")
    table.add_row(
        "0",
        "[dim](starting state)[/dim]",
        f"{initial.raw_deflection_pct:.1f}%",
        "—",
        f"{initial.refusal_aware_deflection_pct:.1f}%",
        f"baseline ({initial.passing}/{initial.total_questions} pass)",
    )
    for idx, step in enumerate(result.steps, start=1):
        # Highlight lift cells in green if positive.
        lift = step.lift_pp
        lift_str = f"[green]+{lift:.1f}[/green]" if lift > 0 else f"{lift:+.1f}"
        table.add_row(
            str(idx),
            f"{step.lever.lever_id.value} {step.lever.name}",
            f"{step.after.raw_deflection_pct:.1f}%",
            lift_str,
            f"{step.after.refusal_aware_deflection_pct:.1f}%",
            step.lever.note,
        )
    console.print(table)
    console.print(
        f"  [dim]Total raw lift: {result.total_raw_lift_pp:+.1f}pp · "
        f"refusal-aware lift: {result.total_refusal_aware_lift_pp:+.1f}pp[/dim]"
    )
    console.print()


def _section_4_q3_commit(console: Console) -> None:
    console.print(
        Panel(
            "[bold]Q3 commit — three staged tiers, not one 90% number[/bold]\n"
            "Each tier has an explicit gate and an explicit observable. "
            "All milestones defended on refusal-aware deflection.",
            border_style="cyan",
        )
    )
    commit = recommended_q3_commit()

    console.print(f"  [italic]{commit.headline}[/italic]")
    console.print()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Tier")
    table.add_column("Window")
    table.add_column("Target", justify="right")
    table.add_column("Metric")
    table.add_column("Levers")
    for m in commit.milestones:
        table.add_row(
            m.tier.value,
            m.week_window,
            f"{m.target_value_pct:.0f}%",
            m.target_metric.value,
            ", ".join(m.primary_levers),
        )
    console.print(table)
    console.print()

    console.print("[bold]Explicit Q3 non-commits[/bold]")
    for nc in commit.non_commits:
        console.print(f"  • [bold]{nc.item}[/bold]")
        console.print(f"    [dim]→ {nc.reason}[/dim]")
        console.print(f"    [dim]→ earliest: {nc.earliest_reasonable_quarter}[/dim]")
    console.print()


def main() -> None:
    console = Console()
    console.rule("[bold magenta]Task 3 — Evaluation and expansion[/bold magenta]")
    _section_1_verdicts(console)
    _section_2_decomposition(console)
    _section_3_trajectory(console)
    _section_4_q3_commit(console)
    console.rule("[dim]End of demo[/dim]")


if __name__ == "__main__":
    main()
