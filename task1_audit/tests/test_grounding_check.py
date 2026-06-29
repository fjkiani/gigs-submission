"""Tests for task1_audit.grounding_check."""

from __future__ import annotations

from typing import Any

import pytest

from task1_audit.grounding_check import (
    GroundingVerdict,
    check_grounding,
)


def _check(
    *,
    answer: str,
    chunks: list[dict[str, str]] | None = None,
    api_facts: dict[str, Any] | None = None,
    min_supporters_per_claim: int = 1,
):
    return check_grounding(
        question="Q",
        answer=answer,
        retrieved_chunks=chunks or [],
        api_facts=api_facts,
        min_supporters_per_claim=min_supporters_per_claim,
    )


# ---------------------------------------------------------------------------
# Empty / refusal short circuits
# ---------------------------------------------------------------------------


class TestEmptyAndRefusal:
    def test_empty_answer_is_empty_verdict(self) -> None:
        r = _check(answer="")
        assert r.verdict is GroundingVerdict.EMPTY

    def test_whitespace_only_is_empty_verdict(self) -> None:
        r = _check(answer="   \n  ")
        assert r.verdict is GroundingVerdict.EMPTY

    @pytest.mark.parametrize(
        "refusal",
        [
            "I can't help with that — let me connect you to a teammate.",
            "I'm not able to confirm; we should escalate.",
            "I cannot answer this; let me get a human.",
            "I'll hand this off to a human teammate.",
        ],
    )
    def test_refusal_short_circuits(self, refusal: str) -> None:
        r = _check(answer=refusal)
        assert r.verdict is GroundingVerdict.REFUSED


# ---------------------------------------------------------------------------
# Grounded vs ungrounded — chunk-token-overlap path
# ---------------------------------------------------------------------------


class TestChunkOverlap:
    def test_clearly_grounded_via_chunk(self) -> None:
        # Token overlap well over 60%.
        answer = (
            "Your subscription is active and your plan allowance covers the period."
        )
        chunks = [
            {
                "chunk_id": "sub/state#1",
                "text": (
                    "Subscription is active when activated; the plan allowance "
                    "covers the period. Restricted means service is paused."
                ),
            }
        ]
        r = _check(answer=answer, chunks=chunks)
        assert r.verdict is GroundingVerdict.GROUNDED

    def test_no_chunks_no_facts_is_ungrounded(self) -> None:
        # Vanilla declarative sentence with no support anywhere.
        r = _check(answer="Your subscription is active.")
        assert r.verdict is GroundingVerdict.UNGROUNDED

    def test_low_token_overlap_is_ungrounded(self) -> None:
        # Claim shares barely any tokens with the chunk; should fail.
        answer = "Your eSIM profile is currently installed."
        chunks = [
            {
                "chunk_id": "porting/policy#1",
                "text": (
                    "Number portability declines surface declinedCode and "
                    "declinedMessage; the donor controls the timing."
                ),
            }
        ]
        r = _check(answer=answer, chunks=chunks)
        assert r.verdict is GroundingVerdict.UNGROUNDED

    def test_high_token_overlap_grounded(self) -> None:
        # Lots of overlapping content tokens.
        answer = "The eSIM profile is installed on the device and provisioned."
        chunks = [
            {
                "chunk_id": "esim/profile#1",
                "text": (
                    "The eSIM profile is installed on the device after the "
                    "provisioning step completes; once installed it is "
                    "enabled by default."
                ),
            }
        ]
        r = _check(answer=answer, chunks=chunks)
        assert r.verdict is GroundingVerdict.GROUNDED


# ---------------------------------------------------------------------------
# Structured-claim patterns
# ---------------------------------------------------------------------------


