---
chunk_id: device.troubleshooting.basics
topic: devices
intent: troubleshoot_device
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
---

# Basic device troubleshooting

If a CashCard line was working and stopped, walk through these in
order. Each step has a "stop here if it works" exit.

## 1. Carrier status

Check `subscription.status` first. If it's not `active`, no amount of
device fiddling helps. Likely culprits:

- `restricted` — see `02_plan_questions/payment_failed.md` and
  `06_other/restricted_subscription.md`.
- `ended` — the user cancelled or the subscription rolled off; they need
  to resubscribe.

## 2. Airplane mode toggle

Classic but works. Toggle airplane mode on, wait 10 seconds, toggle
off. Forces the device to re-handshake with the carrier.

## 3. eSIM profile state

Settings → Cellular (iOS) or Settings → SIM manager (Android). Confirm
the CashCard line is listed and the cellular data toggle is on. Some
users accidentally disable the line when adding a second eSIM.

## 4. APN reset

CashCard pushes APNs automatically. If the device shows manual APN
entries, the user (or a previous carrier) overrode the auto-config.
Walk them through Settings → Cellular → CashCard line → Cellular Data
Network → Reset Settings.

## 5. Network reset

Last resort before escalation. Settings → General → Transfer or Reset
iPhone → Reset → Reset Network Settings. Warn the user this also
forgets every Wi-Fi password the device has saved.

## When to escalate

If 1–5 don't resolve it, escalate with: device model, OS version,
the user's report of what stopped working, and the last value seen for
`subscription.status` + `eSimProfile.status`. The teammate will use
those values verbatim — do not paraphrase them.
