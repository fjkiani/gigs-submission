"""Tests for task2_cashcard.demo.

The demo is a thin Rich-rendered wrapper around the readiness checker,
eval runner, and gap analyzer. We don't snapshot the *output* (it
contains ANSI codes that drift across rich versions); instead we
confirm the demo runs end-to-end without raising and exercises each
of the three blocks.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from task2_cashcard import demo


class TestDemoEndToEnd:
    def test_main_runs_without_exception(self) -> None:
        # Capture stdout/stderr via the Console redirection point.
        buf = io.StringIO()
        old_console = demo.Console  # type: ignore[attr-defined]
        try:
            demo.Console = lambda **kw: Console(  # type: ignore[attr-defined]
                file=buf, force_terminal=False, width=120, **kw
            )
            demo.main()
        finally:
            demo.Console = old_console  # type: ignore[attr-defined]
        out = buf.getvalue()
        assert out, "demo produced no output"

    def test_output_mentions_each_block(self) -> None:
        buf = io.StringIO()
        old_console = demo.Console  # type: ignore[attr-defined]
        try:
            demo.Console = lambda **kw: Console(  # type: ignore[attr-defined]
                file=buf, force_terminal=False, width=120, **kw
            )
            demo.main()
        finally:
            demo.Console = old_console  # type: ignore[attr-defined]
        out = buf.getvalue()
        # The three section headers, in plain text
        assert "Go-live readiness" in out
        assert "Eval scorecard" in out
        assert "KB coverage" in out

    def test_verdict_is_ready_for_shipped_config(self) -> None:
        buf = io.StringIO()
        old_console = demo.Console  # type: ignore[attr-defined]
        try:
            demo.Console = lambda **kw: Console(  # type: ignore[attr-defined]
                file=buf, force_terminal=False, width=120, **kw
            )
            demo.main()
        finally:
            demo.Console = old_console  # type: ignore[attr-defined]
        out = buf.getvalue()
        # The verdict footer says "Verdict: READY" plainly. The
        # intro panel mentions both READY and NOT_READY as part of the
        # documentation text, so we have to look for the actual
        # verdict line.
        assert "Verdict: READY" in out
        assert "Verdict: NOT_READY" not in out

    def test_eval_metrics_present(self) -> None:
        buf = io.StringIO()
        old_console = demo.Console  # type: ignore[attr-defined]
        try:
            demo.Console = lambda **kw: Console(  # type: ignore[attr-defined]
                file=buf, force_terminal=False, width=120, **kw
            )
            demo.main()
        finally:
            demo.Console = old_console  # type: ignore[attr-defined]
        out = buf.getvalue()
        assert "raw_deflection" in out
        assert "refusal_aware" in out
        # The 75% target should be named so reviewers see the bar
        assert "75%" in out


class TestDemoHelpers:
    def test_render_readiness_table_has_six_rows(self) -> None:
        from pathlib import Path

        from task1_audit.kb_freshness_watcher import KB_INVALIDATING_EVENT_TYPES
        from task2_cashcard.go_live_checklist import assess_readiness
        from task2_cashcard.tests.fixtures import make_config

        kb = Path(__file__).parent.parent / "kb_skeleton"
        gold = Path(__file__).parent.parent / "eval" / "gold_set.yaml"
        report = assess_readiness(
            config=make_config(),
            kb_root=kb,
            gold_set_path=gold,
            secrets={"SVIX_SHARED_SECRET": "x"},
            subscribed_event_types=KB_INVALIDATING_EVENT_TYPES,
        )
        t = demo._render_readiness_table(report)
        assert t.row_count == 6

    def test_kb_coverage_table_has_six_buckets(self) -> None:
        from pathlib import Path

        from task2_cashcard.tests.fixtures import make_config

        kb = Path(__file__).parent.parent / "kb_skeleton"
        cfg = make_config()
        t = demo._render_kb_coverage_table(kb, cfg.contact_mix_prior)
        assert t.row_count == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
