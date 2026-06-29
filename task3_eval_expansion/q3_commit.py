"""Q3 commit — staged delivery with named gates instead of a single number.

The brief asks: "What do you commit to delivering this quarter? Defending
90% deflection." The locked design says: push back hard. This module is
the typed substrate for the pushback.

What we're doing instead of committing to a single 90% number:

1. **Three named milestones**, each independently shippable, each with
   an explicit gate (must-be-true precondition) and an explicit observable
   (how a board member knows it shipped). The first one is "live in
   week 2", the last one is "live by week 12".

2. **A measurement-discipline section** — every commit references which
   metric it's defended on (raw vs refusal-aware) so we can't quietly
   shift the denominator mid-quarter.

3. **An explicit non-commit** — three things we are NOT committing to
   this quarter (and why), so the pushback is constructive, not just
   "no".

The audit prose §3 reads from this module. Editing a milestone here flows
through to the doc without rewording.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommitTier(StrEnum):
    """Three tiers of Q3 commitment.

    The audit prose's §3 argues a staged commit — instead of one big
    number, three escalating tiers that the leadership team can choose
    to ship at:

    - DEFENDABLE — pure measurement + KB hygiene; ships week 2-4
    - PRODUCT — KB delta + grounding tightening; ships week 6-8
    - STRETCH — escalation triggers + eval-in-CI; ships week 10-12
    """

    DEFENDABLE = "defendable"
    PRODUCT = "product"
    STRETCH = "stretch"


class HeadlineMetric(StrEnum):
    """Which metric a commit is defended on.

    Pinning this in the typed object stops the temptation to silently
    quote the raw number in week 1 and the refusal-aware number in
    week 12.
    """

    RAW_DEFLECTION = "raw_deflection"
    REFUSAL_AWARE_DEFLECTION = "refusal_aware_deflection"


@dataclass(frozen=True)
class Milestone:
    """One staged milestone.

    `gate` is the precondition that must be true before the milestone is
    declared shipped. `observable` is what a board member can see to
    verify it shipped (a metric value, a dashboard, a config commit).
    `risk_if_skipped` is the cost of skipping this milestone and jumping
    to the next — used in the audit prose's §3.3 risk discussion.
    """

    tier: CommitTier
    name: str
    week_window: str
    """Human-readable target window, e.g. 'weeks 2-4'."""

    target_metric: HeadlineMetric
    target_value_pct: float
    """The projected metric value at this milestone."""

    gate: str
    """Precondition — what must be true for this to land."""

    observable: str
    """How a non-engineer can verify the milestone shipped."""

    primary_levers: tuple[str, ...]
    """Which L1-L5 levers drive this milestone."""

    risk_if_skipped: str
    """What you lose if you skip this and jump to the next tier."""

    def __post_init__(self) -> None:
        if not (0.0 <= self.target_value_pct <= 100.0):
            raise ValueError(
                f"target_value_pct {self.target_value_pct} out of [0, 100]"
            )
        if not self.primary_levers:
            raise ValueError(
                f"Milestone {self.name!r}: must declare at least one primary lever"
            )


@dataclass(frozen=True)
class NonCommit:
    """An explicit statement of what is NOT being shipped this quarter.

    The pushback is constructive: by naming what doesn't ship and why,
    leadership can choose to accept the scope or escalate the missing
    piece into a separate work-stream.
    """

    item: str
    reason: str
    """Why it doesn't ship this quarter."""

    earliest_reasonable_quarter: str
    """When it could plausibly ship, given current dependencies."""


