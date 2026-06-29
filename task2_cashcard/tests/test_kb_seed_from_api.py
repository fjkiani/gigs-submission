"""Tests for kb_seed_from_api derivers.

Each deriver is deterministic: given the same input, it emits the same chunks
(modulo `derived_at` timestamp, which is checked separately).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from task2_cashcard.kb_seed_from_api import (
    US_PORTING_DECLINE_CODES,
    US_PORTING_REQUIRED_FIELDS,
    SeededChunk,
    derive_esim_eligibility,
    derive_plan_chunks,
    derive_porting_required_fields,
)

# ---- derive_plan_chunks ------------------------------------------------------


class TestDerivePlanChunks:
    @staticmethod
    def _sample_plan() -> dict[str, object]:
        return {
            "id": "pln_unlimited_us",
            "name": "Unlimited US",
            "allowances": [
                {"type": "data", "amount": -1, "unit": "GB"},
                {"type": "voice", "amount": -1, "unit": "minutes"},
                {"type": "sms", "amount": -1, "unit": "messages"},
            ],
            "limits": [
                {"type": "throttle_after", "value": "30GB"},
            ],
            "simTypes": ["eSIM"],
            "validity": {"amount": 30, "unit": "days"},
            "coverage": {"countries": ["US"]},
            "description": "Unlimited data + talk + text, US only.",
        }

    def test_emits_one_chunk_per_plan(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert len(chunks) == 1

    def test_chunk_has_plan_name_and_id(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        body = chunks[0].body
        assert "Unlimited US" in body
        assert "pln_unlimited_us" in body

    def test_chunk_body_contains_allowances(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert "Allowances:" in chunks[0].body

    def test_chunk_body_contains_coverage(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert "US" in chunks[0].body

    def test_chunk_topic_is_plan_questions(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert chunks[0].topic == "plan_questions"

    def test_chunk_has_source_endpoint(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert "/plans/pln_unlimited_us" in chunks[0].source_endpoint

    def test_chunk_id_is_stable(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert chunks[0].chunk_id == "plan.pln_unlimited_us"

    def test_derived_at_is_utc(self) -> None:
        before = datetime.now(UTC)
        chunks = derive_plan_chunks(self._sample_plan())
        after = datetime.now(UTC)
        assert chunks[0].derived_at.tzinfo is not None
        assert before <= chunks[0].derived_at <= after

    def test_missing_id_rejected(self) -> None:
        bad = dict(self._sample_plan())
        del bad["id"]
        with pytest.raises(ValueError, match="must have 'id'"):
            derive_plan_chunks(bad)

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be dict"):
            derive_plan_chunks("not a plan")  # type: ignore[arg-type]

    def test_plan_with_no_allowances_still_emits_chunk(self) -> None:
        sparse = {"id": "pln_x", "simTypes": ["eSIM"]}
        chunks = derive_plan_chunks(sparse)
        assert len(chunks) == 1
        assert "pln_x" in chunks[0].body

    def test_ttl_is_24h(self) -> None:
        chunks = derive_plan_chunks(self._sample_plan())
        assert chunks[0].ttl_seconds == 24 * 3600


# ---- derive_porting_required_fields ------------------------------------------


class TestDerivePortingRequiredFields:
    def test_us_emits_one_required_chunk_plus_one_per_code(self) -> None:
        chunks = derive_porting_required_fields("US")
        # 1 required-fields chunk + N decline-code chunks
        assert len(chunks) == 1 + len(US_PORTING_DECLINE_CODES)

    def test_required_chunk_lists_every_field(self) -> None:
        chunks = derive_porting_required_fields("US")
        required = chunks[0]
        for field in US_PORTING_REQUIRED_FIELDS:
            assert f"`{field}`" in required.body

    def test_required_chunk_id_stable(self) -> None:
        chunks = derive_porting_required_fields("US")
        assert chunks[0].chunk_id == "porting.us.required_fields"
        assert chunks[0].topic == "port_in"

    def test_each_decline_code_has_its_own_chunk(self) -> None:
        chunks = derive_porting_required_fields("US")
        code_chunks = [c for c in chunks if c.chunk_id.startswith("porting.decline.")]
        codes_seen = {c.chunk_id.split(".", 2)[2] for c in code_chunks}
        codes_expected = {code for code, _ in US_PORTING_DECLINE_CODES}
        assert codes_seen == codes_expected

    def test_decline_code_chunk_contains_code_name(self) -> None:
        chunks = derive_porting_required_fields("US")
        for chunk in chunks:
            if not chunk.chunk_id.startswith("porting.decline."):
                continue
            code = chunk.chunk_id.split(".", 2)[2]
            assert f"`{code}`" in chunk.body

    def test_non_us_country_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="US"):
            derive_porting_required_fields("UK")


# ---- derive_esim_eligibility -------------------------------------------------


class TestDeriveEsimEligibility:
    def test_p3_returns_meaningful_lifecycle_chunk(self) -> None:
        chunks = derive_esim_eligibility("p3")
        assert len(chunks) == 1
        body = chunks[0].body
        assert "p3" in body
        assert "meaningful" in body.lower()

    def test_p14_returns_meaningful_lifecycle_chunk(self) -> None:
        chunks = derive_esim_eligibility("p14")
        assert "meaningful" in chunks[0].body.lower()

    def test_p15_returns_meaningful_lifecycle_chunk(self) -> None:
        chunks = derive_esim_eligibility("p15")
        assert "meaningful" in chunks[0].body.lower()

    def test_unsupported_provider_returns_unknown_chunk(self) -> None:
        chunks = derive_esim_eligibility("p7")
        body = chunks[0].body
        assert "unknown" in body.lower()
        assert "must NOT claim" in body or "must not claim" in body.lower()

    def test_chunk_id_stable(self) -> None:
        chunks = derive_esim_eligibility("p3")
        assert chunks[0].chunk_id == "esim.lifecycle.p3"

    def test_topic_is_esim_activation(self) -> None:
        for provider in ("p3", "p14", "p15", "p7", "p99"):
            chunks = derive_esim_eligibility(provider)
            assert chunks[0].topic == "esim_activation"

    def test_empty_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            derive_esim_eligibility("")


# ---- SeededChunk frozen ------------------------------------------------------


class TestSeededChunkFrozen:
    def test_seeded_chunk_is_frozen(self) -> None:
        import dataclasses

        chunks = derive_esim_eligibility("p3")
        with pytest.raises(dataclasses.FrozenInstanceError):
            chunks[0].body = "tampered"  # type: ignore[misc]

    def test_seeded_chunk_is_correct_type(self) -> None:
        chunks = derive_esim_eligibility("p3")
        assert isinstance(chunks[0], SeededChunk)
