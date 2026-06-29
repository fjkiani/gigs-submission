---
chunk_id: plan.overview.how_plans_work
topic: plan_questions
intent: explain_plans
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [plan.allowances, plan.coverage, plan.priceCents, plan.currency]
---

# How CashCard plans work

A plan on CashCard is a monthly subscription bundle. Three things matter
to most users: the **allowances** (data/talk/text), the **coverage**
(which countries the allowances apply in), and the **price**.

## Allowances

Allowances are pulled from the carrier API per plan. Each plan exposes:

- `data_mb` — total data per period (some plans are unlimited, in which
  case the field is `unlimited: true` and the cap on full-speed data is
  reported separately).
- `voice_minutes` — domestic call minutes.
- `sms_count` — domestic text count.

Agent rule: **never quote a number you didn't read from the API**. If the
plan doc here mentions "5 GB" but the API says `data_mb: 6144`, the API
wins. Quote what the API said for *this user's plan*.

## Coverage

CashCard launches in the US only. All plans cover the 50 states + DC.
Allowances do **not** apply in other countries unless the plan
explicitly includes roaming (see `04_roaming/`). If the plan doesn't
list a country in `plan.coverage`, the user has no service there.

## Billing cycle

The cycle starts on the day of subscription activation, not the 1st of
the month. Renewal happens on the same date the following month. If
that date doesn't exist (e.g. the 31st in February), the cycle renews
on the last day of the next month.
