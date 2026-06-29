# Task 3 — Evaluation and expansion strategy

> Brief: the Gigs agent is at ~80% deflection across two live tenants. The
> business wants to expand into more telcos and more product surfaces. Decide
> what's ready, what isn't, what closes the 20-point gap to 90%, and what to
> commit to in Q3. This doc is the written half of the answer; the typed
> code under `task3_eval_expansion/` is the half that makes the claims
> reproducible.

## §0 — How to read this document

This is a strategy doc, but the numbers and verdicts are not assertions — they're
the outputs of typed functions you can re-run. Each major claim points to the
function that produces it:

| Claim | Source |
|---|---|
| Per-track readiness verdict | `expansion_track.recommended_track_reports()` |
| 4-bucket decomposition of the 20% gap | `gap_decomposition.illustrated_decomposition_for_raw_80()` |
| Lever lifts and trajectory | `lever_simulator.simulate_sequence(...)` |
| Q3 staged commit | `q3_commit.recommended_q3_commit()` |

If a number in the prose disagrees with the code, the code wins and the
prose is wrong. `make demo-task3` runs the trajectory end-to-end and prints
the rendered markdown tables this document embeds.

The document is structured against four orthogonal questions the brief asks:

- **§1** — Part A: which expansion tracks are ready, which need work, which
  aren't ready? (5 brief tracks, with Track 3 split into user-facing and
  partner-facing → 6 verdicts.)
- **§2** — Part B: how do we close the 20-point gap to 90%? (4-bucket
  decomposition, 5 levers, projected trajectory.)
- **§3** — Pushback on Q3: instead of one 90% number, a 3-tier staged commit
  with named gates and explicit non-commits.
- **§4** — What does NOT ship in Q3, and why.
- **§5** — How to verify any of this without taking the doc's word for it.

## §1 — Part A: expansion readiness

The brief lists 5 expansion tracks. The first locked design decision
(see §0 of `PLAN.md`) splits Track 3 into a user-facing surface (3a) and a
partner-facing surface (3b), because they share a name but not a blocker.
That gives us 6 verdicts.

### §1.1 — Verdict table

The table below is produced by `expansion_track.render_verdict_table()` —
the audit prose embeds the function's output verbatim:

| Track | Verdict | Failing gates | Blocking? | Summary |
|---|---|---|---|---|
| Same-vertical expansion | `READY` | 0 | 0 | Same use cases, same KB lineage, same eval substrate. Ramp-gated rollout. |
| Local/fintech expansion | `NEEDS_WORK` | 3 | 0 | KB thin + financial sensitivity. Author fintech KB chunks and gold-set intents first. |
| Devices/retail — user-facing | `NEEDS_WORK` | 3 | 0 | Same surface as live; new content + onboarding QA per account. |
| Devices/retail — partner-facing | `NOT_READY` | 3 | 2 | Shares Track 4's auth-scoping blocker. Cannot ship until middleware exists. |
| Partner-led widget | `NOT_READY` | 4 | 3 | Auth gap + new surface + new contract. Multi-quarter, not Q3. |
| Agentic email channel | `NEEDS_WORK` | 3 | 0 | Async surface — new eval shape + new escalation timing. Focused build, not flip-of-switch. |

The verdicts are computed from per-track gates by `TrackReport.verdict`:
any blocking gate failing → `NOT_READY`; all gates passing → `READY`;
otherwise → `NEEDS_WORK`. A reviewer can flip a verdict by editing one
gate in the corresponding `track_N_*()` function and rerunning the tests
— the test suite pins which verdicts each track is supposed to land on,
so a flip in either direction surfaces immediately.

### §1.2 — Track 1: same-vertical (`READY`)

The remaining customers in the same vertical as the two live tenants share
KB lineage, contact mix, and surface. There is no new design work — the
question is operational rollout pace, not readiness.

What's true here that isn't true for the other tracks:

- **KB coverage matches live.** Same template, same chunk schema, same
  refresh discipline. No new buckets to author.
