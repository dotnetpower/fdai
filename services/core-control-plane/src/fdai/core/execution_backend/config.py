"""Strict startup loader for server-owned execution backend profiles."""

from __future__ import annotations

from collections.abc import Mapping

from .profiles import (
    CancellationGuarantee,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    ExecutionBackendProfileRegistry,
    ExecutionNetworkProfile,
    PersistenceMode,
    ResourceCeilings,
    WorkspaceMode,
)

_PROFILE_KEYS = frozenset(
    {
        "profile_id",
        "version",
        "backend_kind",
        "workload_ids",
        "workspace_mode",
        "network_profiles",
        "credential_profile_refs",
        "max_timeout_seconds",
        "max_output_bytes",
        "resources",
        "persistence_mode",
        "regions",
        "scope_refs",
        "cancellation_guarantee",
        "template_ref",
        "artifact_digest",
    }
)
_RESOURCE_KEYS = frozenset(
    {"cpu_millis", "memory_bytes", "ephemeral_storage_bytes", "max_concurrency"}
)


def load_execution_backend_registry(
    raw: Mapping[str, object],
) -> ExecutionBackendProfileRegistry:
    """Validate a complete registry document and keep profiles disabled by default."""

    if set(raw) - {"profiles", "enabled_profile_ids"}:
        raise ValueError("execution backend registry contains unknown fields")
    values = raw.get("profiles")
    if not isinstance(values, list):
        raise ValueError("execution backend profiles MUST be an array")
    profiles = tuple(_profile(_mapping(value, "profile")) for value in values)
    enabled = _string_set(raw.get("enabled_profile_ids", []), "enabled_profile_ids")
    return ExecutionBackendProfileRegistry(
        profiles,
        enabled_profile_ids=enabled,
    )


def _profile(raw: Mapping[str, object]) -> ExecutionBackendProfile:
    unknown = set(raw) - _PROFILE_KEYS
    if unknown:
        raise ValueError(
            "execution backend profile contains unknown fields: " + ", ".join(sorted(unknown))
        )
    resources = _mapping(raw.get("resources"), "resources")
    resource_unknown = set(resources) - _RESOURCE_KEYS
    if resource_unknown:
        raise ValueError("execution backend resources contain unknown fields")
    return ExecutionBackendProfile(
        profile_id=_string(raw, "profile_id"),
        version=_string(raw, "version"),
        backend_kind=ExecutionBackendKind(_string(raw, "backend_kind")),
        workload_ids=_string_set(raw.get("workload_ids"), "workload_ids"),
        workspace_mode=WorkspaceMode(_string(raw, "workspace_mode")),
        network_profiles=frozenset(
            ExecutionNetworkProfile(value)
            for value in _string_set(raw.get("network_profiles"), "network_profiles")
        ),
        credential_profile_refs=_string_set(
            raw.get("credential_profile_refs", []),
            "credential_profile_refs",
        ),
        max_timeout_seconds=_integer(raw, "max_timeout_seconds"),
        max_output_bytes=_integer(raw, "max_output_bytes"),
        resources=ResourceCeilings(
            cpu_millis=_integer(resources, "cpu_millis"),
            memory_bytes=_integer(resources, "memory_bytes"),
            ephemeral_storage_bytes=_integer(resources, "ephemeral_storage_bytes"),
            max_concurrency=_integer(resources, "max_concurrency"),
        ),
        persistence_mode=PersistenceMode(_string(raw, "persistence_mode")),
        regions=_string_set(raw.get("regions"), "regions"),
        scope_refs=_string_set(raw.get("scope_refs"), "scope_refs"),
        cancellation_guarantee=CancellationGuarantee(_string(raw, "cancellation_guarantee")),
        template_ref=_optional_string(raw.get("template_ref"), "template_ref"),
        artifact_digest=_optional_string(raw.get("artifact_digest"), "artifact_digest"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"execution backend {name} MUST be an object")
    return value


def _string(raw: Mapping[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"execution backend {name} MUST be a non-empty string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"execution backend {name} MUST be a non-empty string")
    return value


def _integer(raw: Mapping[str, object], name: str) -> int:
    value = raw.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"execution backend {name} MUST be an integer")
    return value


def _string_set(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"execution backend {name} MUST be an array of strings")
    if len(value) != len(set(value)):
        raise ValueError(f"execution backend {name} MUST NOT contain duplicates")
    return frozenset(value)


__all__ = ["load_execution_backend_registry"]
