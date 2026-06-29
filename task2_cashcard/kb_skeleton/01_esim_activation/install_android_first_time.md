---
chunk_id: esim.install.android.first_time
topic: esim_activation
intent: how_to_install
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [eSimProfile.status, sim.type]
---

# Installing your CashCard eSIM on Android (first time)

CashCard sends the eSIM as an activation code (LPA string) by email and
also exposes it as a QR code in the CashCard app. Android does not yet
have a universal OTA push path, so the flow varies by manufacturer.

## Pixel 7 and newer (Android 13+)

1. Settings → Network & internet → SIMs → **+ Add SIM** → **Download a
   SIM instead?**
2. The phone offers to scan a QR code. Open the CashCard app on a
   second device and show the QR.
3. Confirm activation. The phone shows the carrier name and a switch
   for cellular data.

## Samsung Galaxy S22 and newer (One UI 5+)

1. Settings → Connections → SIM manager → **Add eSIM**.
2. Tap **Scan QR code from service provider**.
3. Same QR flow as Pixel.

## What "installed" means

The carrier API is the source of truth — confirm install only when
`eSimProfile.status == "installed"`. Until then, say "your eSIM is
downloading". Do not claim the line is "active on your device". See
`esim.install.ios.first_time` for the same rule on iPhone.

## Common Android-specific failures

- **"Could not download eSIM"** on Pixel: the activation code expired.
  Each LPA string is single-use; generate a new one from the app.
- **No QR scanner option**: the user is on an old Android version. Ask
  for the device model and OS; on anything before Android 12, eSIM via
  QR isn't supported.
