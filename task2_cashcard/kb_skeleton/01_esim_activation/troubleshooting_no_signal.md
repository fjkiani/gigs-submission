---
chunk_id: esim.troubleshooting.no_signal
topic: esim_activation
intent: troubleshoot_no_signal
last_reviewed: 2026-06-28
covers_providers: [p3, p14, p15]
api_facts_referenced: [eSimProfile.status, subscription.status, sim.lastSeenAt]
---

# eSIM installed but no signal

There are three classes of cause here. Identify which one we're in
before suggesting fixes.

## Class 1: the profile is downloaded but not provisioned

Symptom: `eSimProfile.status == "installed"` but the device shows "No
service" or the carrier name appears greyed out.

This is a carrier-side provisioning lag and is most common in the first
30 minutes after activation. Tell the user to wait 5 minutes and toggle
airplane mode on/off once. Do **not** promise it will work in any
specific time window — the carrier doesn't guarantee that.

## Class 2: the subscription is restricted

Symptom: `subscription.status == "restricted"`. The eSIM is technically
installed but the carrier is suppressing the line for a payment or
fraud reason on our end.

Do **not** tell the user to "wait for the signal to come back". Escalate
with the restriction reason from `subscription.restrictionReason`.

## Class 3: the device APN settings are off

Symptom: install is good, line is unrestricted, but data doesn't flow.

For CashCard, APNs are pushed automatically on all supported providers
(p3, p14, p15). If APNs need manual entry, that's a signal the device
isn't supported. Check the user's device model against the supported
list before walking them through manual APN entry.

## Things never to say

- "Your eSIM is active on your device." (We can only see the carrier
  profile state, not whether the device is connected.)
- "It should work in about 30 minutes." (No carrier guarantees that.)
- A specific signal-bar count.
