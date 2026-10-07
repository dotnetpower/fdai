from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from fdai_deployment_cli import offline_kit
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.runtime_release import (
    RUNTIME_RELEASE_PATH,
    RecallRecord,
    RuntimeRelease,
    RuntimeReleaseError,
    compare_release_ids,
    evaluate_recall_candidate,
    is_release_id,
    load_runtime_release,
    parse_runtime_release_manifest,
    recall_target_ordering,
    validate_schema_transition,
)

COMMIT = "a" * 40
PLATFORM = "linux-x86_64"
BUNDLE_DIGEST = hashlib.sha256(b"synthetic signed deployment bundle").hexdigest()
SERVICES = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
SIDECARS = ("clamav", "pgvector")
INSTALLATION_AGENTS = ("infrastructure-agent", "lifecycle-agent")
NOTICE_A = "c" * 64
NOTICE_B = "d" * 64
NOTICE_C = "e" * 64


def _record(root: Path, role: str, service: bool = False) -> dict[str, str]:
    result = {}
    for kind in ("archive", "sbom", "provenance") if service else ("archive", "sbom"):
        relative = f"runtime/{role}/{kind}.bin"
        content = f"synthetic {role} {kind}".encode()
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        result[kind] = relative
        result[f"{kind}_sha256"] = hashlib.sha256(content).hexdigest()
    if service:
        result["image_digest"] = "sha256:" + "b" * 64
    return result


def _catalog(root: Path) -> dict[str, Any]:
    return {
        "schema_version": "fdai.runtime-release.v1",
        "source_commit": COMMIT,
        "platform_tag": PLATFORM,
        "deployment_bundle_sha256": BUNDLE_DIGEST,
        "services": {role: _record(root, role, True) for role in SERVICES},
        "console": _record(root, "console"),
        "deployment_support": _record(root, "deployment-support"),
    }


def _catalog_v3(root: Path) -> dict[str, Any]:
    catalog = _catalog(root)
    catalog["schema_version"] = "fdai.runtime-release.v3"
    catalog["sidecars"] = {role: _record(root, role, True) for role in SIDECARS}
    catalog["installation_agents"] = {
        role: _record(root, role, True) for role in INSTALLATION_AGENTS
    }
    catalog["schema"] = {"target": 15, "tolerates": {"minimum": 12, "maximum": 16}}
    catalog["capabilities"] = {
        "action:scale-service": {"kind": "ActionType", "maximum_mode": "enforce"},
        "workflow:incident-triage": {"kind": "Workflow", "maximum_mode": "shadow"},
    }
    catalog["downtime"] = {"entities": ["core", "operator-api"]}
    return catalog


def _save(root: Path, catalog: object) -> None:
    (root / RUNTIME_RELEASE_PATH).write_bytes(canonical_bytes(catalog))


def _load(root: Path, **expected: str) -> RuntimeRelease:
    return load_runtime_release(
        root,
        expected_source_commit=expected.get("commit", COMMIT),
        expected_platform_tag=expected.get("platform", PLATFORM),
    )


@pytest.mark.parametrize("platform", [PLATFORM, "linux-aarch64"])
def test_runtime_release_validates_local_bytes_and_canonical_metadata(
    tmp_path: Path, platform: str
) -> None:
    """Opaque synthetic archives, SBOMs, and provenance need only matching file hashes."""

    catalog = _catalog(tmp_path)
    catalog["platform_tag"] = platform
    _save(tmp_path, catalog)
    result = _load(tmp_path, platform=platform)
    assert result.source_commit == COMMIT
    assert result.platform_tag == platform
    assert result.deployment_bundle_sha256 == BUNDLE_DIGEST
    assert result.digest == hashlib.sha256(canonical_bytes(catalog)).hexdigest()
    assert result.to_mapping() == catalog
    assert len(result.artifact_paths) == 19
    assert result.artifact_paths == tuple(sorted(result.artifact_paths))
    assert RUNTIME_RELEASE_PATH not in result.artifact_paths
    for path in result.artifact_paths:
        assert (tmp_path / path).read_bytes().startswith(b"synthetic ")
    detached = result.to_mapping()
    detached_services = detached["services"]
    assert isinstance(detached_services, dict)
    detached_services.clear()
    assert result.to_mapping() == catalog
    (tmp_path / RUNTIME_RELEASE_PATH).write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    assert _load(tmp_path, platform=platform).digest == result.digest
    (tmp_path / "unrelated.txt").write_bytes(b"outside the runtime subtree")
    assert _load(tmp_path, platform=platform).digest == result.digest


