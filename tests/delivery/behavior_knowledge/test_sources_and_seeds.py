"""Tracked-source freshness and built-in behavior seed tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from fdai.delivery.behavior_knowledge import InMemoryBehaviorKnowledgeIndex
from fdai.delivery.behavior_knowledge.seeds import (
    SEED_SOURCE_PATHS,
    build_seed_behavior_specs,
)
from fdai.delivery.behavior_knowledge.source_freshness import GitTrackedSourceValidator
from fdai.shared.providers.behavior_knowledge import BehaviorSource


def _git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("git executable is unavailable")
    return subprocess.run(  # noqa: S603 - fixed executable, no shell
        (executable, *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def test_validator_allows_only_tracked_files_and_detects_staleness(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    tracked = tmp_path / "tracked.py"
    untracked = tmp_path / "untracked.py"
    tracked.write_text("value = 1\n", encoding="utf-8")
    untracked.write_text("value = 2\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.py")
    original_sha = _git(tmp_path, "hash-object", "tracked.py")
    validator = GitTrackedSourceValidator(tmp_path)
    source = BehaviorSource(
        source_kind="code",
        path="tracked.py",
        symbol="value",
        line_start=1,
        line_end=1,
        blob_sha=original_sha,
        authority_role="implementation",
    )

    assert (await validator.validate(source)).fresh
    tracked.write_text("value = 3\n", encoding="utf-8")
    stale = await validator.validate(source)
    assert stale.tracked
    assert not stale.fresh
    assert stale.current_blob_sha != original_sha

    untracked_source = BehaviorSource(
        source_kind="code",
        path="untracked.py",
        symbol="value",
        line_start=1,
        line_end=1,
        blob_sha=_git(tmp_path, "hash-object", "untracked.py"),
        authority_role="implementation",
    )
    untracked_result = await validator.validate(untracked_source)
    assert not untracked_result.tracked
    assert not untracked_result.fresh


async def test_seed_contracts_answer_required_questions_without_raw_source() -> None:
    specs = build_seed_behavior_specs(
        indexed_commit="commit-sha",
        blob_shas={path: f"blob-{index}" for index, path in enumerate(SEED_SOURCE_PATHS)},
    )
    index = InMemoryBehaviorKnowledgeIndex()
    for spec in specs:
        await index.upsert(spec)

    incident = (await index.search("Incident ID는 어떻게 생성돼?"))[0].spec
    odin_trigger = (await index.search("언제 Odin이 개입해?"))[0].spec
    odin_exclusion = (await index.search("Odin이 개입하지 않는 경우는?"))[0].spec
    issue = (await index.search("Issue 중복은 어떻게 처리해?"))[0].spec

    assert incident.behavior_id == "incident.deterministic-id"
    assert "Deduplicate and sort" in incident.steps[1]
    assert odin_trigger.behavior_id == "odin.cross-domain-arbitration"
    assert odin_exclusion.behavior_id == odin_trigger.behavior_id
    assert "single-domain" in odin_exclusion.exclusions[0]
    assert issue.behavior_id == "issue.fingerprint-deduplication"
    assert all("def " not in item for spec in specs for item in spec.search_text().splitlines())
    assert all("text" not in source.citation() for spec in specs for source in spec.sources)


def test_every_seed_citation_is_current_and_symbol_precise() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    indexed_commit = _git(repository_root, "rev-parse", "HEAD")
    blob_shas = {
        path: _git(repository_root, "hash-object", "--", path) for path in SEED_SOURCE_PATHS
    }

    for spec in build_seed_behavior_specs(
        indexed_commit=indexed_commit,
        blob_shas=blob_shas,
    ):
        for source in spec.sources:
            lines = (repository_root / source.path).read_text(encoding="utf-8").splitlines()
            assert 1 <= source.line_start <= source.line_end <= len(lines)
            fragment = "\n".join(lines[source.line_start - 1 : source.line_end])
            assert source.symbol.rsplit(".", 1)[-1] in fragment
