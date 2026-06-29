"""Task 2 demo — CashCard launch readiness in one screen.

Run via ``python -m task2_cashcard.demo`` (or ``make demo-task2``).

Three blocks, deterministic, no network, no LLM:

    1. Readiness report — six gates, READY/NOT_READY, per gate reason.
    2. Eval scorecard   — 50-question gold set, raw vs refusal-aware
                          deflection side-by-side.
    3. KB coverage      — per-bucket chunk count vs floor, priority ordering.

The point of the demo is to show a reviewer in 5 seconds that:

- The launch gate is binary (not slideware).
- The deflection number is honest (both metrics on screen).
- The KB coverage is at or above floor in every weighted bucket.

If any of the three blocks shows a regression, the demo stays the same —
the *numbers* in the table change, and that's the visible signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from task1_audit.kb_freshness_watcher import KB_INVALIDATING_EVENT_TYPES
from task2_cashcard.eval.eval_runner import run_eval
from task2_cashcard.go_live_checklist import (
    ReadinessReport,
    assess_readiness,
    render_readiness,
)
from task2_cashcard.kb_gap_analyzer import analyse_coverage
from task2_cashcard.tests.fixtures import make_config

# Paths anchored relative to this module so `python -m task2_cashcard.demo`
# works from any CWD.
_HERE = Path(__file__).parent
_KB_ROOT = _HERE / "kb_skeleton"
_GOLD_SET = _HERE / "eval" / "gold_set.yaml"


def _render_readiness_table(report: ReadinessReport) -> Table:
    """Six-gate readiness as a Rich table."""
    t = Table(
        title=f"§3 Go-live readiness — {report.verdict}",
        show_lines=False,
        title_justify="left",
    )
    t.add_column("Gate", style="bold")
    t.add_column("Verdict", style="bold")
    t.add_column("Reason")
    for g in report.gates:
        marker = "[green]PASS[/green]" if g.passed else "[red]FAIL[/red]"
        t.add_row(g.name.value, marker, g.reason)
    return t


@dataclass(frozen=True, slots=True)
class _ScorecardBlock:
    """Render output of the eval scorecard: a headline plus a Rich table."""

    headline: str
    table: Table


def _render_scorecard_block(
    gold_set_path: Path, kb_root: Path
) -> _ScorecardBlock:
    """Eval scorecard — both deflection metrics side-by-side."""
    scorecard = run_eval(gold_set_path, kb_root=kb_root)
    t = Table(
        title="§6 Eval scorecard — deflection metrics (oracle answer-fn)",
        show_lines=False,
        title_justify="left",
    )
    t.add_column("Bucket", style="bold")
    t.add_column("Total", justify="right")
    t.add_column("Grounded", justify="right", style="green")
    t.add_column("Ungrnd", justify="right", style="red")
    t.add_column("Refused", justify="right")
    for b in scorecard.bucket_scores:
        t.add_row(
            b.bucket,
            str(b.total),
            str(b.answered_grounded),
            str(b.answered_ungrounded),
            str(b.refused),
        )
    t.add_section()
    t.add_row(
        "TOTAL",
        str(scorecard.total),
        str(scorecard.grounded_count),
        str(scorecard.ungrounded_count),
        str(scorecard.refused_count),
        style="bold",
    )

    headline = (
        f"raw_deflection         {scorecard.raw_deflection:6.1%}\n"
        f"refusal_aware_deflect. {scorecard.refusal_aware_deflection:6.1%} "
        f"(target ≥ 75%)\n"
        f"pass / fail            {scorecard.pass_count}/{scorecard.fail_count}"
    )
    return _ScorecardBlock(headline=headline, table=t)


def _render_kb_coverage_table(kb_root: Path, contact_mix: dict[str, float]) -> Table:
    """Per-bucket chunk count vs floor, with priority ordering."""
    report = analyse_coverage(kb_root, contact_mix_prior=contact_mix)
    t = Table(
        title=(
            f"§1 KB coverage — {report.total_chunks} chunks, "
            f"min {report.min_chunks_per_bucket} per bucket"
        ),
        show_lines=False,
        title_justify="left",
    )
    t.add_column("Bucket", style="bold")
    t.add_column("Weight", justify="right")
    t.add_column("Chunks", justify="right")
    t.add_column("Floor", justify="right")
    t.add_column("Priority", justify="right")
    t.add_column("OK?", justify="center")
    for b in report.buckets:
        ok = (
            "[green]OK[/green]"
            if b.chunk_count >= b.min_chunks
            else "[red]LOW[/red]"
        )
        t.add_row(
            b.bucket,
            f"{b.weight:.0%}",
            str(b.chunk_count),
            str(b.min_chunks),
            f"{b.priority:.2f}",
            ok,
        )
    if report.unknown_buckets:
        t.caption = (
            f"WARN: unknown buckets (not in contact_mix): "
            f"{list(report.unknown_buckets)}"
        )
    return t


def _build_intro_panel() -> Panel:
    body = (
        "[bold]Task 2 demo — CashCard launch readiness[/bold]\n"
        "[dim]Three deterministic blocks, no network, no LLM.[/dim]\n"
        "\n"
        "1. §3 — Six-gate readiness checker (READY / NOT_READY).\n"
        "2. §6 — Eval scorecard with both deflection metrics.\n"
        "3. §1 — Per-bucket KB coverage vs floor.\n"
        "\n"
        "All three numbers are reproducible: see "
        "[bold]02_TASK2_CASHCARD.md[/bold] for the prose."
    )
    return Panel(body, expand=False, border_style="cyan")


def main() -> None:
    console = Console()
    console.print(_build_intro_panel())

    # ----- Block 1: readiness -----
    cfg = make_config()
    report = assess_readiness(
        config=cfg,
        kb_root=_KB_ROOT,
        gold_set_path=_GOLD_SET,
        secrets={"SVIX_SHARED_SECRET": "whsec_demo"},
        subscribed_event_types=KB_INVALIDATING_EVENT_TYPES,
    )
    console.print()
    console.print(_render_readiness_table(report))

    # ----- Block 2: eval scorecard -----
    sc = _render_scorecard_block(_GOLD_SET, _KB_ROOT)
    console.print()
    console.print(sc.headline)
    console.print(sc.table)

    # ----- Block 3: KB coverage -----
    console.print()
    console.print(_render_kb_coverage_table(_KB_ROOT, cfg.contact_mix_prior))

    # Plain-text fallback so a reviewer running without rich still sees
    # the verdict.
    console.print()
    console.print(
        "[dim]"
        + render_readiness(report).splitlines()[0]
        + "[/dim]"
    )


if __name__ == "__main__":
    main()
