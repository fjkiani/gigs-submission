# Task 4 — The Architecture Decision

> Brief: Gigs runs two parallel integration architectures for the agentic
> layer (a legacy per-customer backend path and a newer direct-from-core
> path). The longer-term direction is a dedicated multi-tenant middleware
> service. Vendor consolidation in the AI space is accelerating. Answer
> three things: the risks of the dual architecture and short-term
> management; the design of the middleware; and what a vendor swap (or
> in-house foundation) would actually cost. This is the document Task 1's
> grounding work, Task 2's tenant policies, and Task 3's Q3 non-commit
> have been building toward.

## §0 — How to read this document

Three questions, one sidebar. Unlike Tasks 1–3, Task 4 ships as prose
only — no new code under `task4_architecture/`. The primitives I'd
build with already exist in this repo:

| Concern | Lives in |
|---|---|
| Tenant boundary (`project_id` as partition key) | `task1_audit/escalation_context.py`, `task2_cashcard/cashcard_config.py` |
| Scope-policy primitives (surfaces, actions, refuse vs. answer) | `task2_cashcard/escalation_triggers.py` + Task 2 routing config |
| Per-tenant eval hook, non-regression discipline | `task3_eval_expansion/lever_simulator.py`, Task 2 `eval_runner.py` |
| Refusal-aware deflection as the headline metric | `task2_cashcard/eval/eval_runner.py`, defended `03_TASK3_EVAL.md §3.1` |

The position, up front: the middleware exists primarily to enforce
**scope policy the Gigs API does not enforce** [33]. Everything else —
context aggregation, audit logging, the eval hook — is real work but
secondary. Three places I disagree with the brief's framing are called
out as **Pushback #1/#2/#3** in §1, §2, and §3.

## §1 — Dual-architecture risk

Two paths today. Legacy: native app → per-customer backend → AI vendor.
New: AI vendor called from the core platform with context in the body,
actions back against the Gigs API. Same vendor at the boundary; what
differs is what sits between Gigs and the model.

The risks, ranked:

1. **Auth-scope inconsistency, and it's asymmetric.** Legacy mints
   per-customer tokens with whatever scoping was implemented at
   onboarding. The new path uses Gigs public API keys, and "an API
   key provides full access to all the data in a project" [33]. Same
   agent, two different blast radii. A taxonomy `OUT_OF_SCOPE_OVER_REACH`
   on the new path is a policy bug; on the legacy path it's a
   customer-isolation bug. The paths don't fail equivalently.

2. **Context-shape drift.** Two surfaces shipping context differently
   means either the prompt template forks (Task 3's eval harness
   doubles) or we collapse to the lower-common-denominator context
   (capability loss). Both are bad.

3. **Failure-mode invisibility.** Task 1's taxonomy assumes one ingest
   path. If a field is dropped pre-agent on legacy but present on the
   new path, `STALE_USAGE` annotations land on new-path reports while
   legacy looks clean — not because it is, but because the detector
   can't see it.

4. **Operational doubling.** Two release pipelines, two on-calls, two
   sets of customer-specific exceptions. Linear cost, compounding
   cognitive load.

**Short-term management.** Four moves:

- **Freeze new customers on the new path.** Nobody joins the legacy
  path from here. Cheapest move, most important.
- **Cap legacy-path changes to security patches.** Customization
  requests get "available once the middleware ships." Forcing
  function on the middleware timeline.
- **Same telemetry shape on both paths.** Task 3's metrics frame
  already specifies the schema — emit from both so the Q3 commit in
  `03_TASK3_EVAL.md §3.2` is defended across the fleet.
- **Conditional sunset, not calendar sunset.** "When middleware ships,
  legacy is read-only within 60 days and decommissioned within 180."
  Calendar-anchored sunsets slip with the calendar.

**Pushback #1.** The brief calls these "two parallel integration
architectures." For the legacy path, the internal backend isn't an
integration — it's the security boundary for those customers. Pulling
it before the middleware can enforce equivalent scoping is the *worst*
version of running two architectures, not graceful degradation. The
risk register has to weight that asymmetry.

## §2 — Middleware design

### §2.1 What it owns vs. what the vendor owns

The boundary is the **tool-call line**. Anything that touches the
Gigs API, customer PII, or scope decisions belongs to the middleware.
Anything that's text-in / text-out / retrieval-over-content-we-handed-it
stays with the vendor.