def test_runtime_release_v3_validates_lifecycle_manifest_fields(tmp_path: Path) -> None:
    catalog = _catalog_v3(tmp_path)
    _save(tmp_path, catalog)
    result = _load(tmp_path)
    assert result.schema_version == "fdai.runtime-release.v3"
    assert result.schema_target == 15
    assert result.schema_range is not None
    assert result.schema_range.minimum == 12
    assert result.schema_range.maximum == 16
    assert result.capability_maximums == {
        "action:scale-service": "enforce",
        "workflow:incident-triage": "shadow",
    }
    assert result.downtime_entities == ("core", "operator-api")
    assert result.installation_agent_images == INSTALLATION_AGENTS
    assert len(result.artifact_paths) == 31
    assert result.to_mapping() == catalog


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("schema", {"target": 15, "tolerates": {"minimum": 17, "maximum": 16}}),
        ("schema", {"target": "15", "tolerates": {"minimum": 12, "maximum": 16}}),
        ("schema", {"target": 15, "tolerates": {"minimum": -1, "maximum": 16}}),
        ("schema", {"target": True, "tolerates": {"minimum": 12, "maximum": 16}}),
        ("schema", {"target": 15, "tolerates": {"minimum": False, "maximum": 16}}),
        ("capabilities", {}),
        ("capabilities", {"action:scale-service": {"kind": "ActionType", "maximum_mode": "admin"}}),
        ("downtime", {"entities": ["core", "core"]}),
        ("installation_agents", {"lifecycle-agent": {"archive": "runtime/agent/archive.bin"}}),
    ],
)
def test_runtime_release_v3_rejects_invalid_lifecycle_manifest_fields(
    tmp_path: Path, section: str, value: object
) -> None:
    catalog = _catalog_v3(tmp_path)
    catalog[section] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


def test_schema_transition_blocks_upgrade_outside_tolerated_range(tmp_path: Path) -> None:
    catalog = _catalog_v3(tmp_path)
    _save(tmp_path, catalog)
    release = _load(tmp_path)
    assert validate_schema_transition(
        current_schema_revision=12, candidate=release, direction="upgrade"
    ).allowed
    outside = validate_schema_transition(
        current_schema_revision=17, candidate=release, direction="upgrade"
    )
    assert outside.allowed is False
    assert outside.reason_code == "schema_revision_outside_tolerated_range"
    backward = validate_schema_transition(
        current_schema_revision=16, candidate=release, direction="upgrade"
    )
    assert backward.allowed is False
    assert backward.reason_code == "schema_target_not_forward"
    assert validate_schema_transition(
        current_schema_revision=16, candidate=release, direction="rollback"
    ).allowed
    invalid = validate_schema_transition(
        current_schema_revision=True, candidate=release, direction="upgrade"
    )
    assert invalid.allowed is False
    assert invalid.reason_code == "schema_revision_invalid"


def test_recall_decision_blocks_repromotion_and_orders_recall_targets() -> None:
    records = (
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=7,
            notice_digest=NOTICE_A,
        ),
        RecallRecord(scope="release", target="1.5.0", sequence=3, notice_digest=NOTICE_B),
        RecallRecord(
            scope="capability",
            target="workflow:incident-triage",
            sequence=5,
            notice_digest=NOTICE_C,
        ),
    )
    denied = evaluate_recall_candidate(
        release_id="1.5.0",
        capability_ids=("action:scale-service",),
        recall_records=records,
    )
    assert denied.allowed is False
    assert denied.reason_code == "release_recalled"
    capability_denied = evaluate_recall_candidate(
        release_id="1.5.1",
        capability_ids=("action:scale-service",),
        recall_records=records,
    )
    assert capability_denied.allowed is False
    assert capability_denied.reason_code == "capability_recalled"
    assert recall_target_ordering(
        release_id="1.5.0",
        capability_ids=("action:scale-service", "workflow:incident-triage"),
        recall_records=records,
    ) == (
        "release:1.5.0",
        "capability:action:scale-service",
        "capability:workflow:incident-triage",
    )


