# CashCard KB skeleton

Hand-authored chunks. The API-derived facts (plan allowances, eSIM
eligibility per provider, the US porting required-fields list, decline
codes) are produced at runtime by `kb_seed_from_api.py` and merged in
when the retriever indexes — they are **not** mirrored here.

What lives here:

- **Policy and posture**: what we will and won't promise (e.g. activation
  timing on each provider, what to do when an answer would require a
  write, how we phrase refusals).
- **Step-by-steps**: install instructions per device family, how to
  reset a profile, what to try before escalating.
- **Decoded errors**: human-readable explanations for the porting
  decline codes and other failure surfaces.
- **Edge cases**: scenarios the API can't speak to directly (lost
  phone, expired plan, abuse pattern) where the agent should refuse or
  escalate.

Layout follows the contact-mix prior. Each bucket folder is named with
the prior's order so KB authors see priority at a glance.

Folder | Bucket | Prior weight
-------|--------|-------------
`01_esim_activation/` | `esim_activation` | 0.35
`02_plan_questions/` | `plan_questions` | 0.25
`03_devices/`        | `devices`         | 0.15
`04_roaming/`        | `roaming`         | 0.10
`05_port_in/`        | `port_in`         | 0.10
`06_other/`          | `other`           | 0.05

Frontmatter: every chunk starts with a YAML block — `chunk_id` and
`topic` are required, others are advisory:

    ---
    chunk_id: esim.install.ios.first_time
    topic: esim_activation
    intent: how_to_install
    last_reviewed: 2026-06-28
    covers_providers: [p3, p14, p15]
    api_facts_referenced: [eSimProfile.status, sim.type]
    ---

`topic` MUST match one of the canonical buckets in
`task2_cashcard.cashcard_config.CONTACT_BUCKETS`. Anything else surfaces
as an "unknown bucket" in the gap report.