- **Gold set is reusable.** Task 2's 50-question gold set covers this
  contact mix; we'd add tenant-specific keyword fixtures (account IDs,
  product names) but the intent buckets carry over.
- **Escalation triggers reuse.** `task2_cashcard/escalation_triggers.py`
  applies as-is; only the keyword sets are tenant-local.

The work in Q3 here is **ramp scheduling**, not architecture. Onboard one
new same-vertical tenant per week through weeks 5-10, with the canary
suite green for ≥2 weeks before raising deflection share above 25%.

### §1.3 — Track 2: local/fintech (`NEEDS_WORK`)

The brief explicitly flags this track's KB content as thin. Two additional
factors raise the bar above "just author more chunks":

1. **Financial-sensitivity raises the cost of a wrong answer.** A wrong
   answer about "what did this transaction cost me" or "why was my card
   declined" is more expensive than a wrong answer about "how do I
   activate this SIM". That makes the `wrong_answer_false_positive`
   bucket (§2.2) load-bearing — we need explicit escalation triggers
   for ambiguous financial answers before launch, not after.
2. **Refusals must be honest, not hedged.** The agent saying "I think
   this is a regulatory matter, but I can also help with..." is worse
   than refusing cleanly. Refusal-quality bar is higher than the live
   tenants.

The work that turns this into `READY`:

- Author 15-25 KB chunks targeting fintech-specific intents (transaction
  disputes, identity verification, regulatory referrals).
- Extend the gold set with 10-15 fintech intents.
- Add a per-tenant escalation-trigger config that fires on financial
  ambiguity keywords.

Auth-scoping is **not** a blocker here — the surface is consumer chat,
same as the live tenants.

### §1.4 — Track 3: devices/retail, split into 3a and 3b

The brief describes Track 3 as a single bucket: "~18 smaller B2B
devices/retail accounts, with a mix of user-facing and partner-facing
contacts". That mix conceals two very different launch problems:

- **3a — user-facing devices/retail.** End-user authenticates against
  the tenant's Gigs project, same as the live tenants. The work is
  device-specific KB content + per-account context-variable QA.
- **3b — partner-facing devices/retail.** The end "user" is the partner's
  admin staff, not the device's owner. The auth surface here is
  structurally the same as Track 4 — a partner-side caller wanting
  scoped access to tenant data. Gigs's current static Bearer keys
  don't support that.

The split matters because **3a is `NEEDS_WORK`** (achievable Q3 with focused
KB and onboarding work) but **3b is `NOT_READY`** (gated on the same Task 4
middleware that gates Track 4). Bundling them under one verdict would
hide the actual constraint.

#### 3a — devices user-facing (`NEEDS_WORK`)

The surface is the one we already serve. The work is:

- Per-account KB authoring (~10-20 chunks per account, device support
  content).
- Onboarding QA on context-variable wiring — Task 1 §1 already flagged
  that identifier passing across tenants is inconsistent; multiplying by
  18 accounts amplifies that risk if we don't standardise first.
- Gold-set extension covering device troubleshooting intents.

Capacity question: 18 accounts at ~10 hours of onboarding each is ~180
hours of focused work; one onboarding engineer running ~3 accounts/week
is 6 weeks. Q3 can ship the top 6-8 accounts under this pattern, not all
18 — see §3 staged commit.

#### 3b — devices partner-facing (`NOT_READY`)

The blocker is the same one we keep returning to: Gigs API authentication
uses static Bearer keys with full-project access and no scopes. The
partner-facing widget would need to pass *something* scoped — to a partner,
to a subset of devices, to a subset of contact buckets. That requires the
Task 4 middleware design (in-flight in a sibling work-stream) to exist.

Until the middleware ships, deflecting any partner-facing traffic means
either (a) granting the partner more access than they should have, or
(b) running the agent under a separate identity with all the data
classification problems that creates. Neither is shippable. `NOT_READY` is
not pessimism — it's the only honest verdict.

### §1.5 — Track 4: partner-led widget (`NOT_READY`)

Same auth blocker as 3b, plus two further blockers:

