"""Execution backend profiles can only narrow validated sandbox authority."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.core.execution_backend import (
    CancellationGuarantee,
    ExecutionAuthority,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionBackendProfileRegistry,
    ExecutionNetworkProfile,
    ExecutionProfileError,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
    intersect_execution_profile,
)


def _resources(**overrides: int) -> ResourceCeilings:
    values = {
        "cpu_millis": 1_000,
        "memory_bytes": 512_000_000,
        "ephemeral_storage_bytes": 1_000_000_000,
        "max_concurrency": 1,
    }
    values.update(overrides)
    return ResourceCeilings(**values)


def _authority() -> ExecutionAuthority:
    return ExecutionAuthority(
        backend_kind=ExecutionBackendKind.BUBBLEWRAP,
        workload_ids=frozenset({"code.search", "code.inspect"}),
        workspace_mode=WorkspaceMode.READ_ONLY,
        network_profiles=frozenset({ExecutionNetworkProfile.NONE}),
        credential_profile_refs=frozenset(),
        max_timeout_seconds=60,
        max_output_bytes=100_000,
        resources=_resources(),
        regions=frozenset({"local"}),
        scope_refs=frozenset({"workspace"}),
    )


def _profile() -> ExecutionBackendProfile:
    return ExecutionBackendProfile(
        profile_id="local.read",
        version="1.0.0",
        backend_kind=ExecutionBackendKind.BUBBLEWRAP,
        workload_ids=frozenset({"code.search"}),
        workspace_mode=WorkspaceMode.READ_ONLY,
        network_profiles=frozenset({ExecutionNetworkProfile.NONE}),
        credential_profile_refs=frozenset(),
        max_timeout_seconds=30,
        max_output_bytes=10_000,
        resources=_resources(cpu_millis=500, memory_bytes=256_000_000),
        persistence_mode=PersistenceMode.DURABLE,
        regions=frozenset({"local"}),
        scope_refs=frozenset({"workspace"}),
        cancellation_guarantee=CancellationGuarantee.BEST_EFFORT,
    )


def test_profile_intersection_preserves_only_narrower_values() -> None:
    effective = intersect_execution_profile(_authority(), _profile())

    assert effective.workload_ids == frozenset({"code.search"})
    assert effective.max_timeout_seconds == 30
    assert effective.max_output_bytes == 10_000
    assert effective.resources.cpu_millis == 500
    assert effective.credential_profile_refs == frozenset()


@pytest.mark.parametrize(
    "candidate",
    (
        replace(_profile(), workload_ids=frozenset({"code.search", "code.delete"})),
        replace(
            _profile(),
            credential_profile_refs=frozenset({"azure.executor"}),
        ),
        replace(
            _profile(),
            network_profiles=frozenset(
                {
                    ExecutionNetworkProfile.NONE,
                    ExecutionNetworkProfile.AZURE_CONTROL_PLANE,
                }
            ),
        ),
        replace(_profile(), workspace_mode=WorkspaceMode.READ_WRITE),
        replace(_profile(), max_timeout_seconds=61),
        replace(_profile(), max_output_bytes=100_001),
        replace(_profile(), resources=_resources(cpu_millis=1_001)),
        replace(_profile(), regions=frozenset({"local", "other-region"})),
        replace(_profile(), scope_refs=frozenset({"workspace", "subscription"})),
    ),
)
def test_profile_widening_is_rejected(candidate: ExecutionBackendProfile) -> None:
    with pytest.raises(ExecutionProfileError, match="widen"):
        intersect_execution_profile(_authority(), candidate)


def test_registry_is_disabled_until_server_selection_enables_profile() -> None:
    registry = ExecutionBackendProfileRegistry((_profile(),))

    with pytest.raises(ExecutionProfileError, match="disabled"):
        registry.require_enabled("local.read")

    selected = registry.select_enabled(frozenset({"local.read"}))
    assert selected.require_enabled("local.read") == _profile()


def test_registry_rejects_unknown_server_selection() -> None:
    registry = ExecutionBackendProfileRegistry((_profile(),))

    with pytest.raises(ExecutionProfileError, match="unknown"):
        registry.select_enabled(frozenset({"missing.profile"}))