| Owned by middleware | Owned by AI vendor |
|---|---|
| Identity (signed subject of the conversation) | Model call, token generation |
| Scope policy (what this session may read/write) | Conversation state within a session |
| Context aggregation from Gigs API + per-tenant KB | Persona, system prompt instance |
| Tool catalogue, gated per session | Tool selection (which to call, when) |
| Tool execution (the actual `GET /sims/{id}` lives here) | Tool argument extraction from the user turn |
| Audit log, eval hook, PII redaction at the boundary | Retrieval against KB content we provided |
| Refusal on tool-call attempts that fail scope | Refusal on out-of-domain user turns |

Two refusal paths is intentional. The vendor handles "user asked
off-topic, decline politely." The middleware handles "session has
`read:subscription` scope but the model tried to call `POST /portings`,
refuse and emit a `policy_denied` event." The vendor never sees a
Gigs project key.

### §2.2 The interface

Three surfaces.

**Inbound from product surfaces** (app, partner widget, email — the
last two are still in Task 3's non-commit bucket pending this
middleware). One endpoint:

```http
POST /v1/conversations/{tenant}/turn
{ "session_id", "subject": {user_id, signature},
  "surface": "app_chat" | "partner_widget" | "email",
  "message", "locale" }
```

`tenant` is the Gigs project, carried in the path so it survives
proxy logging and matches the Task 1 / Task 2 tenant model.

**Outbound to the AI vendor** (per turn): resolved context the
middleware aggregated. The shape, summarized:

```yaml
subscription: { id, status, restriction_details?, current_period? }
usage:        { data_used_gb, as_of }       # as_of mandatory — see Task 1 STALE_USAGE
porting_history: [ {state, declined_code, declined_message}, … ]
esim_profile: { status }                    # 'unknown' on providers outside p3/p14/p15
tools_allowed: [ {name, scope}, … ]
```

What's missing: no Gigs API key, no full user object, no email.
Vendor sees only what the prompt needs.

**Outbound to Gigs core API.** Every model-initiated tool call goes
through a signed proxy that mints a per-call scope token (~90s TTL)
encoding `(tenant, subject, action, resource_filter)`. HMAC mint is
cheap; revocation is implicit via TTL expiry. Per-tenant policies
live in version-controlled YAML:

```yaml
tenants.cashcard_prod.surfaces.app_chat:
  allowed_actions: [subscription.read.self, sims.read.self,
                    usage.read.self, porting.read.self]
  denied_actions:  ["*.write.*"]            # day-1 deflection-only
  require_step_up: [porting.cancel.self]
```

Day-1 posture for a new tenant is read-only-self. Adding a write
action is a deliberate scope-policy commit, not a prompt edit.

### §2.3 What the middleware is and isn't

It is a scope-policy enforcement point that happens to also aggregate
context, log audit events, and emit eval telemetry. It is not:

- a model abstraction layer (we still call one vendor at a time per
  session — model swapping mid-conversation is §3's question, not §2's);
