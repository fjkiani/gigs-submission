# Gigs Research Notes — Facts Established Before Drafting

> Every line below is grounded in a numbered source from the live citation pool.
> Anything in **bold** is something the assignment text either implies or relies on,
> and that turned out to match reality. Anything in *italic* is a divergence from
> the assignment prompt or an interesting limit the prompt didn't mention.

## 1. Company & product positioning

- Gigs is **"the OS for embedded telecom"** / **"Stripe for phone plans"** — a Telecom-as-a-Service
  platform that lets any tech company become a Mobile Virtual Network Operator (MVNO) without
  building their own integrations with carriers, OSS/BSS, billing, or support [23, 26, 30].
- Combines MVNE/MVNA, wholesale connectivity (eSIM + pSIM), OSS/BSS, billing,
  subscription management, lifecycle comms, and **support automation** in a single platform [25].
- Carrier of Record — Gigs handles telecom compliance on customer's behalf [23, 25].
- Founded 2020 (Berlin → SF), YC W21, $97M total funding through Series B in Dec 2024
  ($73M led by Ribbit Capital, with Google Gradient, YC Continuity, and angels Dara Khosrowshahi,
  Tony Xu, Fidji Simo) [24, 26].
- ~150 employees, HQ San Francisco, hubs in SF/London/Berlin [23, 27].
- Operates in US + Europe (24 countries) [24]. Wholesale partners include
  Vodafone UK [29] and AT&T + T-Mobile in the US [32].

## 2. Known customers (matter for the CashCard problem)

- **Tide** — UK SMB neobank, launched embedded 5G mobile plans for small firms (Mar 2026) [27].
- **Sezzle** — US BNPL fintech, launched $29.99 unlimited mobile (Feb 2026) [27].
- **Revolut** — UK/EU neobank, Revolut Mobile at £12.50/month unlimited (Dec 2025) [27].

These are the live multi-tenant proof points. **"CashCard" in the assignment is a thinly
disguised analog of Sezzle/Revolut** — a fintech-into-mobile play. Anything we build
should plausibly work for both Sezzle's actual US/eSIM stack and Revolut's UK/multi-product
stack without changes.

## 3. The "agentic layer" — what it actually is

- The Gigs homepage names the product: **"Operator. Agentic AI for connectivity."** [23]
  That is the system the assignment is asking us to audit.
- TechCrunch (Dec 2024) confirms a then-upcoming **"AI customer support assistant
  dubbed 'operator'"** that lets end customers "update their credit card details … or request
  a new eSIM without involving any human agent" [26]. So Operator is both an answering
  agent *and* an action-taking agent.
- The press release for the Series B describes the platform as providing **"AI-powered
  customer service"** as a core capability [29].
- The Head-of-Support job posting says verbatim: support is **"a core part of our product"**;
  the team builds **"self-healing flows, intuitive self-serve, and AI-first assistance"**;
  recurring issues are treated as **"product bugs, not team problems"** [16].

## 4. The role I'm interviewing for — what it actually wants

From the Support Platform Engineer JD (also listed as Support Operations Engineer on YC) [13, 14]:

- *"The backbone of how Gigs delivers support at scale."*
- *Sits at the intersection of Delivery and Scale.*
- *"Identify recurring issues and escalation patterns and translate them into actionable
  improvements for Product, Engineering, and internal processes."*
- **"Maintain and improve the knowledge base and documentation infrastructure that powers our
  support operation and AI tools."** ← This is exactly Task 2 and Task 3.
- *"Configure, optimize, and improve the tooling and workflows the support team runs on."*
- **"Contribute to automation and agentic support initiatives, helping define how AI fits
  into the support workflow."** ← This is Task 1 and Task 4.
- *"Genuine interest in AI, automation, and how they can make support smarter over time."*