def test_recall_lift_allows_later_candidate() -> None:
    records = (
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=7,
            notice_digest=NOTICE_A,
        ),
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=8,
            notice_digest=NOTICE_B,
            action="lift",
            lifting_release_id="1.5.1",
        ),
    )
    still_recalled = evaluate_recall_candidate(
        release_id="1.5.0",
        capability_ids=("action:scale-service",),
        recall_records=records,
    )
    assert still_recalled.allowed is False
    assert still_recalled.reason_code == "capability_recalled"
    assert evaluate_recall_candidate(
        release_id="1.5.1",
        capability_ids=("action:scale-service",),
        recall_records=records,
    ).allowed


@pytest.mark.parametrize("reverse", [False, True])
def test_recall_duplicate_sequence_fails_closed_in_both_orders(reverse: bool) -> None:
    duplicate = (
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=5,
            notice_digest=NOTICE_A,
            action="recall",
        ),
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=5,
            notice_digest=NOTICE_B,
            action="lift",
            lifting_release_id="1.5.1",
        ),
    )
    records = tuple(reversed(duplicate)) if reverse else duplicate
    decision = evaluate_recall_candidate(
        release_id="1.5.1",
        capability_ids=("action:scale-service",),
        recall_records=records,
    )
    assert decision.allowed is False
    assert decision.reason_code == "recall_sequence_duplicate"
    with pytest.raises(RuntimeReleaseError, match="recall_sequence_duplicate"):
        recall_target_ordering(
            release_id="1.5.1",
            capability_ids=("action:scale-service",),
            recall_records=records,
        )


def test_release_scope_lift_does_not_readmit_same_recalled_release() -> None:
    records = (
        RecallRecord(scope="release", target="1.5.0", sequence=1, notice_digest=NOTICE_A),
        RecallRecord(
            scope="release",
            target="1.5.0",
            sequence=2,
            notice_digest=NOTICE_B,
            action="lift",
            lifting_release_id="1.5.1",
        ),
    )
    decision = evaluate_recall_candidate(
        release_id="1.5.0",
        capability_ids=(),
        recall_records=records,
    )
    assert decision.allowed is False
    assert decision.reason_code == "release_recalled"


def test_recall_lift_requires_valid_candidate_release_ordering() -> None:
    records = (
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=1,
            notice_digest=NOTICE_A,
        ),
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=2,
            notice_digest=NOTICE_B,
            action="lift",
            lifting_release_id="1.5.1",
        ),
    )
    decision = evaluate_recall_candidate(
        release_id="candidate",
        capability_ids=("action:scale-service",),
        recall_records=records,
    )
    assert decision.allowed is False
    assert decision.reason_code == "release_version_invalid"


@pytest.mark.parametrize(
    ("candidate", "lifting_release", "allowed"),
    [
        ("1.5.0-rc.2", "1.5.0-rc.10", False),
        ("1.5.0-rc2", "1.5.0-rc10", False),
        ("1.5.0-beta.11", "1.5.0-beta.2", True),
        ("1.5.0-alpha.1.1", "1.5.0-alpha.1", True),
        ("1.5.0-alpha.1", "1.5.0-alpha.1.1", False),
        ("1.5.0", "1.5.0-rc.10", True),
    ],
)
def test_recall_lift_uses_semver_prerelease_precedence(
    candidate: str, lifting_release: str, allowed: bool
) -> None:
    records = (
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=1,
            notice_digest=NOTICE_A,
        ),
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=2,
            notice_digest=NOTICE_B,
            action="lift",
            lifting_release_id=lifting_release,
        ),
    )
    decision = evaluate_recall_candidate(
        release_id=candidate,
        capability_ids=("action:scale-service",),
        recall_records=records,
    )
    assert decision.allowed is allowed
    if not allowed:
        assert decision.reason_code == "capability_recalled"


@pytest.mark.parametrize(
    "release_id",
    ["v1.5.0", "1.05.0", "١.5.0", "1.5.0+build.1", "1.5.0-01"],
)
def test_recall_candidate_rejects_noncanonical_release_id(release_id: str) -> None:
    records = (RecallRecord(scope="release", target="1.5.0", sequence=1, notice_digest=NOTICE_A),)
    decision = evaluate_recall_candidate(
        release_id=release_id,
        capability_ids=(),
        recall_records=records,
    )
    assert decision.allowed is False
    assert decision.reason_code == "release_version_invalid"
    with pytest.raises(RuntimeReleaseError, match="release_version_invalid"):
        recall_target_ordering(release_id=release_id, capability_ids=(), recall_records=records)


