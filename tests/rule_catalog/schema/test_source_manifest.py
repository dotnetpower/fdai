"""SourceManifest loader — schema + per-kind validators."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aiopspilot.rule_catalog.schema.source_manifest import (
    Cadence,
    FetchKind,
    ManifestError,
    Redistribution,
    SourceManifest,
    load_source_manifest_from_mapping,
    load_source_manifest_from_yaml,
)


def _valid_local() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "id": "example-source",
        "name": "Example",
        "license": "Apache-2.0",
        "redistribution": "embeddable",
        "fetch": {"kind": "local", "path": "rule-catalog/catalog"},
        "parser": "rule-yaml",
    }


def test_loads_minimal_local_manifest() -> None:
    manifest = load_source_manifest_from_mapping(_valid_local())
    assert isinstance(manifest, SourceManifest)
    assert manifest.id == "example-source"
    assert manifest.fetch.kind is FetchKind.LOCAL
    assert manifest.redistribution is Redistribution.EMBEDDABLE
    assert manifest.cadence is Cadence.ON_DEMAND


def test_loads_valid_git_manifest() -> None:
    raw = _valid_local()
    raw["fetch"] = {
        "kind": "git",
        "repo": "https://github.com/open-policy-agent/gatekeeper-library",
        "revision": "abc1234567890abcdef1234567890abcdef1234",
        "subpath": "library",
    }
    manifest = load_source_manifest_from_mapping(raw)
    assert manifest.fetch.kind is FetchKind.GIT
    assert manifest.fetch.subpath == "library"


def test_missing_required_field_reports_all() -> None:
    raw = _valid_local()
    del raw["license"]
    with pytest.raises(ManifestError) as exc:
        load_source_manifest_from_mapping(raw)
    assert any("license" in i.message for i in exc.value.issues)


def test_git_rejects_mutable_ref() -> None:
    raw = _valid_local()
    raw["fetch"] = {"kind": "git", "repo": "https://x/y", "revision": "main"}
    with pytest.raises(ManifestError) as exc:
        load_source_manifest_from_mapping(raw)
    assert any("mutable ref" in i.message for i in exc.value.issues)


def test_git_requires_repo_and_revision() -> None:
    raw = _valid_local()
    raw["fetch"] = {"kind": "git"}
    with pytest.raises(ManifestError):
        load_source_manifest_from_mapping(raw)


def test_http_requires_url_and_expected_sha256() -> None:
    raw = _valid_local()
    raw["fetch"] = {"kind": "http"}
    with pytest.raises(ManifestError):
        load_source_manifest_from_mapping(raw)


def test_http_rejects_short_sha() -> None:
    raw = _valid_local()
    raw["fetch"] = {
        "kind": "http",
        "url": "https://example.org/policy.json",
        "expected_sha256": "notasha",
    }
    with pytest.raises(ManifestError):
        load_source_manifest_from_mapping(raw)


def test_local_requires_path() -> None:
    raw = _valid_local()
    raw["fetch"] = {"kind": "local"}
    with pytest.raises(ManifestError):
        load_source_manifest_from_mapping(raw)


def test_id_pattern_enforced() -> None:
    raw = _valid_local()
    raw["id"] = "BadID"
    with pytest.raises(ManifestError):
        load_source_manifest_from_mapping(raw)


def test_yaml_loader_rejects_non_mapping_root(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("- item\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="mapping"):
        load_source_manifest_from_yaml(p)


def test_yaml_loader_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump(_valid_local()), encoding="utf-8")
    manifest = load_source_manifest_from_yaml(p)
    assert manifest.id == "example-source"


def test_shipped_seed_manifest_loads() -> None:
    """The example seed manifest committed with this cycle MUST load clean."""
    repo_root = Path(__file__).resolve().parents[3]
    manifest = load_source_manifest_from_yaml(
        repo_root / "rule-catalog" / "sources" / "aiopspilot-p1-seed" / "manifest.yaml"
    )
    assert manifest.id == "aiopspilot-p1-seed"
    assert manifest.fetch.kind is FetchKind.LOCAL
