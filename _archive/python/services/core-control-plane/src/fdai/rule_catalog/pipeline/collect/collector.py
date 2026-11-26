"""Pipeline orchestrator - fetch, verify, snapshot.

Parser + normalization stages ship in follow-up phases; this module
lands the deterministic side (fetch by pinned revision → hash → write
a tamper-evident snapshot with provenance). The output layout is:

    rule-catalog/sources/<id>/<short-revision>/
        SNAPSHOT.json       ← provenance (source id, revision, sha256, ts)
        tree/               ← copied source files (verbatim)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

from fdai.rule_catalog.pipeline.collect.fetch import (
    Fetcher,
    FetchError,
    build_fetcher,
)
from fdai.rule_catalog.schema.source_manifest import (
    FetchKind,
    Redistribution,
    SourceManifest,
    load_source_manifest_from_yaml,
)

_SNAPSHOT_MANIFEST: Final[str] = "SNAPSHOT.json"
_SUCCESS_RECEIPT: Final[str] = "COLLECTION_SUCCESS.json"
RedistributionValue = Literal["embeddable", "reference-only"]


def _redistribution_value(value: object) -> RedistributionValue:
    raw = str(value)
    if raw not in {item.value for item in Redistribution}:
        raise ValueError("collector success redistribution MUST be declared")
    return cast(RedistributionValue, raw)


@dataclass(frozen=True, slots=True)
class SnapshotReport:
    """Frozen record describing one collector run.

    ``mismatch`` is set when the manifest carried an ``expected_sha256``
    (kind=http) and the computed hash differs - the caller SHOULD abort
    a promotion when that field is populated.
    """

    source_id: str
    resolved_revision: str
    snapshot_dir: Path
    content_sha256: str
    file_count: int
    parser: str
    license: str
    redistribution: str
    mismatch: str | None = None


@dataclass(frozen=True, slots=True)
class CollectorSuccessReceipt:
    """Validated, replayable evidence that one source collection succeeded."""

    source_id: str
    resolved_revision: str
    content_sha256: str
    license: str
    redistribution: RedistributionValue
    verified_rules: int
    verified_at: datetime

    def __post_init__(self) -> None:
        if not self.source_id or not self.resolved_revision or not self.license:
            raise ValueError("collector success provenance fields MUST NOT be empty")
        if len(self.content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_sha256
        ):
            raise ValueError("collector success content_sha256 MUST be lowercase SHA-256")
        if self.redistribution not in {item.value for item in Redistribution}:
            raise ValueError("collector success redistribution MUST be declared")
        if self.verified_rules < 1:
            raise ValueError("collector success requires at least one verified rule")
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("collector success verified_at MUST be timezone-aware")

    def to_mapping(self) -> dict[str, object]:
        """Return the stable receipt shape persisted beside the snapshot."""
        return {
            "schema_version": "1.0.0",
            "source_id": self.source_id,
            "resolved_revision": self.resolved_revision,
            "content_sha256": self.content_sha256,
            "license": self.license,
            "redistribution": self.redistribution,
            "verified_rules": self.verified_rules,
            "verified_at": self.verified_at.isoformat(),
            "schema_validated": True,
            "provenance_validated": True,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> CollectorSuccessReceipt:
        """Validate a persisted success receipt without trusting its producer."""
        if value.get("schema_version") != "1.0.0":
            raise ValueError("collector success schema_version MUST be 1.0.0")
        if value.get("schema_validated") is not True:
            raise ValueError("collector success MUST prove schema validation")
        if value.get("provenance_validated") is not True:
            raise ValueError("collector success MUST prove provenance validation")
        try:
            verified_at = datetime.fromisoformat(str(value["verified_at"]))
            verified_rules = int(value["verified_rules"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("collector success receipt is malformed") from exc
        return cls(
            source_id=str(value.get("source_id") or ""),
            resolved_revision=str(value.get("resolved_revision") or ""),
            content_sha256=str(value.get("content_sha256") or ""),
            license=str(value.get("license") or ""),
            redistribution=_redistribution_value(value.get("redistribution") or ""),
            verified_rules=verified_rules,
            verified_at=verified_at,
        )


class CollectorPipeline:
    """Fetch + verify + snapshot for one source manifest."""

    def __init__(
        self,
        *,
        repo_root: Path,
        output_root: Path | None = None,
        fetcher: Fetcher | None = None,
    ) -> None:
        if not repo_root.is_dir():
            raise ValueError(f"repo_root MUST be a directory; got {repo_root!r}")
        self._repo_root = repo_root
        self._output_root = output_root or (repo_root / "rule-catalog" / "sources")
        # A caller MAY pin a specific fetcher (tests) - otherwise the
        # dispatcher runs, kind-aware.
        self._fetcher_override = fetcher

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_from_manifest_path(
        self, manifest_path: Path, *, dry_run: bool = False
    ) -> SnapshotReport:
        manifest = load_source_manifest_from_yaml(manifest_path)
        return self.collect(manifest, dry_run=dry_run)

    def collect(self, manifest: SourceManifest, *, dry_run: bool = False) -> SnapshotReport:
        """Fetch and hash one source, then materialize only redistributable content.

        Reference-only sources may run in dry-run mode to produce a transient hash report, but
        their raw trees are never copied into a persistent snapshot directory.
        """
        fetcher = self._fetcher_override or build_fetcher(
            manifest.fetch.kind, repo_root=self._repo_root
        )

        with tempfile.TemporaryDirectory(prefix="fdai-collect-") as tmpname:
            tmp = Path(tmpname)
            work = tmp / "work"
            work.mkdir(parents=True, exist_ok=True)
            result = fetcher.fetch(config=manifest.fetch, dest_root=work)
            content_hash = _hash_tree(result.tree_root)
            file_count = _count_files(result.tree_root)

            mismatch = None
            if (
                manifest.fetch.kind is FetchKind.HTTP
                and manifest.fetch.expected_sha256
                and manifest.fetch.expected_sha256 != content_hash
            ):
                mismatch = f"expected_sha256={manifest.fetch.expected_sha256} actual={content_hash}"

            if manifest.redistribution is Redistribution.REFERENCE_ONLY and not dry_run:
                raise ValueError(
                    "reference-only sources require --dry-run; raw source trees "
                    "cannot be materialized"
                )

            snapshot_dir = self._snapshot_dir_for(manifest.id, result.resolved_revision)

            if dry_run or mismatch is not None:
                # Never touch on-disk snapshots for a dry-run or mismatch;
                # the caller decides whether to retry.
                return SnapshotReport(
                    source_id=manifest.id,
                    resolved_revision=result.resolved_revision,
                    snapshot_dir=snapshot_dir,
                    content_sha256=content_hash,
                    file_count=file_count,
                    parser=manifest.parser,
                    license=manifest.license,
                    redistribution=manifest.redistribution.value,
                    mismatch=mismatch,
                )

            self._materialize(
                snapshot_dir=snapshot_dir,
                tree_root=result.tree_root,
                manifest=manifest,
                resolved_revision=result.resolved_revision,
                content_hash=content_hash,
                file_count=file_count,
            )
            return SnapshotReport(
                source_id=manifest.id,
                resolved_revision=result.resolved_revision,
                snapshot_dir=snapshot_dir,
                content_sha256=content_hash,
                file_count=file_count,
                parser=manifest.parser,
                license=manifest.license,
                redistribution=manifest.redistribution.value,
                mismatch=None,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _snapshot_dir_for(self, source_id: str, revision: str) -> Path:
        short = _short_revision(revision)
        return self._output_root / source_id / short

    def _materialize(
        self,
        *,
        snapshot_dir: Path,
        tree_root: Path,
        manifest: SourceManifest,
        resolved_revision: str,
        content_hash: str,
        file_count: int,
    ) -> None:
        # Idempotent overwrite - the pipeline's contract is that the same
        # (source, revision) always yields the same snapshot bytes; a
        # re-run REPLACES the tree so a mid-flight failure never leaves
        # a half-written directory that later tools would treat as valid.
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        snapshot_dir.mkdir(parents=True)

        target_tree = snapshot_dir / "tree"
        shutil.copytree(tree_root, target_tree)

        provenance = {
            "source_id": manifest.id,
            "name": manifest.name,
            "license": manifest.license,
            "redistribution": manifest.redistribution.value,
            "parser": manifest.parser,
            "resolved_revision": resolved_revision,
            "fetch_kind": manifest.fetch.kind.value,
            "content_sha256": content_hash,
            "file_count": file_count,
            "collected_at": datetime.now(tz=UTC).isoformat(),
        }
        (snapshot_dir / _SNAPSHOT_MANIFEST).write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_revision(revision: str) -> str:
    """Sanitize + shorten a revision for use as a directory name.

    Git commit shas are already filesystem-safe; local paths may include
    slashes → hash them so the on-disk layout stays flat and portable.
    """
    if all(c.isalnum() for c in revision):
        return revision[:12] if len(revision) > 12 else revision
    return hashlib.sha256(revision.encode("utf-8")).hexdigest()[:12]


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _hash_tree(root: Path) -> str:
    """Deterministic SHA-256 over the sorted (relative-path, content) pairs."""
    digest = hashlib.sha256()
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _count_files(root: Path) -> int:
    return sum(1 for _ in _iter_files(root))


def record_success_receipt(
    report: SnapshotReport,
    *,
    verified_rules: int,
    verified_at: datetime | None = None,
) -> CollectorSuccessReceipt:
    """Atomically record success after schema and exact provenance validation."""
    if report.mismatch is not None:
        raise ValueError("collector hash mismatch cannot produce a success receipt")
    snapshot_path = report.snapshot_dir / _SNAPSHOT_MANIFEST
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("collector snapshot provenance is unavailable") from exc
    if not isinstance(raw, dict):
        raise ValueError("collector snapshot provenance MUST be an object")
    expected = {
        "source_id": report.source_id,
        "resolved_revision": report.resolved_revision,
        "content_sha256": report.content_sha256,
        "license": report.license,
        "redistribution": report.redistribution,
    }
    if any(raw.get(key) != value for key, value in expected.items()):
        raise ValueError("collector snapshot provenance does not match the verified report")
    receipt = CollectorSuccessReceipt(
        source_id=report.source_id,
        resolved_revision=report.resolved_revision,
        content_sha256=report.content_sha256,
        license=report.license,
        redistribution=_redistribution_value(report.redistribution),
        verified_rules=verified_rules,
        verified_at=verified_at or datetime.now(tz=UTC),
    )
    target = report.snapshot_dir / _SUCCESS_RECEIPT
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(receipt.to_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return receipt


def read_success_receipt(path: Path) -> CollectorSuccessReceipt:
    """Load and validate one persisted collection success receipt."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("collector success receipt is unavailable") from exc
    if not isinstance(raw, dict):
        raise ValueError("collector success receipt MUST be an object")
    return CollectorSuccessReceipt.from_mapping(raw)


__all__ = [
    "CollectorSuccessReceipt",
    "CollectorPipeline",
    "FetchError",
    "SnapshotReport",
    "read_success_receipt",
    "record_success_receipt",
]
