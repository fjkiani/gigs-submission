---
chunk_id: device.lost_or_stolen.policy
topic: devices
intent: report_lost_device
last_reviewed: 2026-06-28
---

# Lost or stolen device

This is a write action — the line gets suspended and a new eSIM
profile generated for the user's replacement device. The day-1 agent
**cannot** do this directly. It collects the report and hands off to a
human within an SLA target.

## What the agent collects

1. Approximate time and location of loss.
2. Whether the user has a replacement device ready (yes/no/unknown).
3. The user's preferred contact for the human callback.
4. Whether they want to suspend the line immediately (yes by default).
5. Whether they've filed a police report (informational only — not
   required for us to suspend).

## What the agent says

> I'm sorry — I'll get a teammate on this within the hour so we can
> suspend the line and get a new eSIM ready for your replacement device.
> While you wait, do not click any "your eSIM is ready" emails unless
> they come from a confirmed CashCard address — phishing attempts spike
> after lost-device reports.

## What the agent never says

- "I've suspended your line." (We didn't; a human teammate will.)
- "Your charges have been refunded for the period since you lost it."
  (Possible policy outcome, but refund decisions are not in scope for
  the agent.)
- "You won't be charged for anything that happens after now." (We can't
  promise that until the line is actually suspended.)

## Fraud watch

If usage data shows a spike right around the reported loss time, mention
it in the handoff. The teammate may need to escalate further to the
fraud team.
