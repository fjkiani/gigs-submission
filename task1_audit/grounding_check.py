"""grounding_check — offline, deterministic grounding gate for candidate answers.

Given a question, the chunks retrieved, the candidate answer, and (optionally)
a snapshot of the Gigs API state at the time, this module decides whether the
answer is *citation-grounded* — meaning every factual claim in it traces back
to either:

    (a) a KB chunk that was actually retrieved, OR
    (b) a Gigs API field lookup that the runtime actually performed.

What this is NOT:
  - This is not an LLM-as-judge. We do not call any model from inside the
    gate; everything here is deterministic and reproducible.
  - This is not a 'truth checker' — it doesn't validate whether the KB content
    is correct. It validates whether the *answer* is faithful to what was
    retrieved.

Why deterministic? Because the eval harness (Task 3) re-runs this thousands of
times in CI per prompt change; a stochastic judge would make the deflection
metric uninterpretable.

Design:
  - We extract candidate atomic claims from the answer (sentence-level + a
    handful of structured patterns: "you have X.X GB", "your subscription is
    {state}", "your eSIM is {state}").
  - For each claim, we check it has lexical support in at least one retrieved
    chunk OR matches a known API-derived fact in `api_facts`.
  - If any claim is unsupported, the gate REFUSES and emits a structured
    verdict the eval harness can read.

This file is intentionally small and reviewable: every rule is explicit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class GroundingVerdict(StrEnum):
    GROUNDED = "grounded"
    UNGROUNDED = "ungrounded"
    REFUSED = "refused"  # answer was already a refusal — that's a pass
    EMPTY = "empty"  # no answer text to evaluate


@dataclass(frozen=True)
class ClaimEvidence:
    """How a single claim was (or wasn't) supported."""

    claim: str
    supported_by_chunk_ids: tuple[str, ...]
    supported_by_api_fields: tuple[str, ...]

    @property
    def is_supported(self) -> bool:
        return bool(self.supported_by_chunk_ids or self.supported_by_api_fields)


@dataclass(frozen=True)
class GroundingReport:
    """Result of running grounding_check on one (q, a, retrieved, facts) tuple."""

    verdict: GroundingVerdict
    claims: tuple[ClaimEvidence, ...]
    reason: str
    # When verdict == UNGROUNDED, these are the claims that failed.
    ungrounded_claims: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Claim extraction. The patterns below come from the failure taxonomy:
# the same patterns the auditor knows are the ones most likely to be wrong.
# ---------------------------------------------------------------------------

# Sentence split — paragraph-respecting, no heavy NLP.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

# Structured-claim patterns.
_NUM_BALANCE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:GB|MB|gigabytes?|megabytes?|minutes?|texts?|messages?)\b",
    re.IGNORECASE,
)
_SUBSCRIPTION_STATE = re.compile(
    r"\b(active|pending|initiated|restricted|ended|canceled|suspended)\b",
    re.IGNORECASE,
)
_ESIM_STATE = re.compile(
    r"\b(installed|enabled|disabled|deleted)\b\s+(?:e?sim|profile)?",
    re.IGNORECASE,
)
_PORTING_STATE = re.compile(
    r"\b(in progress|completed|declined|requested|canceled|expired|failed)\b",
    re.IGNORECASE,
)

# Refusal patterns — if the answer is a clean refusal, we mark REFUSED and skip.
_REFUSAL_HINTS = (
    "i can't help with",
    "i'm not able to",
    "i cannot answer",
    "let me connect you",
    "i'll hand this off",
    "let me get a human",
    "we should escalate",
)


def _extract_claims(answer: str) -> list[str]:
    """Extract claim candidates. Sentence-level + structured patterns."""
    answer = answer.strip()
    if not answer:
        return []

    # Sentence-level
    sentences = _SENT_SPLIT.split(answer)
    sentences = [s.strip().rstrip(".") for s in sentences if s.strip()]

    # Structured: any substring matching one of the patterns is also a claim.
    claims: list[str] = []
    for s in sentences:
        claims.append(s)

    # Add structured matches as their own claims so a sentence containing
    # multiple structured facts can fail on each one independently.
    structured: list[str] = []
    for pattern in (_NUM_BALANCE, _SUBSCRIPTION_STATE, _ESIM_STATE, _PORTING_STATE):
        structured.extend(m.group(0).strip() for m in pattern.finditer(answer))

    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in claims + structured:
        c_norm = re.sub(r"\s+", " ", c.lower()).strip()
        if c_norm and c_norm not in seen:
            seen.add(c_norm)
            out.append(c)
    return out


def _is_refusal(answer: str) -> bool:
    a = answer.lower()
    return any(hint in a for hint in _REFUSAL_HINTS)


