---
chunk_id: esim.refusal.unsupported_device
topic: esim_activation
intent: refuse_unsupported_device
last_reviewed: 2026-06-28
api_facts_referenced: [sim.type]
---

# When the user's device doesn't support our eSIM

CashCard is eSIM-only. If a user is on a device that doesn't support
eSIM, or is in a region/SKU where their device's eSIM is locked to a
specific carrier (e.g. some US carrier-locked iPhones bought in
instalment plans before 2023), we cannot activate them — and we should
not promise we can.

## Devices we know are not supported

- Any phone without eSIM hardware (iPhone XR/XS predecessors, most
  pre-2020 Android handsets).
- Carrier-locked devices from another US carrier still in their
  unlock window.
- iPads bought as Wi-Fi only (no cellular hardware).

## How to phrase the refusal

> CashCard is eSIM-only, so we'd need a phone that supports eSIM and
> isn't locked to another carrier to set you up. From what you've shared,
> that device won't work with us today. Want me to point you to the
> carrier check tool so you can confirm before buying a new phone?

Avoid:
- Listing every supported device by name (the list changes; trust the
  carrier check tool instead).
- Promising a workaround. There isn't one — eSIM-only means eSIM-only.
- Telling the user to "try anyway and see". Each failed activation
  attempt costs the carrier a per-attempt fee.
