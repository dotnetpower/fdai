"""Resolve the reference seed catalog into exact tracked-source commitments."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fdai.delivery.behavior_knowledge.behavior_seeds import SEEDS, SeedRef
from fdai.shared.providers.behavior_knowledge import BehaviorContent, BehaviorSource, BehaviorSpec

MANIFEST = (
    "services/core-control-plane/src/fdai/delivery/behavior_knowledge/behavior_seeds.generated.json"
)
EXTRACTOR_VERSION = "behavior-seed-v2"
_BLOB = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED = {
    "code": ("services/core-control-plane/src/fdai/", ".py"),
    "test": ("services/core-control-plane/tests/", ".py"),
    "schema": ("rule-catalog/vocabulary/object-types/", ".yaml"),
    "doc": (".github/instructions/", ".md"),
}
_MAX_LINES = 400
_MAX_CHARS = 25000


def _tracked(root: Path) -> set[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to resolve tracked behavior sources")
    result = subprocess.run(  # noqa: S603 - fixed Git executable, no shell
        (git, "ls-files", "-z", "--cached"),
        cwd=root,
        check=True,
        capture_output=True,
    )
    return {path.decode("utf-8") for path in result.stdout.split(b"\0") if path}


def _symbol_range(path: str, symbol: str, lines: list[str]) -> tuple[int, int]:
    if path.endswith(".py"):
        scope: Sequence[ast.AST] = [ast.parse("\n".join(lines) + "\n", filename=path)]
        for part in symbol.split("."):
            matches = [
                child
                for node in scope
                for child in getattr(node, "body", ())
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == part
            ]
            if len(matches) != 1:
                raise ValueError(f"behavior symbol must resolve exactly once: {path}#{symbol}")
            scope = matches
        node = scope[0]
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            raise ValueError(f"invalid behavior symbol: {path}#{symbol}")
        return node.lineno, node.end_lineno or node.lineno
    if path.endswith(".yaml"):
        if symbol != "lifecycle.deduplication":
            raise ValueError(f"unsupported behavior schema symbol: {path}#{symbol}")
        lifecycle_lines = [i for i, line in enumerate(lines, 1) if line == "lifecycle:"]
        schema_matches = [i for i, line in enumerate(lines, 1) if line == "  deduplication:"]
        if (
            len(lifecycle_lines) != 1
            or len(schema_matches) != 1
            or lifecycle_lines[0] >= schema_matches[0]
        ):
            raise ValueError(f"missing or ambiguous behavior schema symbol: {path}#{symbol}")
        start = schema_matches[0]
        end = next(
            (
                i - 1
                for i in range(start + 1, len(lines) + 1)
                if lines[i - 1] and not lines[i - 1].startswith("    ")
            ),
            len(lines),
        )
        return start, end
    if path.endswith(".md"):
        doc_matches = [i for i, line in enumerate(lines, 1) if line == f"## {symbol}"]
        if len(doc_matches) != 1:
            raise ValueError(f"missing or ambiguous behavior doc heading: {path}#{symbol}")
        start = doc_matches[0]
        end = next(
            (i - 1 for i in range(start + 1, len(lines) + 1) if lines[i - 1].startswith("## ")),
            len(lines),
        )
        return start, end
    raise ValueError(f"unsupported behavior source: {path}")


def _source(root: Path, tracked: set[str], ref: SeedRef) -> dict[str, str | int]:
    if ref.kind not in _ALLOWED:
        raise ValueError(f"unsafe behavior source kind: {ref.kind}")
    prefix, suffix = _ALLOWED[ref.kind]
    path = ref.path
    if (
        not path.startswith(prefix)
        or not path.endswith(suffix)
        or "\\" in path
        or ".." in path.split("/")
    ):
        raise ValueError(f"unsafe behavior source path: {path}")
    if path not in tracked:
        raise ValueError(f"missing or untracked behavior source: {path}")
    file = root / path
    if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"unsafe behavior source file: {path}")
    raw = file.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    start, end = _symbol_range(path, ref.symbol, lines)
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"invalid behavior source range: {path}#{ref.symbol}")
    if end - start + 1 > _MAX_LINES or len("\n".join(lines[start - 1 : end])) > _MAX_CHARS:
        raise ValueError(f"unbounded behavior source range: {path}#{ref.symbol}")
    blob = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
    ).hexdigest()
    return BehaviorSource(
        source_kind=ref.kind,  # type: ignore[arg-type]
        path=path,
        symbol=ref.symbol,
        line_start=start,
        line_end=end,
        blob_sha=blob,
        authority_role={
            "code": "implementation",
            "test": "verification",
            "schema": "design",
            "doc": "design",
        }[ref.kind],  # type: ignore[arg-type]
    ).manifest_record()


def generate_manifest(root: Path) -> dict[str, Any]:
    """Build a deterministic, citation-only artifact from the canonical declarations."""
    tracked = _tracked(root)
    ids: set[str] = set()
    subjects: set[tuple[str, str]] = set()
    aliases: set[str] = set()
    intervals: dict[str, list[tuple[int, int]]] = {}
    records: list[dict[str, Any]] = []
    if len(SEEDS) != 13:
        raise ValueError("reference seed catalog must contain exactly 13 behaviors")
    for seed in SEEDS:
        if seed.behavior_id in ids or not seed.behavior_id:
            raise ValueError(f"duplicate or empty behavior id: {seed.behavior_id}")
        ids.add(seed.behavior_id)
        subject = (seed.subject_kind, seed.subject_id)
        if not all(subject) or subject in subjects:
            raise ValueError(f"duplicate or empty behavior subject: {subject}")
        subjects.add(subject)
        if len(seed.aliases) != 2 or any(not alias.strip() for alias in seed.aliases):
            raise ValueError(f"behavior seed needs English and Korean aliases: {seed.behavior_id}")
        for alias in seed.aliases:
            key = alias.casefold().strip()
            if key in aliases:
                raise ValueError(f"duplicate behavior alias: {alias}")
            aliases.add(key)
        for content in (seed.english, seed.korean):
            if any(
                not values or any(not value.strip() or len(value) > 500 for value in values)
                for values in asdict(content).values()
            ):
                raise ValueError(f"missing or unbounded behavior content: {seed.behavior_id}")
        if not seed.refs or (
            seed.status == "implemented" and not {"code", "test"} <= {ref.kind for ref in seed.refs}
        ):
            raise ValueError(f"unsupported implementation claim: {seed.behavior_id}")
        sources = [_source(root, tracked, ref) for ref in seed.refs]
        for source in sources:
            path = str(source["path"])
            start, end = int(source["line_start"]), int(source["line_end"])
            if any(
                start <= previous_end and previous_start <= end
                for previous_start, previous_end in intervals.get(path, [])
            ):
                raise ValueError(f"overlapping behavior citations: {path}")
            intervals.setdefault(path, []).append((start, end))
        digest = hashlib.sha256(
            json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        records.append(
            {
                "behavior_id": seed.behavior_id,
                "subject_kind": seed.subject_kind,
                "subject_id": seed.subject_id,
                "status": seed.status,
                "owner": seed.owner,
                "question_aliases": list(seed.aliases),
                "english": asdict(seed.english),
                "ko": asdict(seed.korean),
                "sources": sources,
                "source_manifest_hash": digest,
            }
        )
    return {"extractor_version": EXTRACTOR_VERSION, "seeds": records}


def serialized_manifest(root: Path) -> str:
    return json.dumps(generate_manifest(root), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def check_manifest(root: Path) -> dict[str, Any]:
    """Reject stale or hand-edited source blobs, symbol ranges and seed metadata."""
    expected = serialized_manifest(root)
    if (root / MANIFEST).read_text(encoding="utf-8") != expected:
        raise ValueError("behavior seed artifact is stale; regenerate from tracked sources")
    return json.loads(expected)  # type: ignore[no-any-return]


def build_seed_behavior_specs(root: Path, *, indexed_commit: str) -> tuple[BehaviorSpec, ...]:
    """Materialize read-only specs only when the entire seed set is current."""
    artifact = check_manifest(root)
    if not _BLOB.fullmatch(indexed_commit):
        raise ValueError("indexed_commit must be a full Git commit SHA")
    return tuple(
        BehaviorSpec(
            behavior_id=row["behavior_id"],
            subject_kind=row["subject_kind"],
            subject_id=row["subject_id"],
            status=row["status"],
            owner=row["owner"],
            question_aliases=tuple(row["question_aliases"]),
            trigger=tuple(row["english"]["trigger"]),
            preconditions=tuple(row["english"]["preconditions"]),
            steps=tuple(row["english"]["steps"]),
            outcomes=tuple(row["english"]["outcomes"]),
            exclusions=tuple(row["english"]["exclusions"]),
            safety=tuple(row["english"]["safety"]),
            localized={
                "ko": BehaviorContent(**{key: tuple(value) for key, value in row["ko"].items()})
            },
            sources=tuple(BehaviorSource(**source) for source in row["sources"]),
            indexed_commit=indexed_commit,
            extractor_version=artifact["extractor_version"],
            source_manifest_hash=row["source_manifest_hash"],
        )
        for row in artifact["seeds"]
    )