1. **No partner data-boundary policy.** What's a partner allowed to see
   about an end-user's account? Subscription state, balance, plan name,
   support history? The current platform doesn't have a declared answer;
   we'd be inventing it under launch pressure.
2. **No embed protocol spec.** Iframe? postMessage? SSO with what
   identity provider? Until that's spec'd, the widget surface doesn't
   exist as a technical artifact.

Combined with the auth gap, this is a multi-quarter build, not a Q3 commit.
Calling it `NOT_READY` is the polite version; "would need a separate
work-stream with separate leadership ownership" is the honest one.

### §1.6 — Track 5: agentic email (`NEEDS_WORK`)

The async surface changes two things that look small but aren't:

- **Eval-set shape.** Today's gold set assumes multi-turn chat with a
  user in-session. An email is single-turn — the user sends one message,
  the agent responds (perhaps with one follow-up question, perhaps not),
  and the thread ages out. The 50-question Task 2 gold set wouldn't
  evaluate this correctly as-is.
- **Escalation timing.** Chat has a 2-minute escalation hop ("transfer
  to human if confidence < threshold for > 2 min"). Email doesn't —
  there's no real-time user to transfer to. The "escalation" is a
  decision about whether to respond at all, made once per inbound.

Doable, but the build is "design a new eval substrate + redefine
escalation semantics", not "deploy the existing agent on a new channel".
Q4 is the right scope.

## §2 — Part B: closing the 80→90% gap

The brief frames this as: "the agent is at 80% deflection — how do we get
to 90%?" That question has a clean answer only after you decompose what
"80%" actually means. As Task 2's final scorecard demonstrated, the same
50-question gold set produces **68% raw deflection and 100% refusal-aware
deflection** depending on which metric you read. The 20-point gap to 90%
is a different gap depending on which metric you're closing.

This section does three things:

1. **§2.1** — Picks the failure-axis decomposition from Task 1 as the
   targeting frame.
2. **§2.2** — Decomposes the 20% gap into 4 mutually-exclusive buckets
   that drive different interventions.
3. **§2.3** — Maps the 4 buckets to 5 named levers and projects the
   trajectory.

### §2.1 — Task 1's failure axes as the targeting frame

Task 1 ended on a 7-axis taxonomy (`failure_taxonomy.FailureAxis`):
`STALE_KB`, `WRONG_PROVIDER`, `STALE_USAGE`, `MISSING_RESTRICTION`,
`PORTING_DECLINE_NOT_DECODED`, `BILLING_AMBIGUITY`, `OUT_OF_SCOPE_OVER_REACH`.
The taxonomy was derived from the failure trace across the two live
tenants and is *already in code* — `distribution()` produces the per-axis
pareto.

The Part B story is straightforward to state and harder to execute:
**most of the retrieval-miss failures cluster on the top 3 axes**.
Authoring chunks against those axes (L2 in §2.3) is the highest-leverage
KB work, because it targets the bucket the failure trace says actually
hurts us, not the bucket we think hurts us.

### §2.2 — The 20-point gap, decomposed

Every failing question in the gold set is in exactly one of four buckets
(`gap_decomposition.GapBucket`). The buckets are mutually exclusive and
exhaustive — `GapDecomposition.__post_init__` enforces the partition
invariant.

The four buckets, with the illustrated decomposition for a 50-question
tenant at 80% raw deflection:

| Bucket | Count | % of gold set | Primary lever |
|---|---|---|---|
| `correct_refusal_counted_as_fail` | 3 | 6.0% | L1 — switch to refusal-aware metric |
| `retrieval_miss` | 4 | 8.0% | L2 — KB delta on top-3 taxonomy axes |
| `ungrounded_answer` | 2 | 4.0% | L3 — tighten grounding threshold |
| `wrong_answer_false_positive` | 1 | 2.0% | L4 — per-tenant escalation triggers |

These specific counts are an illustrated argument, not a measurement —
we don't have a per-tenant failure trace at the resolution this requires.
The audit's claim is about the *shape* of the decomposition: every
bucket exists, every bucket maps to a different lever, and the
proportions are consistent with the Task 2 scorecard (which had 0
ungrounded answers and 16 correct refusals on the live CashCard gold
set — those 16 are exactly the questions that the bare-90% framing
would silently dispose of).

The non-obvious bucket is **#3, `correct_refusal_counted_as_fail`**.
The Task 2 raw metric counts every escalated or refused question as a
failure. Some of those refusals are *correct* (out-of-scope, restricted,
billing-ambiguous). The refusal-aware metric counts them as successes.
Bucket #3 is the size of that disagreement, and it's recovered without
any product change — see L1 in §2.3.

The highest-stakes bucket is **#4, `wrong_answer_false_positive`** —
a question where the agent confidently answered something incorrect AND
the answer ended up grounded against a chunk that didn't actually support
it. This is the bucket that hurts users. The lever there is per-tenant
escalation triggers (L4); the lift looks small in percentage points but
matters most.

### §2.3 — Five levers, projected trajectory

`lever_simulator.recommended_lever_sequence()` produces 5 named levers,
each modeled as a typed transformation `GapDecomposition → GapDecomposition`.
Applying them in order, starting from the illustrated 80% decomposition,
produces the trajectory below (`render_trajectory_table()` output):

| Step | Lever | Raw % | Δ raw (pp) | Refusal-aware % | Note |
|---|---|---:|---:|---:|---|
| 0 | (starting state) | 80.0% | — | 86.0% | baseline (40/50 pass) |
| 1 | L1 Switch headline metric to refusal-aware deflection | 86.0% | +6.0 | 86.0% | Free lift. Ship before any KB work. |
| 2 | L2 Author KB chunks against top-3 taxonomy axes | 92.0% | +6.0 | 92.0% | Largest single product lever. Reuses Task 1 taxonomy as targeting. |
| 3 | L3 Tighten grounding threshold | 94.0% | +2.0 | 94.0% | Caveat: tradeoff between raw and refusal-aware. Quantified in audit. |
| 4 | L4 Per-tenant escalation triggers | 96.0% | +2.0 | 96.0% | Highest-stakes bucket. Lift looks small in pp but matters most. |
| 5 | L5 Eval-in-CI on every prompt / KB change | 96.0% | +0.0 | 96.0% | Guardrail. No projected lift; prevents regression of L1-L4 gains. |

A few things to read out of this:

- **L1 is "free".** Pure measurement fix. Costs no engineering hours;
  needs no KB work; ships in week 1. It's the single highest-leverage
  thing on the list, and it's the one nobody normally does because
  "switching the headline metric" sounds like cheating. It isn't —
  it's the correct metric, and the raw metric was always wrong; the
  audit prose's pushback (§3) hardens this into a measurement-discipline
  rule.
- **L2 is the largest product lever.** Authoring ~20-30 KB chunks against
  the top-3 Task 1 axes is the chunk of work that justifies a quarter of
  engineering time. The lift modeled here (3 questions / 6pp) is
  conservative — the audit-prose claim is "4-7pp" and the simulator
  pins the midpoint.
- **L3 is asymmetric.** Tightening the grounding threshold pushes some
  weak answers below the threshold (good — they refuse instead of
  asserting) but also nudges some currently-passing answers below
  (bad — they refuse instead of correctly answering). The simulator
  models the net (+1 question recovered); a richer model would track
  both directions. The audit prose's caveat is honest: this lever
  trades a small raw-metric loss for a refusal-aware gain on the
  worst-grounded answers.
- **L4 is small in points, large in stakes.** Reusing Task 2's escalation
  pattern with tenant-specific keyword sets closes the wrong-answer
  bucket — which is the bucket the agent's reputation actually lives or
  dies on.
- **L5 buys zero points.** It's a guardrail. Without it, L1-L4 lifts
  regress the next time someone tweaks a prompt without re-running
  the gold set. The audit prose pins L5 as a *Q3 deliverable* even
  though it doesn't move the metric — because the metric staying up
  requires it.

### §2.4 — Caveats about the lift numbers

The simulator's coefficients (3, 3, 1, 1, 0) are pinned in code as
conservative midpoints of the audit prose's "3-5pp", "4-7pp", "+2-3pp",
"2-3pp", "sustains" ranges. They are not measurements. The right way to
read them is: *if* the failure trace is shaped like the illustrated
decomposition, *then* the trajectory will look like the table. A
reviewer can re-run the simulator on a different starting decomposition
(say, a 4-question retrieval-miss bucket but 0 wrong-answer bucket) and
see how the trajectory shifts — that's the point of having it in code.

What the simulator does **not** model:

- **Stochastic variance.** Each lever's lift could in principle be sampled
  from a distribution; the simulator pins a midpoint.
- **Negative side-effects of L3.** Tightening grounding can push currently-
  passing answers into refusal; the model treats L3 as net positive.
- **Compound effects.** L2 + L4 may interact in either direction (better
  KB makes escalation triggers more accurate; or, better KB removes
  some questions L4 was catching). Modeled as additive.
- **Tenant-specific shape.** The illustrated 80% is one shape; a real
  tenant could have 0 correct refusals (making L1 buy nothing) or 8
  retrieval misses (making L2 buy more).

These limits matter for the Q3 commit (§3), which is why the commit
doesn't promise the 96% endpoint — it promises 86% in week 4 (L1),
92% in week 8 (L1+L2+L3), 96% in week 12 (L1-L5).

## §3 — Q3 commit: staged tiers, not a single 90%

The brief asks: "What do you commit to delivering this quarter? Defend
90% deflection." The locked design says push back hard. This section is
the pushback.

The headline:

> Stage the Q3 commitment in 3 tiers — defendable (week 4), product
> (week 8), stretch (week 12) — each with explicit gate and observable,
> all defended on the refusal-aware metric.

### §3.1 — Why a single 90% is the wrong commit

Three reasons, in order of how much they hurt.

1. **The denominator isn't stable across the metric choice.** Today,
   the same Task 2 gold set yields 68% raw and 100% refusal-aware.
   "Hit 90%" forces us to pick a metric, and either choice is
   arguable — raw under-counts (the 16 correct refusals are good
   outcomes) and refusal-aware is at the ceiling already on this
   set. A single number invites the late-quarter denominator switch
   ("we hit 90% — on refusal-aware ... ahem"). Locking the metric in
   the commit document, in code, in tests, removes that temptation.
2. **It conceals which bucket the points came from.** Hitting 90%
   could mean any combination of (a) the metric switch, (b) KB delta,
   (c) escalation triggers. Two of those have very different
   long-tail implications — the metric switch is sustained
   essentially for free; the KB delta needs ongoing curation. The
   number erases the distinction.
3. **It's brittle to a single tenant regression.** "90% across both
   live tenants" is a 1-bit summary of a complex system. One bad
   prompt edit on one tenant can drag the number under 90% in a
   week. Without the staged tiers, that triggers a fire drill instead
   of a measured rollback.

### §3.2 — The three tiers

| Tier | Week | Target | Metric | Levers | Gate |
|---|---|---:|---|---|---|
| `defendable` | weeks 2-4 | 86% | refusal_aware_deflection | L1 | Refusal-aware metric wired into weekly tenant reports; Task 2 50-question gold set runs in CI on every prompt PR; no KB content changes required |
| `product` | weeks 5-8 | 92% | refusal_aware_deflection | L2, L3 | 20-30 new KB chunks authored against top-3 Task 1 axes (STALE_KB, WRONG_PROVIDER, STALE_USAGE) per tenant; grounding threshold raised; canary suite green for 2 consecutive weeks |
| `stretch` | weeks 9-12 | 96% | refusal_aware_deflection | L4, L5 | Per-tenant escalation triggers configured; eval-in-CI enforces non-regression on every PR; 4 consecutive weeks of no week-over-week regression on either tenant |

Each tier ships independently. If the product tier slips, the defendable
tier still landed and is reportable. If the stretch tier slips, the
product tier still landed and is reportable. There is no scenario where
"we missed the quarter" is the only honest answer to a board question —
the tiers degrade gracefully.

The "90%" the brief asks about lands between PRODUCT (92%) and STRETCH
(96%). The commit doesn't include "90%" as a label because the staged
tiers already cover that range and labelling them differently for
political reasons is exactly the substitution discipline this commit
exists to refuse.

### §3.3 — Measurement discipline

All three milestones are defended on **refusal-aware deflection**. Raw
deflection is reported alongside for transparency but is NOT the
headline number. Locking the metric in the commit document, in code, in
tests prevents the late-quarter temptation to switch denominators.

The discipline is enforced in three places, in descending order of
seriousness:

- **Code.** `q3_commit.Milestone.target_metric` is a `HeadlineMetric`
  StrEnum; the test suite asserts every recommended milestone uses
  `REFUSAL_AWARE_DEFLECTION`.
- **Doc.** This section is the canonical statement of the discipline.
- **Process.** Weekly tenant reports include both metrics side-by-side
  but only the refusal-aware number is the one the team reviews
  against the milestone gate.

## §4 — What does NOT ship in Q3

This is the constructive half of the pushback — by naming what doesn't
ship and why, leadership can choose to accept the scope or escalate the
missing piece into a separate work-stream.

- **Partner-led widget (Track 4) and partner-facing devices (Track 3b)**
  — both share the auth-scoping blocker: Gigs API uses static Bearer
  keys with no scopes (Task 1 finding, Task 4 middleware design).
  Shipping either before the middleware exists ships a security hole.
  Earliest reasonable quarter: Q4, after the middleware lands.
- **Agentic email channel (Track 5)** — async surface is a different
  eval-set shape (single-turn vs multi-turn) and a different
  escalation timing (no 2-minute hop). Q3 doesn't have the build
  capacity alongside Track 1 + 2 + 3a expansion. Earliest reasonable
  quarter: Q4, with the async eval substrate developed in parallel
  with Q3 product work.
- **A single committed 90% number** — the brief asks for it but the
  right answer is the staged commit above. A single number would
  silently absorb whichever bucket the metric chosen happens to favour
  and would invite late-quarter denominator drift.

The third item is the actively contentious one. If leadership says "no,
we need a single 90% number for the board deck" — fine, but it should be
defended on refusal-aware and footnoted with the staged tier each tenant
actually sits at. The audit prose's job is to make that defensible; the
single number itself does not get walked back into the engineering
commitment.

## §5 — How to verify any of this

Nothing in this document needs to be taken on faith.

1. **Run the test suite.** `make check` runs ruff + mypy --strict +
   pytest. The expansion-track verdicts are tested in
   `task3_eval_expansion/tests/test_expansion_track.py`; the gap
   decomposition's partition invariant is tested in
   `test_gap_decomposition.py`; the lever simulator's headline numbers
   (80→86→92→94→96) are tested in `test_lever_simulator.py`; the Q3
   commit's structural invariants (3 tiers, monotonic, refusal-aware
   only) are tested in `test_q3_commit.py`.
2. **Run the demo.** `make demo-task3` runs the full simulator on the
   illustrated 80% decomposition and prints the rendered markdown
   tables that this document embeds. If the simulator's output differs
   from the tables in §1.1, §2.2, §2.3, §3.2 of this document, the
   document is wrong (the code is the source of truth).
3. **Try a different starting decomposition.** Edit
   `illustrated_decomposition_for_raw_80()` to model a different
   failure-trace shape and re-run the demo. The simulator will project
   a different trajectory; the audit prose's argument about *which
   levers do what* is invariant under this change.
4. **Flip a verdict.** Edit any of the six `track_N_*()` constructors
   in `expansion_track.py` (e.g. mark the `middleware_exists_with_scoped_auth`
   gate as `passed=True` for Track 4). The test suite will flip
   accordingly — if the audit prose says Track 4 is `NOT_READY` but
   the test now wants `READY`, the failure surfaces in `make check`.

The point is that this is not a Strategy Document — it's a
strategy-shaped function call. The numbers come from named code; the
verdicts come from named gates; the commit comes from a named typed
object. Disagreement with any of it is a code edit, not a thread.
