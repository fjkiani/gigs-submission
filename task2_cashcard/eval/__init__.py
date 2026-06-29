"""Pre-launch evaluation harness for CashCard.

Modules:
    eval_runner: walks gold_set.yaml, runs each question through a
        stub agent and the grounding gate, emits a Scorecard with
        raw + refusal-aware deflection and per-bucket breakdown.
"""
