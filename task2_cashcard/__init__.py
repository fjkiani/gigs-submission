"""Task 2 — CashCard multi-tenant KB design.

Code-first companion to ``02_TASK2_CASHCARD.md``. See submodules:

- ``cashcard_config``       — InstanceConfig + routing/guardrails dataclasses
- ``kb_seed_from_api``      — API → KB chunks (drift-resistant half)
- ``kb_gap_analyzer``       — coverage report against the contact-mix prior
- ``escalation_triggers``   — rules engine: EscalationContext → Trigger
- ``week1_canaries``        — runtime checks for week-1 failure modes
- ``go_live_checklist``     — executable READY/NOT_READY gate
- ``eval.eval_runner``      — gold-set scorecard (raw + refusal-aware)

Builds on Task 1 by direct module imports. Task 1 files are not modified.
"""