@dataclass(frozen=True)
class Q3Commit:
    """The full Q3 commit document.

    `headline` is the one-sentence summary a board member can read in 30
    seconds. `milestones` are the 3 staged tiers. `measurement_discipline`
    is the metric-pinning policy. `non_commits` are the explicit
    exclusions.
    """

    headline: str
    milestones: tuple[Milestone, ...]
    measurement_discipline: str
    non_commits: tuple[NonCommit, ...]

    def __post_init__(self) -> None:
        # Enforce 3 tiers in canonical order.
        if len(self.milestones) != 3:
            raise ValueError(
                f"Q3Commit must declare exactly 3 milestones, got {len(self.milestones)}"
            )
        tiers = [m.tier for m in self.milestones]
        expected = [CommitTier.DEFENDABLE, CommitTier.PRODUCT, CommitTier.STRETCH]
        if tiers != expected:
            raise ValueError(
                f"Milestones must be in order {[t.value for t in expected]}, "
                f"got {[t.value for t in tiers]}"
            )
        # Target values must be monotonically non-decreasing across tiers.
        values = [m.target_value_pct for m in self.milestones]
        if values != sorted(values):
            raise ValueError(
                f"Milestone target values must be monotonically non-decreasing, "
                f"got {values}"
            )

    @property
    def defendable(self) -> Milestone:
        return self.milestones[0]

    @property
    def product(self) -> Milestone:
        return self.milestones[1]

    @property
    def stretch(self) -> Milestone:
        return self.milestones[2]


# ---------------------------------------------------------------------------
# The actual Q3 commit the audit prose §3 argues
# ---------------------------------------------------------------------------


