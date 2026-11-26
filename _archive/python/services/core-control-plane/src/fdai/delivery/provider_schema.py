"""Content-addressed provider schema accounting without ontology authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9.]+/[A-Za-z0-9][A-Za-z0-9./-]*$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProviderSchemaError(ValueError):
    """Reject incomplete or ambiguous provider schema evidence."""


class ProviderSchemaChannel(StrEnum):
    """Release channel derived from an upstream API version."""

    STABLE = "stable"
    PREVIEW = "preview"


class ProviderSchemaCoverageStatus(StrEnum):
    """Deterministic relationship between raw provider types and reviewed semantics."""

    MODELED = "modeled"
    STRUCTURAL_ONLY = "structural-only"
    READ_ONLY = "read-only"
    PREVIEW_ONLY = "preview-only"
    UNSUPPORTED_WITH_REASON = "unsupported-with-reason"


class ProviderSchemaDriftKind(StrEnum):
    """Compatibility class for one complete snapshot transition."""

    UNCHANGED = "unchanged"
    COMPATIBLE = "compatible"
    BREAKING = "breaking"


@dataclass(frozen=True, slots=True)
class ProviderSchemaType:
    """One globally accounted provider resource type from an immutable source revision."""

    resource_type: str
    stable_api_versions: tuple[str, ...]
    preview_api_versions: tuple[str, ...]
    preferred_api_version: str
    source_document: str
    parent_type: str | None = None
    readable_scopes: tuple[str, ...] = ()
    writable_scopes: tuple[str, ...] = ()
    scope_evidence_available: bool = False

    def __post_init__(self) -> None:
        normalized = self.resource_type.casefold()
        if not _TYPE_PATTERN.fullmatch(self.resource_type):
            raise ProviderSchemaError(f"invalid provider resource type: {self.resource_type!r}")
        stable = _normalized_values(self.stable_api_versions, field="stable_api_versions")
        preview = _normalized_values(self.preview_api_versions, field="preview_api_versions")
        if set(stable) & set(preview):
            raise ProviderSchemaError(f"API version belongs to both channels: {normalized}")
        if not stable and not preview:
            raise ProviderSchemaError(f"provider resource type has no API versions: {normalized}")
        expected_preferred = stable[-1] if stable else preview[-1]
        if self.preferred_api_version != expected_preferred:
            raise ProviderSchemaError(
                f"preferred API version MUST be latest stable else preview: {normalized}"
            )
        if not self.source_document or self.source_document.startswith(("/", "..")):
            raise ProviderSchemaError("source_document MUST be a bounded relative path")
        if self.parent_type is not None and not _TYPE_PATTERN.fullmatch(self.parent_type):
            raise ProviderSchemaError(f"invalid provider parent type: {self.parent_type!r}")
        object.__setattr__(self, "resource_type", normalized)
        object.__setattr__(self, "stable_api_versions", stable)
        object.__setattr__(self, "preview_api_versions", preview)
        object.__setattr__(self, "parent_type", _casefold_optional(self.parent_type))
        object.__setattr__(
            self,
            "readable_scopes",
            _normalized_values(self.readable_scopes, field="readable_scopes"),
        )
        object.__setattr__(
            self,
            "writable_scopes",
            _normalized_values(self.writable_scopes, field="writable_scopes"),
        )

    @property
    def preferred_channel(self) -> ProviderSchemaChannel:
        return (
            ProviderSchemaChannel.STABLE
            if self.stable_api_versions
            else ProviderSchemaChannel.PREVIEW
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "resource_type": self.resource_type,
            "stable_api_versions": list(self.stable_api_versions),
            "preview_api_versions": list(self.preview_api_versions),
            "preferred_api_version": self.preferred_api_version,
            "preferred_channel": self.preferred_channel.value,
            "source_document": self.source_document,
            "parent_type": self.parent_type,
            "readable_scopes": list(self.readable_scopes),
            "writable_scopes": list(self.writable_scopes),
            "scope_evidence_available": self.scope_evidence_available,
        }


@dataclass(frozen=True, slots=True)
class ProviderSchemaSnapshot:
    """One complete normalized provider corpus at an immutable source revision."""

    provider: str
    source_revision: str
    types: tuple[ProviderSchemaType, ...]
    schema_digest: str

    @classmethod
    def build(
        cls,
        *,
        provider: str,
        source_revision: str,
        types: tuple[ProviderSchemaType, ...],
    ) -> ProviderSchemaSnapshot:
        normalized_provider = provider.strip().casefold()
        if not normalized_provider or not source_revision.strip():
            raise ProviderSchemaError("provider and immutable source_revision MUST be non-empty")
        ordered = tuple(sorted(types, key=lambda item: item.resource_type))
        if not ordered:
            raise ProviderSchemaError("provider schema snapshot MUST contain at least one type")
        identities = [item.resource_type for item in ordered]
        if len(identities) != len(set(identities)):
            raise ProviderSchemaError("provider schema snapshot contains duplicate type identities")
        identity_set = set(identities)
        missing_parents = sorted(
            {
                item.parent_type
                for item in ordered
                if item.parent_type is not None and item.parent_type not in identity_set
            }
        )
        if missing_parents:
            raise ProviderSchemaError(
                "provider schema snapshot has missing parent types: " + ", ".join(missing_parents)
            )
        payload = {
            "schema_version": "1.0.0",
            "provider": normalized_provider,
            "source_revision": source_revision.strip(),
            "types": [item.to_mapping() for item in ordered],
        }
        digest = "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()
        return cls(
            provider=normalized_provider,
            source_revision=source_revision.strip(),
            types=ordered,
            schema_digest=digest,
        )

    def __post_init__(self) -> None:
        if not _DIGEST_PATTERN.fullmatch(self.schema_digest):
            raise ProviderSchemaError("schema_digest MUST be sha256-prefixed lowercase hex")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "provider": self.provider,
            "source_revision": self.source_revision,
            "schema_digest": self.schema_digest,
            "type_count": len(self.types),
            "types": [item.to_mapping() for item in self.types],
            "grants_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ProviderSchemaCoverageEntry:
    resource_type: str
    status: ProviderSchemaCoverageStatus
    reason: str | None


@dataclass(frozen=True, slots=True)
class ProviderSchemaCoverage:
    """Exact accounting of every raw type against the reviewed semantic subset."""

    schema_digest: str
    entries: tuple[ProviderSchemaCoverageEntry, ...]

    @classmethod
    def build(
        cls,
        *,
        snapshot: ProviderSchemaSnapshot,
        modeled_provider_types: frozenset[str],
    ) -> ProviderSchemaCoverage:
        modeled = {item.casefold() for item in modeled_provider_types}
        entries: list[ProviderSchemaCoverageEntry] = []
        for item in snapshot.types:
            if item.resource_type in modeled:
                status = ProviderSchemaCoverageStatus.MODELED
                reason = None
            elif not item.stable_api_versions:
                status = ProviderSchemaCoverageStatus.PREVIEW_ONLY
                reason = "no_stable_api_version"
            elif item.scope_evidence_available and not item.writable_scopes:
                status = ProviderSchemaCoverageStatus.READ_ONLY
                reason = "preferred_resource_has_no_writable_scope"
            elif item.parent_type is not None:
                status = ProviderSchemaCoverageStatus.STRUCTURAL_ONLY
                reason = "semantic_mapping_not_reviewed"
            else:
                status = ProviderSchemaCoverageStatus.UNSUPPORTED_WITH_REASON
                reason = "semantic_mapping_not_reviewed"
            entries.append(
                ProviderSchemaCoverageEntry(
                    resource_type=item.resource_type,
                    status=status,
                    reason=reason,
                )
            )
        return cls(schema_digest=snapshot.schema_digest, entries=tuple(entries))

    @property
    def modeled_count(self) -> int:
        return sum(item.status is ProviderSchemaCoverageStatus.MODELED for item in self.entries)

    def to_mapping(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        for entry in self.entries:
            status_counts[entry.status.value] = status_counts.get(entry.status.value, 0) + 1
        return {
            "schema_version": "1.0.0",
            "schema_digest": self.schema_digest,
            "type_count": len(self.entries),
            "modeled_count": self.modeled_count,
            "status_counts": dict(sorted(status_counts.items())),
            "entries": [
                {
                    "resource_type": entry.resource_type,
                    "status": entry.status.value,
                    "reason": entry.reason,
                }
                for entry in self.entries
            ],
            "grants_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ProviderSchemaDrift:
    """Deterministic complete-corpus diff; removals are evidence tombstones."""

    baseline_digest: str
    observed_digest: str
    kind: ProviderSchemaDriftKind
    added_types: tuple[str, ...]
    removed_types: tuple[str, ...]
    added_stable_versions: tuple[str, ...]
    removed_stable_versions: tuple[str, ...]
    added_preview_versions: tuple[str, ...]
    removed_preview_versions: tuple[str, ...]
    drift_digest: str


def compare_provider_schema_snapshots(
    baseline: ProviderSchemaSnapshot,
    observed: ProviderSchemaSnapshot,
) -> ProviderSchemaDrift:
    """Compare complete snapshots and classify any type or stable-version removal as breaking."""

    if baseline.provider != observed.provider:
        raise ProviderSchemaError("provider schema snapshots MUST have the same provider")
    before = {item.resource_type: item for item in baseline.types}
    after = {item.resource_type: item for item in observed.types}
    added_types = tuple(sorted(after.keys() - before.keys()))
    removed_types = tuple(sorted(before.keys() - after.keys()))
    common = sorted(before.keys() & after.keys())

    def version_delta(channel: str, *, added: bool) -> tuple[str, ...]:
        values: list[str] = []
        for resource_type in common:
            before_versions = set(getattr(before[resource_type], channel))
            after_versions = set(getattr(after[resource_type], channel))
            delta = after_versions - before_versions if added else before_versions - after_versions
            values.extend(f"{resource_type}@{version}" for version in sorted(delta))
        return tuple(values)

    added_stable = version_delta("stable_api_versions", added=True)
    removed_stable = version_delta("stable_api_versions", added=False)
    added_preview = version_delta("preview_api_versions", added=True)
    removed_preview = version_delta("preview_api_versions", added=False)
    changed = any(
        (
            added_types,
            removed_types,
            added_stable,
            removed_stable,
            added_preview,
            removed_preview,
        )
    )
    breaking = bool(removed_types or removed_stable)
    kind = (
        ProviderSchemaDriftKind.BREAKING
        if breaking
        else ProviderSchemaDriftKind.COMPATIBLE
        if changed
        else ProviderSchemaDriftKind.UNCHANGED
    )
    material = {
        "schema_version": "1.0.0",
        "provider": baseline.provider,
        "baseline_digest": baseline.schema_digest,
        "observed_digest": observed.schema_digest,
        "kind": kind.value,
        "added_types": added_types,
        "removed_types": removed_types,
        "added_stable_versions": added_stable,
        "removed_stable_versions": removed_stable,
        "added_preview_versions": added_preview,
        "removed_preview_versions": removed_preview,
    }
    return ProviderSchemaDrift(
        baseline_digest=baseline.schema_digest,
        observed_digest=observed.schema_digest,
        kind=kind,
        added_types=added_types,
        removed_types=removed_types,
        added_stable_versions=added_stable,
        removed_stable_versions=removed_stable,
        added_preview_versions=added_preview,
        removed_preview_versions=removed_preview,
        drift_digest=hashlib.sha256(_canonical_json(material)).hexdigest(),
    )


def provider_schema_snapshot_from_mapping(raw: Mapping[str, object]) -> ProviderSchemaSnapshot:
    """Load a serialized snapshot and verify its complete content digest."""

    if raw.get("schema_version") != "1.0.0":
        raise ProviderSchemaError("provider schema snapshot version is unsupported")
    provider = raw.get("provider")
    source_revision = raw.get("source_revision")
    raw_types = raw.get("types")
    if not isinstance(provider, str) or not isinstance(source_revision, str):
        raise ProviderSchemaError("provider schema snapshot identity is invalid")
    if not isinstance(raw_types, Sequence) or isinstance(raw_types, (str, bytes)):
        raise ProviderSchemaError("provider schema snapshot types MUST be an array")
    types: list[ProviderSchemaType] = []
    for index, raw_type in enumerate(raw_types):
        if not isinstance(raw_type, Mapping):
            raise ProviderSchemaError(f"provider schema type {index} MUST be an object")
        try:
            resource_type = raw_type["resource_type"]
            stable = raw_type["stable_api_versions"]
            preview = raw_type["preview_api_versions"]
            preferred = raw_type["preferred_api_version"]
            source_document = raw_type["source_document"]
        except KeyError as exc:
            raise ProviderSchemaError(f"provider schema type {index} is incomplete") from exc
        if not all(isinstance(value, str) for value in (resource_type, preferred, source_document)):
            raise ProviderSchemaError(f"provider schema type {index} identity is invalid")
        if not _is_string_sequence(stable) or not _is_string_sequence(preview):
            raise ProviderSchemaError(f"provider schema type {index} versions are invalid")
        readable = raw_type.get("readable_scopes", ())
        writable = raw_type.get("writable_scopes", ())
        if not _is_string_sequence(readable) or not _is_string_sequence(writable):
            raise ProviderSchemaError(f"provider schema type {index} scopes are invalid")
        parent_type = raw_type.get("parent_type")
        scope_available = raw_type.get("scope_evidence_available", False)
        if parent_type is not None and not isinstance(parent_type, str):
            raise ProviderSchemaError(f"provider schema type {index} parent is invalid")
        if not isinstance(scope_available, bool):
            raise ProviderSchemaError(f"provider schema type {index} scope state is invalid")
        types.append(
            ProviderSchemaType(
                resource_type=resource_type,
                stable_api_versions=tuple(stable),
                preview_api_versions=tuple(preview),
                preferred_api_version=preferred,
                source_document=source_document,
                parent_type=parent_type,
                readable_scopes=tuple(readable),
                writable_scopes=tuple(writable),
                scope_evidence_available=scope_available,
            )
        )
    snapshot = ProviderSchemaSnapshot.build(
        provider=provider,
        source_revision=source_revision,
        types=tuple(types),
    )
    expected_digest = raw.get("schema_digest")
    if expected_digest != snapshot.schema_digest:
        raise ProviderSchemaError("provider schema snapshot content digest mismatch")
    type_count = raw.get("type_count")
    if type_count is not None and type_count != len(snapshot.types):
        raise ProviderSchemaError("provider schema snapshot type count mismatch")
    return snapshot


def provider_schema_observation_time(value: datetime) -> str:
    """Render an explicit UTC observation time for machine receipts."""

    if value.tzinfo is None:
        raise ProviderSchemaError("provider schema observation time MUST be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _normalized_values(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    normalized = tuple(sorted({item.strip() for item in values if item.strip()}))
    if len(normalized) != len(values):
        raise ProviderSchemaError(f"{field} MUST contain unique non-empty values")
    return normalized


def _casefold_optional(value: str | None) -> str | None:
    return None if value is None else value.casefold()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _is_string_sequence(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(isinstance(item, str) for item in value)
    )


__all__ = [
    "ProviderSchemaChannel",
    "ProviderSchemaCoverage",
    "ProviderSchemaCoverageEntry",
    "ProviderSchemaCoverageStatus",
    "ProviderSchemaDrift",
    "ProviderSchemaDriftKind",
    "ProviderSchemaError",
    "ProviderSchemaSnapshot",
    "ProviderSchemaType",
    "compare_provider_schema_snapshots",
    "provider_schema_observation_time",
    "provider_schema_snapshot_from_mapping",
]