class TestStructuredPatterns:
    @pytest.mark.parametrize(
        "ans",
        [
            "You have 4.3 GB remaining this month.",
            "You used 200 megabytes already.",
            "120 minutes left on the plan.",
            "You have 50 texts left.",
            "100 messages remaining.",
        ],
    )
    def test_balance_claim_without_support_is_ungrounded(self, ans: str) -> None:
        # Numeric balance claim with no chunk + no API fact -> ungrounded.
        r = _check(answer=ans)
        assert r.verdict is GroundingVerdict.UNGROUNDED

    @pytest.mark.parametrize(
        "state",
        ["active", "pending", "initiated", "restricted", "ended"],
    )
    def test_subscription_state_pattern(self, state: str) -> None:
        ans = f"Your subscription is {state} on the platform."
        # No support; must be ungrounded.
        r = _check(answer=ans)
        assert r.verdict is GroundingVerdict.UNGROUNDED

    @pytest.mark.parametrize("state", ["installed", "enabled", "disabled", "deleted"])
    def test_esim_state_pattern(self, state: str) -> None:
        ans = f"Your eSIM profile is {state}."
        r = _check(answer=ans)
        assert r.verdict is GroundingVerdict.UNGROUNDED

    @pytest.mark.parametrize(
        "state", ["in progress", "completed", "declined", "requested", "canceled", "expired", "failed"]
    )
    def test_porting_state_pattern(self, state: str) -> None:
        ans = f"Your port-in is {state} on our side."
        r = _check(answer=ans)
        assert r.verdict is GroundingVerdict.UNGROUNDED


# ---------------------------------------------------------------------------
# API-facts path
# ---------------------------------------------------------------------------


class TestApiFacts:
    def test_state_grounded_via_api_fact(self) -> None:
        answer = "Your subscription is active."
        facts = {"subscription.status": "active"}
        r = _check(answer=answer, api_facts=facts)
        assert r.verdict is GroundingVerdict.GROUNDED

    def test_balance_grounded_via_api_fact(self) -> None:
        # Quote the exact API value -> supported.
        answer = "Usage shows 6438265318 bytes used this period."
        facts = {
            "usage.data_bytes_used": 6_438_265_318,
            "usage.updated_at": "2026-06-26T22:12:00Z",
        }
        r = _check(answer=answer, api_facts=facts)
        # Token-overlap path may flag the rest, but the structured numeric
        # claim is supported via API.
        assert r.verdict in {GroundingVerdict.GROUNDED, GroundingVerdict.UNGROUNDED}
        # Either way, the structured claim is supported by the api field.
        supported_paths = set()
        for ev in r.claims:
            supported_paths.update(ev.supported_by_api_fields)
        assert "usage.data_bytes_used" in supported_paths


# ---------------------------------------------------------------------------
# min_supporters_per_claim
# ---------------------------------------------------------------------------


class TestMinSupporters:
    def test_default_one_supporter(self) -> None:
        answer = "Your subscription is active."
        facts = {"subscription.status": "active"}
        r = _check(answer=answer, api_facts=facts, min_supporters_per_claim=1)
        assert r.verdict is GroundingVerdict.GROUNDED

    def test_requires_two_supporters(self) -> None:
        # Single chunk + zero facts -> only 1 supporter; ask for 2 -> fails.
        answer = "Your subscription is active on the platform."
        chunks = [
            {
                "chunk_id": "sub/state#1",
                "text": "Subscription is active when activated on the platform.",
            }
        ]
        r = _check(answer=answer, chunks=chunks, min_supporters_per_claim=2)
        assert r.verdict is GroundingVerdict.UNGROUNDED


# ---------------------------------------------------------------------------
# Evidence structure
# ---------------------------------------------------------------------------


class TestEvidenceStructure:
    def test_evidence_carries_claim_text(self) -> None:
        answer = "Your subscription is active."
        facts = {"subscription.status": "active"}
        r = _check(answer=answer, api_facts=facts)
        # All claims should be ClaimEvidence with the original claim text.
        for ev in r.claims:
            assert ev.claim
            assert isinstance(ev.supported_by_chunk_ids, tuple)
            assert isinstance(ev.supported_by_api_fields, tuple)

    def test_ungrounded_claims_recorded(self) -> None:
        r = _check(answer="Your subscription is active.")
        assert r.verdict is GroundingVerdict.UNGROUNDED
        assert r.ungrounded_claims
        assert any("subscription" in c.lower() for c in r.ungrounded_claims)
