---
chunk_id: plan.billing.payment_failed
topic: plan_questions
intent: explain_payment_failure
last_reviewed: 2026-06-28
api_facts_referenced: [invoice.status, invoice.amountDueCents, invoice.paidAt, subscription.status]
---

# When a renewal payment fails

If a renewal payment fails, the invoice stays in `status: "finalized"`
with `amount_due_cents > 0` and `paid_at: null`. The subscription does
**not** flip to `restricted` immediately — the carrier gives a short
grace period (typically 48–72 hours) for the user's payment method to
clear.

## What the agent sees

- `invoice.status == "finalized"` AND
- `invoice.amount_due_cents > 0` AND
- `invoice.paid_at is None`

The `invoice_payment_failed` escalation trigger fires on this exact
combination. The agent does not auto-retry payments and does not tell
the user "your card will be retried tomorrow at noon" — we don't
control that schedule.

## What the agent says

> I can see a payment didn't go through on your last invoice. We'll keep
> service running for a short grace period while the carrier retries.
> If you want to update your payment method now, I can pass that to a
> teammate who'll get it updated for you.

## What changes for the user during grace

- Service keeps working.
- A new card-on-file can be added via the CashCard app (no agent
  action required) or via the human handoff (with agent prep).
- After grace, the subscription flips to `restricted` and the
  `restricted_subscription` trigger takes over — see
  `06_other/restricted_subscription.md`.

## Refunds for the failed charge

There is no refund — the failed charge never settled. The user's bank
may still show a pending authorisation that drops off after a few
business days. The agent should mention this so the user doesn't panic
about a double charge they can see in their banking app.
