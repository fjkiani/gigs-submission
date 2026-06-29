---
chunk_id: esim.transfer.between_devices
topic: esim_activation
intent: transfer_esim
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [eSimProfile.status, sim.type]
---

# Moving your eSIM to a new phone

eSIMs are tied to the device, not the SIM tray, so moving to a new phone
is a delete-and-reissue. CashCard does this for you when you ask — the
old profile is invalidated and a new activation code is sent.

## What the agent can do today

**Read-only**: confirm the user's current SIM ID and current
`eSimProfile.status`, and explain the steps below.

**Cannot do directly**: issue a new eSIM. This requires a write to the
carrier API (POST `/sims/{sim_id}/reissue`). All write actions go to a
human teammate during the day-1 launch window. The agent will
collect the user's new device model and IMEI, summarise it as an
escalation, and hand off.

## What the user should know up-front

- The **old profile stops working** the moment we issue the new one.
  Make sure the new phone is the one you want service on before you
  ask us to transfer.
- The activation code is single-use; if you delete it from the email
  thread, we can resend, but the count of resends per support window
  is limited.
- We can only transfer between supported device families. Apple Watch
  cellular plans are a separate flow.

## Iphone-to-iPhone quick transfer

Apple supports "Convert Cellular Plan" / eSIM Quick Transfer between
two iPhones running iOS 16+. If both phones are signed into the same
Apple ID, the user can do this themselves without contacting us. We
will still see the new `eSimProfile.status` flip when the new device
reports the install.
