---
chunk_id: device.support.list
topic: devices
intent: list_supported_devices
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [sim.type]
---

# Supported devices

CashCard is eSIM-only. Eligible devices must:

1. Have eSIM hardware,
2. Be unlocked (or locked only to a carrier the user has unlocked from),
3. Be sold or imported as a US-region SKU on the launch carriers.

## Confirmed-working families

- **Apple iPhone**: XS and newer (iOS 16+). Including SE 2nd/3rd gen.
- **Google Pixel**: 3 and newer (Android 12+ recommended; Android 13+
  for the OTA-push path on Pixel 7).
- **Samsung Galaxy**: S20+ and newer with One UI 5+. The standard S20
  was eSIM-capable in some regions but not all — confirm with the user
  by model number.
- **Apple iPad**: Pro 2018+, Air 3+, Mini 5+, with cellular SKU.

## Known-not-working

- Any Galaxy device sold as "China unlocked": no eSIM hardware.
- US carrier-locked iPhones still in their lock window.
- Older iPad Air / Mini Wi-Fi-only SKUs (no cellular hardware).

## When in doubt: device check

If the user asks "will my phone work?", the agent should ask for the
exact model + how/where they bought it. Don't promise compatibility
based on the family name alone. The list above is the agent's prior,
not a guarantee.

## Why we don't sell physical SIMs

The product decision is eSIM-only. The agent should not entertain
"can you ship me a physical SIM" requests — the answer is no, and
escalating won't change that. Phrase the refusal politely and point
to the device check tool instead.
