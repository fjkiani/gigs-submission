"""Pre-launch evaluation harness.

Takes a candidate ``answer_fn`` and walks the gold set, recording for
each question:

- the handoff decision (None vs HandoffReason),
- the grounding verdict on the candidate answer (REFUSED is acceptable
  if the question's expected_handoff_reason is non-null),
- which golden keywords the answer included,
- whether the eval-runner's read of the situation matches the gold-set
  expectations.

Two deflection metrics are emitted:

- **raw_deflection**: fraction of questions where the agent answered
  without escalation. This is the headline number marketing usually
  quotes; it's the one that pretends an unbacked answer counts as
  "handled".

- **refusal_aware_deflection**: fraction where the agent (a) answered
  AND (b) was grounded, OR (c) refused/escalated when the gold set
  said it should. This is the honest metric — if the agent
  hallucinates instead of escalating, that's a regression even if it
  "answered".

Both are reported, side by side, so reviewers can see the gap.

The runner does **not** call any LLM. The default ``answer_fn`` is a
deterministic oracle that knows the gold set. Reviewers can swap in a
real LLM-backed function when the agent stack is wired up; the
harness contract is just `answer_fn(question, api_facts, retrieved_chunks)
-> str`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from task1_audit import GroundingVerdict, HandoffReason
from task1_audit.grounding_check import check_grounding

# ---------------------------------------------------------------------------
# Loading the gold set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoldQuestion:
    """One row of gold_set.yaml."""

    id: str
    bucket: str
    question: str
    expected_intent: str
    expected_handoff_reason: HandoffReason | None
    expected_grounding: GroundingVerdict
    api_facts: dict[str, Any]
    golden_answer_keywords: tuple[str, ...]
    # Which kb_skeleton chunks the retriever would surface for this question.
    # Pre-computed; the eval runner loads them via a chunk index.
    retrieved_chunk_ids: tuple[str, ...]


def _coerce_handoff(value: object) -> HandoffReason | None:
    if value is None:
        return None
    if isinstance(value, str):
        return HandoffReason(value.lower())
    raise TypeError(f"expected str/None, got {type(value).__name__}")


def _coerce_verdict(value: object) -> GroundingVerdict:
    if not isinstance(value, str):
        raise TypeError(f"expected str, got {type(value).__name__}")
    return GroundingVerdict(value.lower())


def load_gold_set(path: Path) -> tuple[GoldQuestion, ...]:
    """Parse the YAML gold set into a tuple of frozen rows."""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError(f"{path}: missing top-level 'questions:' key")
    rows: list[GoldQuestion] = []
    for raw in data["questions"]:
        rows.append(
            GoldQuestion(
                id=str(raw["id"]),
                bucket=str(raw["bucket"]),
                question=str(raw["question"]),
                expected_intent=str(raw["expected_intent"]),
                expected_handoff_reason=_coerce_handoff(
                    raw.get("expected_handoff_reason")
                ),
                expected_grounding=_coerce_verdict(raw["expected_grounding"]),
                api_facts=dict(raw.get("api_facts") or {}),
                golden_answer_keywords=tuple(raw.get("golden_answer_keywords") or ()),
                retrieved_chunk_ids=tuple(raw.get("retrieved_chunk_ids") or ()),
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# KB chunk index — used by the runner to fetch retrieved chunks per question
# ---------------------------------------------------------------------------


def build_chunk_index(kb_root: Path) -> dict[str, dict[str, str]]:
    """Walk kb_root and return a {chunk_id: {chunk_id, text}} index.

    `text` contains the body **without** the YAML frontmatter — the
    grounding gate only inspects body content. The text is lowercased
    at lookup time by the gate's own matcher, so we keep the original
    casing here.
    """
    from task2_cashcard.kb_gap_analyzer import load_chunks

    chunks = load_chunks(kb_root)
    index: dict[str, dict[str, str]] = {}
    for chunk in chunks:
        text = chunk.path.read_text(encoding="utf-8")
        # Strip the frontmatter block
        if text.startswith("---"):
            close = text.find("\n---", 3)
            if close >= 0:
                body_start = text.find("\n", close + 4)
                text = text[body_start + 1 :] if body_start >= 0 else ""
        index[chunk.chunk_id] = {"chunk_id": chunk.chunk_id, "text": text}
    return index


def retrieve_chunks_for_question(
    chunk_index: Mapping[str, Mapping[str, str]],
    chunk_ids: tuple[str, ...],
) -> list[Mapping[str, str]]:
    """Resolve a tuple of chunk ids against the chunk index.

    Missing ids raise KeyError so silent drift between gold_set and
    kb_skeleton fails loudly.
    """
    out: list[Mapping[str, str]] = []
    for cid in chunk_ids:
        if cid not in chunk_index:
            raise KeyError(f"chunk_id {cid!r} not in KB index")
        out.append(chunk_index[cid])
    return out


# ---------------------------------------------------------------------------
# Answer functions
# ---------------------------------------------------------------------------


# The harness contract. The function takes the question, the API facts the
# runtime would have looked up, and the retrieved chunks (we keep this
# parameter for future use; the oracle ignores it). It returns the candidate
# answer string, with an empty-string return treated as a refusal/escalation.
AnswerFn = Callable[[str, Mapping[str, Any], list[Mapping[str, str]]], str]


# Stock refusal phrases the oracle uses; these match the prefixes
# `_is_refusal` in task1_audit recognises.
_REFUSAL_PREFIXES = (
    "I'll loop in a teammate",
    "I can't",
    "I want to flag",
    "Before I make any changes",
    "I'm going to bring in a teammate",
)


def oracle_answer_fn(
    question: str,
    api_facts: Mapping[str, Any],
    retrieved_chunks: list[Mapping[str, str]],
) -> str:
    """Deterministic answer-function for the shipped gold set.

    Maps each question to a known-correct response. Returns empty
    string to signal "the agent should refuse/escalate here".

    Each answer here is written to stay close to the language of the
    retrieved chunk so the deterministic grounding gate (token-overlap
    ≥ 60%) accepts it. The production agent should follow the same
    "stick to the chunk" discipline — that's the contract.

    This is **not** the production agent. It exists so the eval harness
    can be exercised end-to-end before the real agent is wired in. The
    contract is fixed so swap-in is a one-line change.
    """
    del retrieved_chunks  # oracle gets chunks via run_eval; doesn't read them
    q = question.lower()

    # ---- Refuse/escalate when api_facts indicate restricted/stale/write ----
    if api_facts.get("subscription.status") == "restricted":
        return ""  # escalate via POLICY_REFUSAL
    minutes_ago = api_facts.get("usage.usage_updated_at_minutes_ago")
    if isinstance(minutes_ago, int) and minutes_ago > 60:
        return ""  # escalate via TOOL_FAILURE
    if api_facts.get("invoice.status") == "finalized" and not api_facts.get(
        "invoice.paid_at"
    ):
        return ""  # escalate via WRITE_REQUIRES_HUMAN
    if api_facts.get("recent_events"):
        return ""  # escalate via WRITE_REQUIRES_HUMAN

    # ---- Roaming write-actions check BEFORE the read-only roaming branch ----
    # Buying or troubleshooting an active roaming pass is a write — must
    # escalate even if the question mentions a country.
    if "mexico city" in q or "switzerland" in q or "data pack" in q:
        return ""  # WRITE — roaming pass setup or troubleshoot

    # ---- Cross-cutting write/refuse intents (check before topical answers) ----
    if "physical sim" in q:
        return (
            "I can't activate a physical SIM on CashCard. CashCard is "
            "eSIM-only and a physical SIM won't work with us today. Want "
            "me to point you to the carrier check tool so you can confirm "
            "your device before buying?"
        )
    if "iphone 7" in q or "carrier-locked" in q or "locked from verizon" in q:
        return (
            "I can't activate that device on CashCard. CashCard is "
            "eSIM-only and your phone won't work with us today. Want me "
            "to point you to the carrier check tool so you can confirm a "
            "different device before buying?"
        )
    if "transfer" in q and ("new phone" in q or "line" in q):
        return ""
    if "deleted the activation email" in q or ("delete" in q and "email" in q):
        return ""
    if "switch" in q or "downgrade" in q or "bigger plan" in q:
        return ""
    if "refund" in q:
        return ""
    if "lost" in q or "stolen" in q:
        return ""
    if "cancel my port" in q or "cancel my port" in q.lower():
        return ""
    if "password" in q.lower() and "reset" in q.lower():
        return ""

    # ---- Topical, chunk-faithful answers ----
    if "iphone" in q and ("install" in q or "iphone 15" in q):
        return (
            "On a supported iPhone running iOS 16 or later, open the "
            "activation email from CashCard and tap Install eSIM. iOS will "
            "open Settings to the Cellular page with the new line "
            "preselected."
        )
    if "pixel" in q and "install" in q:
        return (
            "On Pixel 7 and newer running Android 13, open Settings → "
            "Network & internet → SIMs → Add SIM, then choose Download a "
            "SIM instead. Scan the QR code from the CashCard app on a "
            "second device."
        )
    if "galaxy" in q or "samsung" in q:
        return (
            "On a Samsung Galaxy S22 or newer running One UI 5, open "
            "Settings → Connections → SIM manager → Add eSIM, then scan "
            "the QR code from your CashCard app on a second device."
        )
    if "downloading" in q and "no service" in q:
        return (
            "Wait until the device reports the install — usually within "
            "a few minutes — and the line should come up. The carrier "
            "API reports profile state, not device state."
        )
    if "no service" in q or "no signal" in q or "could not activate cellular" in q:
        return (
            "When the eSIM profile is installed but the carrier shows no "
            "service, that is usually a carrier-side provisioning lag in "
            "the first 30 minutes after activation. Wait 5 minutes and "
            "toggle airplane mode on and off once."
        )
    if "hasn't installed" in q or ("how long" in q and "install" in q):
        return (
            "Until the device reports the install, the correct phrasing "
            "is that your eSIM is downloading. Once iOS finishes the OTA "
            "download the carrier API will see the install — usually "
            "within a few minutes."
        )
    if "qr code" in q and "find" in q:
        return (
            "The activation email contains the eSIM, and the CashCard app "
            "shows the QR code under Activation. Scan the QR code from "
            "the CashCard app on a second device."
        )
    if "scan the qr code from the screen" in q:
        return (
            "You need a second device to show the QR code. The phone "
            "you're installing on cannot scan its own screen during the "
            "eSIM install flow."
        )
    if "is my esim active" in q or "esim active on my phone" in q:
        # api_facts says installed — answer with the API fact
        return (
            "The carrier API reports your eSIM profile status as "
            "installed. The eSIM profile is installed and we see the "
            "device reporting the install."
        )
    if "ipad" in q:
        return (
            "Yes — CashCard supports iPad Pro 2018 and newer, iPad Air 3 "
            "and newer, and iPad Mini 5 and newer, all with cellular "
            "SKUs. iPad Wi-Fi-only models do not have cellular hardware."
        )
    if "another carrier" in q or "still work if i get a new sim" in q:
        return (
            "Your CashCard eSIM line keeps working when you add another "
            "carrier alongside it on the device. eSIMs are tied to the "
            "device, not the SIM tray, so the lines do not interfere."
        )

    # plan_questions
    if "data have i used" in q:
        used = api_facts.get("usage.data_mb_used")
        mins = api_facts.get("usage.usage_updated_at_minutes_ago", 0)
        if used is not None:
            gb = used / 1024
            return (
                f"You have used {gb:.1f} GB of data this cycle, as of "
                f"{mins} minutes ago when the carrier last reported "
                f"usage."
            )
        return ""
    if "minutes do i have" in q or ("minutes" in q and "left" in q):
        used_min = api_facts.get("usage.voice_minutes_used")
        plan_min = api_facts.get("plan.voice_minutes")
        mins = api_facts.get("usage.usage_updated_at_minutes_ago", 0)
        if used_min is not None and plan_min is not None:
            return (
                f"You have used {used_min} of your {plan_min} voice "
                f"minutes this cycle, as of {mins} minutes ago when the "
                f"carrier last reported usage."
            )
        return ""
    if "plan include" in q:
        plan_name = api_facts.get("plan.name", "your plan")
        return (
            f"Your CashCard plan {plan_name} includes the allowances the "
            f"carrier API reports — data, voice minutes, and SMS for the "
            f"US. Allowances do not apply outside the US unless a roaming "
            f"add-on is attached."
        )
    if "when does my plan renew" in q or "plan renew" in q:
        renewal = api_facts.get("subscription.next_renewal_date")
        return (
            f"Your subscription renews on {renewal}. The billing cycle "
            f"starts on the day of subscription activation, not the 1st "
            f"of the month, so the renewal happens on the same date each "
            f"cycle."
        )
    if "family plan" in q:
        return (
            "A plan on CashCard is a monthly subscription bundle per "
            "line; the carrier API exposes per-plan allowances and "
            "coverage. Three things matter to most users: the "
            "allowances, the coverage, and the price."
        )
    if "running out of data" in q or "approaching" in q or "slow me down" in q:
        return (
            "CashCard plans use monthly allowances pulled from the "
            "carrier API per plan. The agent quotes what the API "
            "reported for this user's plan rather than projecting."
        )
    if "plan more expensive" in q or "more expensive" in q:
        price = api_facts.get("plan.price_cents")
        currency = api_facts.get("plan.currency", "USD")
        if price is not None:
            return (
                f"Your CashCard plan is billed at {price / 100:.2f} "
                f"{currency} per cycle on the carrier API. The allowances "
                f"on your plan come from the same carrier API the agent "
                f"reads."
            )
        return ""

    # devices
    if "pixel 6a" in q:
        return (
            "Yes, Pixel 6a is a supported device on CashCard. Pixel 3 "
            "and newer with Android 12 or later are confirmed-working "
            "for our eSIM activation."
        )
    if "iphone 14" in q:
        return (
            "Yes, an unlocked iPhone 14 from Best Buy is a supported "
            "device on CashCard. iPhone XS and newer running iOS 16+ "
            "are confirmed-working — and an unlocked model is exactly "
            "what we want."
        )
    if "stopped working" in q or "dropped calls" in q:
        return (
            "Check the subscription status first; if subscription.status "
            "is restricted, no amount of device fiddling helps. Then "
            "toggle airplane mode on and off once to force the device to "
            "re-handshake with the carrier."
        )
    if "apn" in q:
        return (
            "CashCard pushes APN settings automatically. If your device "
            "shows manual APN entries, reset them via device Settings → "
            "Cellular → CashCard line → Cellular Data Network → Reset "
            "Settings."
        )
    if "aliexpress" in q:
        return (
            "Send the exact model and where the phone was sold; I'll "
            "check it against the supported device list. CashCard is "
            "eSIM-only and some imported devices won't work in the US."
        )

    # roaming
    if "paris" in q or ("forget" in q and "pass" in q) or "per mb" in q:
        return (
            "Your CashCard plan covers the US only. To use data, calls, "
            "or texts in another country, you need to add a roaming "
            "pass before you travel. I can pass this to a teammate so "
            "you're set up before you fly."
        )

    # port_in
    if "port my number" in q or "verizon" in q:
        return (
            "To port your number from a US carrier we need six fields: "
            "account number, port-out PIN, last 4 of SSN, zip code on "
            "the donor account, the phone number being ported, and the "
            "donor provider name."
        )
    if "portingpinincorrect" in q:
        return (
            "The portingPinIncorrect code means the donor carrier said "
            "the port-out PIN we sent didn't match. The typical fix is "
            "to log into your donor account and generate a fresh "
            "port-out PIN, then we re-submit the port."
        )
    if "port was declined" in q.lower() or "why was my port declined" in q:
        return (
            "Your port was declined with portingAccountNumberMismatch. "
            "The donor carrier said the account number we sent doesn't "
            "match the one on file. Confirm the account number on your "
            "last donor billing statement and we re-submit."
        )
    if "porting usually take" in q or "how long" in q:
        return (
            "Porting typically takes 1 to 24 hours for the donor "
            "carrier to release the number. The agent never quotes a "
            "specific time inside that window — the donor carrier "
            "controls the release."
        )

    # other
    if "restricted" in q:
        return ""
    # Fallback: refuse rather than hallucinate
    return ""


# ---------------------------------------------------------------------------
# Score model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionResult:
    """Per-question evaluation outcome."""

    id: str
    bucket: str
    expected_handoff: HandoffReason | None
    answer_text: str
    is_refusal: bool
    grounding_verdict: GroundingVerdict
    keywords_present: tuple[str, ...]
    keywords_missing: tuple[str, ...]
    passed: bool
    failure_reason: str | None


@dataclass(frozen=True)
class BucketScore:
    bucket: str
    total: int
    answered_grounded: int
    answered_ungrounded: int
    refused: int


@dataclass(frozen=True)
class Scorecard:
    """End-to-end run outcome."""

    total: int
    raw_deflection: float
    refusal_aware_deflection: float
    grounded_count: int
    ungrounded_count: int
    refused_count: int
    pass_count: int
    fail_count: int
    bucket_scores: tuple[BucketScore, ...]
    results: tuple[QuestionResult, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------


def _check_keywords(
    answer: str, golden_keywords: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (present, missing). Case-insensitive substring matching."""
    a = answer.lower()
    present: list[str] = []
    missing: list[str] = []
    for kw in golden_keywords:
        if kw.lower() in a:
            present.append(kw)
        else:
            missing.append(kw)
    return tuple(present), tuple(missing)


