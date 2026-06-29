"""Tests for go_live_checklist — six readiness gates.

Per the plan: every gate has both a happy path AND a failure path.
NOT_READY enumerates every failing gate, not just the first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from task1_audit.kb_freshness_watcher import KB_INVALIDATING_EVENT_TYPES
from task2_cashcard.cashcard_config import (
    ContextVarSpec,
    Guardrails,
    InstanceConfig,
    TwoHopEscalation,
)
from task2_cashcard.go_live_checklist import (
    MAX_UNGROUNDED_ANSWERS,
    MIN_GOLD_SET_QUESTIONS,
    MIN_REFUSAL_AWARE_DEFLECTION,
    REQUIRED_CONTEXT_VARS,
    GateName,
    GateResult,
    ReadinessReport,
    assess_readiness,
    render_readiness,
)
from task2_cashcard.tests.fixtures import AT, make_config

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_KB_ROOT = Path(__file__).parent.parent / "kb_skeleton"
_GOLD = Path(__file__).parent.parent / "eval" / "gold_set.yaml"


def _good_secrets() -> dict[str, str | bool]:
    return {"SVIX_SHARED_SECRET": "whsec_test_value"}


def _good_events() -> frozenset[str]:
    return KB_INVALIDATING_EVENT_TYPES


def _run(
    *,
    config: InstanceConfig | None = None,
    kb_root: Path | None = None,
    gold_set_path: Path | None = None,
    secrets: dict[str, str | bool] | None = None,
    subscribed_event_types: Any = None,
) -> ReadinessReport:
    return assess_readiness(
        config=config or make_config(),
        kb_root=kb_root or _KB_ROOT,
        gold_set_path=gold_set_path or _GOLD,
        secrets=secrets if secrets is not None else _good_secrets(),
        subscribed_event_types=(
            subscribed_event_types
            if subscribed_event_types is not None
            else _good_events()
        ),
    )


def _gate(report: ReadinessReport, name: GateName) -> GateResult:
    matches = [g for g in report.gates if g.name == name]
    assert len(matches) == 1, f"expected exactly one {name} gate"
    return matches[0]


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


class TestReadinessHappyPath:
    def test_all_gates_pass(self) -> None:
        report = _run()
        assert report.verdict == "READY"
        assert report.is_ready is True
        assert all(g.passed for g in report.gates)
        assert report.failing_gates == ()

    def test_all_six_gates_present_in_order(self) -> None:
        report = _run()
        names = [g.name for g in report.gates]
        assert names == [
            GateName.KB_COVERAGE,
            GateName.EVAL_PASS_RATE,
            GateName.ESCALATION_CONTEXT,
            GateName.FRESHNESS_WATCHER,
            GateName.PII_WRITE_GUARDRAILS,
            GateName.TWO_HOP_ESCALATION,
        ]

    def test_report_is_frozen(self) -> None:
        import dataclasses

        report = _run()
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.verdict = "NOT_READY"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.gates[0].passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Gate 1: KB coverage
# ---------------------------------------------------------------------------


class TestKbCoverageGate:
    def test_pass_with_shipped_kb(self) -> None:
        report = _run()
        g = _gate(report, GateName.KB_COVERAGE)
        assert g.passed, g.reason
        assert "21 chunks" in g.reason

    def test_fails_when_kb_root_missing(self, tmp_path: Path) -> None:
        report = _run(kb_root=tmp_path / "does_not_exist")
        g = _gate(report, GateName.KB_COVERAGE)
        assert not g.passed
        assert "does not exist" in g.reason

    def test_fails_when_kb_empty(self, tmp_path: Path) -> None:
        report = _run(kb_root=tmp_path)
        g = _gate(report, GateName.KB_COVERAGE)
        assert not g.passed
        assert "no chunks" in g.reason

    def test_fails_when_bucket_underfilled(self, tmp_path: Path) -> None:
        # Build a minimal KB with one chunk in esim_activation -> 1 < 3
        bucket = tmp_path / "01_esim_activation"
        bucket.mkdir()
        chunk = bucket / "only.md"
        chunk.write_text(
            "---\n"
            "chunk_id: esim.only\n"
            "topic: esim_activation\n"
            "covers_providers: [p3]\n"
            "---\n"
            "Body.\n"
        )
        report = _run(kb_root=tmp_path)
        g = _gate(report, GateName.KB_COVERAGE)
        assert not g.passed
        assert "underfilled" in g.reason
        assert "esim_activation" in g.reason

    def test_fails_when_agent_bucket_lacks_provider_coverage(
        self, tmp_path: Path
    ) -> None:
        # 3 chunks in esim_activation but NONE with covers_providers
        bucket = tmp_path / "01_esim_activation"
        bucket.mkdir()
        for i in range(3):
            (bucket / f"c{i}.md").write_text(
                f"---\n"
                f"chunk_id: esim.c{i}\n"
                f"topic: esim_activation\n"
                f"covers_providers: []\n"
                f"---\n"
                f"Body {i}.\n"
            )
        # Also fill other weighted buckets with one bucket each (3 chunks)
        for topic in (
            "plan_questions",
            "devices",
            "roaming",
            "port_in",
            "other",
        ):
            sub = tmp_path / topic
            sub.mkdir()
            for i in range(3):
                (sub / f"x{i}.md").write_text(
                    f"---\n"
                    f"chunk_id: {topic}.x{i}\n"
                    f"topic: {topic}\n"
                    f"covers_providers: [p3]\n"
                    f"---\n"
                    f"Body.\n"
                )
        report = _run(kb_root=tmp_path)
        g = _gate(report, GateName.KB_COVERAGE)
        assert not g.passed
        assert "esim_activation" in g.reason
        assert "provider" in g.reason

    def test_fails_when_chunk_in_unknown_bucket(self, tmp_path: Path) -> None:
        # First fill the 6 known buckets so the underfilled check passes
        for topic in (
            "esim_activation",
            "plan_questions",
            "devices",
            "roaming",
            "port_in",
            "other",
        ):
            sub = tmp_path / topic
            sub.mkdir()
            for i in range(3):
                (sub / f"x{i}.md").write_text(
                    f"---\n"
                    f"chunk_id: {topic}.x{i}\n"
                    f"topic: {topic}\n"
                    f"covers_providers: [p3]\n"
                    f"---\n"
                    f"Body.\n"
                )
        # And add a chunk in an unknown topic
        rogue = tmp_path / "rogue"
        rogue.mkdir()
        (rogue / "extra.md").write_text(
            "---\n"
            "chunk_id: rogue.x\n"
            "topic: not_a_real_bucket\n"
            "---\n"
            "Body.\n"
        )
        report = _run(kb_root=tmp_path)
        g = _gate(report, GateName.KB_COVERAGE)
        assert not g.passed
        assert "unknown buckets" in g.reason


# ---------------------------------------------------------------------------
# Gate 2: Eval pass-rate
# ---------------------------------------------------------------------------


class TestEvalPassRateGate:
    def test_pass_with_shipped_gold_set(self) -> None:
        report = _run()
        g = _gate(report, GateName.EVAL_PASS_RATE)
        assert g.passed, g.reason
        assert "refusal_aware" in g.reason

    def test_fails_when_gold_set_missing(self, tmp_path: Path) -> None:
        report = _run(gold_set_path=tmp_path / "missing.yaml")
        g = _gate(report, GateName.EVAL_PASS_RATE)
        assert not g.passed
        assert "not found" in g.reason

    def test_fails_when_gold_set_too_small(self, tmp_path: Path) -> None:
        # Build a tiny gold set with <50 questions
        small = tmp_path / "small.yaml"
        rows = []
        for i in range(5):
            rows.append(
                f"  - id: q{i}\n"
                f"    bucket: esim_activation\n"
                f'    question: "tiny {i}"\n'
                f"    expected_intent: install_esim\n"
                f"    expected_handoff_reason: null\n"
                f"    expected_grounding: grounded\n"
                f"    api_facts: {{}}\n"
                f"    golden_answer_keywords: []\n"
                f"    retrieved_chunk_ids: []\n"
            )
        small.write_text("questions:\n" + "".join(rows))
        report = _run(gold_set_path=small)
        g = _gate(report, GateName.EVAL_PASS_RATE)
        assert not g.passed
        assert "5 questions" in g.reason


class TestEvalGateConstants:
    """Pin the thresholds the plan committed to."""

    def test_min_questions_is_50(self) -> None:
        assert MIN_GOLD_SET_QUESTIONS == 50

    def test_min_refusal_aware_is_75pct(self) -> None:
        assert MIN_REFUSAL_AWARE_DEFLECTION == 0.75

    def test_max_ungrounded_is_zero(self) -> None:
        assert MAX_UNGROUNDED_ANSWERS == 0


# ---------------------------------------------------------------------------
# Gate 3: Escalation context wired
# ---------------------------------------------------------------------------


class TestEscalationContextGate:
    def test_pass_when_required_vars_declared(self) -> None:
        report = _run()
        g = _gate(report, GateName.ESCALATION_CONTEXT)
        assert g.passed, g.reason

    def test_fails_when_var_not_marked_required(self) -> None:
        # The config validator forces required=True for the 3 mandatory
        # vars, so to test "declared but not required" we have to
        # bypass via model_copy(update=...) which preserves all the
        # already-validated nested models and skips re-validation on
        # the patched field.
        cfg = make_config()
        new_ctx = tuple(
            ContextVarSpec(
                name=v.name,
                required=False if v.name == "sim_id" else v.required,
                source=v.source,
            )
            for v in cfg.context_variables
        )
        broken = cfg.model_copy(update={"context_variables": new_ctx})
        report = _run(config=broken)
        g = _gate(report, GateName.ESCALATION_CONTEXT)
        assert not g.passed
        assert "sim_id" in g.reason

    def test_required_context_vars_constant(self) -> None:
        # Pin the contract: these are the exact 3 names.
        assert frozenset(
            {"subscription_id", "sim_id", "user_id"}
        ) == REQUIRED_CONTEXT_VARS


# ---------------------------------------------------------------------------
# Gate 4: Freshness watcher subscribed
# ---------------------------------------------------------------------------


class TestFreshnessWatcherGate:
    def test_pass_with_full_subscription(self) -> None:
        report = _run()
        g = _gate(report, GateName.FRESHNESS_WATCHER)
        assert g.passed, g.reason
        assert "10 invalidating event types" in g.reason

    def test_fails_when_secret_missing(self) -> None:
        report = _run(secrets={})
        g = _gate(report, GateName.FRESHNESS_WATCHER)
        assert not g.passed
        assert "SVIX_SHARED_SECRET" in g.reason

    def test_fails_when_secret_empty(self) -> None:
        report = _run(secrets={"SVIX_SHARED_SECRET": ""})
        g = _gate(report, GateName.FRESHNESS_WATCHER)
        assert not g.passed
        assert "SVIX_SHARED_SECRET" in g.reason

    def test_fails_when_event_types_incomplete(self) -> None:
        # Drop a couple of invalidating types from the subscription
        reduced = set(KB_INVALIDATING_EVENT_TYPES)
        reduced.discard("com.gigs.plan.updated")
        reduced.discard("com.gigs.porting.declined")
        report = _run(subscribed_event_types=reduced)
        g = _gate(report, GateName.FRESHNESS_WATCHER)
        assert not g.passed
        assert "missing" in g.reason
        # Both dropped types should be named
        assert "com.gigs.plan.updated" in g.reason
        assert "com.gigs.porting.declined" in g.reason

    def test_pass_with_superset_subscription(self) -> None:
        # Subscribing to MORE events than required is fine
        extras = set(KB_INVALIDATING_EVENT_TYPES) | {
            "com.gigs.someExtra.created"
        }
        report = _run(subscribed_event_types=extras)
        g = _gate(report, GateName.FRESHNESS_WATCHER)
        assert g.passed, g.reason


# ---------------------------------------------------------------------------
# Gate 5: PII-write guardrails
# ---------------------------------------------------------------------------


class TestPiiWriteGuardrailsGate:
    def test_pass_when_default_guardrails(self) -> None:
        report = _run()
        g = _gate(report, GateName.PII_WRITE_GUARDRAILS)
        assert g.passed, g.reason

    def test_fails_when_read_only_writes_false(self) -> None:
        cfg = make_config(read_only_writes=False)
        report = _run(config=cfg)
        g = _gate(report, GateName.PII_WRITE_GUARDRAILS)
        assert not g.passed
        assert "read_only_writes" in g.reason

    def test_fails_when_refuse_pii_writes_false(self) -> None:
        cfg = make_config()
        broken_guardrails = Guardrails(
            read_only_writes=True,
            refuse_pii_writes=False,
        )
        broken = cfg.model_copy(update={"guardrails": broken_guardrails})
        report = _run(config=broken)
        g = _gate(report, GateName.PII_WRITE_GUARDRAILS)
        assert not g.passed
        assert "refuse_pii_writes" in g.reason


# ---------------------------------------------------------------------------
# Gate 6: Two-hop escalation declared
# ---------------------------------------------------------------------------


class TestTwoHopEscalationGate:
    def test_pass_when_both_targets_emails(self) -> None:
        report = _run()
        g = _gate(report, GateName.TWO_HOP_ESCALATION)
        assert g.passed, g.reason

    def test_fails_when_tier1_not_email(self) -> None:
        cfg = make_config()
        # tier1_target Field has min_length=3 only — "not-an-email" passes
        # field-level validation. The gate's responsibility is the email
        # *shape* check.
        broken_two_hop = TwoHopEscalation(
            tier1_target="not-an-email",
            tier2_target=f"tier2{AT}gigs.example",
        )
        broken = cfg.model_copy(update={"two_hop": broken_two_hop})
        report = _run(config=broken)
        g = _gate(report, GateName.TWO_HOP_ESCALATION)
        assert not g.passed
        assert "tier1_target" in g.reason

    def test_fails_when_tier2_not_email(self) -> None:
        cfg = make_config()
        broken_two_hop = TwoHopEscalation(
            tier1_target=f"tier1{AT}cashcard.example",
            tier2_target="missing-at-sign",
        )
        broken = cfg.model_copy(update={"two_hop": broken_two_hop})
        report = _run(config=broken)
        g = _gate(report, GateName.TWO_HOP_ESCALATION)
        assert not g.passed
        assert "tier2_target" in g.reason

    def test_fails_when_targets_match(self) -> None:
        cfg = make_config()
        same = f"same{AT}example.com"
        broken_two_hop = TwoHopEscalation(
            tier1_target=same,
            tier2_target=same,
        )
        broken = cfg.model_copy(update={"two_hop": broken_two_hop})
        report = _run(config=broken)
        g = _gate(report, GateName.TWO_HOP_ESCALATION)
        assert not g.passed
        assert "must differ" in g.reason


# ---------------------------------------------------------------------------
# Aggregation: NOT_READY enumerates every failure
# ---------------------------------------------------------------------------


class TestNotReadyEnumeratesAllFailures:
    """Plan committed: NOT_READY shows every failing gate, not just first."""

    def test_two_independent_failures_both_reported(self, tmp_path: Path) -> None:
        # Break gate 1 (kb missing) AND gate 4 (no secret) simultaneously
        report = _run(
            kb_root=tmp_path / "missing",
            secrets={},
        )
        assert report.verdict == "NOT_READY"
        failing_names = {g.name for g in report.failing_gates}
        assert GateName.KB_COVERAGE in failing_names
        assert GateName.FRESHNESS_WATCHER in failing_names

    def test_eval_gate_still_runs_after_kb_gate_fails(
        self, tmp_path: Path
    ) -> None:
        """Confirm gates don't short-circuit on each other."""
        report = _run(kb_root=tmp_path / "missing")
        eval_gate = _gate(report, GateName.EVAL_PASS_RATE)
        # The eval gate will likely fail too because it uses the same
        # kb_root for chunk lookup, but the key invariant is that the
        # GateResult exists at all.
        assert eval_gate is not None

    def test_failing_gates_property_excludes_passers(self) -> None:
        report = _run(secrets={})
        all_failing = report.failing_gates
        # Every entry in failing_gates is actually failing
        assert all(not g.passed for g in all_failing)
        # And every gate not in failing_gates passed
        failing_names = {g.name for g in all_failing}
        passing = [g for g in report.gates if g.name not in failing_names]
        assert all(g.passed for g in passing)


# ---------------------------------------------------------------------------
# render_readiness
# ---------------------------------------------------------------------------


class TestRenderReadiness:
    def test_ready_render_shows_each_gate(self) -> None:
        report = _run()
        text = render_readiness(report)
        assert "Verdict: READY" in text
        for g in report.gates:
            assert g.name.value in text
        # No "Blocking gates" footer when ready
        assert "Blocking gates" not in text

    def test_not_ready_render_has_blocking_section(self) -> None:
        report = _run(secrets={})
        text = render_readiness(report)
        assert "Verdict: NOT_READY" in text
        assert "Blocking gates" in text
        assert GateName.FRESHNESS_WATCHER.value in text
