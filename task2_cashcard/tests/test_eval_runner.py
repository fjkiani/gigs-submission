"""Tests for the eval_runner.

Covers:
- gold-set parsing (schema + coercion)
- chunk index build from kb_skeleton
- retrieve_chunks_for_question (happy + missing-id error)
- run_eval against the shipped oracle + shipped gold set
- Scorecard math (raw_deflection, refusal_aware_deflection)
- swap-in answer-fn contract (we can pass a custom oracle that always
  hallucinates and see refusal_aware_deflection drop accordingly)
- render_scorecard output sanity
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from task1_audit import GroundingVerdict, HandoffReason
from task2_cashcard.eval.eval_runner import (
    AnswerFn,
    GoldQuestion,
    build_chunk_index,
    load_gold_set,
    oracle_answer_fn,
    render_scorecard,
    retrieve_chunks_for_question,
    run_eval,
)

_GOLD_PATH = Path(__file__).parent.parent / "eval" / "gold_set.yaml"
_KB_ROOT = Path(__file__).parent.parent / "kb_skeleton"


# ---- load_gold_set ----------------------------------------------------------


class TestLoadGoldSet:
    def test_loads_shipped_yaml(self) -> None:
        gold = load_gold_set(_GOLD_PATH)
        assert len(gold) == 50

    def test_every_row_has_required_fields(self) -> None:
        gold = load_gold_set(_GOLD_PATH)
        for row in gold:
            assert isinstance(row, GoldQuestion)
            assert row.id
            assert row.bucket
            assert row.question
            assert row.expected_intent
            assert isinstance(row.expected_grounding, GroundingVerdict)
            assert isinstance(row.api_facts, dict)
            assert isinstance(row.golden_answer_keywords, tuple)
            assert isinstance(row.retrieved_chunk_ids, tuple)

    def test_handoff_reason_coercion(self) -> None:
        gold = load_gold_set(_GOLD_PATH)
        # Every non-null handoff_reason should be a HandoffReason instance
        for row in gold:
            if row.expected_handoff_reason is not None:
                assert isinstance(row.expected_handoff_reason, HandoffReason)

    def test_distribution_matches_brief(self) -> None:
        """Sanity-check we ship the documented 18/12/8/5/5/2 split."""
        from collections import Counter

        gold = load_gold_set(_GOLD_PATH)
        counts = Counter(q.bucket for q in gold)
        assert counts == {
            "esim_activation": 18,
            "plan_questions": 12,
            "devices": 8,
            "roaming": 5,
            "port_in": 5,
            "other": 2,
        }

    def test_unique_ids(self) -> None:
        gold = load_gold_set(_GOLD_PATH)
        ids = [q.id for q in gold]
        assert len(set(ids)) == len(ids)

    def test_missing_top_level_questions_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("wrong_key:\n  - id: foo\n")
        with pytest.raises(ValueError, match="missing top-level"):
            load_gold_set(bad)

    def test_invalid_handoff_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "questions:\n"
            "  - id: x\n"
            "    bucket: other\n"
            "    question: q\n"
            "    expected_intent: i\n"
            "    expected_handoff_reason: not_a_real_reason\n"
            "    expected_grounding: refused\n"
            "    api_facts: {}\n"
            "    golden_answer_keywords: []\n"
            "    retrieved_chunk_ids: []\n"
        )
        with pytest.raises(ValueError):
            load_gold_set(bad)


# ---- build_chunk_index ------------------------------------------------------


class TestBuildChunkIndex:
    def test_loads_shipped_kb(self) -> None:
        idx = build_chunk_index(_KB_ROOT)
        # At least one chunk per bucket
        assert len(idx) >= 18

    def test_every_chunk_has_text(self) -> None:
        idx = build_chunk_index(_KB_ROOT)
        for cid, chunk in idx.items():
            assert chunk["chunk_id"] == cid
            assert chunk["text"].strip()

    def test_frontmatter_is_stripped(self) -> None:
        idx = build_chunk_index(_KB_ROOT)
        for chunk in idx.values():
            # The body should NOT contain the YAML delimiter
            # (anything between --- and --- is removed)
            assert not chunk["text"].lstrip().startswith("---")
            # And should not contain "chunk_id:" as the first non-blank line
            first_real_line = next(
                (line for line in chunk["text"].splitlines() if line.strip()),
                "",
            )
            assert not first_real_line.lstrip().startswith("chunk_id:")


# ---- retrieve_chunks_for_question -------------------------------------------


class TestRetrieveChunksForQuestion:
    def test_happy_path(self) -> None:
        idx = build_chunk_index(_KB_ROOT)
        chunks = retrieve_chunks_for_question(
            idx, ("esim.install.ios.first_time",)
        )
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == "esim.install.ios.first_time"

    def test_missing_id_raises(self) -> None:
        idx = build_chunk_index(_KB_ROOT)
        with pytest.raises(KeyError, match="not in KB index"):
            retrieve_chunks_for_question(idx, ("does.not.exist",))

    def test_empty_returns_empty(self) -> None:
        idx = build_chunk_index(_KB_ROOT)
        assert retrieve_chunks_for_question(idx, ()) == []


# ---- run_eval (oracle integration test) -------------------------------------


class TestRunEvalOracle:
    """Confirm the shipped oracle clears the day-1 deflection target."""

    def test_oracle_hits_target(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        # Brief says ≥75% deflection day one.
        # The refusal-aware metric is the honest one — that's the bar.
        assert scorecard.refusal_aware_deflection >= 0.75, (
            f"refusal-aware deflection {scorecard.refusal_aware_deflection:.1%} "
            f"is below the 75% day-1 target"
        )

    def test_oracle_grounding_clean(self) -> None:
        """No grounded-answer should be ungrounded against its retrieved chunks."""
        scorecard = run_eval(_GOLD_PATH)
        assert scorecard.ungrounded_count == 0, (
            f"{scorecard.ungrounded_count} hallucinations slipped through"
        )

    def test_oracle_every_question_passes(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        assert scorecard.fail_count == 0, (
            f"{scorecard.fail_count} questions failed; see render output"
        )

    def test_total_matches_gold_set_size(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        gold = load_gold_set(_GOLD_PATH)
        assert scorecard.total == len(gold)

    def test_results_tuple_has_one_per_question(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        assert len(scorecard.results) == scorecard.total

    def test_bucket_scores_cover_all_buckets(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        buckets = {b.bucket for b in scorecard.bucket_scores}
        assert buckets == {
            "esim_activation",
            "plan_questions",
            "devices",
            "roaming",
            "port_in",
            "other",
        }


# ---- run_eval (swap-in answer-fn contract) ----------------------------------


def _always_hallucinate(
    question: str,
    api_facts: Mapping[str, Any],
    retrieved_chunks: list[Mapping[str, str]],
) -> str:
    """A bad-faith answer-fn that always returns ungrounded content.

    This is the "raw deflection" trap — the agent looks great on
    raw_deflection but refusal_aware_deflection should be near 0
    when no answer is grounded and no escalation happens.
    """
    del api_facts, retrieved_chunks
    return f"Hello! Definitely yes to your question: {question}. Trust me."


def _always_escalate(
    question: str,
    api_facts: Mapping[str, Any],
    retrieved_chunks: list[Mapping[str, str]],
) -> str:
    del question, api_facts, retrieved_chunks
    return ""  # empty = refusal


class TestRunEvalSwapIn:
    def test_hallucinator_has_high_raw_but_low_aware(self) -> None:
        scorecard = run_eval(_GOLD_PATH, answer_fn=_always_hallucinate)
        # Almost every answer is non-empty -> high raw
        assert scorecard.raw_deflection > 0.9
        # But none are grounded -> aware is just the rows that were
        # supposed to escalate (16/50 = 32%)
        assert scorecard.refusal_aware_deflection < 0.4

    def test_always_escalate_is_zero_raw(self) -> None:
        scorecard = run_eval(_GOLD_PATH, answer_fn=_always_escalate)
        # Every "answer" is empty -> raw deflection = 0
        assert scorecard.raw_deflection == 0.0
        # But refusal_aware credits the 16 rows that should escalate
        assert 0.30 <= scorecard.refusal_aware_deflection <= 0.34

    def test_per_question_chunks_override(self) -> None:
        """Custom retrieved_chunks_by_id should override kb_skeleton."""
        custom = {
            "esim_001": [{"chunk_id": "fake", "text": "completely unrelated"}]
        }
        scorecard = run_eval(
            _GOLD_PATH,
            answer_fn=oracle_answer_fn,
            retrieved_chunks_by_id=custom,
        )
        # The fake chunk won't ground the oracle's iPhone answer -> ungrounded
        esim_001 = next(r for r in scorecard.results if r.id == "esim_001")
        assert esim_001.grounding_verdict == GroundingVerdict.UNGROUNDED


# ---- Scorecard math --------------------------------------------------------


class TestScorecardMath:
    def test_raw_deflection_is_fraction_not_escalated(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        not_refused = sum(1 for r in scorecard.results if not r.is_refusal)
        assert (
            abs(scorecard.raw_deflection - not_refused / scorecard.total) < 1e-9
        )

    def test_refusal_aware_counts_correct_outcomes(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        gold = load_gold_set(_GOLD_PATH)
        correct = 0
        for r, g in zip(scorecard.results, gold, strict=True):
            if g.expected_handoff_reason is None:
                if r.grounding_verdict == GroundingVerdict.GROUNDED:
                    correct += 1
            else:
                if r.is_refusal:
                    correct += 1
        assert (
            abs(scorecard.refusal_aware_deflection - correct / scorecard.total)
            < 1e-9
        )

    def test_pass_count_matches_results(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        passed = sum(1 for r in scorecard.results if r.passed)
        assert scorecard.pass_count == passed


# ---- render_scorecard ------------------------------------------------------


class TestRenderScorecard:
    def test_renders_all_buckets(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        rendered = render_scorecard(scorecard)
        for b in scorecard.bucket_scores:
            assert b.bucket in rendered

    def test_includes_both_deflection_metrics(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        rendered = render_scorecard(scorecard)
        assert "raw_deflection" in rendered
        assert "refusal_aware_deflection" in rendered

    def test_no_failures_section_when_clean(self) -> None:
        scorecard = run_eval(_GOLD_PATH)
        rendered = render_scorecard(scorecard)
        # When fail_count == 0, no failures section
        if scorecard.fail_count == 0:
            assert "Failures:" not in rendered

    def test_failures_section_lists_each_failure(self) -> None:
        scorecard = run_eval(_GOLD_PATH, answer_fn=_always_hallucinate)
        rendered = render_scorecard(scorecard)
        assert "Failures:" in rendered
        # Every failing id should appear
        for r in scorecard.results:
            if not r.passed:
                assert r.id in rendered


# ---- AnswerFn protocol coverage --------------------------------------------


class TestAnswerFnContract:
    def test_oracle_returns_str(self) -> None:
        result = oracle_answer_fn("How do I install eSIM on iPhone?", {}, [])
        assert isinstance(result, str)

    def test_oracle_returns_empty_for_unknown(self) -> None:
        result = oracle_answer_fn(
            "What is the meaning of life?",
            {},
            [],
        )
        assert result == ""

    def test_oracle_escalates_on_restricted(self) -> None:
        result = oracle_answer_fn(
            "Why is my subscription restricted?",
            {"subscription.status": "restricted"},
            [],
        )
        assert result == ""

    def test_oracle_escalates_on_stale_usage(self) -> None:
        result = oracle_answer_fn(
            "How much data have I used?",
            {"usage.usage_updated_at_minutes_ago": 125},
            [],
        )
        assert result == ""

    def test_oracle_escalates_on_unpaid_invoice(self) -> None:
        result = oracle_answer_fn(
            "My payment failed.",
            {
                "invoice.status": "finalized",
                "invoice.amount_due_cents": 2999,
                "invoice.paid_at": None,
            },
            [],
        )
        assert result == ""

    def test_answer_fn_type_is_callable(self) -> None:
        # Just a structural check that AnswerFn is the alias we expect.
        fn: AnswerFn = oracle_answer_fn
        assert callable(fn)


# ---- Dataclasses frozen ----------------------------------------------------


class TestFrozenDataclasses:
    def test_scorecard_frozen(self) -> None:
        import dataclasses

        scorecard = run_eval(_GOLD_PATH)
        with pytest.raises(dataclasses.FrozenInstanceError):
            scorecard.total = -1  # type: ignore[misc]

    def test_bucket_score_frozen(self) -> None:
        import dataclasses

        scorecard = run_eval(_GOLD_PATH)
        with pytest.raises(dataclasses.FrozenInstanceError):
            scorecard.bucket_scores[0].total = -1  # type: ignore[misc]

    def test_gold_question_frozen(self) -> None:
        import dataclasses

        gold = load_gold_set(_GOLD_PATH)
        with pytest.raises(dataclasses.FrozenInstanceError):
            gold[0].question = "tampered"  # type: ignore[misc]
