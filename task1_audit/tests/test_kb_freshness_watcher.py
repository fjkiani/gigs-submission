"""Tests for task1_audit.kb_freshness_watcher."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from task1_audit.kb_freshness_watcher import (
    DEFAULT_SKEW_SECONDS,
    KB_INVALIDATING_EVENT_TYPES,
    StaleFlag,
    WebhookVerificationError,
    event_to_stale_flag,
    handle_webhook,
    make_signature_header,
    verify_signature,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SECRET_A = b"whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
SECRET_B = b"whsec_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"


def _envelope(
    *,
    event_type: str = "com.gigs.plan.updated",
    project: str = "prj_abc",
    event_id: str = "evt_1",
    when: str = "2026-06-27T10:30:00Z",
    data: dict | None = None,
) -> dict:
    return {
        "object": "event",
        "id": event_id,
        "type": event_type,
        "project": project,
        "time": when,
        "data": data or {"id": "plan_xyz"},
    }


def _signed_headers(
    *,
    body: str,
    secret: bytes = SECRET_A,
    msg_id: str = "msg_1",
    ts: int | None = None,
) -> tuple[dict[str, str], int]:
    ts = ts or int(datetime.now(tz=UTC).timestamp())
    sig = make_signature_header(msg_id=msg_id, timestamp=ts, body=body, secret=secret)
    return (
        {
            "webhook-id": msg_id,
            "webhook-timestamp": str(ts),
            "webhook-signature": sig,
        },
        ts,
    )


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_happy_path_roundtrip(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        verify_signature(headers=headers, body=body, secrets=[SECRET_A], now_unix=ts)

    def test_case_insensitive_headers(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        upper = {k.upper(): v for k, v in headers.items()}
        verify_signature(headers=upper, body=body, secrets=[SECRET_A], now_unix=ts)

    def test_missing_header_rejected(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        del headers["webhook-id"]
        with pytest.raises(WebhookVerificationError, match="missing headers"):
            verify_signature(headers=headers, body=body, secrets=[SECRET_A], now_unix=ts)

    def test_non_integer_timestamp_rejected(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        headers["webhook-timestamp"] = "not-a-number"
        with pytest.raises(WebhookVerificationError, match="non-integer"):
            verify_signature(headers=headers, body=body, secrets=[SECRET_A], now_unix=ts)

    def test_skew_window_rejected(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        # Sign with an old timestamp, then verify "now" much later.
        old_ts = 1_700_000_000
        headers, _ = _signed_headers(body=body, ts=old_ts)
        with pytest.raises(WebhookVerificationError, match="skew"):
            verify_signature(
                headers=headers,
                body=body,
                secrets=[SECRET_A],
                now_unix=old_ts + DEFAULT_SKEW_SECONDS + 1,
            )

    def test_skew_window_inclusive(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        ts = 1_700_000_000
        headers, _ = _signed_headers(body=body, ts=ts)
        # Right at the edge — still passes.
        verify_signature(
            headers=headers,
            body=body,
            secrets=[SECRET_A],
            now_unix=ts + DEFAULT_SKEW_SECONDS,
        )

    def test_secret_rotation(self) -> None:
        # Old secret signed; verifier accepts because [B, A] both tried.
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body, secret=SECRET_A)
        verify_signature(
            headers=headers,
            body=body,
            secrets=[SECRET_B, SECRET_A],
            now_unix=ts,
        )

    def test_bad_secret_rejected(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body, secret=SECRET_A)
        with pytest.raises(WebhookVerificationError, match="no candidate"):
            verify_signature(headers=headers, body=body, secrets=[SECRET_B], now_unix=ts)

    def test_tampered_body_rejected(self) -> None:
        body = json.dumps(_envelope(), separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        tampered = body.replace("plan_xyz", "plan_evil")
        with pytest.raises(WebhookVerificationError, match="no candidate"):
            verify_signature(headers=headers, body=tampered, secrets=[SECRET_A], now_unix=ts)

    def test_unknown_signature_version_ignored(self) -> None:
        # If header has only a v2 entry, no v1 match -> reject.
        body = json.dumps(_envelope(), separators=(",", ":"))
        _, ts = _signed_headers(body=body)
        bad_headers = {
            "webhook-id": "msg_1",
            "webhook-timestamp": str(ts),
            "webhook-signature": "v2,abcdef",
        }
        with pytest.raises(WebhookVerificationError, match="no candidate"):
            verify_signature(
                headers=bad_headers,
                body=body,
                secrets=[SECRET_A],
                now_unix=ts,
            )


# ---------------------------------------------------------------------------
# Event -> StaleFlag translation
# ---------------------------------------------------------------------------


class TestEventToStaleFlag:
    @pytest.mark.parametrize("etype", sorted(KB_INVALIDATING_EVENT_TYPES))
    def test_invalidating_event_yields_flag(self, etype: str) -> None:
        env = _envelope(event_type=etype, event_id=f"evt_{etype}")
        flag = event_to_stale_flag(env)
        assert flag is not None
        assert flag.event_type == etype
        assert flag.event_id == f"evt_{etype}"
        assert flag.project_id == "prj_abc"
        assert isinstance(flag.flagged_at, datetime)

    def test_non_invalidating_event_returns_none(self) -> None:
        env = _envelope(event_type="com.gigs.sim.created")
        assert event_to_stale_flag(env) is None

    def test_non_event_object_rejected(self) -> None:
        env = _envelope()
        env["object"] = "not-event"
        with pytest.raises(ValueError, match="not a CloudEvents"):
            event_to_stale_flag(env)

    def test_non_namespaced_type_rejected(self) -> None:
        env = _envelope(event_type="stripe.charge.succeeded")
        with pytest.raises(ValueError, match="invalid event type"):
            event_to_stale_flag(env)

    def test_naive_time_falls_back_to_now(self) -> None:
        env = _envelope(event_type="com.gigs.plan.updated")
        # Remove the time string entirely.
        env.pop("time")
        flag = event_to_stale_flag(env)
        assert flag is not None
        # flagged_at must be UTC-aware.
        assert flag.flagged_at.tzinfo is not None

    def test_referenced_ids_extracted(self) -> None:
        env = _envelope(
            event_type="com.gigs.plan.updated",
            data={"id": "plan_xyz", "planId": "plan_xyz"},
        )
        flag = event_to_stale_flag(env)
        assert flag is not None
        # 'id' and 'planId' both pulled in.
        assert "plan_xyz" in flag.referenced_resource_ids


class TestKBInvalidatingEventTypes:
    def test_exactly_ten(self) -> None:
        assert len(KB_INVALIDATING_EVENT_TYPES) == 10

    def test_all_namespaced(self) -> None:
        assert all(t.startswith("com.gigs.") for t in KB_INVALIDATING_EVENT_TYPES)


# ---------------------------------------------------------------------------
# StaleFlag frozen-ness
# ---------------------------------------------------------------------------


class TestStaleFlagFrozen:
    def test_stale_flag_is_frozen(self) -> None:
        flag = StaleFlag(
            flagged_at=datetime.now(tz=UTC),
            project_id="prj",
            event_id="evt",
            event_type="com.gigs.plan.updated",
            reason="r",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            flag.reason = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# End-to-end handle_webhook
# ---------------------------------------------------------------------------


class TestHandleWebhook:
    def test_happy_path_emits_flag(self) -> None:
        env = _envelope(event_type="com.gigs.plan.updated")
        body = json.dumps(env, separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        flag = handle_webhook(
            headers=headers, raw_body=body, secrets=[SECRET_A], now_unix=ts
        )
        assert flag is not None
        assert flag.event_type == "com.gigs.plan.updated"

    def test_unknown_event_skips_flag(self) -> None:
        env = _envelope(event_type="com.gigs.sim.created")
        body = json.dumps(env, separators=(",", ":"))
        headers, ts = _signed_headers(body=body)
        flag = handle_webhook(
            headers=headers, raw_body=body, secrets=[SECRET_A], now_unix=ts
        )
        assert flag is None

    def test_bad_signature_raises(self) -> None:
        env = _envelope(event_type="com.gigs.plan.updated")
        body = json.dumps(env, separators=(",", ":"))
        headers, ts = _signed_headers(body=body, secret=SECRET_A)
        with pytest.raises(WebhookVerificationError):
            handle_webhook(
                headers=headers, raw_body=body, secrets=[SECRET_B], now_unix=ts
            )

    def test_non_json_body_raises(self) -> None:
        body = "not-json"
        headers, ts = _signed_headers(body=body)
        with pytest.raises(json.JSONDecodeError):
            handle_webhook(
                headers=headers, raw_body=body, secrets=[SECRET_A], now_unix=ts
            )

    def test_non_object_body_raises(self) -> None:
        body = "123"
        headers, ts = _signed_headers(body=body)
        with pytest.raises(ValueError, match="not a JSON object"):
            handle_webhook(
                headers=headers, raw_body=body, secrets=[SECRET_A], now_unix=ts
            )