This is not a traditional Tier-2 escalation role. The Technical Support Engineer JD [15, 17, 18]
is the one that handles escalations directly ("primary escalation point for complex
connectivity challenges that stump our Tier 1 partners"). The role this assignment is
attached to is the *operations/platform* counterpart — agent reliability, KB engineering,
deflection metrics, eval frameworks, vendor coordination.

The Technical Support Lead JD [19] phrase **"the best support ticket is the one not created"**
is doctrine here. Our deflection framing should adopt it explicitly.

## 5. API surface — what the agent has to work with

### 5.1 Authentication model — this is critical for Task 4

- Gigs uses **static Bearer API keys**, one per project (e.g. `production`, `test`) [33].
- *"An API key provides full access to all the data in a project."* [33, 35] — there is
  **no scope system, no per-user permissions, no fine-grained tokens** in the public API.
- The `APIKey` object has only `id`, `createdAt`, `expiresAt`, `name`, `token` — no `scopes`
  field [34].
- **Implication for the middleware**: the agent's effective permissions cannot be enforced
  by Gigs' auth. Any read-only/write-allowed/customer-scoped distinction must be enforced
  in a layer *we* build between the agent and the Gigs API.
- Errors return `{object: "error", code, type, message, hint, documentation[]}` — consistent
  shape across endpoints, so the middleware can normalize errors uniformly.

### 5.2 Resource hierarchy

All resources are scoped under `/projects/{project}/...`. Tenant isolation in Gigs is at the
**project** level [1, 7, 33, 35]:

```
/projects/{project}/users
/projects/{project}/users/{user}/addresses
/projects/{project}/sims
/projects/{project}/sims/{sim}/eSimProfile
/projects/{project}/sims/{sim}/credentials
/projects/{project}/sims/search
/projects/{project}/plans
/projects/{project}/subscriptions
/projects/{project}/subscriptions/{subscription}/usage
/projects/{project}/subscriptions/{subscription}/addons
/projects/{project}/subscriptionChanges
/projects/{project}/portings
/projects/{project}/usageBalances
/projects/{project}/devices
/projects/{project}/networkAvailabilities
```

Customer (e.g. CashCard) ≈ one Gigs project. So **multi-tenancy in the KB problem is
multi-project**, not multi-row-per-tenant. That is much cleaner than it sounded in the prompt.

### 5.3 SIM object — the eSIM activation surface [2]

```
sim {
  object: "sim",
  id, metadata, createdAt,
  iccid,
  provider,             // e.g. "p3" (T-Mobile US), "p14", "p15"
  status: inactive | active | retired,
  type: eSIM | pSIM
}

GET /projects/{p}/sims/{s}/eSimProfile  →
  status: deleted | disabled | enabled | installed | unknown
  // "unknown" means provider doesn't expose lifecycle (only p3/p14/p15 do)

GET /projects/{p}/sims/{s}/credentials  →  (eSIM only)
  activationCode, androidInstallUrl, iosInstallUrl, qrCodeUrl,
  puk1, puk2                     // PUK present only for some providers
  // qrCodeUrl is publicly accessible → security implication for the agent
```

**Hard constraint the prompt didn't state**: eSIM lifecycle is meaningful only on
providers `p3`, `p14`, `p15`. For everything else, eSimProfile returns `unknown`.
A correct agent must NOT pretend to verify "your eSIM is installed on your device"
when the provider doesn't report it.

### 5.4 Subscription object [3]

```
subscription {
  object: "subscription",
  id, metadata, createdAt,
  status: pending | initiated | active | restricted | ended | …,
  activatedAt, canceledAt, endedAt, restrictedAt, restoreRequestedAt,
  cancellationDetails, restrictionDetails,
  currentPeriod,         // only when active
  earliestEndAt,         // earliest cancellable date given minimum period
  firstUsageAt,
  phoneNumber,           // E.164, voice plans only
  plan { … }, user { … }, sim { … },
  porting { … }, lastPorting { … },
  userAddress,
  billing                // present if Billing enabled on project
}
```

**Implication for Task 1 grounding**: "Why is my service not working" maps to
`status == "restricted"` + `restrictionDetails`. "When can I cancel" maps to
`earliestEndAt`. These are exact lookups, not heuristic ones — failure to surface
them is hallucination.

### 5.5 Plan object [4]

```
plan {
  object: "plan",
  id, metadata, createdAt,
  name, description, image,
  provider,                              // network provider ID
  simTypes: ["eSIM"] | ["pSIM"] | both,
  allowances { data (bytes), sms, voice (sec) },
  limits     { bandwidth, fairUse, throttling },
  coverage   { … },                      // geographic coverage
  price      { … },
  requirements { … },                    // what must be collected to subscribe
  validity   { periodLength, minimumPeriods },
  activationTrigger: creation | usageStarted,
  firstPeriodTrigger: activation | creation,
  status: available | archived | pending | draft
}
```

For CashCard (US eSIM-only, single carrier), the entire KB universe boils down to:
- *N* plans, each with deterministic allowances/limits/validity
- 1 provider (one of p3/p14/p15)
- US-only coverage
- eSIM-only simTypes

This is *much* smaller and more deterministic than "75% of inquiries" sounds.

### 5.6 Porting object [5]

```
porting {
  object: "porting",
  id, status, createdAt,
  status: draft | initiated | pending | informationRequired |
          requested | declined | completed | canceled | expired | failed,
  accountNumber, accountPinExists, billingPinExists,
  address, firstName, lastName, birthday,
  donorProvider { object:"serviceProvider", id, country, name },  // e.g. "AT&T"
  donorProviderApproval,
  recipientProvider { … },
  phoneNumber (E.164),
  scheduledOn, requestedAt, lastRequestedAt, lastDeclinedAt,
  completedAt, canceledAt, expiredAt,
  declinedAttempts, declinedCode, declinedMessage,
  required[]    // fields the donor demands; e.g.
                // ["accountNumber","accountPin","accountType","address","birthday",
                //  "donorProvider","donorProviderApproval","firstName","lastName"]
}
```

**Critical**: porting is the highest-stakes flow we found.
- 10 distinct statuses.
- US donor providers are named (AT&T, T-Mobile, Verizon → `donorProvider.name`),
  so the agent can ground "what does AT&T need from me" answers in `required[]`.
- Declines surface `declinedCode` (machine-readable) + `declinedMessage` (human).
  Example: `portingPhoneNumberPortProtected` → "The phone number has port protection on the provider."
- Retry semantics: PATCH the porting with empty body retries; provide new info to fix
  `informationRequired`.

For the assignment, **porting is where most of the 35% "activation" inquiries actually
live for any US fintech-MVNO** — Sezzle/Revolut-equivalents have to handle this.

### 5.7 Usage / UsageRecord [6]

```
usageRecord {
  object: "usageRecord",
  start, end,                  // aggregation period
  data (bytes), voice (sec), sms (count),
  dataDeviceBytes, dataTetheringBytes,           // preview
  voiceLocalSeconds, voiceInternationalSeconds,  // preview
  smsLocalMessages, smsInternationalMessages,    // preview
  labels, updatedAt
}

GET /projects/{p}/subscriptions/{s}/usage
  ?period=N | start=…&end=… | aggregation=daily|period|country
```

**Important gap**: there is **no "remaining balance" field**. To answer "how much data do
I have left," the agent must compute:

    remaining = plan.allowances.data - sum(usageRecord.data) for current period

**And**: *"Note that there is a delay in usage data that varies between carriers."* [6]
This is a structural source of hallucination risk — the agent must surface the staleness
in its answer (e.g. "as of {updatedAt}, you've used X of Y GB this period; carrier reports
can lag up to 24h"), not pretend to be live.

### 5.8 User object [7]

```
user {
  object: "user",
  id, metadata, createdAt,
  email, emailVerified,    // unique across all users
  fullName,                // required for some plans
  birthday, preferredLocale,
  status: active | blocked | deleted
}
```

PII surface: email + birthday + fullName. Address is on a separate `UserAddress` object
under `/projects/{p}/users/{user}/addresses`. **No SSN, no government ID, no KYC document
fields** in the public user object — that means Gigs handles KYC behind the carrier
relationship, not in the published API. So we don't need a KYC redaction policy in the
KB pipeline beyond the standard PII set.

### 5.9 Events & Webhooks [8, 10, 11, 12]

- **Webhooks are delivered via Svix** (third-party).
- Verification headers: `webhook-id`, `webhook-signature`, `webhook-timestamp`.
- Payloads use the **CloudEvents** spec: `{object:"event", id, type, source, specversion,
  time, project, actor, data, datacontenttype, version, previousData?}`.
- Event types start with `com.gigs.` prefix. Confirmed types include:
  - `com.gigs.subscriptionChange.created`
  - `com.gigs.subscriptionChange.updated`
  - `com.gigs.invoice.finalized` (billing trigger) [11]
  - Implied: `subscription.*`, `sim.*`, `porting.*`, `user.*`, etc.
- Svix disables endpoints that fail for 5 consecutive days. Recommended: one endpoint for
  all events (not one per type), because per-type endpoints get disabled more easily on bugs.

**For Task 1's "what changed under the agent's feet" question**: the platform team is
*already* publishing the signal we need. We don't need to scrape — we need to subscribe.
A KB-freshness watcher can listen to `com.gigs.plan.updated` / `policy` changes (assuming
they exist) and flag KB pages for re-review.

### 5.10 Billing / Invoice [11]

```
invoice.status: draft | finalized | paid | voided
```

- Customer's own integration is responsible for collecting payment. After payment,
  customer marks the invoice `paid`, which triggers subscription activation.
- Free plans / fully discounted invoices auto-transition to `paid`.
- If a subscription is created without billing, behavior depends on project-level config.

**Implication**: "why is my phone not working after I paid" is genuinely ambiguous — it
could be a customer-side payment-collection bug, an invoice not transitioned to `paid`,
or a real provisioning issue. The escalation context object **must include the invoice
state** for the human to disambiguate fast.

## 6. What the assignment prompt likely got from this surface

Reverse-engineering: the assignment's numbers (75% deflection on launch, 35% activation,
25% billing/plans, 10% porting, 20% other) line up cleanly with the resource shapes:

| Assignment category | Maps to API resource(s)                                  | Deterministic? |
|---|---|---|
| Activation (35%)     | SIM, eSimProfile, credentials, Subscription.status      | High — exact lookups |
| Plan questions (25%) | Plan, Subscription, UsageBalances                       | High — exact lookups |
| Porting (10%)        | Porting (10 statuses, declinedCode, donorProvider.required[]) | High but US-only complexity |
| Billing (subset)     | Invoice (draft/finalized/paid/voided)                   | Customer-side coupling |
| "Other" (20%)        | Device compatibility, coverage, generic policy         | Lower — KB-only |

A deflection-rate regression from 80% → 61% across **80 customers**, each with their own
project, plan catalog, and KB version, is exactly the pattern you'd expect from a single
shared agent prompt + a per-tenant KB layer that's been mutated 80 different ways with
inconsistent vocabulary.

---

## 7. Open questions I can't resolve from public sources alone

Listed so I don't bluff in the submission.

1. **Vendor stack for Operator**: not publicly disclosed. The Senior Platform Engineer
   JD [20] and Staff Engineer JD [21] talk about event-driven architectures and AI
   tooling but don't name LLM providers, ticketing system, or KB store. I will explicitly
   not name a vendor; I will design around the *signatures* (foundation-model API, webhook
   ingest, ticketing tool, KB datastore) so the architecture is vendor-agnostic.
2. **Whether Operator has tools/function-calling** vs. retrieval-only. The TechCrunch
   piece [26] says it can *take actions* ("update credit card", "request a new eSIM"),
   so it has tools. But the public interface and tool schema are not disclosed.
3. **Per-customer eval harness reality**: I'm assuming there is no proper eval framework
   today, since the assignment says so and the Head-of-Support JD lists "Automate everything
   that can be" as future work [16]. I'll treat this as confirmed by the prompt.
4. **What the metric "deflection rate" actually measures at Gigs**: I'll define it
   explicitly in Task 1 and Task 3 as `(resolved_in_agent_without_human_handoff) /
   (total_inquiries)` over a rolling window, and note alternative definitions
   (refusal-aware deflection vs. raw deflection) to avoid Goodharting.

---

## 8. Sources used (re-cited inline above)

- [1] https://developers.gigs.com — top-level resource index
- [2] /api/latest/core/sims — SIM object + eSIM endpoints
- [3] /api/latest/core/subscriptions — Subscription schema
- [4] /api/latest/core/plans — Plan schema (allowances, limits, simTypes)
- [5] /api/latest/core/portings — Porting schema, US-specific required fields
- [6] /api/latest/core/usage — UsageRecord schema, carrier delay note
- [7] /api/latest/core/users — User schema (PII surface)
- [8] /docs/core/events/events-webhooks — Svix-based webhooks
- [10] /api/latest/events/schemas/com.gigs.subscriptionChange.updated
- [11] /docs/billing/billing-users — invoice lifecycle
- [12] /api/latest/events/schemas/com.gigs.subscriptionChange.created
- [13] https://gigs.com/careers/.../Support Platform Engineer
- [14] YC mirror of same role
- [15] https://gigs.com/careers/.../Technical Support Engineer
- [16] https://gigs.com/careers/.../Head of Support
- [17, 18] Mirrors of Technical Support Engineer
- [19] BuiltInNYC — Technical Support Lead
- [20] /engineering — Senior Platform Engineer, Developer Experience
- [21] /engineering — Staff Software Engineer
- [22] (Cognition AI Support Engineer — discarded, not Gigs)
- [23] https://gigs.com — homepage; "Operator. Agentic AI for connectivity."
- [24] CEO LinkedIn — Hermann Frank
- [25] /use-cases/mvno-in-a-box — full stack description
- [26] TechCrunch Dec 2024 — Series B, Operator AI assistant announced
- [27] YC company page — Tide / Sezzle / Revolut as customers
- [28] LightReading podcast — CEO interview
- [29] /press/... — Vodafone UK partnership (AI-powered customer service named)
- [30] TechCrunch 2022 — Series A
- [31] TelcoDR podcast
- [32] FierceNetwork — AT&T + T-Mobile US deals
- [33] /api/authentication — static Bearer keys, no scopes
- [34] /api/latest/core/schemas/apiKey — APIKey shape
- [35] /api/introduction — same auth model + project hierarchy