def recommended_q3_commit() -> Q3Commit:
    """The Q3 commit document the audit prose §3 argues.

    Numbers reference the lever simulator's illustrated trajectory
    (80% → 86% after L1, → 92% after L2, → 94% after L3, → 96% after L4).
    The defendable tier hits week 4 with the metric switch alone; the
    product tier hits week 8 after the KB delta; the stretch tier hits
    week 12 with all 4 lift levers + L5 guardrail.

    The "90%" the brief asks about lands somewhere between PRODUCT (92%
    refusal-aware) and STRETCH (96%). The audit prose's pushback is:
    pin the staged commit, not the single number.
    """
    return Q3Commit(
        headline=(
            "Stage the Q3 commitment in 3 tiers — defendable (week 4), "
            "product (week 8), stretch (week 12) — each with explicit "
            "gate and observable, all defended on the refusal-aware "
            "metric."
        ),
        milestones=(
            Milestone(
                tier=CommitTier.DEFENDABLE,
                name="Measurement + KB hygiene live",
                week_window="weeks 2-4",
                target_metric=HeadlineMetric.REFUSAL_AWARE_DEFLECTION,
                target_value_pct=86.0,
                gate=(
                    "Refusal-aware metric wired into weekly tenant reports; "
                    "Task 2 50-question gold set runs in CI on every prompt PR; "
                    "no KB content changes required"
                ),
                observable=(
                    "Tenant weekly dashboard shows refusal-aware % alongside "
                    "raw %; both numbers move together when prompts change"
                ),
                primary_levers=("L1",),
                risk_if_skipped=(
                    "Without the metric switch every later % claim is mis-"
                    "measured. Skipping makes every later tier indefensible."
                ),
            ),
            Milestone(
                tier=CommitTier.PRODUCT,
                name="KB delta + grounding threshold tightened",
                week_window="weeks 5-8",
                target_metric=HeadlineMetric.REFUSAL_AWARE_DEFLECTION,
                target_value_pct=92.0,
                gate=(
                    "20-30 new KB chunks authored against top-3 Task 1 axes "
                    "(STALE_KB, WRONG_PROVIDER, STALE_USAGE) per tenant; "
                    "grounding threshold raised; canary suite green for 2 "
                    "consecutive weeks"
                ),
                observable=(
                    "Refusal-aware % crosses 90% on both live tenants; "
                    "Task 1 axis distribution shifts away from top-3 in "
                    "the failure trace"
                ),
                primary_levers=("L2", "L3"),
                risk_if_skipped=(
                    "Skipping the product tier means the stretch tier ships "
                    "without the substrate it depends on — escalation "
                    "triggers don't help if retrieval still misses."
                ),
            ),
            Milestone(
                tier=CommitTier.STRETCH,
                name="Escalation triggers + eval-in-CI sustained",
                week_window="weeks 9-12",
                target_metric=HeadlineMetric.REFUSAL_AWARE_DEFLECTION,
                target_value_pct=96.0,
                gate=(
                    "Per-tenant escalation triggers configured; eval-in-CI "
                    "enforces non-regression on every PR; 4 consecutive "
                    "weeks of no week-over-week regression on either tenant"
                ),
                observable=(
                    "Refusal-aware ≥ 95% on both tenants for 4 weeks; "
                    "no PR reverts due to eval regression; "
                    "wrong_answer_false_positive incidents ≤ 1 per tenant "
                    "per month"
                ),
                primary_levers=("L4", "L5"),
                risk_if_skipped=(
                    "Skipping stretch keeps refusal-aware at ~92%, which is "
                    "still defensible but loses the durability guardrail."
                ),
            ),
        ),
        measurement_discipline=(
            "All three milestones are defended on refusal-aware deflection. "
            "Raw deflection is reported alongside for transparency but is "
            "NOT the headline number. The two metrics agree on the live "
            "Task 2 gold set when correct refusals are 0 — by week 4 they "
            "are computed identically because the metric definition is the "
            "same; the difference is what counts as a success. Locking "
            "this here prevents the late-quarter temptation to switch "
            "denominators."
        ),
        non_commits=(
            NonCommit(
                item="Partner-led widget (Track 4) and partner-facing "
                "devices (Track 3b)",
                reason=(
                    "Both share the auth-scoping blocker: Gigs API uses "
                    "static Bearer keys with no scopes (Task 1 finding, "
                    "Task 4 middleware design). Shipping either before the "
                    "middleware exists ships a security hole."
                ),
                earliest_reasonable_quarter=(
                    "Q4 at earliest — middleware design is Task 4, then "
                    "implementation + threat model + per-tenant scope "
                    "configuration."
                ),
            ),
            NonCommit(
                item="Agentic email channel (Track 5)",
                reason=(
                    "Async surface is a different eval-set shape (single-"
                    "turn vs multi-turn) and a different escalation timing "
                    "(no 2-minute hop). Q3 doesn't have the build capacity "
                    "alongside the Track 1 + 2 + 3a expansion."
                ),
                earliest_reasonable_quarter=(
                    "Q4 — async eval substrate can be developed in parallel "
                    "with Q3 product work and ship in Q4."
                ),
            ),
            NonCommit(
                item="A single committed 90% number",
                reason=(
                    "The brief asks for it but the right answer is the "
                    "staged commit above. A single 90% would have to choose "
                    "raw or refusal-aware (the same agent is at 80% raw and "
                    "100% refusal-aware on the Task 2 gold set today) and "
                    "would silently absorb whichever buckets the metric "
                    "chosen happens to favour."
                ),
                earliest_reasonable_quarter=(
                    "Never as headline — always as a per-milestone, per-"
                    "metric number with a gate beside it."
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_commit_table(commit: Q3Commit) -> str:
    """Render the commit as a markdown table the audit prose embeds.

    Includes the 3 milestones + the measurement discipline + non-commits.
    """
    lines = [
        "### Headline",
        "",
        f"> {commit.headline}",
        "",
        "### Staged milestones",
        "",
        "| Tier | Week | Target | Metric | Levers | Gate |",
        "|---|---|---:|---|---|---|",
    ]
    for m in commit.milestones:
        lines.append(
            f"| `{m.tier.value}` | {m.week_window} | "
            f"{m.target_value_pct:.0f}% | "
            f"{m.target_metric.value} | "
            f"{', '.join(m.primary_levers)} | {m.gate} |"
        )
    lines.extend(
        [
            "",
            "### Measurement discipline",
            "",
            commit.measurement_discipline,
            "",
            "### Explicit non-commits (Q3)",
            "",
        ]
    )
    for nc in commit.non_commits:
        lines.append(
            f"- **{nc.item}** — {nc.reason} _Earliest: {nc.earliest_reasonable_quarter}_"
        )
    return "\n".join(lines)


__all__ = [
    "CommitTier",
    "HeadlineMetric",
    "Milestone",
    "NonCommit",
    "Q3Commit",
    "recommended_q3_commit",
    "render_commit_table",
]
