# Task 1 — Agentic Support Layer Audit

*Fahad Kiani — Gigs Support Platforms take-home, Task 1 of 4*

---

## How I'm framing this audit

The prompt frames the question as a regression: deflection has slipped from
80% to 61% and we want it back. That's a real number to chase. But the way
deflection is usually measured — *fraction of tickets that don't reach a
human* — is one of the easiest metrics in support to Goodhart, and treating
the slip purely as a regression risks the wrong fix. Two scenarios produce
the same 80%:

1. The agent answers correctly four times out of five.
2. The agent answers *something* five times out of five, and two of those
   answers are quietly wrong. Customers don't always come back, especially
   for connectivity questions where they'd rather just power-cycle.

The right thing to recover is not deflection in the abstract — it is
**refusal-aware deflection**: tickets the agent closed *and* whose closing
answer is faithful to evidence the agent actually had. The bar from Gigs'
own marketing, that **"the best support ticket is the one not created"**
[19], only holds if the closing answer is correct. Otherwise a "deflected"
ticket is a deferred refund.

So this audit treats the 80→61% slip not as a number to claw back, but as
a signal to ask: *which class of grounded-answer failure is silently
inflating the closed-ticket count?* The recovery is not "tune the
prompt" — it is closing the **operator-answers / human-resolves /
system-learns** loop the Head-of-Support post calls "self-healing flows,
intuitive self-serve, and AI-first assistance" [16]. The system the
assignment refers to is named: it is **Operator**, Gigs' agentic AI for
connectivity [23, 26, 29]. I'll use that name throughout.

The audit has five sections:

- §1: Four hypotheses for the regression, ranked by likely contribution.
- §2: A 7-axis failure taxonomy — what "wrong answer" actually means.
- §3: Three concrete process changes that close the learning loop.
- §4: Where AI fits in the workflow, and where the prompt's framing
       sells the question short.
- §5: A 30/60/90-day plan to recover to ≥80% refusal-aware deflection.

Every claim in §1–§5 is backed by a real artefact under `task1_audit/`:
`escalation_context.py`, `failure_taxonomy.py`, `grounding_check.py`,
`kb_freshness_watcher.py`, plus tests and a demo. The audit is not
slide-ware — it is testable.

---

## §1 — Four hypotheses for the 80→61% drop

The platform serves 80 brands across multiple jurisdictions on the same
Gigs core API (Plans, Subscriptions, SIMs, Portings, Usage, Invoices) and
the same provider matrix (only **p3, p14, p15** report eSIM lifecycle state
[2]; everyone else returns `unknown`). A 19-point drop is large, and the
shape of the drop matters: regressions in agentic systems are usually
*compositional* — multiple smaller defects compound. Below are the four
hypotheses I'd test, ranked.

### H1 — KB drift dominates (most likely)

Gigs ships event-driven state through Svix webhooks [8]; plans, allowances,
add-ons, and porting decline codes change at customer-pace. The
`com.gigs.plan.updated`, `com.gigs.subscriptionChange.updated`,
`com.gigs.porting.declined`, and `com.gigs.invoice.finalized` events are
the surface where ground truth shifts — and *none of them* automatically
triggers a KB re-write. The set of event types that *should* invalidate KB
content is 10 events long; I enumerate them in
`task1_audit/kb_freshness_watcher.py` as `KB_INVALIDATING_EVENT_TYPES`
(`plan.created`, `plan.updated`, `plan.archived`, `subscription.updated`,
`subscriptionChange.created`, `subscriptionChange.updated`, `addon.updated`,
`porting.declined`, `invoice.finalized`, `networkAvailability.updated`).

The mechanism: 80 tenants × steady stream of plan/policy changes × no
automatic stale-flagging = chunks slowly drift past truth. The agent still
retrieves them — they still match the question's vocabulary — so it
*answers*. The answer is just wrong in ways the customer accepts in the
moment ("oh, I guess that's how it works now") and triages later via a
refund or a churn. From the metric's perspective, those tickets
**deflected**. From the platform's perspective, they regressed.