def run_eval(
    gold_path: Path,
    answer_fn: AnswerFn = oracle_answer_fn,
    *,
    kb_root: Path | None = None,
    retrieved_chunks_by_id: Mapping[str, list[Mapping[str, str]]] | None = None,
) -> Scorecard:
    """Run the harness end to end.

    Args:
        gold_path: path to gold_set.yaml.
        answer_fn: callable matching ``AnswerFn``. Defaults to the
            oracle.
        kb_root: optional path to a kb_skeleton/ tree. When provided,
            each gold question's ``retrieved_chunk_ids`` are resolved
            against this tree and passed to ``check_grounding`` as the
            ``retrieved_chunks`` argument. When None, defaults to the
            shipped ``task2_cashcard/kb_skeleton/`` next to this file.
        retrieved_chunks_by_id: optional per-question override. When
            present, takes precedence over ``kb_root``-derived chunks.
            Used by tests that want to inject a specific chunk fixture.

    Returns:
        ``Scorecard``.
    """
    gold = load_gold_set(gold_path)
    chunks_lookup = retrieved_chunks_by_id or {}

    # Build the kb_skeleton chunk index. ``retrieved_chunks_by_id``
    # overrides on a per-question basis (not wholesale) so callers can
    # pin a single question's chunks while letting the rest resolve
    # normally.
    if kb_root is None:
        kb_root = Path(__file__).parent.parent / "kb_skeleton"
    chunk_index = build_chunk_index(kb_root)

    results: list[QuestionResult] = []
    for q in gold:
        if q.id in chunks_lookup:
            retrieved: list[Mapping[str, str]] = list(chunks_lookup[q.id])
        else:
            retrieved = retrieve_chunks_for_question(
                chunk_index, q.retrieved_chunk_ids
            )
        answer = answer_fn(q.question, q.api_facts, retrieved)

        # Convert Mapping[str, str] -> dict[str, str] for the gate signature.
        retrieved_for_gate: list[dict[str, str]] = [dict(r) for r in retrieved]

        verdict_report = check_grounding(
            question=q.question,
            answer=answer,
            retrieved_chunks=retrieved_for_gate,
            api_facts=q.api_facts,
        )
        verdict = verdict_report.verdict

        present, missing = _check_keywords(answer, q.golden_answer_keywords)
        is_refusal = (
            verdict == GroundingVerdict.REFUSED
            or verdict == GroundingVerdict.EMPTY
        )

        # Pass logic:
        # - If expected_handoff is None: answer must be grounded + keywords met
        # - If expected_handoff is non-null: answer must be refused/empty
        passed = True
        failure: str | None = None
        if q.expected_handoff_reason is None:
            if verdict != GroundingVerdict.GROUNDED:
                passed = False
                failure = f"expected grounded, got {verdict.value}"
            elif missing:
                passed = False
                failure = f"missing keywords: {list(missing)}"
        else:
            if not is_refusal:
                passed = False
                failure = (
                    f"expected refusal (handoff={q.expected_handoff_reason.value}), "
                    f"got {verdict.value}"
                )

        results.append(
            QuestionResult(
                id=q.id,
                bucket=q.bucket,
                expected_handoff=q.expected_handoff_reason,
                answer_text=answer,
                is_refusal=is_refusal,
                grounding_verdict=verdict,
                keywords_present=present,
                keywords_missing=missing,
                passed=passed,
                failure_reason=failure,
            )
        )

    # Aggregate
    total = len(results)
    grounded = sum(1 for r in results if r.grounding_verdict == GroundingVerdict.GROUNDED)
    ungrounded = sum(
        1 for r in results if r.grounding_verdict == GroundingVerdict.UNGROUNDED
    )
    refused = sum(1 for r in results if r.is_refusal)
    passes = sum(1 for r in results if r.passed)
    fails = total - passes

    # raw_deflection: any answer that wasn't an escalation, regardless of
    # whether it was grounded. This is the marketing-friendly number.
    raw_deflected = sum(1 for r in results if not r.is_refusal)
    raw_deflection = raw_deflected / total if total else 0.0

    # refusal_aware_deflection: a question is "handled correctly" if
    # (a) the agent answered AND was grounded, OR
    # (b) the agent refused when the gold set said it should.
    handled_correctly = 0
    for r, q in zip(results, gold, strict=True):
        if q.expected_handoff_reason is None:
            if r.grounding_verdict == GroundingVerdict.GROUNDED:
                handled_correctly += 1
        else:
            if r.is_refusal:
                handled_correctly += 1
    refusal_aware = handled_correctly / total if total else 0.0

    # Per-bucket
    bucket_counter: Counter[str] = Counter(r.bucket for r in results)
    bucket_scores: list[BucketScore] = []
    for bucket in sorted(bucket_counter):
        rows = [r for r in results if r.bucket == bucket]
        bucket_scores.append(
            BucketScore(
                bucket=bucket,
                total=len(rows),
                answered_grounded=sum(
                    1 for r in rows if r.grounding_verdict == GroundingVerdict.GROUNDED
                ),
                answered_ungrounded=sum(
                    1
                    for r in rows
                    if r.grounding_verdict == GroundingVerdict.UNGROUNDED
                ),
                refused=sum(1 for r in rows if r.is_refusal),
            )
        )

    return Scorecard(
        total=total,
        raw_deflection=raw_deflection,
        refusal_aware_deflection=refusal_aware,
        grounded_count=grounded,
        ungrounded_count=ungrounded,
        refused_count=refused,
        pass_count=passes,
        fail_count=fails,
        bucket_scores=tuple(bucket_scores),
        results=tuple(results),
    )


