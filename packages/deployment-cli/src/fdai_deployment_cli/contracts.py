"""Strict, deterministic contracts for subscription genesis planning."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_CONNECTIVITY = frozenset({"online", "offline"})
_HOSTS = frozenset({"existing-host", "managed-vm"})
_TRANSPORTS = frozenset({"manual", "github-actions"})
_ACCESS_METHODS = frozenset(
    {"internal_ssh", "temporary_public_ssh", "github_actions", "bastion", "run_command"}
)


class ApprovalClass(StrEnum):
    """Approval strength required by one manifest entry."""

    STANDARD = "standard"
    HIGH_IMPACT = "high-impact"


@dataclass(frozen=True, slots=True)
class ProvisionProfile:
    """Secret-free desired state selected by an operator."""

    environment: str
    region: str
    connectivity: str
    host: str
    transport: str
    access_method: str
    shadow_only: bool
    approval_quorum: int
    monthly_cost_ceiling: int

    def __post_init__(self) -> None:
        if self.environment not in _ENVIRONMENTS:
            raise ValueError("environment is unsupported")
        if _ID.fullmatch(self.region) is None:
            raise ValueError("region MUST be a lowercase stable identifier")
        if self.connectivity not in _CONNECTIVITY:
            raise ValueError("connectivity is unsupported")
        if self.host not in _HOSTS:
            raise ValueError("host is unsupported")
        if self.transport not in _TRANSPORTS:
            raise ValueError("transport is unsupported")
        if self.access_method not in _ACCESS_METHODS:
            raise ValueError("access_method is unsupported")
        if self.transport == "github-actions" and self.access_method != "github_actions":
            raise ValueError("github-actions transport requires github_actions access")
        if self.transport == "manual" and self.access_method == "github_actions":
            raise ValueError("manual transport cannot use github_actions access")
        if not self.shadow_only:
            raise ValueError("subscription genesis MUST start shadow-only")
        if self.approval_quorum < 1:
            raise ValueError("approval_quorum MUST be positive")
        if self.monthly_cost_ceiling < 0:
            raise ValueError("monthly_cost_ceiling MUST be non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ProvisionProfile:
        """Decode a profile and reject unknown or missing fields."""

        expected = {
            "schema_version",
            "environment",
            "region",
            "connectivity",
            "host",
            "transport",
            "access_method",
            "shadow_only",
            "approval_quorum",
            "monthly_cost_ceiling",
        }
        _require_exact_keys(value, expected, "provision profile")
        if value["schema_version"] != "fdai.provision-profile.v1":
            raise ValueError("provision profile schema_version is unsupported")
        return cls(
            environment=_text(value, "environment"),
            region=_text(value, "region"),
            connectivity=_text(value, "connectivity"),
            host=_text(value, "host"),
            transport=_text(value, "transport"),
            access_method=_text(value, "access_method"),
            shadow_only=_bool(value, "shadow_only"),
            approval_quorum=_int(value, "approval_quorum"),
            monthly_cost_ceiling=_int(value, "monthly_cost_ceiling"),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical JSON-compatible profile."""

        return {
            "schema_version": "fdai.provision-profile.v1",
            "environment": self.environment,
            "region": self.region,
            "connectivity": self.connectivity,
            "host": self.host,
            "transport": self.transport,
            "access_method": self.access_method,
            "shadow_only": self.shadow_only,
            "approval_quorum": self.approval_quorum,
            "monthly_cost_ceiling": self.monthly_cost_ceiling,
        }


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One finite, dependency-ordered provisioning responsibility."""

    entry_id: str
    owner: str
    desired_state: str
    prerequisites: tuple[str, ...]
    approval_class: ApprovalClass
    idempotency_key: str
    timeout_seconds: int
    no_progress_seconds: int
    rollback_ref: str
    observer: str

    def __post_init__(self) -> None:
        for label, value in (
            ("entry_id", self.entry_id),
            ("owner", self.owner),
            ("desired_state", self.desired_state),
            ("idempotency_key", self.idempotency_key),
            ("rollback_ref", self.rollback_ref),
            ("observer", self.observer),
        ):
            if _ID.fullmatch(value) is None:
                raise ValueError(f"{label} MUST be a lowercase stable identifier")
        if len(set(self.prerequisites)) != len(self.prerequisites):
            raise ValueError("manifest prerequisites MUST be unique")
        if any(_ID.fullmatch(item) is None for item in self.prerequisites):
            raise ValueError("manifest prerequisites MUST be stable identifiers")
        if self.entry_id in self.prerequisites:
            raise ValueError("manifest entry cannot depend on itself")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds MUST be positive")
        if not 1 <= self.no_progress_seconds <= self.timeout_seconds:
            raise ValueError("no_progress_seconds MUST be within the stage timeout")

    def to_mapping(self) -> dict[str, object]:
        """Return canonical entry data."""

        return {
            "entry_id": self.entry_id,
            "owner": self.owner,
            "desired_state": self.desired_state,
            "prerequisites": list(self.prerequisites),
            "approval_class": self.approval_class.value,
            "idempotency_key": self.idempotency_key,
            "timeout_seconds": self.timeout_seconds,
            "no_progress_seconds": self.no_progress_seconds,
            "rollback_ref": self.rollback_ref,
            "observer": self.observer,
        }


@dataclass(frozen=True, slots=True)
class SubscriptionProvisioningManifest:
    """Finite manifest whose digest seals one local plan."""

    source_commit: str
    profile_digest: str
    entries: tuple[ManifestEntry, ...]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None:
            raise ValueError("source_commit MUST be a lowercase 40-character SHA")
        if re.fullmatch(r"[0-9a-f]{64}", self.profile_digest) is None:
            raise ValueError("profile_digest MUST be a lowercase SHA-256")
        if not self.entries:
            raise ValueError("provisioning manifest MUST contain entries")
        ids = tuple(entry.entry_id for entry in self.entries)
        if len(ids) != len(set(ids)):
            raise ValueError("provisioning manifest entry ids MUST be unique")
        known = set(ids)
        for entry in self.entries:
            unknown = set(entry.prerequisites) - known
            if unknown:
                raise ValueError(f"manifest entry {entry.entry_id!r} has unknown prerequisites")
        _assert_acyclic(self.entries)

    @property
    def digest(self) -> str:
        """Return the replay-stable manifest digest."""

        return canonical_digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return canonical manifest data."""

        return {
            "schema_version": "fdai.subscription-provisioning-manifest.v1",
            "source_commit": self.source_commit,
            "profile_digest": self.profile_digest,
            "entries": [entry.to_mapping() for entry in self.entries],
        }


