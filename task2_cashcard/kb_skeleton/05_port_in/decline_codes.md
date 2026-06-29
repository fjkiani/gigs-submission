---
chunk_id: porting.us.decline_codes_overview
topic: port_in
intent: explain_decline
last_reviewed: 2026-06-28
api_facts_referenced: [porting.declineCode, porting.declinedAt]
---

# Decoding port-in decline codes

When the donor carrier rejects a port, the carrier API exposes a
`portingDeclineCode` and `declinedAt` timestamp on the porting
transition. The agent **must** quote the code by name and explain what
to fix — never paraphrase to "your port didn't go through".

The decoded explanations come from
`kb_seed_from_api.US_PORTING_DECLINE_CODES`. The seeded chunk is the
source of truth; the table below is a quick reference for KB authors
adding decline-handling content.

## Codes (advisory list)

| Code | Plain language |
|---|---|
| `portingPhoneNumberPortProtected` | Donor account has port protection on. User clears it on the donor side. |
| `portingAccountNumberMismatch` | Wrong donor account number. User checks billing statement. |
| `portingPinIncorrect` | Wrong port-out PIN. User requests a fresh PIN from donor. |
| `portingZipCodeMismatch` | Zip code doesn't match donor account. User confirms zip on donor side. |
| `portingSsnLast4Mismatch` | SSN last 4 doesn't match. User confirms with donor (or that the line is on their SSN at all). |
| `portingNumberNotPortable` | Number can't be ported (e.g. landline, recently ported, prepaid line on a postpaid donor). |

## Canary check

`canary_porting_declined_not_decoded` will fire on any agent answer that
mentions a port decline without naming the specific code. The agent
must say:

> Your port was declined with code **portingPinIncorrect** — that's the
> donor carrier saying the port-out PIN we sent didn't match. The
> typical fix is to log into your donor account and generate a fresh
> port-out PIN, then we'll re-submit.

Not:

> Your port didn't go through. Please try again.
