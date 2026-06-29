# gigs-submission

Fahad Kiani — take-home submission for the Gigs **Support Platforms Engineer** role.

This repo holds my response to the four tasks in the brief. Each task is a
self-contained subfolder, organised so a reviewer can read the prose, run the
code, and reach the same conclusions I did. Where the prompt's framing felt
off, I push back in the audit doc instead of dressing it up.

## Status

- **Task 1 — Agentic support layer audit.** Complete. Prose at
  [`task1_audit/01_TASK1_AUDIT.md`](task1_audit/01_TASK1_AUDIT.md); code under
  `task1_audit/`; offline demo at `python -m task1_audit.demo` or `make demo`.
- **Task 2 — CashCard launch readiness.** Complete. Prose at
  [`task2_cashcard/02_TASK2_CASHCARD.md`](task2_cashcard/02_TASK2_CASHCARD.md);
  code under `task2_cashcard/`; offline demo at `python -m task2_cashcard.demo`
  or `make demo-task2`.
- **Task 3 — Evaluation and expansion strategy.** Complete. Prose at
  [`task3_eval_expansion/03_TASK3_EVAL.md`](task3_eval_expansion/03_TASK3_EVAL.md);
  code under `task3_eval_expansion/`; offline demo at `python -m task3_eval_expansion.demo`
  or `make demo-task3`. Pushes back on the brief's single 90% target in favour of
  a 3-tier staged commit defended on refusal-aware deflection.
- **Task 4.** Planned but not yet started. It lands in a follow-up commit and
  tag (`v0.4.0-task4`) so a reviewer can read it in isolation.

## Repo layout

```
gigs-submission/
├── README.md                      # this file
├── pyproject.toml                 # ruff, mypy, pytest, hatchling config
├── Makefile                       # one-line entry points (make check, make demo)
├── .github/workflows/ci.yml       # CI: lint + mypy + pytest + demo
├── research/
│   └── 00_gigs_facts.md           # fact pack with citations to Gigs docs
├── task1_audit/
│   ├── 01_TASK1_AUDIT.md          # the Task 1 audit prose
│   ├── escalation_context.py      # human-handoff packet (pydantic)
│   ├── failure_taxonomy.py        # 7-axis classifier for grounded-answer failures
│   ├── grounding_check.py         # offline grounding gate
│   ├── kb_freshness_watcher.py    # Svix-verified webhook -> stale-flag emitter
│   ├── demo.py                    # offline replay of 3 escalations
│   └── tests/                     # 138 deterministic pytest cases
├── task2_cashcard/
│   ├── 02_TASK2_CASHCARD.md       # the Task 2 audit prose
│   ├── cashcard_config.py         # InstanceConfig (pydantic v2, frozen)
│   ├── kb_seed_from_api.py        # pure derivers: plan/porting/eSIM chunks
│   ├── kb_skeleton/               # 21 hand-authored markdown chunks
│   ├── kb_gap_analyzer.py         # gap report vs contact-mix prior
│   ├── escalation_triggers.py     # 7 triggers, first-match-wins
│   ├── week1_canaries.py          # 6 canary checks, post-hoc on agent output
│   ├── eval/
│   │   ├── gold_set.yaml          # 50 questions, distribution matches mix
│   │   └── eval_runner.py         # raw + refusal-aware deflection
│   ├── go_live_checklist.py       # 6-gate readiness checker
│   ├── demo.py                    # 3-block rich demo
│   └── tests/                     # 215 pytest cases
└── task3_eval_expansion/
    ├── 03_TASK3_EVAL.md           # the Task 3 strategy prose
    ├── expansion_track.py         # 6 typed track verdicts (Track 3 split 3a/3b)
    ├── gap_decomposition.py       # 4-bucket partition of the 20% gap
    ├── lever_simulator.py         # 5 levers, pure-function trajectory sim
    ├── q3_commit.py               # staged 3-tier Q3 commit + explicit non-commits
    ├── demo.py                    # 4-block rich demo
    └── tests/                     # 142 pytest cases
```

## How to run

Python 3.11. The repo uses `uv` for installs but plain `pip` works too.

```bash
# Install (editable, with dev deps)
make install
# or:
uv pip install -e ".[dev]"

# Full gate: ruff + mypy + pytest
make check

# Just the offline demo
make demo
```

## Honesty about this repo's surface

A few things I want a reviewer to know up front:

1. **Code-first, not slide-ware.** Every claim in `01_TASK1_AUDIT.md` is
   backed by an artefact: a typed handoff packet, an annotated failure
   taxonomy, a deterministic grounding gate, and a real Svix verifier.
   None of those needs an LLM at the boundary — the audit is testable.
2. **Operator is named where it matters.** When the audit talks about the
   agent layer, I use the name from Gigs' own materials: Operator. When the
   prompt's framing felt incomplete, I say so in §1 / §4 rather than wrapping
   the disagreement in diplomacy.
3. **No mocks where it counts.** The grounding gate, taxonomy, and webhook
   verifier are real code with real tests. The demo replays three concrete
   escalations end-to-end.
4. **Custom to Gigs.** Every design constraint maps to a documented Gigs
   API surface (subscription states, eSIM provider matrix p3/p14/p15,
   usageRecord.updatedAt freshness, Svix CloudEvents). See `research/00_gigs_facts.md`.

## Reproduction summary

- **495 pytest cases**, all green (138 Task 1 + 215 Task 2 + 142 Task 3)
- ruff clean (E, F, I, B, UP, SIM, RUF)
- mypy strict clean across all three task packages
- `python -m task1_audit.demo` prints three escalation verdicts
- `python -m task2_cashcard.demo` prints the launch-readiness scorecard
  (READY verdict, 50/50 gold-set pass, 100% refusal-aware deflection on the
  shipped oracle)
- `python -m task3_eval_expansion.demo` prints expansion verdicts, the 4-bucket
  gap decomposition, the 80→96% lever trajectory, and the staged Q3 commit

Task 4 will arrive in a follow-up commit.
