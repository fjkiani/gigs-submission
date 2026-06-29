---
chunk_id: roaming.no_service.abroad
topic: roaming
intent: troubleshoot_no_service_abroad
last_reviewed: 2026-06-28
api_facts_referenced: [plan.coverage, sim.lastSeenAt]
---

# "I'm abroad and have no service"

Default state. CashCard is US-only at launch. Without a roaming add-on,
the line will show "no service" the moment the device hands over to a
foreign network.

## Triage

1. Read the user's current plan and check
   `plan.coverage`. If the country isn't listed and `plan.roamingAddOns`
   is empty for the user, this is expected behaviour.
2. If they have a roaming pass attached and still have no service:
   confirm the pass is for the country they're in, not a neighbouring
   one (people frequently buy "Europe" passes and travel to
   Switzerland, which isn't always in the bundle).
3. If the pass should cover the country and the device is on a
   compatible network, escalate. Carrier provisioning issues abroad
   are rare but they happen.

## What the agent shouldn't promise

- A timeline for when service will work.
- That toggling roaming on/off will fix it (toggling roaming in
  device settings is irrelevant for eSIM — the line either has a
  pass or it doesn't).
- That a refund will be issued for the time abroad.

## Phrasing

> Your CashCard plan is US-only by default, so no service abroad is the
> expected behaviour without a roaming pass. Want me to flag this to a
> teammate so we can get a pass set up — or if you already have one,
> dig into why it's not working?

Both branches are escalations because both involve a write or a deeper
carrier-side check.
