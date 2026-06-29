---
chunk_id: other.escalation.two_hop
topic: other
intent: explain_escalation_path
last_reviewed: 2026-06-28
---

# How escalations work

CashCard's day-1 escalation is two-hop:

1. **First hop**: Tier-1 human, in-app chat. SLA-bound to first reply
   within a target window (configured in `cashcard_config.two_hop`).
   Receives the full `EscalationContext` from task1_audit.
2. **Second hop**: Tier-2 specialist. Only reachable from Tier-1, and
   only for: lost device, fraud flag, port escalations older than 24
   hours, multi-line account oddities.

The agent never tells a user "I'm escalating to Tier-2 directly". The
two-hop sequence is non-negotiable for the first 90 days because Tier-2
capacity is small and we want Tier-1 to filter.

## What the user sees

> "I'm going to bring in a teammate who can help with this. They'll
> have everything we've talked about, so you won't need to repeat
> yourself."

The "won't need to repeat" promise is real because we ship the
`EscalationContext` payload — masked PII, recent turns, retrieved
chunks the agent leaned on, and the handoff reason.

## What the teammate sees

- The agent's last answer and the user's last 3 turns.
- The user's account snapshot at the moment of escalation
  (subscription, sim, latest usage, latest invoice).
- Up to the most-recent 3 porting transitions.
- The `HandoffReason` and any structured detail
  (`Trigger.kind`, `Trigger.detail`).

The teammate can re-query the carrier API live for anything that may
have changed in the seconds between handoff and pickup.

## Patterns the agent should not invent

- Tier-2 cold transfers. Always Tier-1 first.
- Direct email handoffs. We use the in-app chat thread, with a
  ticket created automatically on handoff.
- "I'll have someone call you in 5 minutes." The agent doesn't
  control the callback queue.