- a routing layer in the LLM-router sense (intent classification stays
  with the vendor's routing config);
- a chat history store (the vendor keeps that — see §3).

### §2.4 Things that make this harder than it looks

- **Surface cardinality.** Chat is turn-shaped. Agentic email (Track
  5) is a multi-message thread with hours between turns; partner
  widgets (Track 4) embed in dashboards that may suspend the session.
  The middleware can't be strict request-response; the conversation
  model has to be a graph the surfaces drive.
- **Eval-hook coupling.** If every turn must emit to Task 3's harness
  before returning, that harness becomes a deployment-blocking
  dependency. Fire the telemetry, don't wait for it; replay
  out-of-band when a regression is suspected.
- **Scope token TTL.** Too short, mint rate climbs; too long,
  revocation lag widens. 90s with refresh on tool use is a defensible
  start; the right number is empirical and tenant-specific.

**Pushback #2.** The brief lists the middleware's job as "context
aggregation, scoped permissions, auditability, and routing" — four
co-equal bullets. They aren't co-equal. Scope enforcement is the
load-bearing reason this thing exists; it's why Task 3 declared
Tracks 3b and 4 NOT_READY in `03_TASK3_EVAL.md §1.4`. The other three
bullets are features of a scope-policy engine, not parallel goals.

## §3 — Vendor swap and the in-house foundation question

### §3.1 What carries over and what doesn't

With the middleware in place, **most of the work is
vendor-independent**. Scope engine, context aggregator, audit log,
eval harness, KB content, tool catalogue, Task 3's measurement frame —
all Gigs assets. The vendor sees redacted resolved context and a list
of allowed tools; it returns a turn response and tool-call attempts.
Both sides of that boundary are specified by us.

The actual swap surface is narrow: prompt template format,
function-calling JSON schema, streaming protocol, conversation-state
model (session IDs, turn limits, message-role conventions), intent
classifier if vendor-provided.

Honest estimate with the middleware: **4–6 weeks** to swap, ~2 weeks
integration code, ~3-4 weeks eval-harness re-baselining across
tenants. Without the middleware, the same swap is a **re-platforming**
— every per-customer config ported one at a time. That gap is the
real cost of the middleware not existing yet.

### §3.2 In-house foundation model — a different question

Replacing the vendor with an in-house foundation is not a swap. It
introduces training-data governance, evaluation that isn't
third-party-relative, an inference SRE function, capacity planning,
and an unbounded research tail. None of that work is duplicated by
the middleware, and the middleware doesn't accelerate it.

Gating signals are operational and economic, not strategic. Make the
call when:

- vendor instability persists >2 quarters and a swap to a second
  vendor has the same incidence;
- per-turn vendor pricing crosses self-served inference at the
  volumes Task 3's Q3 commit projects (computable once the commit is
  a quarter live);
- a regulatory or data-residency constraint exists that no vendor
  meets.

Absent any of those, the middleware is the right defensive posture
and the in-house build is the optionality it preserves, not a
project to start.

**Pushback #3.** "Vendor swap" is the wrong lead question. The right
one is: *what stays under Gigs' control regardless of which model
serves the next token?* With the middleware: identity, scope,
context, audit, eval, tool execution — everything that defines the
support experience. Without it: very little. The architecture
decision is the middleware. The vendor question is downstream.

## §4 — Sidebar: what I'd want to know, what could surprise us

**What I'd want to know first.** The current Operator tool-use
surface in production — what tools the vendor config permits today,
how the function-calling schema is structured, what the legacy-path
token shape grants. The §2.2 scope grammar is a sensible default
without that; with it, it's tuned to what's being replaced.

**What could surprise us.** Already in §2.4: surface cardinality,
eval-hook coupling, TTL choice. Beyond: per-tenant policy *churn* —
every CashCard-style launch adds a policy file, and the operational
owner of those files isn't named.

**Vendor lock-in at the AI layer.** Defensive answer: the middleware.
Offensive answer: keep the prompt template, KB, eval harness, and
tool catalogue under version control alongside the middleware. They
are the asset; the vendor is the runtime.

**A question the brief didn't ask.** Who owns the middleware
operationally? Support Platforms (the role this assignment attaches
to) is the natural product owner — it inherits the KB, eval harness,
taxonomy, and deflection metric. But the middleware is a service with
an SLO and an on-call. Either Support Platforms grows that capability
or the service is co-owned with Platform Engineering. The decision
shapes team boundaries; deferring it produces a service nobody picks
up at 3am.

## §5 — What this commits Gigs to

Realistic build: ~3 quarters end-to-end. Q1: scope engine, signed
proxy to the core API, audit log, baseline resolved-context schema.
Q2: context aggregator (Gigs-side joins), eval-hook integration,
legacy-path retrofit. Q3: non-chat surfaces (partner widget, agentic
email) — the surfaces that unlock Tracks 3b and 4 from Task 3.

During: no new customers on the legacy path, Tracks 3b/4 stay in
Task 3's non-commit bucket per `03_TASK3_EVAL.md §4`, and the Q3
commit (86%→92%→96% refusal-aware on the two live tenants plus
Track 1) is unchanged. After GA: the dual-architecture risk register
collapses, Tracks 3b/4 become normal expansion work, and the vendor
swap in §3.1 becomes 4–6 weeks instead of a re-platforming.

That's the architecture decision. It isn't glamorous, and the cost
isn't where the brief puts it — context aggregation is the easy
quarter; the scope engine is the hard one. But it's what makes
Tasks 1, 2, and 3 land: Task 1's taxonomy needs one ingest path to
be observable; Task 2's tenant policies need a place to live that
isn't a prompt edit; Task 3's Q3 commit needs the same metric
defended across the fleet.

Everything else in this repo has been pointing here.