def canonical_bytes(value: object) -> bytes:
    """Serialize one machine record with stable ordering."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_digest(value: object) -> str:
    """Return a lowercase SHA-256 over canonical JSON."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _assert_acyclic(entries: Sequence[ManifestEntry]) -> None:
    by_id = {entry.entry_id: entry for entry in entries}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(entry_id: str) -> None:
        if entry_id in visiting:
            raise ValueError("provisioning manifest dependency cycle detected")
        if entry_id in visited:
            return
        visiting.add(entry_id)
        for dependency in by_id[entry_id].prerequisites:
            visit(dependency)
        visiting.remove(entry_id)
        visited.add(entry_id)

    for key in sorted(by_id):
        visit(key)


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields do not match the schema")


def _text(value: Mapping[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise ValueError(f"{field} MUST be a string")
    return item


def _bool(value: Mapping[str, object], field: str) -> bool:
    item = value[field]
    if not isinstance(item, bool):
        raise ValueError(f"{field} MUST be a boolean")
    return item


def _int(value: Mapping[str, object], field: str) -> int:
    item = value[field]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{field} MUST be an integer")
    return item


def load_json_object(data: bytes, *, label: str, max_bytes: int = 1_048_576) -> dict[str, Any]:
    """Decode one bounded JSON object."""

    if not data or len(data) > max_bytes:
        raise ValueError(f"{label} is empty or exceeds its size limit")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST be a JSON object")
    return value
