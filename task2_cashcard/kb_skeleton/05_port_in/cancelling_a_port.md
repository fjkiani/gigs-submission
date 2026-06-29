---
chunk_id: porting.us.cancellation
topic: port_in
intent: cancel_port
last_reviewed: 2026-06-28
api_facts_referenced: [porting.status]
---

# Cancelling an in-flight port

A user can cancel a port before it completes. The cancellation
window depends on the donor carrier — typically up to a few hours
before the scheduled cutover.

This is a write action. Day-1 agent **does not** cancel ports directly.
It hands off with the user's account context attached.

## What the agent collects

1. The reason for cancellation (changed mind, ported wrong number,
   forgot PIN, etc.) — informational, not used to gate.
2. Whether the user wants to keep their current CashCard line active
   while they decide (yes by default — we don't deactivate anything
   without confirmation).
3. The user's preferred follow-up channel.

## What the agent says

> I'll get a teammate on this right away — cancelling a port has to be
> done while it's still cancellable, so we want to move fast. While you
> wait, do **not** start any new port requests with any other carrier,
> as that can complicate the cancellation.

## What the agent never says

- "I've cancelled your port." (The agent didn't; a teammate will.)
- "Your old line will be reconnected." (The donor carrier may have
  already initiated their disconnect.)
- "There's no charge for cancelling." (Donor carriers sometimes charge
  port-out fees; we don't have visibility into those.)

## Post-cancellation

Once a teammate confirms, the agent can quote the new
`porting.status` from the API. Cancelled ports show up with a clear
status; the user keeps any phone number they already had on CashCard.
