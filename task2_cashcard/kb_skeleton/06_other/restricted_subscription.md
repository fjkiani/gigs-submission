---
chunk_id: other.subscription.restricted
topic: other
intent: explain_restriction
last_reviewed: 2026-06-28
api_facts_referenced: [subscription.status, subscription.restrictionReason]
---

# Restricted subscriptions

When `subscription.status == "restricted"`, the carrier is suppressing
the line. Common reasons exposed in
`subscription.restrictionReason`:

- `payment_overdue` — grace period expired after a failed payment.
- `fraud_flag` — automated risk system pulled the line.
- `usage_violation` — pattern of abuse (e.g. unlimited plan used for
  hotspot far beyond policy).
- `manual_hold` — a teammate flagged the account.

## The agent never works around a restriction

The week-1 canary `restriction_ignored` watches for action verbs
("activate", "use ", "enable", "go ahead") in answers given on a
restricted subscription. The agent's job is to **explain the
restriction and escalate** — not to suggest a workaround.

## Phrasing

> Your subscription is currently restricted — looks like a
> `payment_overdue` flag from the carrier. I can connect you with a
> teammate who can sort the billing side and lift the restriction.

If the restriction reason is `fraud_flag`, do **not** speculate about
what triggered it. The fraud team handles that and the agent doesn't
have visibility. Just escalate.

## What restriction blocks

- Outbound calls, SMS, data.
- Plan changes (the carrier rejects writes against restricted
  subscriptions).
- Roaming pass purchases.

Inbound calls/SMS may still arrive. Don't promise they will or won't —
that depends on the carrier.

## Escalation context

When escalating, the handoff payload includes
`subscription.status`, `subscription.restriction_reason`, and the user's
last 5 conversation turns. The teammate sees everything the agent saw.
