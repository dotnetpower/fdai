"""Execution backend profiles bind only through validated server composition."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.composition import Container, bind_execution_backends
from fdai.core.execution_backend import (
    ExecutionBackendKind,
    InMemoryExecutionSubmissionLedger,
    load_execution_backend_registry,
)


def _raw_profile() -> dict[str, object]:
    return {
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


def test_registry_document_is_disabled_by_default() -> None:
    registry = load_execution_backend_registry({"profiles": [_raw_profile()]})

    with pytest.raises(ValueError, match="disabled"):
        registry.require_enabled("vm.report")


def test_profile_cannot_self_enable_or_carry_raw_credential_value() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        load_execution_backend_registry({"profiles": [{**_raw_profile(), "enabled": True}]})
    with pytest.raises(ValueError, match="references"):
        load_execution_backend_registry(
            {
                "profiles": [
                    {
                        **_raw_profile(),
                        "credential_profile_refs": ["Bearer secret-value"],
                    }
                ]
            }
        )


def test_public_composition_binds_coordinator(container: Container) -> None:
    registry = load_execution_backend_registry(
        {
            "profiles": [_raw_profile()],
            "enabled_profile_ids": ["vm.report"],
        }
    )
    backend = object()

    bound = bind_execution_backends(
        container,
        profiles=registry,
        backends={ExecutionBackendKind.VM_TASK: backend},  # type: ignore[dict-item]
        ledger=InMemoryExecutionSubmissionLedger(),
    )

    assert container.execution_backend_coordinator is None
    assert bound.execution_backend_coordinator is not None


def test_composition_rejects_missing_backend_binding(container: Container) -> None:
    registry = load_execution_backend_registry({"profiles": [_raw_profile()]})

    with pytest.raises(RuntimeError, match="not bound"):
        bind_execution_backends(
            replace(container),
            profiles=registry,
            backends={},
            ledger=InMemoryExecutionSubmissionLedger(),
        )