def _claim_supported_by_chunk(claim: str, chunk_text: str) -> bool:
    """Token-overlap heuristic with a guardrail.

    A claim is supported by a chunk if the claim's *content* tokens (length >= 4)
    are sufficiently covered by the chunk's tokens. We use a high threshold
    (>= 60%) so trivial words like 'the' don't get a free pass.

    We deliberately do NOT do paraphrase / embedding matching here — that would
    be non-deterministic and let bad answers through. If a claim only matches
    its source via paraphrase, the agent should have quoted more closely.
    """
    claim_tokens = {t for t in re.findall(r"[A-Za-z0-9]{4,}", claim.lower())}
    if not claim_tokens:
        # Pure numbers or stopwords — require a stricter check: the literal
        # token must appear in the chunk.
        literals = set(re.findall(r"\S+", claim.lower()))
        return any(lit in chunk_text.lower() for lit in literals if len(lit) >= 2)
    chunk_tokens = {t for t in re.findall(r"[A-Za-z0-9]{4,}", chunk_text.lower())}
    if not chunk_tokens:
        return False
    overlap = len(claim_tokens & chunk_tokens) / len(claim_tokens)
    return overlap >= 0.6


def _claim_supported_by_facts(claim: str, api_facts: dict[str, Any]) -> tuple[str, ...]:
    """Return the dotted API paths supporting the claim, or empty tuple.

    api_facts is a flat dict like:
        {
            "subscription.status": "active",
            "subscription.restricted_at": None,
            "sim.provider": "p3",
            "esim_profile.status": "installed",
            "usage.data_bytes_used": 4_200_000_000,
            "usage.updated_at": "2026-06-27T08:00:00Z",
            "plan.allowances.data": 10_737_418_240,  # 10 GiB
            "porting.declined_code": null,
        }

    For each entry, if the *value* (as a string) appears literally in the
    claim, we count it as supported by that field.
    """
    supporters: list[str] = []
    for path, value in api_facts.items():
        if value is None:
            continue
        # Stringify primitives, leave complex out (caller flattens).
        if isinstance(value, (str, int, float, bool)):
            sval = str(value).lower()
            if len(sval) < 2:
                continue
            if sval in claim.lower():
                supporters.append(path)
    return tuple(supporters)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_grounding(
    *,
    question: str,
    answer: str,
    retrieved_chunks: list[dict[str, str]],
    api_facts: dict[str, Any] | None = None,
    min_supporters_per_claim: int = 1,
) -> GroundingReport:
    """Run the deterministic grounding gate.

    Args:
        question: the user's question (currently unused for verdict; carried
            for future expansion and logged-by-eval-harness purposes).
        answer: the candidate answer.
        retrieved_chunks: list of {'chunk_id': str, 'text': str} that the
            agent retrieved.
        api_facts: optional flat dict of Gigs-API-derived facts the runtime
            actually looked up. See _claim_supported_by_facts for shape.
        min_supporters_per_claim: how many supporters (chunk + API combined)
            each claim must have to be considered supported. Default 1.

    Returns:
        GroundingReport with verdict + per-claim evidence.
    """
    api_facts = api_facts or {}
    _ = question  # currently unused; retained for symmetric API.
    if not answer or not answer.strip():
        return GroundingReport(
            verdict=GroundingVerdict.EMPTY,
            claims=(),
            reason="No answer text to evaluate.",
        )

    if _is_refusal(answer):
        return GroundingReport(
            verdict=GroundingVerdict.REFUSED,
            claims=(),
            reason="Answer is a refusal/escalation; grounding gate does not apply.",
        )

    claims = _extract_claims(answer)
    if not claims:
        # Answer had no sentences and no structured facts — degenerate. Treat
        # as ungrounded so the gate fails-safe.
        return GroundingReport(
            verdict=GroundingVerdict.UNGROUNDED,
            claims=(),
            reason="Answer contained no extractable claims; gate fails closed.",
            ungrounded_claims=(answer,),
        )

    evidence: list[ClaimEvidence] = []
    ungrounded: list[str] = []
    for claim in claims:
        supporting_chunks = tuple(
            c["chunk_id"]
            for c in retrieved_chunks
            if _claim_supported_by_chunk(claim, c.get("text", ""))
        )
        supporting_facts = _claim_supported_by_facts(claim, api_facts)
        ev = ClaimEvidence(
            claim=claim,
            supported_by_chunk_ids=supporting_chunks,
            supported_by_api_fields=supporting_facts,
        )
        evidence.append(ev)
        if (len(supporting_chunks) + len(supporting_facts)) < min_supporters_per_claim:
            ungrounded.append(claim)

    if ungrounded:
        return GroundingReport(
            verdict=GroundingVerdict.UNGROUNDED,
            claims=tuple(evidence),
            reason=(
                f"{len(ungrounded)} of {len(claims)} claims lacked support; "
                f"required {min_supporters_per_claim} supporter(s) each."
            ),
            ungrounded_claims=tuple(ungrounded),
        )

    return GroundingReport(
        verdict=GroundingVerdict.GROUNDED,
        claims=tuple(evidence),
        reason=f"All {len(claims)} claims supported.",
    )


# ---------------------------------------------------------------------------
# Helpers used by the eval harness in Task 3.
# ---------------------------------------------------------------------------


def now_utc() -> datetime:
    """Tiny helper — kept here so tests can monkeypatch a single import point."""
    return datetime.now(tz=UTC)
