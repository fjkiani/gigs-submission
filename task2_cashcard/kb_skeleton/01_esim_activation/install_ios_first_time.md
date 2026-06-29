---
chunk_id: esim.install.ios.first_time
topic: esim_activation
intent: how_to_install
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [eSimProfile.status, sim.type]
---

# Installing your CashCard eSIM on iPhone (first time)

CashCard sends the eSIM profile to your phone over the air. You do not
need to scan a QR code, and you do not need a SIM tray — your device
should be iPhone XS or newer running iOS 16 or later.

## What you do

1. Open the activation email from CashCard on your iPhone.
2. Tap the **Install eSIM** button. iOS opens Settings to the Cellular
   page with the new line preselected.
3. Confirm the line you want to use for data and the line you want for
   default voice/iMessage. CashCard recommends using the new line for
   data.
4. iOS shows a "Cellular Plan Ready to Be Installed" prompt; tap
   **Continue**.

## What "installed" means

Once iOS finishes the OTA download, the agent can confirm install **only**
when the carrier API reports `eSimProfile.status == "installed"`. Until
then, the correct phrasing is:

> Your eSIM is downloading. We'll see it in our system once your phone
> reports the install — usually within a few minutes.

Do not say the eSIM is "installed", "active", or "set up" on the user's
device based on the API alone. The carrier API reports profile state,
not device state.

## When it doesn't work

- **No prompt appears**: walk the user through Settings → Cellular →
  Add eSIM → Use QR code on Another Device.
- **"Could not activate cellular"**: usually a transient carrier
  push retry; ask the user to wait 60 seconds and reopen Settings.
- **Profile downloads but no signal**: the profile is installed but
  the line hasn't been provisioned by the carrier. Escalate.
