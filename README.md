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
- **Tasks 2-4.** Planned but not yet started — see
  [`/mnt/results/execution_trace/PLAN.md`](https://example.invalid/) for the
  overall plan (kept in my working notes; not part of this repo's surface).

## Repo layout

```
gigs-submission/
├── README.md                      # this file
├── pyproject.toml                 # ruff, mypy, pytest, hatchling config
├── Makefile                       # one-line entry points (make check, make demo)
├── .github/workflows/ci.yml       # CI: lint + mypy + pytest + demo
├── research/
│   └── 00_gigs_facts.md           # fact pack with citations to Gigs docs
└── task1_audit/
    ├── 01_TASK1_AUDIT.md          # the audit prose
    ├── escalation_context.py      # human-handoff packet (pydantic)
    ├── failure_taxonomy.py        # 7-axis classifier for grounded-answer failures
    ├── grounding_check.py         # offline grounding gate
    ├── kb_freshness_watcher.py    # Svix-verified webhook -> stale-flag emitter
    ├── demo.py                    # offline replay of 3 escalations
    └── tests/                     # 106 deterministic pytest cases
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

- 106 pytest cases, all green
- ruff clean (E, F, I, B, UP, SIM, RUF)
- mypy strict clean
- `python -m task1_audit.demo` prints the three expected verdicts: ungrounded /
  grounded / refused

Hand-off after Task 1 is complete; Tasks 2-4 will arrive in follow-up commits.
