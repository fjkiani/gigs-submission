"""ExpansionTrack — typed verdicts for the 5 Part A tracks.

The brief asks: for each of 5 expansion tracks, give a ready / needs-work /
not-ready verdict and explain the non-obvious ones. This module is the typed
backbone for those verdicts.

It does two things:

1. **Models the world.** A ``Track`` carries the name, the population it
   covers, and the surface-class (consumer chat, partner widget, async
   email). A ``ReadinessGate`` is a single binary precondition with a name
   and an explanation. A ``TrackReport`` is the combination — a track plus
   the list of gates that must pass before it can ship.
2. **Computes verdicts deterministically.** ``TrackReport.verdict`` is
   ``READY`` if every gate passes, ``NEEDS_WORK`` if any non-blocking gate
   fails, ``NOT_READY`` if any blocking gate fails. The classification is
   pure — given the same gate state, you always get the same verdict.

What this is NOT:

- Not a config loader. The 5 (6 with devices split) actual reports for the
  brief are constructed in ``recommended_track_reports()`` below, in code,
  so the verdicts are reviewable in a single diff and the audit prose can
  link to them by name.
- Not a scheduling engine. Sequencing decisions live in ``q3_commit.py``.
- Not a lift estimator. That's ``lever_simulator.py``.

Cross-references to prior work:

- The "auth scoping" blocker on Track 3b (partner-facing devices/retail)
  and Track 4 (partner widget) is the same gap Task 1's audit identified
  on the legacy path: static Bearer API keys, no scopes, full project
  access. The fix lives in the Task 4 middleware design. Task 3 just
  refuses to ship those tracks before it exists.
- The "gold-set coverage" gate reuses Task 2's eval substrate semantically:
  a track without a gold set sized to its contact mix can't claim a
  deflection number, so it isn't ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReadinessVerdict(StrEnum):
    """The three legal verdicts in Part A of the brief."""

    READY = "READY"
    """Every blocking gate passes; track can ship under the normal ramp."""

    NEEDS_WORK = "NEEDS_WORK"
    """Some non-blocking gates fail; named build work unblocks the track."""

    NOT_READY = "NOT_READY"
    """A blocking gate fails (e.g. middleware doesn't exist yet)."""


class SurfaceClass(StrEnum):
    """Which conversational surface the track ships on.

    The surface drives a different set of gates: a partner-widget surface
    must clear an auth-scoping gate that consumer chat does not, an async
    email surface must clear an eval-set-shape gate consumer chat does not.
    """

    CONSUMER_CHAT = "consumer_chat"
    """In-app or web chat aimed at end-users. Same as the 2 live tenants."""

    PARTNER_WIDGET = "partner_widget"
    """Agent rendered inside a partner's own admin/dashboard UI."""

    ASYNC_EMAIL = "async_email"
    """Async / batched conversation surface (email or email-like)."""


@dataclass(frozen=True)
class Track:
    """One expansion track.

    `name` is the brief's own label. `population` is a human-readable
    description of who the track covers ("~18 smaller B2B devices/retail
    accounts", "remaining customers in same vertical"). `surface_class`
    drives the gate selection.
    """

    name: str
    population: str
    surface_class: SurfaceClass


@dataclass(frozen=True)
class ReadinessGate:
    """A single binary precondition for a track.

    `passed` is the only state that matters at verdict time. `blocking`
    distinguishes between "this MUST be true before launch" (e.g. middleware
    exists) and "this SHOULD be true before launch but we can ramp toward
    it" (e.g. gold-set sized to contact mix).

    `evidence` is a free-text pointer to the artifact / commit / dashboard
    that demonstrates the gate's state. We don't enforce a schema — the
    audit prose reads this directly.
    """

    name: str
    passed: bool
    blocking: bool
    evidence: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ReadinessGate.name must be non-empty")
        if not self.evidence:
            raise ValueError(
                f"ReadinessGate {self.name!r}: evidence must be non-empty — "
                "every gate state must point to an artifact"
            )


@dataclass(frozen=True)
class TrackReport:
    """A track plus the gates that must pass before it can ship.

    The verdict is computed from the gates; you don't set it directly.
    That way the verdict in the audit prose is reproducible from the
    code, and a reviewer can diff a single gate flip to see the verdict
    change.
    """

    track: Track
    gates: tuple[ReadinessGate, ...]
    summary: str = ""
    """One-line human-readable reason. Lands in the markdown table in §1."""

    def __post_init__(self) -> None:
        if not self.gates:
            raise ValueError(
                f"TrackReport {self.track.name!r}: must declare at least one gate"
            )
        # Gate names must be unique within a report so the prose can
        # cite them unambiguously.
        names = [g.name for g in self.gates]
        if len(names) != len(set(names)):
            raise ValueError(
                f"TrackReport {self.track.name!r}: duplicate gate names: {names}"
            )

    @property
    def verdict(self) -> ReadinessVerdict:
        """Compute the verdict from the gate states.

        Rules:
        - Any blocking gate failed → NOT_READY.
        - All gates passed → READY.
        - Otherwise (some non-blocking gate failed) → NEEDS_WORK.
        """
        if any(not g.passed and g.blocking for g in self.gates):
            return ReadinessVerdict.NOT_READY
        if all(g.passed for g in self.gates):
            return ReadinessVerdict.READY
        return ReadinessVerdict.NEEDS_WORK

    @property
    def failing_gates(self) -> tuple[ReadinessGate, ...]:
        """Gates that did not pass, in declaration order."""
        return tuple(g for g in self.gates if not g.passed)

    @property
    def blocking_failures(self) -> tuple[ReadinessGate, ...]:
        """Subset of failing gates that are blocking."""
        return tuple(g for g in self.failing_gates if g.blocking)


# ---------------------------------------------------------------------------
# The 5 (split to 6) actual track reports the audit prose argues.
# ---------------------------------------------------------------------------


def _gate(name: str, passed: bool, blocking: bool, evidence: str) -> ReadinessGate:
    """Tiny constructor — keeps the report bodies readable."""
    return ReadinessGate(name=name, passed=passed, blocking=blocking, evidence=evidence)


def track_1_same_vertical() -> TrackReport:
    """Track 1 — remaining customers in the same vertical as the 2 live ones.

    Verdict: READY. Same use cases, same KB lineage, same eval coverage.
    The work is ramp-gated rollout, not new design.
    """
    return TrackReport(
        track=Track(
            name="Same-vertical expansion",
            population="Remaining customers in same vertical as 2 live tenants",
            surface_class=SurfaceClass.CONSUMER_CHAT,
        ),
        gates=(
            _gate(
                "kb_coverage_matches_live",
                passed=True,
                blocking=True,
                evidence="Same template KB as live tenants; no new buckets",
            ),
            _gate(
                "gold_set_reusable",
                passed=True,
                blocking=True,
                evidence="Task 2 50-question gold set covers this contact mix",
            ),
            _gate(
                "escalation_triggers_reusable",
                passed=True,
                blocking=True,
                evidence="task2_cashcard/escalation_triggers.py applies as-is",
            ),
            _gate(
                "per_tenant_canary_in_ci",
                passed=True,
                blocking=False,
                evidence="task2_cashcard/week1_canaries.py supports per-tenant fixtures",
            ),
        ),
        summary="Same use cases, same KB lineage, same eval substrate. Ramp-gated rollout.",
    )


def track_2_local_fintech() -> TrackReport:
    """Track 2 — local/fintech customers.

    Verdict: NEEDS_WORK. KB content is thin per the brief; the financial
    sensitivity raises the refusal-quality bar. New gold-set coverage and
    a refused-correctly canary are required before launch.
    """
    return TrackReport(
        track=Track(
            name="Local/fintech expansion",
            population="Local / fintech customers (different use cases)",
            surface_class=SurfaceClass.CONSUMER_CHAT,
        ),
        gates=(
            _gate(
                "kb_coverage_local_fintech",
                passed=False,
                blocking=False,
                evidence="Brief: 'KB content is thin' for local/fintech",
            ),
            _gate(
                "gold_set_fintech_intents",
                passed=False,
                blocking=False,
                evidence="No fintech-specific intents in task2 gold set",
            ),
            _gate(
                "refused_quality_bar",
                passed=False,
                blocking=False,
                evidence="Financial sensitivity: refusals must be honest, not hedged",
            ),
            _gate(
                "auth_scoping_intact",
                passed=True,
                blocking=True,
                evidence="Surface is consumer chat — same auth model as live tenants",
            ),
        ),
        summary="KB thin + financial sensitivity. Author fintech KB chunks and gold-set intents first.",
    )


def track_3a_devices_user_facing() -> TrackReport:
    """Track 3a — devices/retail, user-facing surface.

    Verdict: NEEDS_WORK. New device-side KB content per cohort, but the
    surface itself is the same consumer-chat shape we already serve. The
    per-account context-variable wiring needs QA at onboarding time but
    isn't a structural blocker.
    """
    return TrackReport(
        track=Track(
            name="Devices/retail — user-facing",
            population="User-facing tickets across ~18 smaller B2B accounts",
            surface_class=SurfaceClass.CONSUMER_CHAT,
        ),
        gates=(
            _gate(
                "kb_coverage_device_content",
                passed=False,
                blocking=False,
                evidence="Per-account device support content not yet authored",
            ),
            _gate(
                "context_vars_qa_per_account",
                passed=False,
                blocking=False,
                evidence="Task 1 §1 already flagged inconsistent identifier passing across tenants",
            ),
            _gate(
                "gold_set_covers_devices",
                passed=False,
                blocking=False,
                evidence="No device-troubleshooting intents in task2 gold set",
            ),
            _gate(
                "auth_scoping_intact",
                passed=True,
                blocking=True,
                evidence="User-facing surface uses same per-end-user auth as live tenants",
            ),
        ),
        summary="Same surface as live; new content + onboarding QA per account.",
    )


def track_3b_devices_partner_facing() -> TrackReport:
    """Track 3b — devices/retail, partner-facing surface.

    Verdict: NOT_READY. The partner-facing surface is the same architectural
    problem as Track 4: a static Gigs Bearer key (full-project access, no
    scopes) gives a partner widget more than it should have. Task 4's
    middleware exists to solve this. Until it ships, partner-facing
    deflection cannot ship.
    """
    return TrackReport(
        track=Track(
            name="Devices/retail — partner-facing",
            population="Partner-facing tickets inside B2B accounts' admin tools",
            surface_class=SurfaceClass.PARTNER_WIDGET,
        ),
        gates=(
            _gate(
                "middleware_exists_with_scoped_auth",
                passed=False,
                blocking=True,
                evidence="Gigs API: static Bearer keys, no scopes (Task 4 middleware design)",
            ),
            _gate(
                "partner_dashboard_context_spec",
                passed=False,
                blocking=True,
                evidence="No spec for what the widget passes vs the embedding partner sees",
            ),
            _gate(
                "kb_coverage_partner_intents",
                passed=False,
                blocking=False,
                evidence="Partner intents (provisioning, batch tickets) absent from KB",
            ),
        ),
        summary="Shares Track 4's auth-scoping blocker. Cannot ship until middleware exists.",
    )


def track_4_partner_widget() -> TrackReport:
    """Track 4 — partner-led support widget inside partner's own dashboard.

    Verdict: NOT_READY. Same auth/scoping blocker as 3b. Plus a new
    conversation surface and a new context-variable contract. Multi-quarter
    work, not a Q3 deliverable.
    """
    return TrackReport(
        track=Track(
            name="Partner-led widget",
            population="Partner-embedded agent widget inside partner's admin UI",
            surface_class=SurfaceClass.PARTNER_WIDGET,
        ),
        gates=(
            _gate(
                "middleware_exists_with_scoped_auth",
                passed=False,
                blocking=True,
                evidence="Gigs API: static Bearer keys, no scopes (Task 4 middleware design)",
            ),
            _gate(
                "partner_data_boundary_policy",
                passed=False,
                blocking=True,
                evidence="No declared policy for what partner can see vs end-user",
            ),
            _gate(
                "embed_protocol_spec",
                passed=False,
                blocking=True,
                evidence="No defined iframe / postMessage / SSO contract",
            ),
            _gate(
                "kb_coverage_partner_intents",
                passed=False,
                blocking=False,
                evidence="Partner-side intents not authored",
            ),
        ),
        summary="Auth gap + new surface + new contract. Multi-quarter, not Q3.",
    )


def track_5_agentic_email() -> TrackReport:
    """Track 5 — agentic email channel.

    Verdict: NEEDS_WORK. The async pattern changes escalation timing
    semantics and the eval-set shape (one email = one turn, no follow-up
    in-session). The auth model is unchanged from chat (end-user
    authenticates against Gigs project). Doable with focused build.
    """
    return TrackReport(
        track=Track(
            name="Agentic email channel",
            population="Async email-based support across existing live tenants",
            surface_class=SurfaceClass.ASYNC_EMAIL,
        ),
        gates=(
            _gate(
                "auth_scoping_intact",
                passed=True,
                blocking=True,
                evidence="End-user auth via project key — same as chat",
            ),
            _gate(
                "async_eval_set_shape",
                passed=False,
                blocking=False,
                evidence="Gold set assumes multi-turn chat; email is single-turn",
            ),
            _gate(
                "async_escalation_sla",
                passed=False,
                blocking=False,
                evidence="Escalation timing not defined for async — no 2-minute hop",
            ),
            _gate(
                "email_threading_context",
                passed=False,
                blocking=False,
                evidence="Thread-history context-variable not in spec",
            ),
        ),
        summary="Async surface — new eval shape + new escalation timing. Focused build, not flip-of-switch.",
    )


def recommended_track_reports() -> tuple[TrackReport, ...]:
    """The 6 reports the audit prose argues, in brief order.

    Track 3 from the brief is split into 3a and 3b per the locked design
    decision (the brief's own "user-facing and partner-facing" split).
    """
    return (
        track_1_same_vertical(),
        track_2_local_fintech(),
        track_3a_devices_user_facing(),
        track_3b_devices_partner_facing(),
        track_4_partner_widget(),
        track_5_agentic_email(),
    )


# ---------------------------------------------------------------------------
# Aggregate helper — used by the audit prose's verdict table and demo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackReportSummary:
    """Compact per-track summary used in the markdown verdict table."""

    name: str
    verdict: ReadinessVerdict
    summary: str
    failing_gate_count: int
    blocking_failure_count: int


def summarise(report: TrackReport) -> TrackReportSummary:
    return TrackReportSummary(
        name=report.track.name,
        verdict=report.verdict,
        summary=report.summary,
        failing_gate_count=len(report.failing_gates),
        blocking_failure_count=len(report.blocking_failures),
    )


def render_verdict_table(reports: tuple[TrackReport, ...] = ()) -> str:
    """Render a markdown table of verdicts the audit prose embeds.

    Pure function — no I/O. Returns the table as a string. The audit prose
    pastes this output directly, so any verdict change in the report data
    flows through to the doc without manual editing.
    """
    items = reports or recommended_track_reports()
    lines = [
        "| Track | Verdict | Failing gates | Blocking? | Summary |",
        "|---|---|---|---|---|",
    ]
    for r in items:
        s = summarise(r)
        lines.append(
            f"| {s.name} | `{s.verdict.value}` | {s.failing_gate_count} | "
            f"{s.blocking_failure_count} | {s.summary} |"
        )
    return "\n".join(lines)


# Re-exports for the test module and the audit-doc rendering helper.
__all__ = [
    "ReadinessGate",
    "ReadinessVerdict",
    "SurfaceClass",
    "Track",
    "TrackReport",
    "TrackReportSummary",
    "recommended_track_reports",
    "render_verdict_table",
    "summarise",
    "track_1_same_vertical",
    "track_2_local_fintech",
    "track_3a_devices_user_facing",
    "track_3b_devices_partner_facing",
    "track_4_partner_widget",
    "track_5_agentic_email",
]