How I'd confirm: per-tenant slice of the eval scorecard against the
`STALE_KB` axis (`task1_audit/failure_taxonomy.py`), correlated with the
volume of `com.gigs.plan.*` events per tenant in the last 90 days. A
hypothesis is that tenants with the highest plan-update velocity (likely
the larger MVNOs — Tide, Sezzle, Revolut [27], plus the long tail of
smaller brands) carry a disproportionate share of the regression.

### H2 — Tenant-bleed in retrieval / state

The Gigs auth model uses static Bearer keys scoped per project, with no
fine-grained scopes [33, 35]; the *project* is the tenant boundary. If the
retrieval index, the agent's working memory, or its scratchpad is not
strictly project-scoped — or if it is scoped but a top-K retrieval returns
chunks authored for a sibling brand because their plan names are similar
— customers get answers that name another brand's price, allowance, or
restriction policy. Operator's confidence stays high, the customer's
confidence drops to zero, and the ticket creates *more* work than no agent
would have. This is the failure mode the
`EscalationContext.project_id` field exists to make a hard boundary in
escalations (see `task1_audit/escalation_context.py`).

How I'd confirm: a synthetic eval that intentionally seeds two tenants'
KBs with overlapping plan names and asks the agent question phrased
ambiguously. Any cross-tenant leak is an immediate red flag, regardless
of the deflection number.

### H3 — Fair-use / policy language was reworded at the platform level

When the platform updates fair-use, throttling, or restriction language
(e.g. how `subscription.status == "restricted"` is described to end
users), the KB rewrite is usually staged centrally and then propagates to
per-tenant overrides. A wording delta that *individually* looks like a
clean improvement can cause the grounding gate to refuse on adjacent
tenant-specific phrasings, *or* let through over-confident answers that
no longer match the tenant's actual policy. Either way: deflection drops
because either escalations spike (good direction, bad measurement) or
quietly-wrong answers spike (bad direction, masked measurement).

How I'd confirm: time-correlate central KB edits to the per-axis deltas
(particularly `BILLING_AMBIGUITY` and `MISSING_RESTRICTION`).

### H4 — Provider-mix shift on the carrier side

Only `p3`, `p14`, and `p15` expose eSIM lifecycle state [2]; if the carrier
mix has shifted toward providers that return `unknown`, any KB content
that talks about "you'll see your eSIM installed in Settings" becomes a
fiction the agent restates. This is the
`WRONG_PROVIDER` axis. I'd expect this to be a smaller share of the drop
than H1 unless a specific tenant has switched providers in the last 90
days.

How I'd confirm: SIM provider distribution per tenant, time-sliced, vs.
the WRONG_PROVIDER axis frequency.

### My ranking

Without per-tenant data, my point estimate is **H1 ≫ H2 ≈ H3 > H4**.
Order matters because the recovery work in §3 is mostly H1-shaped. If H2
turns out to dominate (cross-tenant leakage), the work is more invasive
than a KB hygiene pass — it's an isolation review of the retrieval
boundary.

---

## §2 — Where the bleed is: failure taxonomy

A regression number is a vibe until it becomes a per-axis count. I'm
introducing a 7-axis classifier for grounded-answer failures, shipped as
`task1_audit/failure_taxonomy.py` and re-used by Task 3's eval scorecard.

The axes are deliberately tied to **observable Gigs API state**, not
linguistic categories like "hallucination" or "tone". Each axis points
to a detector someone can write and run; "OTHER" exists only because we
will be wrong about coverage at first, and it gives us a holding pen.

