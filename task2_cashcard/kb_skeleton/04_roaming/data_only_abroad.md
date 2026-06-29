---
chunk_id: roaming.data_only.abroad
topic: roaming
intent: roaming_data_only
last_reviewed: 2026-06-28
api_facts_referenced: [plan.coverage, plan.roamingAddOns]
---

# "I just want data abroad"

Users frequently ask for "just data" while travelling so they can use
WhatsApp/iMessage without a voice plan. This is a real use case — and
on the launch carriers, the right answer is a data-only roaming
add-on, not a workaround.

## What's available

The carrier API exposes per-country data passes in
`plan.roamingAddOns`. Typical shape:

- A 1 GB / 7-day pass for region "Europe",
- A 3 GB / 14-day pass,
- A 1 GB / 7-day pass for "Mexico + Canada",
- Region availability varies by launch carrier (p3 has the widest, p15
  the narrowest).

The agent must read the add-ons live and quote what the API returns,
not memorise prices. If the carrier sunsets a pass, the API stops
listing it.

## Voice/SMS abroad

We tell users abroad to expect no voice/SMS without an add-on. Both
features cost the carrier per-attempt fees that don't have a clean
allowance model. If the user pushes for voice abroad, the answer is
"we'll need a teammate to set up a voice-inclusive pass" — escalate.

## Activation timing

Data passes activate immediately when purchased. **Buy them before you
land.** The agent should remind users of this; "purchasing while
abroad on hotel Wi-Fi" works fine, but "purchasing while abroad on no
network" obviously doesn't.

## Refund posture

Once a data pass is purchased it is non-refundable unless the carrier
fails to provision it. The agent does not promise a refund. If the
user asks, route to a human.
