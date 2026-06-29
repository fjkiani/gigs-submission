"""Task 1 — Agentic support layer audit.

Code-first companion to ``01_TASK1_AUDIT.md``. Public surface:

- ``escalation_context``   — structured human-handoff packet for tickets
- ``failure_taxonomy``     — 7-axis classifier for grounded-answer failures
- ``grounding_check``      — offline grounding gate (refuse vs ground)
- ``kb_freshness_watcher`` — Svix webhook -> KB stale-flag emitter
"""

from task1_audit.escalation_context import (
    EscalationContext,
    HandoffReason,
    UsageSnapshot,
    UserSnapshot,
    mask_email,
    mask_full_name,
    mask_phone,
)
from task1_audit.failure_taxonomy import (
    FailureAnnotation,
    FailureAxis,
    distribution,
)
from task1_audit.grounding_check import (
    GroundingReport,
    GroundingVerdict,
    check_grounding,
)
from task1_audit.kb_freshness_watcher import (
    KB_INVALIDATING_EVENT_TYPES,
    StaleFlag,
    WebhookVerificationError,
    event_to_stale_flag,
    handle_webhook,
    make_signature_header,
    verify_signature,
)

__all__ = [
    "KB_INVALIDATING_EVENT_TYPES",
    "EscalationContext",
    "FailureAnnotation",
    "FailureAxis",
    "GroundingReport",
    "GroundingVerdict",
    "HandoffReason",
    "StaleFlag",
    "UsageSnapshot",
    "UserSnapshot",
    "WebhookVerificationError",
    "check_grounding",
    "distribution",
    "event_to_stale_flag",
    "handle_webhook",
    "make_signature_header",
    "mask_email",
    "mask_full_name",
    "mask_phone",
    "verify_signature",
]