| Axis | What it means | Detector signal |
|---|---|---|
| `STALE_KB` | Chunk was authored before a relevant plan/policy change. | `chunk.updated_at < plan.updatedAt` of any referenced plan. |
| `WRONG_PROVIDER` | Lifecycle claim on a non-p3/p14/p15 provider. | `sim.provider ∉ {p3,p14,p15}` AND answer mentions eSIM lifecycle. |
| `STALE_USAGE` | Numeric balance with no "as of" qualifier. | answer contains "X GB / minutes / texts" pattern AND no reference to `usageRecord.updatedAt`. |
| `MISSING_RESTRICTION` | Restricted subscription handled as if active. | `subscription.status == 'restricted'` AND answer doesn't surface restriction reason. |
| `PORTING_DECLINE_NOT_DECODED` | Decline code not surfaced. | most recent porting transition has `declinedCode != null` AND answer doesn't include it. |
| `BILLING_AMBIGUITY` | Invoice state collapsed into "payment failed". | `invoice.status ∈ {draft, finalized, voided}` AND answer says "payment failed". |
| `OUT_OF_SCOPE_OVER_REACH` | Off-Gigs question that should have been declined. | intent classifier judges off-domain AND agent engaged. |

A single answer can carry multiple annotations (e.g. STALE_USAGE +
MISSING_RESTRICTION on a "why is my data slow" answer that quotes a stale
balance *and* ignores a `restricted` status). The `distribution()` helper
in the same module aggregates annotations into a pareto chart, ordered by
descending count then by axis name — that's the per-axis breakdown the
30/60/90 plan in §5 acts on.

### Hypothetical pre-recovery distribution

Without the real eval corpus I can't give an honest number per axis, but
the shape I'd expect, given §1's ranking, is **STALE_KB dominant
(~40-50%)**, **MISSING_RESTRICTION and BILLING_AMBIGUITY as the next two
substantial bands (~10-15% each)**, then **STALE_USAGE and
PORTING_DECLINE_NOT_DECODED at the long tail**. WRONG_PROVIDER is a small
absolute count but a high-severity one — getting eSIM lifecycle wrong
breaks activation in a way the customer can't paper over. The
`OUT_OF_SCOPE_OVER_REACH` axis I'd expect to be small for a
well-prompted Operator, but it's the axis where "deflection metric" most
cleanly diverges from "customer was helped".

What this taxonomy is *for* is not the audit doc — it's Task 3's eval
harness. Once we can run that scorecard nightly per tenant, the
"deflection slipped from 80 to 61" sentence becomes a per-axis vector and
the platform team can argue about which axis to attack first instead of
which prompt to tweak.

### What the taxonomy refuses to do

The axes are **not** linguistic. There is no "hallucination" axis here,
because "hallucination" is a description of the model, not a description
of the failure surface. Operators that hallucinate STALE_USAGE numbers
and Operators that confidently restate stale-but-real KB content both
trip the same downstream metric; the platform team's fix is different in
each case. The taxonomy is therefore organised around the *failure
mechanism* (which Gigs API field was the source of truth, and how did the
agent get away from it), not the apparent symptom in the answer text.

---

## §3 — Closing the loop: three process changes

The Head of Support post describes the team's job as making support
**"a core part of our product"** and treating recurring issues as
**"product bugs, not team problems"** [16]. That framing only holds if
two things actually flow: human resolutions back into the KB, and policy
events forward into the retrieval surface. The three changes below close
those flows.

### 3.1 EscalationContext as the *single* required handoff packet

Today, when Operator escalates, the human escalation gets a partial chat
log and whatever ad-hoc summary the agent emitted. That makes the human
do the work the agent already did: pull up the right subscription,
re-fetch usage, dig out the latest porting transition. The
`EscalationContext` (in `task1_audit/escalation_context.py`) is a typed
pydantic packet with everything the human needs — masked PII, freshness
on usage, restriction reason if any, last few `com.gigs.*` events, the
retrieved chunks the agent saw, and the *failure-axis tags* the agent
suspects. It's frozen, JSON-serialisable, validation-strict (extras
rejected), and serializes its email/phone/name in masked form only — the
test suite enforces no raw PII can survive into the packet.

The constraint I'd impose: **no ticket is opened from Operator without an
`EscalationContext` attached**. That single rule turns "this is hard to
audit" into "every escalation is a row in a table we can run analytics
on", which is a precondition for any of the rest of §3 working.

### 3.2 Recurring-escalation → KB-delta workflow, owned by Platform

