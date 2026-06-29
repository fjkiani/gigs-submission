---
chunk_id: roaming.policy.overview
topic: roaming
intent: explain_roaming
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [plan.coverage, plan.roamingAddOns]
---

# Roaming on CashCard

CashCard launches with a US-only base plan. Roaming is **opt-in** via a
roaming add-on and is **not** automatic when crossing a border. Users
who land abroad without an add-on will see "no service".

## How the agent handles roaming requests

1. Read `plan.coverage` for the user's current plan.
2. Read `plan.roamingAddOns` for available add-ons.
3. If the user has a roaming add-on already attached and is on a
   covered country, explain the allowance.
4. If not, do **not** auto-purchase. Roaming add-on purchase is a write;
   it goes to a human teammate during the day-1 launch window.

## Phrasing

> Your current plan covers the US. To use data, calls, or texts in
> [country], you'd need to add a roaming pass. I can pass that to a
> teammate who'll get it set up for you — do you have specific dates?

Avoid:

- "You'll be charged $X per MB". The carrier per-MB pricing only
  applies on plans that don't have a roaming add-on, and the agent
  shouldn't quote per-MB numbers — they vary by country and the
  carrier passes those through, not us.
- "Just turn off data and you're fine". The user may still incur
  charges on background SMS or voice depending on the device. Better:
  set up the roaming add-on or expect no service.

## Why this is a small bucket

The contact-mix prior puts roaming at 10%. That number assumes users
read the launch communications and know we are US-only. If real
traffic skews higher, the gap report will surface it and we expand
this folder.
