"""The runtime loads execution backend profiles only from a validated server document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.runtime.execution_backends import (
    REGISTRY_MAX_BYTES_VARIABLE,
    REGISTRY_PATH_VARIABLE,
    load_execution_backend_registry_from_env,
)


def _document() -> dict[str, object]:
    return {
        "profiles": [
            {
                "profile_id": "vm.report",
                "version": "1.0.0",
                "backend_kind": "vm_task",
                "workload_ids": ["report.render"],
                "workspace_mode": "none",
                "network_profiles": ["azure_control_plane"],
                "credential_profile_refs": ["azure.executor"],
                "max_timeout_seconds": 300,
                "max_output_bytes": 10000,
                "resources": {
                    "cpu_millis": 1000,
                    "memory_bytes": 512000000,
                    "ephemeral_storage_bytes": 1000000000,
                    "max_concurrency": 1,
                },
                "persistence_mode": "durable",
                "regions": ["example-region"],
                "scope_refs": ["resource:vm:example"],
                "cancellation_guarantee": "best_effort",
            }
        ]
    }


def _write(tmp_path: Path, raw: object) -> Path:
    path = tmp_path / "execution-backends.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_unconfigured_runtime_has_no_execution_backend_profiles() -> None:
    assert load_execution_backend_registry_from_env(env={}) is None
    assert load_execution_backend_registry_from_env(env={REGISTRY_PATH_VARIABLE: "  "}) is None


def test_configured_document_loads_and_stays_disabled_by_default(tmp_path: Path) -> None:
    path = _write(tmp_path, _document())

    registry = load_execution_backend_registry_from_env(env={REGISTRY_PATH_VARIABLE: str(path)})

    assert registry is not None
    assert [profile.profile_id for profile in registry.list()] == ["vm.report"]
    with pytest.raises(ValueError, match="disabled"):
        registry.require_enabled("vm.report")


def test_missing_document_fails_startup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="unreadable"):
        load_execution_backend_registry_from_env(
            env={REGISTRY_PATH_VARIABLE: str(tmp_path / "absent.json")}
        )


def test_malformed_document_fails_startup(tmp_path: Path) -> None:
    path = tmp_path / "execution-backends.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unreadable or invalid"):
        load_execution_backend_registry_from_env(env={REGISTRY_PATH_VARIABLE: str(path)})


def test_non_object_root_fails_startup(tmp_path: Path) -> None:
    path = _write(tmp_path, [_document()])

    with pytest.raises(RuntimeError, match="MUST be an object"):
        load_execution_backend_registry_from_env(env={REGISTRY_PATH_VARIABLE: str(path)})


def test_invalid_profile_fails_startup_instead_of_dropping_bounds(tmp_path: Path) -> None:
    document = _document()
    profiles = document["profiles"]
    assert isinstance(profiles, list)
    profile = profiles[0]
    assert isinstance(profile, dict)
    profile["enabled"] = True
    path = _write(tmp_path, document)

    with pytest.raises(ValueError, match="unknown fields"):
        load_execution_backend_registry_from_env(env={REGISTRY_PATH_VARIABLE: str(path)})


def test_oversized_document_fails_before_parsing(tmp_path: Path) -> None:
    path = _write(tmp_path, _document())

    with pytest.raises(RuntimeError, match="byte bound"):
        load_execution_backend_registry_from_env(
            env={
                REGISTRY_PATH_VARIABLE: str(path),
                REGISTRY_MAX_BYTES_VARIABLE: "8",
            }
        )


@pytest.mark.parametrize("raw", ["zero", "0", "-1"])
def test_invalid_byte_bound_fails_startup(tmp_path: Path, raw: str) -> None:
    path = _write(tmp_path, _document())

    with pytest.raises(RuntimeError, match=REGISTRY_MAX_BYTES_VARIABLE):
        load_execution_backend_registry_from_env(
            env={
                REGISTRY_PATH_VARIABLE: str(path),
                REGISTRY_MAX_BYTES_VARIABLE: raw,
            }
        )


def test_a_non_regular_registry_path_fails_startup(tmp_path: Path) -> None:
    directory = tmp_path / "registry-dir"
    directory.mkdir()

    with pytest.raises(RuntimeError, match="regular file"):
        load_execution_backend_registry_from_env(env={REGISTRY_PATH_VARIABLE: str(directory)})
