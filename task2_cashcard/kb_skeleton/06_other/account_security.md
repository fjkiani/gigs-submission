---
chunk_id: other.security.account_takeover_signals
topic: other
intent: handle_security_signal
last_reviewed: 2026-06-28
api_facts_referenced: [recentEvents]
---

# Account security signals

Some signals in `recent_events` raise the bar for what the agent will
do without a human in the loop:

- Recent password reset (within 30 minutes).
- Recent change to the email on file.
- Recent change to the primary payment method.
- Multiple failed logins in the last hour.

When any of these are present, **all writes go to a human regardless of
the standard guardrail setting**. The configured
`guardrails.read_only_writes` flag is a floor, not a ceiling.

## What the agent says

If the user asks for something that would be a write and a recent
security event is on file:

> Before I make any changes, I want to flag that there's been recent
> activity on your account (password reset/payment method change/etc).
> A teammate is going to take it from here — they'll double-check it's
> really you before doing anything that changes the account.

Do not name the user's email or the new payment method's last 4 digits
back to them in this phrasing — that's PII the canary will flag (see
`canary_pii_in_answer`).

## What the agent never does in this state

- Process the requested write, even if guardrails would normally allow
  it.
- Speculate about whether the security event was the user.
- Quote the timestamps or geolocations of the events.
- Add the user's email or phone number to their conversation as a
  "let me confirm".

## Escalation payload

The handoff payload carries `recent_events` verbatim. Tier-1 sees the
event types and timestamps and can match them against the user's story.
