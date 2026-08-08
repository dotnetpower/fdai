"""Server-owned execution backend profiles and pure no-widening intersection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_WORKSPACE_RANK: dict[WorkspaceMode, int]


class ExecutionProfileError(ValueError):
    """An execution profile is invalid, disabled, or widens authority."""


class ExecutionBackendKind(StrEnum):
    BUBBLEWRAP = "bubblewrap"
    VM_TASK = "vm_task"
    AZURE_CONTAINER_APPS_JOB = "azure_container_apps_job"


class WorkspaceMode(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


_WORKSPACE_RANK = {
    WorkspaceMode.NONE: 0,
    WorkspaceMode.READ_ONLY: 1,
    WorkspaceMode.READ_WRITE: 2,
}


class ExecutionNetworkProfile(StrEnum):
    NONE = "none"
    AZURE_CONTROL_PLANE = "azure_control_plane"


class PersistenceMode(StrEnum):
    EPHEMERAL = "ephemeral"
    DURABLE = "durable"


class CancellationGuarantee(StrEnum):
    NONE = "none"
    BEST_EFFORT = "best_effort"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class ResourceCeilings:
    """Maximum resources available to one backend submission."""

    cpu_millis: int
    memory_bytes: int
    ephemeral_storage_bytes: int
    max_concurrency: int

    def __post_init__(self) -> None:
        if not 1 <= self.cpu_millis <= 64_000:
            raise ValueError("cpu_millis MUST be in [1, 64000]")
        if not 1 <= self.memory_bytes <= 256_000_000_000:
            raise ValueError("memory_bytes MUST be in [1, 256000000000]")
        if not 0 <= self.ephemeral_storage_bytes <= 1_000_000_000_000:
            raise ValueError("ephemeral_storage_bytes MUST be in [0, 1000000000000]")
        if not 1 <= self.max_concurrency <= 100:
            raise ValueError("max_concurrency MUST be in [1, 100]")


@dataclass(frozen=True, slots=True)
class ExecutionAuthority:
    """Validated upper bound supplied by the owning sandbox catalog."""

    backend_kind: ExecutionBackendKind
    workload_ids: frozenset[str]
    workspace_mode: WorkspaceMode
    network_profiles: frozenset[ExecutionNetworkProfile]
    credential_profile_refs: frozenset[str]
    max_timeout_seconds: int
    max_output_bytes: int
    resources: ResourceCeilings
    regions: frozenset[str]
    scope_refs: frozenset[str]

    def __post_init__(self) -> None:
        _validate_envelope(self)


@dataclass(frozen=True, slots=True)
class ExecutionBackendProfile:
    """Immutable server-owned selection and resource envelope for a backend."""

    profile_id: str
    version: str
    backend_kind: ExecutionBackendKind
    workload_ids: frozenset[str]
    workspace_mode: WorkspaceMode
    network_profiles: frozenset[ExecutionNetworkProfile]
    credential_profile_refs: frozenset[str]
    max_timeout_seconds: int
    max_output_bytes: int
    resources: ResourceCeilings
    persistence_mode: PersistenceMode
    regions: frozenset[str]
    scope_refs: frozenset[str]
    cancellation_guarantee: CancellationGuarantee
    template_ref: str | None = None
    artifact_digest: str | None = None

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.profile_id) is None:
            raise ValueError("profile_id MUST be a lowercase dotted identifier")
        if _VERSION.fullmatch(self.version) is None:
            raise ValueError("profile version MUST be semantic x.y.z")
        _validate_envelope(self)
        if self.backend_kind is ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB:
            if self.template_ref is None or not _IDENTIFIER.fullmatch(self.template_ref):
                raise ValueError("Container Apps Job profiles require a template_ref")
            if self.artifact_digest is None or not _DIGEST.fullmatch(self.artifact_digest):
                raise ValueError("Container Apps Job profiles require an artifact digest")
        elif self.template_ref is not None or self.artifact_digest is not None:
            raise ValueError("template_ref and artifact_digest are reserved for job profiles")


def _validate_envelope(value: ExecutionAuthority | ExecutionBackendProfile) -> None:
    if not value.workload_ids or any(
        _IDENTIFIER.fullmatch(item) is None for item in value.workload_ids
    ):
        raise ValueError("workload_ids MUST contain lowercase dotted identifiers")
    if not value.network_profiles:
        raise ValueError("network_profiles MUST NOT be empty")
    if any(_IDENTIFIER.fullmatch(item) is None for item in value.credential_profile_refs):
        raise ValueError("credential_profile_refs MUST contain references, not credentials")
    if not 1 <= value.max_timeout_seconds <= 86_400:
        raise ValueError("max_timeout_seconds MUST be in [1, 86400]")
    if not 1 <= value.max_output_bytes <= 100_000_000:
        raise ValueError("max_output_bytes MUST be in [1, 100000000]")
    if not value.regions or not value.scope_refs:
        raise ValueError("regions and scope_refs MUST NOT be empty")
    for item in (*value.regions, *value.scope_refs):
        if not item or len(item) > 512 or "\x00" in item or "\n" in item:
            raise ValueError("regions and scope_refs MUST contain bounded references")


def intersect_execution_profile(
    authority: ExecutionAuthority,
    profile: ExecutionBackendProfile,
) -> ExecutionBackendProfile:
    """Return ``profile`` only when every field is within validated authority."""

    if profile.backend_kind is not authority.backend_kind:
        raise ExecutionProfileError("backend profile would widen backend authority")
    _require_subset(profile.workload_ids, authority.workload_ids, "workload")
    _require_subset(profile.network_profiles, authority.network_profiles, "network")
    _require_subset(
        profile.credential_profile_refs,
        authority.credential_profile_refs,
        "credential",
    )
    _require_subset(profile.regions, authority.regions, "region")
    _require_subset(profile.scope_refs, authority.scope_refs, "scope")
    if _WORKSPACE_RANK[profile.workspace_mode] > _WORKSPACE_RANK[authority.workspace_mode]:
        raise ExecutionProfileError("backend profile would widen workspace authority")
    if profile.max_timeout_seconds > authority.max_timeout_seconds:
        raise ExecutionProfileError("backend profile would widen timeout authority")
    if profile.max_output_bytes > authority.max_output_bytes:
        raise ExecutionProfileError("backend profile would widen output authority")
    if _resources_widen(profile.resources, authority.resources):
        raise ExecutionProfileError("backend profile would widen resource authority")
    return profile


def _require_subset(left: frozenset[object], right: frozenset[object], name: str) -> None:
    if not left.issubset(right):
        raise ExecutionProfileError(f"backend profile would widen {name} authority")


def _resources_widen(left: ResourceCeilings, right: ResourceCeilings) -> bool:
    return (
        left.cpu_millis > right.cpu_millis
        or left.memory_bytes > right.memory_bytes
        or left.ephemeral_storage_bytes > right.ephemeral_storage_bytes
        or left.max_concurrency > right.max_concurrency
    )


class ExecutionBackendProfileRegistry:
    """Immutable registry whose profiles remain disabled until server selection."""

    __slots__ = ("_enabled", "_profiles")

    def __init__(
        self,
        profiles: tuple[ExecutionBackendProfile, ...] = (),
        *,
        enabled_profile_ids: frozenset[str] = frozenset(),
    ) -> None:
        by_id: dict[str, ExecutionBackendProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise ExecutionProfileError(
                    f"duplicate execution backend profile {profile.profile_id!r}"
                )
            by_id[profile.profile_id] = profile
        unknown = enabled_profile_ids - by_id.keys()
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ExecutionProfileError(f"unknown enabled execution profiles: {names}")
        self._profiles = MappingProxyType(by_id)
        self._enabled = enabled_profile_ids

    def list(self) -> tuple[ExecutionBackendProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def select_enabled(
        self,
        profile_ids: frozenset[str],
    ) -> ExecutionBackendProfileRegistry:
        return ExecutionBackendProfileRegistry(
            self.list(),
            enabled_profile_ids=profile_ids,
        )

    def require(self, profile_id: str) -> ExecutionBackendProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ExecutionProfileError(
                f"unknown execution backend profile {profile_id!r}"
            ) from exc

    def require_enabled(self, profile_id: str) -> ExecutionBackendProfile:
        profile = self.require(profile_id)
        if profile_id not in self._enabled:
            raise ExecutionProfileError(f"execution backend profile {profile_id!r} is disabled")
        return profile


__all__ = [
    "CancellationGuarantee",
    "ExecutionAuthority",
    "ExecutionBackendKind",
    "ExecutionBackendProfile",
    "ExecutionBackendProfileRegistry",
    "ExecutionNetworkProfile",
    "ExecutionProfileError",
    "PersistenceMode",
    "ResourceCeilings",
    "WorkspaceMode",
    "intersect_execution_profile",
]
