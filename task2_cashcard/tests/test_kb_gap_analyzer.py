"""Tests for kb_gap_analyzer.

We build small in-tmp KB trees so the tests don't depend on the live
kb_skeleton/. The live tree is exercised separately in
test_kb_skeleton_live (below) as a single integration test — that one
catches drift between the skeleton and the analyzer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from task2_cashcard.kb_gap_analyzer import (
    DEFAULT_MIN_CHUNKS_PER_BUCKET,
    BucketCoverage,
    GapReport,
    analyse_coverage,
    load_chunks,
    render_report,
)

# ---- helpers ----------------------------------------------------------------


def _write_chunk(
    root: Path,
    rel_path: str,
    chunk_id: str,
    topic: str,
    *,
    intent: str | None = None,
    last_reviewed: str | None = None,
    covers_providers: tuple[str, ...] | None = None,
    api_facts_referenced: tuple[str, ...] | None = None,
    body: str = "body\n",
    omit_chunk_id: bool = False,
    omit_topic: bool = False,
) -> Path:
    """Write a markdown chunk into the temp KB tree."""
    file_path = root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["---"]
    if not omit_chunk_id:
        lines.append(f"chunk_id: {chunk_id}")
    if not omit_topic:
        lines.append(f"topic: {topic}")
    if intent is not None:
        lines.append(f"intent: {intent}")
    if last_reviewed is not None:
        lines.append(f"last_reviewed: {last_reviewed}")
    if covers_providers is not None:
        lines.append("covers_providers: [" + ", ".join(covers_providers) + "]")
    if api_facts_referenced is not None:
        lines.append("api_facts_referenced: [" + ", ".join(api_facts_referenced) + "]")
    lines.append("---")
    lines.append("")
    lines.append(body)
    file_path.write_text("\n".join(lines))
    return file_path


def _good_prior() -> dict[str, float]:
    return {
        "esim_activation": 0.35,
        "plan_questions": 0.25,
        "devices": 0.15,
        "roaming": 0.10,
        "port_in": 0.10,
        "other": 0.05,
    }


# ---- load_chunks -----------------------------------------------------------


class TestLoadChunks:
    def test_empty_tree_returns_empty(self, tmp_path: Path) -> None:
        chunks = load_chunks(tmp_path)
        assert chunks == []

    def test_skips_files_without_frontmatter(self, tmp_path: Path) -> None:
        (tmp_path / "no_frontmatter.md").write_text("# Just a heading\n")
        chunks = load_chunks(tmp_path)
        assert chunks == []

    def test_parses_required_fields(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "01/sample.md",
            chunk_id="esim.install.sample",
            topic="esim_activation",
        )
        chunks = load_chunks(tmp_path)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "esim.install.sample"
        assert chunks[0].topic == "esim_activation"
        assert chunks[0].intent is None
        assert chunks[0].last_reviewed is None
        assert chunks[0].covers_providers == ()

    def test_parses_optional_fields(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "01/full.md",
            chunk_id="full",
            topic="esim_activation",
            intent="how_to_install",
            last_reviewed="2026-06-28",
            covers_providers=("p3", "p14"),
            api_facts_referenced=("sim.type",),
        )
        chunks = load_chunks(tmp_path)
        assert chunks[0].intent == "how_to_install"
        assert chunks[0].last_reviewed == "2026-06-28"
        assert chunks[0].covers_providers == ("p3", "p14")
        assert chunks[0].api_facts_referenced == ("sim.type",)

    def test_missing_chunk_id_raises(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "bad.md",
            chunk_id="ignored",
            topic="esim_activation",
            omit_chunk_id=True,
        )
        with pytest.raises(ValueError, match="missing required 'chunk_id'"):
            load_chunks(tmp_path)

    def test_missing_topic_raises(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "bad.md",
            chunk_id="x",
            topic="ignored",
            omit_topic=True,
        )
        with pytest.raises(ValueError, match="missing required 'topic'"):
            load_chunks(tmp_path)

    def test_recursive_walk(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "01/a.md",
            chunk_id="a",
            topic="esim_activation",
        )
        _write_chunk(
            tmp_path,
            "02/nested/b.md",
            chunk_id="b",
            topic="plan_questions",
        )
        chunks = load_chunks(tmp_path)
        assert len(chunks) == 2
        # Order is sorted by path
        assert chunks[0].chunk_id == "a"
        assert chunks[1].chunk_id == "b"

    def test_nonexistent_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_chunks(tmp_path / "does_not_exist")

    def test_root_is_file_raises(self, tmp_path: Path) -> None:
        file_path = tmp_path / "regular_file.md"
        file_path.write_text("not a dir")
        with pytest.raises(NotADirectoryError):
            load_chunks(file_path)


# ---- analyse_coverage ------------------------------------------------------


class TestAnalyseCoverage:
    def test_empty_tree_emits_every_bucket_with_max_priority(
        self, tmp_path: Path
    ) -> None:
        report = analyse_coverage(tmp_path, _good_prior())
        # All buckets present
        bucket_names = {b.bucket for b in report.buckets}
        assert bucket_names == set(_good_prior())
        # All have priority > 0 because they're empty
        assert all(b.priority > 0 for b in report.buckets)

    def test_priority_ranks_by_weight_when_all_buckets_empty(
        self, tmp_path: Path
    ) -> None:
        """Highest-weight bucket should come first when all are equally empty."""
        report = analyse_coverage(tmp_path, _good_prior())
        # esim_activation has the highest weight, should rank first
        assert report.buckets[0].bucket == "esim_activation"

    def test_filled_bucket_drops_to_zero_priority(self, tmp_path: Path) -> None:
        for i in range(3):
            _write_chunk(
                tmp_path,
                f"01/chunk_{i}.md",
                chunk_id=f"c{i}",
                topic="esim_activation",
            )
        report = analyse_coverage(tmp_path, _good_prior())
        esim_row = next(b for b in report.buckets if b.bucket == "esim_activation")
        assert esim_row.priority == 0.0
        assert esim_row.chunk_count == 3

    def test_partial_fill_lowers_priority(self, tmp_path: Path) -> None:
        # 1 chunk for esim (weight 0.35), 0 for plan (weight 0.25).
        # Esim deficit: 3-1=2, priority 0.35*2 = 0.70.
        # Plan deficit: 3-0=3, priority 0.25*3 = 0.75.
        # So plan_questions should outrank esim_activation.
        _write_chunk(
            tmp_path,
            "01/a.md",
            chunk_id="a",
            topic="esim_activation",
        )
        report = analyse_coverage(tmp_path, _good_prior())
        ranked = [b.bucket for b in report.buckets]
        assert ranked.index("plan_questions") < ranked.index("esim_activation")

    def test_unknown_bucket_surfaces(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "01/typo.md",
            chunk_id="t",
            topic="esimm_activation",  # deliberate typo
        )
        report = analyse_coverage(tmp_path, _good_prior())
        assert "esimm_activation" in report.unknown_buckets

    def test_no_typos_leaves_unknown_empty(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "01/clean.md",
            chunk_id="c",
            topic="esim_activation",
        )
        report = analyse_coverage(tmp_path, _good_prior())
        assert report.unknown_buckets == ()

    def test_custom_min_chunks(self, tmp_path: Path) -> None:
        # With min=1, three chunks easily clear it for esim.
        for i in range(3):
            _write_chunk(
                tmp_path,
                f"01/c_{i}.md",
                chunk_id=f"c{i}",
                topic="esim_activation",
            )
        report = analyse_coverage(
            tmp_path, _good_prior(), min_chunks_per_bucket=1
        )
        esim_row = next(b for b in report.buckets if b.bucket == "esim_activation")
        assert esim_row.min_chunks == 1
        assert esim_row.priority == 0.0

    def test_total_chunks_count_is_correct(self, tmp_path: Path) -> None:
        for i in range(3):
            _write_chunk(
                tmp_path,
                f"01/a_{i}.md",
                chunk_id=f"a{i}",
                topic="esim_activation",
            )
        for i in range(2):
            _write_chunk(
                tmp_path,
                f"02/b_{i}.md",
                chunk_id=f"b{i}",
                topic="plan_questions",
            )
        # Also a typo bucket — should still count toward total
        _write_chunk(
            tmp_path,
            "99/typo.md",
            chunk_id="t",
            topic="wrong_bucket",
        )
        report = analyse_coverage(tmp_path, _good_prior())
        assert report.total_chunks == 6  # 3 + 2 + 1 typo

    def test_default_min_chunks(self, tmp_path: Path) -> None:
        report = analyse_coverage(tmp_path, _good_prior())
        for bucket in report.buckets:
            assert bucket.min_chunks == DEFAULT_MIN_CHUNKS_PER_BUCKET

    def test_dataclasses_are_frozen(self, tmp_path: Path) -> None:
        import dataclasses

        report = analyse_coverage(tmp_path, _good_prior())
        assert isinstance(report, GapReport)
        assert isinstance(report.buckets[0], BucketCoverage)
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.buckets[0].priority = -1.0  # type: ignore[misc]


# ---- render_report ---------------------------------------------------------


class TestRenderReport:
    def test_render_includes_all_buckets(self, tmp_path: Path) -> None:
        report = analyse_coverage(tmp_path, _good_prior())
        rendered = render_report(report)
        for bucket in _good_prior():
            assert bucket in rendered

    def test_render_shows_unknown_warning(self, tmp_path: Path) -> None:
        _write_chunk(
            tmp_path,
            "01/typo.md",
            chunk_id="t",
            topic="esimm_activation",
        )
        report = analyse_coverage(tmp_path, _good_prior())
        rendered = render_report(report)
        assert "WARN" in rendered
        assert "esimm_activation" in rendered

    def test_render_no_warning_when_no_unknowns(self, tmp_path: Path) -> None:
        report = analyse_coverage(tmp_path, _good_prior())
        rendered = render_report(report)
        assert "WARN" not in rendered


# ---- live skeleton (integration) -------------------------------------------


class TestLiveSkeleton:
    """One integration test that hits the real kb_skeleton/ folder.

    Catches drift between the shipped skeleton and the analyzer's
    schema. Light on assertions — just confirms it parses and every
    declared bucket is met by ≥3 chunks.
    """

    def test_shipped_skeleton_meets_minimum(self) -> None:
        skeleton = Path(__file__).parent.parent / "kb_skeleton"
        prior = _good_prior()
        report = analyse_coverage(skeleton, prior)
        # No unknown buckets in shipped tree
        assert report.unknown_buckets == ()
        # Every bucket meets the default minimum
        for bucket in report.buckets:
            assert bucket.chunk_count >= DEFAULT_MIN_CHUNKS_PER_BUCKET, (
                f"shipped {bucket.bucket} has only {bucket.chunk_count} chunks "
                f"(need ≥{DEFAULT_MIN_CHUNKS_PER_BUCKET})"
            )
        # Sanity: total chunks ≥ 18 (6 buckets * 3 minimum)
        assert report.total_chunks >= 18