@pytest.mark.parametrize("target", ["v1.5.0", "1.05.0", "١.5.0", "1.5.0+build.1"])
def test_recall_record_rejects_noncanonical_release_target(target: str) -> None:
    with pytest.raises(ValueError, match="Release id|target"):
        RecallRecord(
            scope="release",
            target=target,
            sequence=1,
            notice_digest=NOTICE_A,
        )


@pytest.mark.parametrize("lifting_release", ["v1.5.1", "1.05.1", "١.5.1"])
def test_recall_record_rejects_noncanonical_lifting_release(
    lifting_release: str,
) -> None:
    with pytest.raises(ValueError, match="lifting Release"):
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=1,
            notice_digest=NOTICE_A,
            action="lift",
            lifting_release_id=lifting_release,
        )


def test_recall_record_rejects_bool_sequence_and_missing_notice_digest() -> None:
    with pytest.raises(ValueError, match="sequence"):
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=True,
            notice_digest=NOTICE_A,
        )
    with pytest.raises(ValueError, match="notice digest"):
        RecallRecord(
            scope="capability",
            target="action:scale-service",
            sequence=1,
            notice_digest="not-a-digest",
        )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("", "schema_version", "fdai.runtime-release.v2"),
        ("", "schema_version", None),
        ("", "source_commit", "a" * 39),
        ("", "source_commit", "g" * 40),
        ("", "source_commit", 1),
        ("", "platform_tag", "darwin-aarch64"),
        ("", "platform_tag", []),
        ("", "services", []),
        ("", "console", None),
        ("", "deployment_support", True),
        ("", "extra", "unexpected"),
        ("services", "extra-service", {}),
        ("services", "core-control-plane", "registry.example.com/core@sha256:" + "b" * 64),
        ("console", "image_digest", "sha256:" + "b" * 64),
        ("deployment_support", "provenance", "runtime/provenance.json"),
    ],
)
def test_runtime_release_rejects_invalid_schema(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    catalog = _catalog(tmp_path)
    (catalog[section] if section else catalog)[key] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


@pytest.mark.parametrize("section", ["", "services", "console", "deployment_support", *SERVICES])
def test_runtime_release_rejects_missing_keys(tmp_path: Path, section: str) -> None:
    catalog = _catalog(tmp_path)
    record = catalog["services"][section] if section in SERVICES else catalog.get(section, catalog)
    record.pop(next(iter(record)))
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="schema"):
        _load(tmp_path)


def test_runtime_release_rejects_extra_service_fields(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog["services"][SERVICES[0]]["registry"] = "registry.example.com"
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="schema"):
        _load(tmp_path)


@pytest.mark.parametrize("value", [None, True, [], "", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_runtime_release_rejects_invalid_deployment_bundle_digest(
    tmp_path: Path, value: object
) -> None:
    catalog = _catalog(tmp_path)
    catalog["deployment_bundle_sha256"] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="deployment bundle digest"):
        _load(tmp_path)


def test_runtime_release_requires_deployment_bundle_digest(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    del catalog["deployment_bundle_sha256"]
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="schema"):
        _load(tmp_path)


def test_runtime_release_catalog_digest_binds_deployment_bundle(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    original = _load(tmp_path)
    replacement = hashlib.sha256(b"different synthetic deployment bundle").hexdigest()
    catalog["deployment_bundle_sha256"] = replacement
    _save(tmp_path, catalog)
    changed = _load(tmp_path)
    assert changed.deployment_bundle_sha256 == replacement
    assert changed.digest != original.digest


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/runtime/a",
        "runtime",
        "other/a",
        "runtime/../a",
        "runtime/./a",
        "runtime//a",
        "runtime/a/",
        "runtime/a\\b",
        "runtime/a\nb",
        "runtime/\x00a",
        "runtime/\u00e9",
        "runtime/release.json",
        "registry.example.com/core@sha256:" + "b" * 64,
    ],
)
def test_runtime_release_rejects_unsafe_paths(tmp_path: Path, value: str) -> None:
    catalog = _catalog(tmp_path)
    catalog["console"]["archive"] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="path"):
        _load(tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "archive",
        "archive_sha256",
        "image_digest",
        "sbom",
        "sbom_sha256",
        "provenance",
        "provenance_sha256",
    ],
)
@pytest.mark.parametrize("value", [None, True, 7, [], {}])
def test_runtime_release_rejects_nonstring_fields(tmp_path: Path, key: str, value: object) -> None:
    catalog = _catalog(tmp_path)
    catalog["services"][SERVICES[0]][key] = value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="strings"):
        _load(tmp_path)