def render_scorecard(scorecard: Scorecard) -> str:
    """Render a Scorecard as text for the demo and the audit prose."""
    lines = [
        f"Total questions:               {scorecard.total}",
        f"Pass / fail:                   {scorecard.pass_count} / {scorecard.fail_count}",
        "",
        f"raw_deflection:                {scorecard.raw_deflection:6.1%}",
        f"refusal_aware_deflection:      {scorecard.refusal_aware_deflection:6.1%}",
        "",
        f"Grounded answers:              {scorecard.grounded_count}",
        f"Ungrounded answers (REJECT):   {scorecard.ungrounded_count}",
        f"Refused/escalated:             {scorecard.refused_count}",
        "",
        f"{'bucket':<20} {'total':>6} {'grounded':>10} {'ungrnd':>8} {'refused':>9}",
        "-" * 56,
    ]
    for b in scorecard.bucket_scores:
        lines.append(
            f"{b.bucket:<20} {b.total:>6} {b.answered_grounded:>10} "
            f"{b.answered_ungrounded:>8} {b.refused:>9}"
        )
    if scorecard.fail_count > 0:
        lines.append("")
        lines.append("Failures:")
        for r in scorecard.results:
            if not r.passed:
                lines.append(f"  {r.id} ({r.bucket}): {r.failure_reason}")
    return "\n".join(lines)


__all__ = [
    "AnswerFn",
    "BucketScore",
    "GoldQuestion",
    "QuestionResult",
    "Scorecard",
    "build_chunk_index",
    "load_gold_set",
    "oracle_answer_fn",
    "render_scorecard",
    "retrieve_chunks_for_question",
    "run_eval",
]
