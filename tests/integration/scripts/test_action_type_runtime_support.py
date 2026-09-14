"""Tests for the complete ActionType runtime-support inventory."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "quality" / "architecture" / "check-action-type-runtime-support.py"
MANIFEST = REPO_ROOT / "config" / "action-type-runtime-support.json"
SCHEMA = REPO_ROOT / "config" / "action-type-runtime-support.schema.json"
CHECKER_REF = "scripts/quality/architecture/check-action-type-runtime-support.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_action_type_runtime_support", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _load_module()


@pytest.fixture
def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "action-type-runtime-support.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_shipped_manifest_covers_the_catalog(checker: ModuleType) -> None:
    assert checker.validate(root=REPO_ROOT) == []
    assert checker.main(["--root", str(REPO_ROOT)]) == 0


def test_current_catalog_baseline_has_49_explicit_rows(
    checker: ModuleType,
    manifest: dict[str, Any],
) -> None:
    catalog = checker._load_catalog(REPO_ROOT, manifest["catalog_root"])

    assert len(catalog) == 49
    assert set(manifest["actions"]) == set(catalog)


def test_scale_out_is_core_only_not_isolated(manifest: dict[str, Any]) -> None:
    claim = manifest["actions"]["ops.scale-out@1.0.0"]

    assert set(claim["bindings"]) == {"core-azure-gateway"}
    assert "isolated-azure-gateway" not in claim["bindings"]


def test_missing_catalog_action_fails_closed(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest["actions"].pop("ops.start-vm@1.0.0")

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, manifest),
        schema_path=SCHEMA,
    )

    assert any(
        "missing catalog ActionTypes" in error and "ops.start-vm@1.0.0" in error for error in errors
    )


def test_isolated_scale_out_overclaim_fails_source_assertion(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest["actions"]["ops.scale-out@1.0.0"]["bindings"]["isolated-azure-gateway"] = (
        "isolated-gateway"
    )

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, manifest),
        schema_path=SCHEMA,
    )

    assert any(
        "binding isolated-azure-gateway membership mismatch" in error
        and "ops.scale-out@1.0.0" in error
        for error in errors
    )


def test_missing_binding_source_fails_closed(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest["bindings"]["core-azure-gateway"]["source_assertion"]["path"] = (
        "services/core-control-plane/src/fdai/delivery/azure/missing.py"
    )

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, manifest),
        schema_path=SCHEMA,
    )

    assert any("binding core-azure-gateway source assertion failed" in error for error in errors)


def test_receipt_evidence_requires_an_immutable_revision(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    profile = manifest["support_profiles"]["core-start-vm"]
    profile["evidence"]["level"] = "current_revision_receipt"

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, manifest),
        schema_path=SCHEMA,
    )

    assert any("receipt evidence requires an immutable revision" in error for error in errors)


def test_arbitrary_json_and_zero_revision_cannot_claim_current_receipt(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    profile = manifest["support_profiles"]["core-start-vm"]
    profile["evidence"] = {
        "level": "current_revision_receipt",
        "refs": [
            {
                "path": "config/action-type-runtime-support.json",
                "revision": "0" * 40,
            }
        ],
    }

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, manifest),
        schema_path=SCHEMA,
    )

    assert any("revision MUST NOT be all zeroes" in error for error in errors)
    assert any("has no single revision-bound" in error for error in errors)
    assert any("does not bind the ActionType" in error for error in errors)
    assert any("requires a signed attestation" in error for error in errors)


def test_receipt_facts_must_share_one_record(checker: ModuleType) -> None:
    revision = "a" * 40
    split = {
        "identity": {"receipt_id": "receipt-1"},
        "verification": {"effect_verified": True},
        "source": {"source_revision": revision},
        "integrity": {"receipt_digest": "sha256:" + "b" * 64},
    }
    complete = {
        "receipt_id": "receipt-1",
        "source_revision": revision,
        "effect_verified": True,
        "action_type_ref": "ops.start-vm@1.0.0",
    }
    complete["receipt_digest"] = checker._canonical_receipt_digest(complete)
    tampered = {**complete, "receipt_digest": "sha256:" + "b" * 64}

    assert checker._receipt_records(split, revision=revision) == []
    assert checker._receipt_records(complete, revision=revision) == [complete]
    assert checker._receipt_records(tampered, revision=revision) == []


def test_wired_recovery_requires_an_action_bound_source_symbol(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    recovery = manifest["support_profiles"]["pantheon-t2-route"]["recovery"]
    recovery["refs"] = [
        {
            "path": "services/core-control-plane/src/fdai/runtime/t2_route_registry.py",
            "symbol": "T2RouteRegistry",
        }
    ]

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, manifest),
        schema_path=SCHEMA,
    )

    assert any("wired claim lacks an action-bound source symbol" in error for error in errors)


def test_support_checker_is_registered_in_local_and_ci_gates() -> None:
    paths = (
        "scripts/verify.sh",
        "scripts/automation/run-pre-push-structural-gates.sh",
        "scripts/automation/validation_queue_evidence.py",
        ".github/workflows/ci.yml",
    )

    for relative in paths:
        assert CHECKER_REF in (REPO_ROOT / relative).read_text(encoding="utf-8"), relative


def test_ci_installs_support_checker_schema_dependency() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python3 -m pip install --quiet pyyaml jsonschema" in workflow


def test_profile_reference_must_exist(
    checker: ModuleType,
    manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    broken = copy.deepcopy(manifest)
    broken["actions"]["ops.start-vm@1.0.0"]["bindings"]["core-azure-gateway"] = "missing-profile"

    errors = checker.validate(
        root=REPO_ROOT,
        manifest_path=_write_manifest(tmp_path, broken),
        schema_path=SCHEMA,
    )

    assert any("references unknown support profile missing-profile" in error for error in errors)