@pytest.mark.parametrize(
    "key", ["archive_sha256", "sbom_sha256", "provenance_sha256", "image_digest"]
)
@pytest.mark.parametrize("value", ["", "A" * 64, "g" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n"])
def test_runtime_release_rejects_invalid_hashes(tmp_path: Path, key: str, value: str) -> None:
    catalog = _catalog(tmp_path)
    catalog["services"][SERVICES[0]][key] = ("sha256:" if key == "image_digest" else "") + value
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="digest"):
        _load(tmp_path)


@pytest.mark.parametrize("kind", ["archive", "sbom", "provenance"])
@pytest.mark.parametrize("failure", ["missing", "changed", "symlink", "fifo", "directory"])
def test_runtime_release_requires_real_regular_artifacts(
    tmp_path: Path, kind: str, failure: str
) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    path = tmp_path / catalog["services"][SERVICES[0]][kind]
    path.unlink()
    if failure == "changed":
        path.write_bytes(b"registry.example.com/core@sha256:" + b"b" * 64)
    elif failure == "symlink":
        path.symlink_to(tmp_path / catalog["console"]["archive"])
    elif failure == "fifo":
        os.mkfifo(path)
    elif failure == "directory":
        path.mkdir()
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


@pytest.mark.parametrize("section", ["console", "deployment_support"])
@pytest.mark.parametrize("kind", ["archive", "sbom"])
def test_runtime_release_requires_console_and_support_bytes(
    tmp_path: Path, section: str, kind: str
) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    (tmp_path / catalog[section][kind]).unlink()
    with pytest.raises(RuntimeReleaseError, match="exact file set"):
        _load(tmp_path)


def test_runtime_release_rejects_registry_metadata_without_local_bytes(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    for role in SERVICES:
        (tmp_path / catalog["services"][role]["archive"]).unlink()
    with pytest.raises(RuntimeReleaseError, match="exact file set"):
        _load(tmp_path)


@pytest.mark.parametrize("name", ["extra.bin", "offline-kit.json", "offline-kit.json.sig", "empty"])
def test_runtime_release_rejects_extra_entries(tmp_path: Path, name: str) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    extra = tmp_path / "runtime" / name
    if name == "empty":
        extra.mkdir()
    else:
        extra.write_bytes(b"extra")
    with pytest.raises(RuntimeReleaseError, match="exact file set|extra"):
        _load(tmp_path)


@pytest.mark.parametrize("location", ["root", "ancestor", "runtime", "service", "catalog"])
def test_runtime_release_rejects_symlinked_directories_and_catalog(
    tmp_path: Path, location: str
) -> None:
    root = tmp_path / "kit"
    catalog = _catalog(root)
    _save(root, catalog)
    if location in {"root", "ancestor"}:
        alias = tmp_path / "alias"
        alias.symlink_to(root if location == "root" else tmp_path, target_is_directory=True)
        root = alias if location == "root" else alias / "kit"
    else:
        relative = {
            "runtime": "runtime",
            "service": "runtime/core-control-plane",
            "catalog": RUNTIME_RELEASE_PATH,
        }[location]
        source = root / relative
        moved = tmp_path / "moved"
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=location != "catalog")
    with pytest.raises(RuntimeReleaseError):
        _load(root)


@pytest.mark.parametrize("same_record", [False, True])
def test_runtime_release_rejects_duplicate_paths(tmp_path: Path, same_record: bool) -> None:
    catalog = _catalog(tmp_path)
    catalog["console"]["archive"] = (
        catalog["console"]["sbom"] if same_record else catalog["services"][SERVICES[0]]["archive"]
    )
    _save(tmp_path, catalog)
    with pytest.raises(RuntimeReleaseError, match="duplicated"):
        _load(tmp_path)


@pytest.mark.parametrize("nested", [False, True])
def test_runtime_release_rejects_duplicate_json_keys(tmp_path: Path, nested: bool) -> None:
    catalog = _catalog(tmp_path)
    raw = canonical_bytes(catalog)
    key = b'"schema_version":' if not nested else b'"archive":'
    raw = raw.replace(key, key + b'"ignored",' + key, 1)
    (tmp_path / RUNTIME_RELEASE_PATH).write_bytes(raw)
    with pytest.raises(RuntimeReleaseError, match="duplicate"):
        _load(tmp_path)


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b"{", b"\xff", b" " * (1024 * 1024 + 1)])
def test_runtime_release_rejects_invalid_or_oversized_json(tmp_path: Path, raw: bytes) -> None:
    _catalog(tmp_path)
    (tmp_path / RUNTIME_RELEASE_PATH).write_bytes(raw)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


