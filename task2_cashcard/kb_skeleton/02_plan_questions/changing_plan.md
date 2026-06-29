---
chunk_id: plan.change.during_cycle
topic: plan_questions
intent: change_plan
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
---

# Switching plans

A plan change is a write to the carrier API
(`POST /subscriptions/{id}/plan`). During the day-1 launch window we do
not let the agent do this directly — the request goes to a human
teammate. The write-action canary fires on any agent answer that
implies "I've changed your plan" or "your new plan is active".

## What the agent does

1. Confirm the user's current plan and renewal date from the API.
2. Show what the requested plan would cost and what allowances change.
3. Confirm the timing (effective immediately / at next cycle — see
   below).
4. Hand off to a human with a one-line summary and the plan IDs.

## Timing

CashCard prorates plan upgrades and pushes downgrades to next cycle.

- **Upgrade** (higher monthly price): effective immediately, charged
  prorated.
- **Downgrade** (lower monthly price): effective at next cycle to avoid
  refund weirdness on already-paid time.

The agent must phrase this in the future tense ("once a teammate
confirms, your new plan will start..."), not as a completed action.

## Refunds and credits

We never quote a specific refund or credit amount. The proration math
runs on the carrier side and the final number can shift slightly if a
charge is pending. The agent's job is to explain the rule, not the
dollar amount.
