"""Whole-catalog precision and fail-closed reference seed checks."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.core.knowledge.behavior_index import (
    InMemoryBehaviorKnowledgeIndex,
    TrackedSourceFreshnessValidator,
)
from fdai.delivery.behavior_knowledge import behavior_seed_generation as generator
from fdai.delivery.behavior_knowledge import behavior_seeds as catalog

ROOT = Path(__file__).resolve().parents[5]
EXPECTED_IDS = {
    "incident.deterministic-id",
    "odin.cross-domain-arbitration",
    "issue.fingerprint-deduplication",
    "architecture.trust-tier-routing",
    "architecture.t2-quality-gate",
    "architecture.human-approval-separation",
    "architecture.shadow-promotion",
    "architecture.executor-safety",
    "architecture.console-identity-boundary",
    "architecture.event-ingest-dedup",
    "architecture.vidar-rollback",
    "architecture.bragi-translator",
    "architecture.local-evidence-parity",
}


def _commit_sha() -> str:
    git = shutil.which("git")
    if git is None:
        pytest.fail("git is required for behavior source precision")
    return subprocess.run(  # noqa: S603 - fixed Git executable, no shell
        (git, "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def test_all_thirteen_seeds_bind_current_tracked_symbols_and_blobs() -> None:
    git = shutil.which("git")
    if git is None:
        pytest.fail("git is required for behavior source precision")
    manifest = generator.check_manifest(ROOT)
    assert {row["behavior_id"] for row in manifest["seeds"]} == EXPECTED_IDS
    assert len(manifest["seeds"]) == 13
    assert [row["status"] for row in manifest["seeds"]].count("designed") == 2
    assert all(row["english"] != row["ko"] for row in manifest["seeds"])
    for row in manifest["seeds"]:
        assert row["sources"]
        for source in row["sources"]:
            path = source["path"]
            current = subprocess.run(  # noqa: S603 - fixed Git executable, no shell
                (git, "hash-object", "--", path),
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            assert source["blob_sha"] == current
            lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
            assert generator._symbol_range(path, source["symbol"], lines) == (
                source["line_start"],
                source["line_end"],
            )
            assert 1 <= source["line_start"] <= source["line_end"] <= len(lines)
    specs = generator.build_seed_behavior_specs(ROOT, indexed_commit=_commit_sha())
    assert {spec.behavior_id for spec in specs} == EXPECTED_IDS
    assert all("ko" in spec.localized and spec.sources for spec in specs)
    assert all("body" not in source.citation() for spec in specs for source in spec.sources)


async def test_every_bilingual_alias_resolves_to_fresh_reference_contract() -> None:
    specs = generator.build_seed_behavior_specs(ROOT, indexed_commit=_commit_sha())
    tracked = {source.path: source.blob_sha for spec in specs for source in spec.sources}
    index = InMemoryBehaviorKnowledgeIndex(TrackedSourceFreshnessValidator(tracked))
    for spec in specs:
        await index.upsert(spec)
    for spec in specs:
        for alias in spec.question_aliases:
            result = (await index.search(alias, k=1))[0]
            assert result.spec.behavior_id == spec.behavior_id
            assert result.match_kind == "exact_alias"
            assert not result.stale


@pytest.mark.parametrize("field", ["blob_sha", "line_start", "line_end", "path", "symbol"])
def test_checked_artifact_rejects_stale_source_metadata(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = generator.generate_manifest(ROOT)
    source = artifact["seeds"][0]["sources"][0]
    source[field] = (
        "0" * 40
        if field == "blob_sha"
        else "missing.py"
        if field == "path"
        else "missing.symbol"
        if field == "symbol"
        else source[field] + 1
    )
    original_read = Path.read_text

    def altered_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == ROOT / generator.MANIFEST:
            return json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", altered_read)
    with pytest.raises(ValueError, match="artifact is stale"):
        generator.check_manifest(ROOT)


@pytest.mark.parametrize(
    "ref",
    [
        catalog.SeedRef("code", "services/core-control-plane/src/fdai/../secret.py", "secret"),
        catalog.SeedRef("code", "services/core-control-plane/src/fdai/missing.py", "missing"),
        catalog.SeedRef(
            "code",
            "services/core-control-plane/src/fdai/core/incident/registry.py",
            "IncidentRegistry.absent",
        ),
        catalog.SeedRef("code", "docs/diagrams/generated/fake.py", "fake"),
        catalog.SeedRef(
            "schema", "rule-catalog/vocabulary/object-types/Issue.yaml", "lifecycle.closure"
        ),
    ],
)
def test_generator_rejects_missing_or_unsafe_definitions(
    ref: catalog.SeedRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = catalog.SEEDS[0]
    monkeypatch.setattr(
        generator, "SEEDS", (replace(first, status="designed", refs=(ref,)), *catalog.SEEDS[1:])
    )
    with pytest.raises(ValueError, match="unsafe|missing|symbol|schema"):
        generator.generate_manifest(ROOT)


def test_generator_rejects_overlapping_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    first = catalog.SEEDS[0]
    monkeypatch.setattr(
        generator,
        "SEEDS",
        (replace(first, refs=(*first.refs, first.refs[0])), *catalog.SEEDS[1:]),
    )
    with pytest.raises(ValueError, match="overlapping"):
        generator.generate_manifest(ROOT)


def test_generator_rejects_duplicate_ids_aliases_and_unsupported_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second, *rest = catalog.SEEDS
    for changed in (
        replace(second, behavior_id=first.behavior_id),
        replace(second, subject_kind=first.subject_kind, subject_id=first.subject_id),
        replace(second, aliases=(first.aliases[0], second.aliases[1])),
        replace(second, refs=(catalog.SEEDS[-1].refs[0],)),
    ):
        monkeypatch.setattr(generator, "SEEDS", (first, changed, *rest))
        with pytest.raises(ValueError, match="duplicate|unsupported"):
            generator.generate_manifest(ROOT)


def test_generator_rejects_missing_or_unbounded_localization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = catalog.SEEDS[0]
    for korean in (
        replace(first.korean, safety=()),
        replace(first.korean, safety=("가" * 501,)),
    ):
        monkeypatch.setattr(generator, "SEEDS", (replace(first, korean=korean), *catalog.SEEDS[1:]))
        with pytest.raises(ValueError, match="missing or unbounded"):
            generator.generate_manifest(ROOT)


def test_generated_artifact_is_deterministic_and_has_no_source_bodies() -> None:
    assert generator.serialized_manifest(ROOT) == generator.serialized_manifest(ROOT)
    raw = (ROOT / generator.MANIFEST).read_text(encoding="utf-8")
    assert raw == generator.serialized_manifest(ROOT)
    assert '"source_body"' not in raw
    assert '"execution_authority"' not in raw