If the same axis tag (e.g. `BILLING_AMBIGUITY` on invoice.draft) fires
on N escalations from the same tenant within a window, the platform team
gets a queued *KB delta proposal* — not an alert. The proposal includes
the current chunk content, the per-tenant override (if any), the actual
API state across the cluster of escalations, and a suggested rewrite
draft. The human reviews and either accepts the rewrite, opens a Product
bug ("we should never have shipped allowing this state"), or marks the
escalations as a Tier-2 routing change instead of a KB change.

This is the explicit operationalisation of the Head-of-Support framing
[16]: recurring issues become product bugs because the workflow makes
them visible as recurring issues, not as anonymous 1-star CSAT scores.

### 3.3 KB-freshness watcher + per-tenant CI eval

`task1_audit/kb_freshness_watcher.py` ships the building block: a Svix
HMAC verifier that converts incoming `com.gigs.*` events into structured
`StaleFlag` entries when the event is in
`KB_INVALIDATING_EVENT_TYPES`. The verifier enforces the security
hygiene Svix expects [8]: constant-time signature comparison, 5-minute
skew window, support for *secret rotation* (the verifier accepts multiple
candidate secrets so a rotation doesn't require downtime). It is *the*
piece of code that has to be correct or this entire process change is a
liability rather than an asset, so it has 30+ deterministic tests on its
own.

A `StaleFlag` doesn't auto-rewrite anything. It lands on the platform
team's queue. From there, the same review workflow as 3.2 applies. This
is intentional — the goal is "system learns", not "system writes" — the
human still resolves the substantive question. The system's job is to
*notice that the KB might be stale* and to *not let that fact get lost*.

A second piece of plumbing (deferred to Task 3, but worth flagging
here): a **per-tenant CI eval** that runs the scorecard from §2 nightly
on a held-out set, with a regression gate. If any tenant's
refusal-aware deflection drops more than 5 points in a rolling 7-day
window, CI fails and someone is paged. This is the analogue of a
flakiness budget for support quality.

---

## §4 — Where AI fits in the support workflow

Here is where I want to push back on the prompt's framing. The phrasing
of the task implies AI is a *layer* that sits in front of humans and
either succeeds or fails to deflect. That framing makes the deflection
metric the score, and a slip from 80 to 61 looks like a failure of the
layer. But the way the Head of Support post describes the work, the
phrasing is **"self-healing flows, intuitive self-serve, and AI-first
assistance"** [16] — three things, not one, and *the AI is one of three*.

A better mental model is a three-role loop:

> **Operator answers** — the agent handles the first-pass response,
> grounded in the customer's actual API state, and *refuses early* when
> the grounding gate doesn't pass.

> **Human resolves** — the Technical Support Engineer handles
> escalations and writes the resolution in a structured form that maps
> back to a failure axis.

> **System learns** — Platform code (the watcher, the taxonomy, the eval
> scorecard) feeds the human's resolution back into the KB and the
> agent's eval set, *without* the agent automatically applying it.

This is intentionally not "AI takes over". The Technical Support
Engineer role explicitly describes the human as **"the primary
escalation point for complex connectivity challenges that stump our
Tier 1 partners"** [15] — that's not a role you remove. The
Support Platform Engineer job [13, 14] is the one that owns the
*system* side: the agent reliability, the KB engineering, the eval
framework, the vendor coordination — which is what this audit is
actually about.

The clearer outcome to optimize for, and what this audit recommends as
the headline metric, is **refusal-aware deflection**: tickets the agent
closed *and* whose closing answer is faithful to evidence. The two
ways to push it up are not symmetric:

1. **Make the answer faithful.** This is the §3 work — better KB,
   better grounding gate, better failure-axis surfacing in escalations.
2. **Refuse earlier when faithfulness isn't possible.** This is the
   `grounding_check.py` work — a deterministic gate that decides
   *before* the answer is sent whether every claim has support.

Both are necessary; only the first one is in the spirit of the prompt as
written. The second is, in my view, the more important one. A
60%-deflection-with-100%-faithfulness Operator is better than an
80%-deflection-with-80%-faithfulness one, by every customer-facing
metric, and most internal cost metrics too. The slip from 80 to 61 may
not be a regression at all — it may be the system finally telling the
truth about the false-positive band that existed at 80.

That's a hypothesis I cannot verify without the eval corpus. But it is
the framing I would walk into the review meeting with, and it is the
framing I would change the team's KPI to.

---

## §5 — 30/60/90-day plan to recover to ≥80% refusal-aware deflection

This is the plan I'd commit to if you handed me the platform on day one.
Each milestone has a concrete artefact and a target on
**refusal-aware** deflection, not raw deflection. The non-refusal axes
from §2 are the levers; they are *not* the target.

### Day 30 — instrumentation and triage (target: ≥70% refusal-aware deflection)

- Ship `EscalationContext` as required handoff packet. **No ticket
  opens without one.** Validation runs in CI; a missing packet is a
  hard failure.
- Land the failure-taxonomy module and a first per-axis annotation
  pass against the most recent 90 days of escalations.
- Stand up the per-tenant scorecard. Even with a small held-out set,
  this is the loop that closes the metric.
- KB freshness watcher in shadow mode: receiving Svix events,
  emitting `StaleFlag`s into a queue, no auto-action yet. The
  platform team manually triages.

At 30 days, the goal is not to have moved the metric — the goal is to
have made it interpretable. Anyone on the team can answer "which axis
is the biggest contributor *for which tenant*". I'd take 70% on an
instrumented system over 80% on an opaque one.

### Day 60 — first wave of KB hygiene (target: ≥78% refusal-aware deflection)

- Top-3 axes from the scorecard get a structured remediation per
  tenant. For STALE_KB, that is the §3.2 KB-delta workflow with
  reviews owned by Platform; for MISSING_RESTRICTION, that is a
  prompt + retrieval-pattern fix that surfaces
  `subscription.restrictionDetails`; for BILLING_AMBIGUITY, that is
  a per-status copy rewrite (`draft`, `finalized`, `paid`, `voided`)
  in the response template.
- Grounding gate's threshold (`min_supporters_per_claim`) and
  token-overlap floor are *tuned per tenant* if needed — the demo
  ships at 1 supporter / 60% overlap, but on a tenant with denser
  KB, going to 2 supporters is reasonable and cheap.
- KB freshness watcher promoted to action mode: a `StaleFlag` opens
  a Linear/Jira ticket automatically with the proposed rewrite
  attached.

By day 60, the regressions H1 and H3 from §1 should be visibly
closing. If they aren't, that's a strong signal H2 is contributing
more than my point estimate, and the work pivots to a tenant-isolation
review.

### Day 90 — refusal-aware deflection ≥82% with confidence intervals

- The eval harness from Task 3 runs nightly per tenant; any regression
  >5 points in 7 days fails CI.
- The audit doc you are reading is now a runbook, not a one-shot
  document — the seven axes, the three process changes, and the
  recovery checkpoints are checked weekly against current numbers.
- Where the axes have *plateaued* below an acceptable bar (in my prior,
  WRONG_PROVIDER is likely a stubborn long tail because the underlying
  fact is "the carrier doesn't tell us"), the work shifts from "fix
  the answer" to "fix the prompt's permission to answer", which means
  explicit policy refusals at retrieval time, not at generation time.

The end state at day 90 is not "we hit 82%". It is "we know exactly
where the remaining 18% lives, and we can articulate which slice we
won't pay to close because it isn't worth the risk of regressing into
WRONG_PROVIDER-style confident wrongness".

---

## Closing note

The two design decisions that most differentiate this audit from a
generic "improve agent quality" response:

1. **The headline metric is refusal-aware deflection, not deflection.**
   Anything that lets a quietly-wrong answer count as a success will
   eventually move customers off the platform regardless of what the
   dashboard says.
2. **The seven failure axes are detectors, not narratives.** Each one
   points at a Gigs API field with a clear before/after. That's the
   only kind of taxonomy that survives contact with Task 3's eval
   harness and the per-tenant scoreboard.

The artefacts under `task1_audit/` are the implementation. The
30/60/90 plan above is what I'd commit to. The pushback on framing —
"the slip from 80 to 61 may be the system finally telling the truth"
— is the thing I'd want to argue about in person, because it changes
what we count as success.
