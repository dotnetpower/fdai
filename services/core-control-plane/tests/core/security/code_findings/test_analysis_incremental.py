"""Tests for dependency-aware owned-analysis cache invalidation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_incremental import (
    analyze_python_incremental,
    load_incremental_snapshot,
    save_incremental_snapshot,
)
from fdai.core.security.code_findings.python_analysis import analyze_python_repository
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from pydantic import ValidationError

from ._support import CATALOG_ROOT, REVISION

DIGEST = "sha256:" + "b" * 64


def rule():  # type: ignore[no-untyped-def]
    return next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.python.sql-injection"
    )


def write_repository(root: Path, operator: str = "+") -> None:
    (root / "api.py").write_text(
        """
from flask import request
from query import build
from store import execute

@app.get('/orders')
def orders():
    return execute(build(request.args.get('id')))
""",
        encoding="utf-8",
    )
    (root / "query.py").write_text(
        f"def build(value):\n    return 'SELECT ' {operator} value\n",
        encoding="utf-8",
    )
    (root / "store.py").write_text(
        "def execute(query):\n    return cursor.execute(query)\n",
        encoding="utf-8",
    )


def analyze(
    root: Path,
    previous=None,  # type: ignore[no-untyped-def]
    *,
    revision: str = REVISION,
):  # type: ignore[no-untyped-def]
    return analyze_python_incremental(
        root,
        revision=revision,
        build_context_digest=DIGEST,
        framework_model_digest=rule().digest(),
        rule=rule(),
        previous=previous,
    )


def test_unchanged_inputs_reuse_strict_snapshot_and_round_trip(tmp_path: Path) -> None:
    write_repository(tmp_path)
    first = analyze(tmp_path)
    cache = tmp_path / ".cache" / "analysis.json"
    save_incremental_snapshot(cache, first.snapshot)
    loaded = load_incremental_snapshot(cache)
    second = analyze(tmp_path, loaded)

    assert second.plan.reused_result is True
    assert second.result.graph.digest() == first.result.graph.digest()
    assert tuple(path.digest() for path in second.result.paths) == tuple(
        path.digest() for path in first.result.paths
    )


def test_changed_helper_invalidates_transitive_callers_and_matches_full_run(tmp_path: Path) -> None:
    write_repository(tmp_path)
    first = analyze(tmp_path)
    write_repository(tmp_path, operator="%")

    next_revision = "c" * 40
    incremental = analyze(tmp_path, first.snapshot, revision=next_revision)
    full = analyze_python_repository(
        tmp_path,
        revision=next_revision,
        build_context_digest=DIGEST,
        framework_model_digest=rule().digest(),
        rule=rule(),
    )

    assert incremental.plan.reused_result is False
    assert incremental.plan.changed_files == ("query.py",)
    assert set(incremental.plan.affected_files) == {"api.py", "query.py"}
    assert incremental.result.graph.canonical_bytes() == full.graph.canonical_bytes()
    assert [path.canonical_bytes() for path in incremental.result.paths] == [
        path.canonical_bytes() for path in full.paths
    ]


def test_rule_identity_change_forces_full_invalidation(tmp_path: Path) -> None:
    write_repository(tmp_path)
    first = analyze(tmp_path)
    changed_rule = rule().model_copy(update={"version": "1.0.1"})

    result = analyze_python_incremental(
        tmp_path,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=changed_rule.digest(),
        rule=changed_rule,
        previous=first.snapshot,
    )

    assert result.plan.reason == "analysis_identity_changed"
    assert set(result.plan.affected_files) == {"api.py", "query.py", "store.py"}


def test_revision_only_change_recomputes_without_stale_reuse(tmp_path: Path) -> None:
    write_repository(tmp_path)
    first = analyze(tmp_path)

    second = analyze(tmp_path, first.snapshot, revision="c" * 40)

    assert second.plan.reason == "revision_changed"
    assert second.plan.reused_result is False
    assert set(second.plan.affected_files) == {"api.py", "query.py", "store.py"}
    assert second.result.graph.revision == "c" * 40


def test_frontend_version_change_forces_full_invalidation(tmp_path: Path) -> None:
    write_repository(tmp_path)
    first = analyze(tmp_path)
    stale = first.snapshot.model_copy(update={"frontend_versions": {"python-ast": "0.9.0"}})

    result = analyze(tmp_path, stale)

    assert result.plan.reason == "analysis_identity_changed"


def test_incremental_source_and_cache_symlinks_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "outside.py"
    source.write_text("value = 1\n", encoding="utf-8")
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "linked.py").symlink_to(source)

    with pytest.raises(ValueError, match="unavailable or linked"):
        analyze(repository)

    (repository / "linked.py").unlink()
    write_repository(repository)
    snapshot = analyze(repository).snapshot
    cache = tmp_path / "cache.json"
    target = tmp_path / "target.json"
    target.write_bytes(snapshot.canonical_bytes())
    cache.symlink_to(target)
    with pytest.raises(ValueError, match="unavailable or linked"):
        load_incremental_snapshot(cache)


def test_malformed_incremental_cache_is_rejected(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    cache.write_text('{"schema_version":"1.0.0"}', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_incremental_snapshot(cache)
