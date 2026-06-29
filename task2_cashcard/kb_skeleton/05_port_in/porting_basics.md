---
chunk_id: porting.us.basics
topic: port_in
intent: explain_porting
last_reviewed: 2026-06-28
api_facts_referenced: [porting.requiredFields, porting.status]
---

# Porting your number to CashCard (US)

US number portability is a federally-mandated process. CashCard supports
porting in from any US carrier on day 1, subject to the user's number
being portable.

## What "portable" means

A US wireless number is portable if:

- The number is active and in good standing with the donor carrier.
- The number has not been previously ported within the last 24 hours
  (some donor carriers enforce a short cool-down).
- The donor carrier hasn't placed a "port protection" lock on the
  account (this is a user-facing setting on the donor side).

## What the user provides

Six fields. All six are required for US ports:

1. Account number with the donor carrier.
2. Account PIN (port-out PIN, not the regular account password).
3. Last 4 digits of the account holder's SSN.
4. Zip code on the donor account.
5. The phone number being ported.
6. The donor provider name (free text — we map it).

These are produced by `kb_seed_from_api.derive_porting_required_fields("US")`
and merged into the retriever. The agent **must not** invent additional
fields or omit one — the seeded chunk is the source of truth.

## What happens after submission

The agent submits the port to the carrier API (this is the one
controlled write the day-1 agent might do, depending on guardrails —
see `cashcard_config.guardrails.read_only_writes`). With read-only
mode on day 1, the agent collects the six fields and hands off.

Typical timeline: 1–24 hours for the donor carrier to release the
number. The agent never quotes a specific time inside that window.
