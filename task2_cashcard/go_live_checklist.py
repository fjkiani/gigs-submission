"""Executable go-live readiness checker for a CashCard-style tenant.

The audit doc's §3 ("Go-live readiness criteria") is *operational*, not
just narrative — every claim it makes needs a deterministic gate that can
sit in CI and block a launch.

This module is that gate.

Six gates, in priority order
----------------------------
1. **KB coverage** — every weighted bucket has ≥ N chunks AND every bucket
   we route to AGENT has at least one chunk whose ``covers_providers`` is
   non-empty (so we know we actually have provider-specific copy where
   it matters).
2. **Eval pass-rate** — gold-set file exists, has ≥50 questions, the
   shipped oracle clears refusal-aware deflection ≥ 0.75 (brief's bar)
   with zero ungrounded answers.
3. **Escalation context wired** — config declares the minimum required
   context variables (subscription_id, sim_id, user_id) AND
   ``EscalationContext`` is importable from task1_audit.
4. **Freshness watcher subscribed** — ``SVIX_SHARED_SECRET`` is set in
   secrets dict AND configured event types ⊇ the 10 in
   ``KB_INVALIDATING_EVENT_TYPES``.
5. **PII-write guardrails** — ``config.guardrails.read_only_writes`` is
   True AND ``refuse_pii_writes`` is True. Day 1 is read-only; the
   60/90-day write-action ramp flips these explicitly.
6. **Two-hop escalation declared** — ``config.two_hop`` has both
   tier1_target and tier2_target with parseable email-style addresses.

NOT_READY explicitly enumerates every failing gate. No silent pass:
the report carries a tuple of GateResult so the caller sees every
gate's verdict and reason.

Design notes
------------
- All functions are pure; we pass paths/dicts in, get a frozen
  ``ReadinessReport`` out.
- Gates short-circuit *within themselves* (e.g. KB coverage stops at
  the first failing bucket) but the **report** always runs every gate.
  Reviewers see the full picture, not just the first blocker.
- The Eval gate runs the shipped oracle on the shipped gold set in
  ``run_eval``. That is the deterministic "would a friendly agent pass
  the bar?" check — it does NOT prove a real LLM agent passes; that's
  what the gold set is for at deploy time.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from task1_audit.kb_freshness_watcher import KB_INVALIDATING_EVENT_TYPES
from task2_cashcard.cashcard_config import (
    InstanceConfig,
    IntentHandler,
)
from task2_cashcard.eval.eval_runner import run_eval
from task2_cashcard.kb_gap_analyzer import (
    DEFAULT_MIN_CHUNKS_PER_BUCKET,
    ChunkMetadata,
    analyse_coverage,
    load_chunks,
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class GateName(StrEnum):
    """The six gates, in the order they run."""

    KB_COVERAGE = "kb_coverage"
    EVAL_PASS_RATE = "eval_pass_rate"
    ESCALATION_CONTEXT = "escalation_context"
    FRESHNESS_WATCHER = "freshness_watcher"
    PII_WRITE_GUARDRAILS = "pii_write_guardrails"
    TWO_HOP_ESCALATION = "two_hop_escalation"


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's verdict. ``passed=False`` carries a human-readable reason."""

    name: GateName
    passed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Aggregate output of ``assess_readiness``."""

    verdict: str  # "READY" | "NOT_READY"
    gates: tuple[GateResult, ...]

    @property
    def is_ready(self) -> bool:
        return self.verdict == "READY"

    @property
    def failing_gates(self) -> tuple[GateResult, ...]:
        return tuple(g for g in self.gates if not g.passed)


# Day-1 thresholds — pulled into module-level constants so they're easy
# to find and tune. The plan said ≥75% refusal-aware deflection; we also
# refuse to ship if any answer was ungrounded.
MIN_GOLD_SET_QUESTIONS = 50
MIN_REFUSAL_AWARE_DEFLECTION = 0.75
MAX_UNGROUNDED_ANSWERS = 0

# Required context variables to populate a useful EscalationContext.
# (Matches `InstanceConfig._required_vars_present`.)
REQUIRED_CONTEXT_VARS = frozenset({"subscription_id", "sim_id", "user_id"})

# Email-shape regex for two-hop targets. Deliberately permissive — we
# only care that there's a local part, an @, and a non-empty domain
# with a dot. Real SMTP validation belongs at deploy time.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Gate implementations
# ---------------------------------------------------------------------------


def _check_kb_coverage(
    *,
    config: InstanceConfig,
    kb_root: Path,
    min_chunks_per_bucket: int = DEFAULT_MIN_CHUNKS_PER_BUCKET,
) -> GateResult:
    """Gate 1: every weighted bucket has ≥N chunks AND every AGENT-routed
    bucket has at least one chunk with non-empty ``covers_providers``.
    """
    if not kb_root.exists():
        return GateResult(
            name=GateName.KB_COVERAGE,
            passed=False,
            reason=f"kb_root does not exist: {kb_root}",
        )

    try:
        chunks = load_chunks(kb_root)
    except (OSError, ValueError) as exc:
        return GateResult(
            name=GateName.KB_COVERAGE,
            passed=False,
            reason=f"failed to load chunks: {exc}",
        )

    if not chunks:
        return GateResult(
            name=GateName.KB_COVERAGE,
            passed=False,
            reason=f"no chunks found under {kb_root}",
        )

    coverage = analyse_coverage(
        kb_root,
        contact_mix_prior=config.contact_mix_prior,
        min_chunks_per_bucket=min_chunks_per_bucket,
    )

    # Sub-check 1a: any bucket with weight > 0 and chunk count below floor.
    underfilled = [
        b
        for b in coverage.buckets
        if config.contact_mix_prior.get(b.bucket, 0) > 0
        and b.chunk_count < min_chunks_per_bucket
    ]
    if underfilled:
        names = ", ".join(
            f"{b.bucket}({b.chunk_count}/{min_chunks_per_bucket})"
            for b in underfilled
        )
        return GateResult(
            name=GateName.KB_COVERAGE,
            passed=False,
            reason=f"underfilled buckets: {names}",
        )

    if coverage.unknown_buckets:
        return GateResult(
            name=GateName.KB_COVERAGE,
            passed=False,
            reason=(
                f"chunks in unknown buckets (not in contact_mix_prior): "
                f"{list(coverage.unknown_buckets)}"
            ),
        )

    # Sub-check 1b: every AGENT-routed bucket must have at least one chunk
    # whose covers_providers is non-empty. Buckets routed straight to a
    # human (e.g. "other") are exempt.
    agent_buckets = {
        r.bucket
        for r in config.routing_rules
        if r.handler == IntentHandler.AGENT and r.bucket is not None
    }
    chunks_by_bucket: dict[str, list[ChunkMetadata]] = {}
    for c in chunks:
        chunks_by_bucket.setdefault(c.topic, []).append(c)

    missing_provider_chunks: list[str] = []
    for bucket in sorted(agent_buckets):
        bucket_chunks = chunks_by_bucket.get(bucket, [])
        if not any(c.covers_providers for c in bucket_chunks):
            missing_provider_chunks.append(bucket)
    if missing_provider_chunks:
        return GateResult(
            name=GateName.KB_COVERAGE,
            passed=False,
            reason=(
                f"AGENT-routed buckets without provider-specific chunks: "
                f"{missing_provider_chunks}"
            ),
        )

    return GateResult(
        name=GateName.KB_COVERAGE,
        passed=True,
        reason=(
            f"{len(chunks)} chunks across {len(coverage.buckets)} buckets; "
            f"all weighted buckets ≥ {min_chunks_per_bucket}; "
            f"AGENT-routed buckets have provider coverage"
        ),
    )


def _check_eval_pass_rate(*, gold_set_path: Path, kb_root: Path) -> GateResult:
    """Gate 2: gold set exists, ≥50 questions, refusal-aware ≥ 0.75,
    zero ungrounded answers.
    """
    if not gold_set_path.exists():
        return GateResult(
            name=GateName.EVAL_PASS_RATE,
            passed=False,
            reason=f"gold_set not found: {gold_set_path}",
        )

    try:
        scorecard = run_eval(gold_set_path, kb_root=kb_root)
    except (OSError, ValueError, KeyError) as exc:
        return GateResult(
            name=GateName.EVAL_PASS_RATE,
            passed=False,
            reason=f"eval run failed: {exc}",
        )

    failures: list[str] = []
    if scorecard.total < MIN_GOLD_SET_QUESTIONS:
        failures.append(
            f"only {scorecard.total} questions (need ≥{MIN_GOLD_SET_QUESTIONS})"
        )
    if scorecard.refusal_aware_deflection < MIN_REFUSAL_AWARE_DEFLECTION:
        failures.append(
            f"refusal-aware {scorecard.refusal_aware_deflection:.1%} "
            f"(need ≥{MIN_REFUSAL_AWARE_DEFLECTION:.0%})"
        )
    if scorecard.ungrounded_count > MAX_UNGROUNDED_ANSWERS:
        failures.append(
            f"{scorecard.ungrounded_count} ungrounded answers "
            f"(need ≤{MAX_UNGROUNDED_ANSWERS})"
        )

    if failures:
        return GateResult(
            name=GateName.EVAL_PASS_RATE,
            passed=False,
            reason="; ".join(failures),
        )

    return GateResult(
        name=GateName.EVAL_PASS_RATE,
        passed=True,
        reason=(
            f"{scorecard.total} questions, "
            f"raw_deflection {scorecard.raw_deflection:.1%}, "
            f"refusal_aware {scorecard.refusal_aware_deflection:.1%}, "
            f"{scorecard.ungrounded_count} ungrounded"
        ),
    )


def _check_escalation_context(*, config: InstanceConfig) -> GateResult:
    """Gate 3: required context vars declared AND task1 EscalationContext
    importable.
    """
    declared_required = {v.name for v in config.context_variables if v.required}
    missing = REQUIRED_CONTEXT_VARS - declared_required
    if missing:
        return GateResult(
            name=GateName.ESCALATION_CONTEXT,
            passed=False,
            reason=f"required context vars missing: {sorted(missing)}",
        )

    # Lazy import check — confirms task1_audit is still where we think it is.
    try:
        from task1_audit import EscalationContext  # noqa: F401
    except ImportError as exc:
        return GateResult(
            name=GateName.ESCALATION_CONTEXT,
            passed=False,
            reason=f"task1_audit.EscalationContext not importable: {exc}",
        )

    return GateResult(
        name=GateName.ESCALATION_CONTEXT,
        passed=True,
        reason=(
            f"required context vars ({sorted(REQUIRED_CONTEXT_VARS)}) declared; "
            f"task1_audit.EscalationContext importable"
        ),
    )


def _check_freshness_watcher(
    *,
    secrets: dict[str, str | bool],
    subscribed_event_types: Iterable[str],
) -> GateResult:
    """Gate 4: webhook shared secret present AND subscribed events ⊇
    invalidating events.
    """
    secret = secrets.get("SVIX_SHARED_SECRET")
    if not secret:
        return GateResult(
            name=GateName.FRESHNESS_WATCHER,
            passed=False,
            reason="SVIX_SHARED_SECRET not set in secrets",
        )

    subscribed = frozenset(subscribed_event_types)
    missing = KB_INVALIDATING_EVENT_TYPES - subscribed
    if missing:
        return GateResult(
            name=GateName.FRESHNESS_WATCHER,
            passed=False,
            reason=(
                f"freshness subscription missing {len(missing)} event types: "
                f"{sorted(missing)}"
            ),
        )

    return GateResult(
        name=GateName.FRESHNESS_WATCHER,
        passed=True,
        reason=(
            f"SVIX_SHARED_SECRET set; subscribed to all "
            f"{len(KB_INVALIDATING_EVENT_TYPES)} invalidating event types"
        ),
    )


def _check_pii_write_guardrails(*, config: InstanceConfig) -> GateResult:
    """Gate 5: read_only_writes AND refuse_pii_writes both True."""
    failures: list[str] = []
    if not config.guardrails.read_only_writes:
        failures.append("read_only_writes is False (day-1 must be read-only)")
    if not config.guardrails.refuse_pii_writes:
        failures.append("refuse_pii_writes is False")

    if failures:
        return GateResult(
            name=GateName.PII_WRITE_GUARDRAILS,
            passed=False,
            reason="; ".join(failures),
        )

    return GateResult(
        name=GateName.PII_WRITE_GUARDRAILS,
        passed=True,
        reason="read_only_writes=True and refuse_pii_writes=True",
    )


def _check_two_hop_escalation(*, config: InstanceConfig) -> GateResult:
    """Gate 6: both tier1 and tier2 targets present and look like emails."""
    th = config.two_hop
    failures: list[str] = []

    if not th.tier1_target:
        failures.append("tier1_target empty")
    elif not _EMAIL_RE.match(th.tier1_target):
        failures.append(f"tier1_target {th.tier1_target!r} not an email")

    if not th.tier2_target:
        failures.append("tier2_target empty")
    elif not _EMAIL_RE.match(th.tier2_target):
        failures.append(f"tier2_target {th.tier2_target!r} not an email")

    if th.tier1_target == th.tier2_target and th.tier1_target:
        failures.append("tier1_target and tier2_target must differ")

    if failures:
        return GateResult(
            name=GateName.TWO_HOP_ESCALATION,
            passed=False,
            reason="; ".join(failures),
        )

    return GateResult(
        name=GateName.TWO_HOP_ESCALATION,
        passed=True,
        reason=f"two-hop wired: {th.tier1_target!r} → {th.tier2_target!r}",
    )


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def assess_readiness(
    *,
    config: InstanceConfig,
    kb_root: Path,
    gold_set_path: Path,
    secrets: dict[str, str | bool],
    subscribed_event_types: Iterable[str],
    min_chunks_per_bucket: int = DEFAULT_MIN_CHUNKS_PER_BUCKET,
) -> ReadinessReport:
    """Run all six gates and aggregate into a single readiness report.

    Every gate runs regardless of earlier gate failures — the report
    shows the full picture so the reviewer sees every blocker at once.

    Args:
        config: validated CashCard instance config.
        kb_root: directory containing the bucketed kb_skeleton/.
        gold_set_path: path to the 50-question gold set YAML.
        secrets: deployment secrets dict (presence-only check; we never
            print values).
        subscribed_event_types: event types the freshness watcher is
            actually subscribed to in production.
        min_chunks_per_bucket: KB-coverage floor; default
            ``DEFAULT_MIN_CHUNKS_PER_BUCKET``.

    Returns:
        ``ReadinessReport`` with overall verdict and one ``GateResult``
        per gate, in fixed order.
    """
    gates: tuple[GateResult, ...] = (
        _check_kb_coverage(
            config=config,
            kb_root=kb_root,
            min_chunks_per_bucket=min_chunks_per_bucket,
        ),
        _check_eval_pass_rate(
            gold_set_path=gold_set_path,
            kb_root=kb_root,
        ),
        _check_escalation_context(config=config),
        _check_freshness_watcher(
            secrets=secrets,
            subscribed_event_types=subscribed_event_types,
        ),
        _check_pii_write_guardrails(config=config),
        _check_two_hop_escalation(config=config),
    )
    verdict = "READY" if all(g.passed for g in gates) else "NOT_READY"
    return ReadinessReport(verdict=verdict, gates=gates)


def render_readiness(report: ReadinessReport) -> str:
    """Format a ``ReadinessReport`` as a short ops-friendly text block."""
    lines: list[str] = []
    lines.append(f"Verdict: {report.verdict}")
    lines.append("")
    for g in report.gates:
        marker = "PASS" if g.passed else "FAIL"
        lines.append(f"  [{marker}] {g.name.value}: {g.reason}")
    if not report.is_ready:
        lines.append("")
        lines.append("Blocking gates:")
        for g in report.failing_gates:
            lines.append(f"  - {g.name.value}: {g.reason}")
    return "\n".join(lines)


__all__ = [
    "MAX_UNGROUNDED_ANSWERS",
    "MIN_GOLD_SET_QUESTIONS",
    "MIN_REFUSAL_AWARE_DEFLECTION",
    "REQUIRED_CONTEXT_VARS",
    "GateName",
    "GateResult",
    "ReadinessReport",
    "assess_readiness",
    "render_readiness",
]
