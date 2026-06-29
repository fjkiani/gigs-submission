"""KB coverage analyzer — gap report against the contact-mix prior.

The brief asks "how would you identify content gaps and prioritise". The
answer is: walk the KB tree, read each chunk's frontmatter, group by
`topic`, and compare to the 60-day contact mix. The bucket with the largest
unmet-coverage * weight wins priority.

Frontmatter conventions
-----------------------
Each KB markdown file under `kb_skeleton/` starts with a YAML block:

    ---
    chunk_id: esim.install.ios.first_time
    topic: esim_activation
    intent: how_to_install
    last_reviewed: 2026-06-28
    covers_providers: [p3, p14, p15]
    api_facts_referenced: [eSimProfile.status, sim.type]
    ---

Only `chunk_id` and `topic` are required; the rest are advisory and surfaced
in the report when present.

Output
------
A `GapReport` dataclass that:
- carries per-bucket coverage (chunk count, weight, priority score)
- sorts buckets by priority (descending)
- renders cleanly as text and as YAML
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from task2_cashcard.cashcard_config import CONTACT_BUCKETS

# Default minimum chunks per bucket — anything below this is a gap.
DEFAULT_MIN_CHUNKS_PER_BUCKET = 3

# Frontmatter delimiter pattern: ---\n<yaml>\n---\n
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


@dataclass(frozen=True)
class ChunkMetadata:
    """The parsed frontmatter from one KB markdown file."""

    chunk_id: str
    topic: str
    path: Path
    intent: str | None = None
    last_reviewed: str | None = None
    covers_providers: tuple[str, ...] = ()
    api_facts_referenced: tuple[str, ...] = ()


@dataclass(frozen=True)
class BucketCoverage:
    """Per-bucket coverage row."""

    bucket: str
    chunk_count: int
    weight: float
    min_chunks: int
    # priority = weight * max(0, min_chunks - chunk_count)
    priority: float


@dataclass(frozen=True)
class GapReport:
    """Top-level coverage report.

    `buckets` is sorted by priority descending. `total_chunks` is a sanity
    check that every chunk got counted somewhere (orphaned topic strings
    are surfaced in `unknown_buckets`).
    """

    kb_root: Path
    contact_mix_prior: dict[str, float]
    min_chunks_per_bucket: int
    buckets: tuple[BucketCoverage, ...]
    total_chunks: int
    unknown_buckets: tuple[str, ...] = field(default_factory=tuple)


def _parse_frontmatter(path: Path) -> dict[str, object] | None:
    """Return the YAML frontmatter dict for a markdown file, or None.

    Files without a frontmatter block are skipped silently — they aren't
    KB chunks (could be README, etc.).
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    raw = match.group(1)
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        return None
    return parsed


def _coerce_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, str):
        return (value,)
    raise TypeError(f"expected list/str/None, got {type(value).__name__}")


def load_chunks(kb_root: Path) -> list[ChunkMetadata]:
    """Walk `kb_root`, parse every `*.md` with a frontmatter block.

    Yields one `ChunkMetadata` per file. Files missing required fields
    (chunk_id, topic) raise `ValueError` so silent gaps don't sneak in.
    """
    if not kb_root.exists():
        raise FileNotFoundError(f"kb_root does not exist: {kb_root}")
    if not kb_root.is_dir():
        raise NotADirectoryError(f"kb_root is not a directory: {kb_root}")

    out: list[ChunkMetadata] = []
    for md_path in sorted(kb_root.rglob("*.md")):
        fm = _parse_frontmatter(md_path)
        if fm is None:
            continue
        chunk_id = fm.get("chunk_id")
        topic = fm.get("topic")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError(f"{md_path}: missing required 'chunk_id'")
        if not isinstance(topic, str) or not topic:
            raise ValueError(f"{md_path}: missing required 'topic'")
        intent = fm.get("intent")
        intent_val: str | None = (
            intent if isinstance(intent, str) and intent else None
        )
        last_reviewed = fm.get("last_reviewed")
        last_reviewed_val: str | None = (
            str(last_reviewed)
            if last_reviewed is not None
            else None
        )
        out.append(
            ChunkMetadata(
                chunk_id=chunk_id,
                topic=topic,
                path=md_path,
                intent=intent_val,
                last_reviewed=last_reviewed_val,
                covers_providers=_coerce_str_tuple(fm.get("covers_providers")),
                api_facts_referenced=_coerce_str_tuple(
                    fm.get("api_facts_referenced")
                ),
            )
        )
    return out


def analyse_coverage(
    kb_root: Path,
    contact_mix_prior: dict[str, float],
    *,
    min_chunks_per_bucket: int = DEFAULT_MIN_CHUNKS_PER_BUCKET,
) -> GapReport:
    """Compute per-bucket coverage and rank by priority.

    Priority = weight * max(0, min_chunks - actual_chunks). Higher means
    the bucket needs content most urgently.
    """
    chunks = load_chunks(kb_root)
    counts: Counter[str] = Counter(c.topic for c in chunks)

    # Every bucket in the prior gets a row, even if it has 0 chunks.
    rows: list[BucketCoverage] = []
    for bucket, weight in contact_mix_prior.items():
        actual = counts.get(bucket, 0)
        deficit = max(0, min_chunks_per_bucket - actual)
        priority = weight * deficit
        rows.append(
            BucketCoverage(
                bucket=bucket,
                chunk_count=actual,
                weight=weight,
                min_chunks=min_chunks_per_bucket,
                priority=priority,
            )
        )

    # Sort by priority desc, then bucket name for determinism on ties.
    rows.sort(key=lambda r: (-r.priority, r.bucket))

    # Buckets in the KB that aren't declared in the prior — surface as
    # `unknown_buckets`. Most often a typo in frontmatter.
    declared = set(contact_mix_prior)
    unknown = tuple(sorted(set(counts) - declared))

    return GapReport(
        kb_root=kb_root,
        contact_mix_prior=dict(contact_mix_prior),
        min_chunks_per_bucket=min_chunks_per_bucket,
        buckets=tuple(rows),
        total_chunks=len(chunks),
        unknown_buckets=unknown,
    )


def render_report(report: GapReport) -> str:
    """Render a GapReport as plain text. Used by demo.py."""
    lines = [
        f"KB root: {report.kb_root}",
        f"Total chunks: {report.total_chunks}",
        f"Min chunks per bucket: {report.min_chunks_per_bucket}",
        "",
        f"{'bucket':<24} {'count':>6} {'weight':>8} {'priority':>10}",
        "-" * 52,
    ]
    for row in report.buckets:
        lines.append(
            f"{row.bucket:<24} {row.chunk_count:>6} "
            f"{row.weight:>8.3f} {row.priority:>10.3f}"
        )
    if report.unknown_buckets:
        lines.append("")
        lines.append(
            f"WARN: chunks tagged with unknown buckets: {list(report.unknown_buckets)}"
        )
    return "\n".join(lines)


# Re-export the canonical bucket names so external callers don't import from
# cashcard_config directly.
__all__ = [
    "CONTACT_BUCKETS",
    "DEFAULT_MIN_CHUNKS_PER_BUCKET",
    "BucketCoverage",
    "ChunkMetadata",
    "GapReport",
    "analyse_coverage",
    "load_chunks",
    "render_report",
]
