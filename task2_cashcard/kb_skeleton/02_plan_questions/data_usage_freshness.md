---
chunk_id: plan.usage.data_freshness
topic: plan_questions
intent: explain_usage_lag
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [usage.dataMbUsed, usage.usage_updated_at]
---

# Data usage numbers and freshness

Usage numbers in CashCard come from the carrier, not from the device.
There is **always a lag**. For our launch carriers:

- **p3**: usage typically updates every 15 minutes.
- **p14**: usage typically updates every 30 minutes.
- **p15**: usage typically updates every 60 minutes.

These are typical, not guaranteed. The agent reads
`usage.usage_updated_at` from the API and decides whether the data is
fresh enough to quote.

## The "as of" rule

If the user asks "how much data have I used?", the agent must:

1. Read `usage.dataMbUsed` and `usage.usage_updated_at`.
2. Compute age = `now - usage_updated_at`.
3. If age ≤ 1 hour, answer like:

   > You've used 4.2 GB this cycle as of 12 minutes ago.

4. If age > 1 hour, refuse to give a number and explain why:

   > The carrier hasn't reported new usage in over an hour, so I don't
   > want to give you a number I can't trust. Want me to flag this to
   > a teammate so we can chase the carrier for fresh data?

The "as of" qualifier is non-negotiable. The week-1 canary
`stale_usage_no_qualifier` will fire on any answer that quotes a number
without an "as of"/"last reported"/"updated at" phrase, even if the
data is fresh.

## What "approaching limit" looks like

The agent does **not** estimate when the user will run out. We don't have
their consumption rate and the carrier doesn't expose it. The right
answer is "you've used 4.2 GB out of 5 GB as of 12 minutes ago", not
"you'll hit your limit by tomorrow".
