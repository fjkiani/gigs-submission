"""KB freshness watcher — Svix webhook -> KB stale-flag emitter.

Gigs delivers events via Svix as signed CloudEvents (see
/docs/core/events/events-webhooks). Headers we verify:

    webhook-id          unique message id
    webhook-timestamp   unix seconds; we enforce a 5-minute skew window
    webhook-signature   space-separated list of "v1,<base64-hmac-sha256(secret, id.timestamp.body)>"

The watcher's job is small and focused: when an event arrives that *could*
invalidate KB content (plan updated, policy updated, provider config changed),
emit a structured `StaleFlag` into a queue for the platform team to triage.

We do NOT delete chunks or auto-rewrite them — the platform team approves the
delta. This is the loop the audit doc §3 recommends.

Defensive choices baked in:
  - Constant-time signature comparison.
  - Timestamp skew enforced (replay window).
  - We accept the signature format Svix actually uses ("v1,<sig>"; multiple
    space-separated entries; any matching one passes).
  - We never deserialize the body before signature passes — the body text is
    the canonical thing we sign over.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class WebhookVerificationError(Exception):
    """Raised when a webhook payload fails authenticity checks."""


# Default skew window. Svix recommends 5 minutes; we enforce that.
DEFAULT_SKEW_SECONDS = 300


def _now_unix() -> int:
    return int(datetime.now(tz=UTC).timestamp())


def _sign(secret_bytes: bytes, msg: str) -> str:
    """Compute Svix-style base64 HMAC-SHA256."""
    mac = hmac.new(secret_bytes, msg.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("ascii")


def make_signature_header(*, msg_id: str, timestamp: int, body: str, secret: bytes) -> str:
    """Build a Svix-format signature header from raw inputs. Used by tests."""
    sig = _sign(secret, f"{msg_id}.{timestamp}.{body}")
    return f"v1,{sig}"


def verify_signature(
    *,
    headers: dict[str, str],
    body: str,
    secrets: list[bytes],
    skew_seconds: int = DEFAULT_SKEW_SECONDS,
    now_unix: int | None = None,
) -> None:
    """Verify a Svix webhook signature. Raises WebhookVerificationError on fail.

    Args:
        headers: lowercased-key header dict. Must contain
            'webhook-id', 'webhook-timestamp', 'webhook-signature'.
        body: raw request body as bytes-decoded UTF-8 string. Critical:
            this MUST be the byte-perfect body the sender signed; don't
            re-serialize JSON.
        secrets: list of acceptable signing secrets (for rotation; tries each).
        skew_seconds: max age for the webhook-timestamp.
        now_unix: override the clock for tests.
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    required = ("webhook-id", "webhook-timestamp", "webhook-signature")
    missing = [k for k in required if k not in lowered]
    if missing:
        raise WebhookVerificationError(f"missing headers: {missing}")

    msg_id = lowered["webhook-id"].strip()
    try:
        ts = int(lowered["webhook-timestamp"].strip())
    except ValueError as e:
        raise WebhookVerificationError("non-integer webhook-timestamp") from e

    now = now_unix if now_unix is not None else _now_unix()
    if abs(now - ts) > skew_seconds:
        raise WebhookVerificationError(
            f"timestamp skew {abs(now - ts)}s exceeds window {skew_seconds}s"
        )

    sig_header = lowered["webhook-signature"].strip()
    # Header is a space-separated list of "v1,<b64sig>" entries; any matching one passes.
    entries = sig_header.split()
    expected_msg = f"{msg_id}.{ts}.{body}"

    for secret in secrets:
        expected_sig = _sign(secret, expected_msg)
        for entry in entries:
            # Accept "v1,<sig>" and ignore other versions defensively.
            if "," not in entry:
                continue
            ver, candidate = entry.split(",", 1)
            if ver != "v1":
                continue
            if hmac.compare_digest(expected_sig, candidate):
                return  # OK
    raise WebhookVerificationError("no candidate signature matched")


# ---------------------------------------------------------------------------
# KB stale-flag emission.
# ---------------------------------------------------------------------------