def test_runtime_release_requires_catalog(tmp_path: Path) -> None:
    _catalog(tmp_path)
    with pytest.raises(RuntimeReleaseError):
        _load(tmp_path)


@pytest.mark.parametrize("expected", [{"commit": "c" * 40}, {"platform": "linux-aarch64"}])
def test_runtime_release_checks_compatibility_before_artifact_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expected: dict[str, str]
) -> None:
    _save(tmp_path, _catalog(tmp_path))

    def forbidden(*args: object, **kwargs: object) -> str:
        pytest.fail("incompatible runtime release attempted artifact hashing")

    monkeypatch.setattr(offline_kit, "_sha256_nofollow", forbidden)
    with pytest.raises(RuntimeReleaseError, match="does not match"):
        _load(tmp_path, **expected)


@pytest.mark.parametrize("limit", ["file", "total"])
def test_runtime_release_inherits_offline_kit_size_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    catalog = _catalog(tmp_path)
    _save(tmp_path, catalog)
    if limit == "file":
        size = (tmp_path / RUNTIME_RELEASE_PATH).stat().st_size
        content = b"x" * (size + 1)
        path = tmp_path / catalog["console"]["archive"]
        path.write_bytes(content)
        catalog["console"]["archive_sha256"] = hashlib.sha256(content).hexdigest()
        _save(tmp_path, catalog)
        monkeypatch.setattr(offline_kit, "_MAX_FILE_BYTES", size)
    else:
        total = sum(
            path.stat().st_size for path in (tmp_path / "runtime").rglob("*") if path.is_file()
        )
        monkeypatch.setattr(offline_kit, "_MAX_TOTAL_BYTES", total - 1)
    with pytest.raises(RuntimeReleaseError, match="size limit"):
        _load(tmp_path)


def test_parse_runtime_release_manifest_matches_kit_loader_without_artifacts(
    tmp_path: Path,
) -> None:
    catalog = _catalog_v3(tmp_path)
    _save(tmp_path, catalog)
    loaded = _load(tmp_path)
    parsed = parse_runtime_release_manifest(canonical_bytes(catalog))
    assert parsed == loaded
    other_commit = dict(catalog, source_commit="f" * 40)
    assert parse_runtime_release_manifest(canonical_bytes(other_commit)).source_commit == "f" * 40
    with pytest.raises(RuntimeReleaseError):
        parse_runtime_release_manifest(b'{"schema_version": "fdai.runtime-release.v9"}')
    with pytest.raises(RuntimeReleaseError):
        parse_runtime_release_manifest(b"not json")


def test_compare_release_ids_orders_by_semantic_version_precedence() -> None:
    assert compare_release_ids("1.5.1", "1.5.0") == 1
    assert compare_release_ids("1.5.0", "1.5.0") == 0
    assert compare_release_ids("1.5.0-rc.2", "1.5.0") == -1
    assert compare_release_ids("1.5.0-rc.10", "1.5.0-rc.2") == 1
    with pytest.raises(RuntimeReleaseError):
        compare_release_ids("v1.5.0", "1.5.0")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.6.0", True), ("2.0.0-rc.1", True), ("v1.6.0", False), ("1.6", False), ("01.6.0", False)],
)
def test_is_release_id_accepts_only_canonical_semver(value: str, expected: bool) -> None:
    assert is_release_id(value) is expected