# Event types that can invalidate KB content. This is the audit doc's
# "what events do we listen to" answer in code.
KB_INVALIDATING_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Plans
        "com.gigs.plan.created",
        "com.gigs.plan.updated",
        "com.gigs.plan.archived",
        # Subscriptions — affect generic "what happens when I cancel" KB
        "com.gigs.subscription.updated",
        "com.gigs.subscriptionChange.created",
        "com.gigs.subscriptionChange.updated",
        # Add-ons
        "com.gigs.addon.updated",
        # Portings — donor provider rules change
        "com.gigs.porting.declined",
        # Invoices — billing flow language changes
        "com.gigs.invoice.finalized",
        # Network / provider config
        "com.gigs.networkAvailability.updated",
    }
)


@dataclass(frozen=True)
class StaleFlag:
    """An entry in the platform team's KB freshness queue."""

    flagged_at: datetime
    project_id: str
    event_id: str
    event_type: str
    reason: str
    referenced_resource_ids: tuple[str, ...] = field(default_factory=tuple)


def event_to_stale_flag(payload: dict[str, Any]) -> StaleFlag | None:
    """Translate a verified CloudEvents payload into a StaleFlag, if relevant.

    Args:
        payload: parsed JSON of the webhook body. Must match Gigs' CloudEvents
            envelope: {object:'event', id, type, project, time, data, ...}.

    Returns:
        StaleFlag if the event type is in KB_INVALIDATING_EVENT_TYPES, else None.

    Raises:
        ValueError on malformed envelope.
    """
    if payload.get("object") != "event":
        raise ValueError("payload is not a CloudEvents 'event' object")
    etype = payload.get("type")
    if not isinstance(etype, str) or not etype.startswith("com.gigs."):
        raise ValueError(f"invalid event type: {etype!r}")
    if etype not in KB_INVALIDATING_EVENT_TYPES:
        return None

    event_id = str(payload.get("id", ""))
    project_id = str(payload.get("project", ""))
    when_raw = payload.get("time")
    when = (
        datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
        if isinstance(when_raw, str)
        else datetime.now(tz=UTC)
    )

    data = payload.get("data") or {}
    referenced_ids = _extract_referenced_ids(data)

    return StaleFlag(
        flagged_at=when,
        project_id=project_id,
        event_id=event_id,
        event_type=etype,
        reason=_default_reason_for(etype),
        referenced_resource_ids=referenced_ids,
    )


def _default_reason_for(etype: str) -> str:
    """Short, human-readable rationale per event type."""
    base = etype.removeprefix("com.gigs.")
    return {
        "plan.created": "New plan; KB likely needs a section for it.",
        "plan.updated": "Plan changed; allowances/limits text may be stale.",
        "plan.archived": "Plan archived; KB references must call this out or remove.",
        "subscription.updated": "Subscription rules may have changed.",
        "subscriptionChange.created": "Mid-period change semantics may have shifted.",
        "subscriptionChange.updated": "Mid-period change rules may have changed.",
        "addon.updated": "Add-on terms may have changed; review related KB.",
        "porting.declined": "New decline code may need KB coverage.",
        "invoice.finalized": "Billing-flow copy may need review.",
        "networkAvailability.updated": "Provider/coverage change; coverage KB may be stale.",
    }.get(base, f"Event {etype} is in the KB-invalidating set.")


def _extract_referenced_ids(data: dict[str, Any]) -> tuple[str, ...]:
    """Pull out IDs from common resource shapes Gigs uses."""
    out: list[str] = []
    for key in ("id", "planId", "subscriptionId", "simId", "portingId", "invoiceId", "addonId"):
        v = data.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return tuple(out)


# ---------------------------------------------------------------------------
# Top-level orchestration — what an HTTP handler would call.
# ---------------------------------------------------------------------------


def handle_webhook(
    *,
    headers: dict[str, str],
    raw_body: str,
    secrets: list[bytes],
    now_unix: int | None = None,
) -> StaleFlag | None:
    """End-to-end: verify, parse, return a stale flag or None.

    Designed to be the *single* function a FastAPI/Lambda handler calls.
    Any exception means "do not ack the webhook" — Svix will retry.
    """
    verify_signature(headers=headers, body=raw_body, secrets=secrets, now_unix=now_unix)
    payload = json.loads(raw_body)
    if not isinstance(payload, dict):
        raise ValueError("body is not a JSON object")
    return event_to_stale_flag(payload)
