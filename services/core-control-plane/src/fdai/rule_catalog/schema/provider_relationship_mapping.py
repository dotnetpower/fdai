"""Reviewed provider relationship mapping contract and fail-closed catalog loader."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai.shared.providers.state_evidence import TRUSTED_LINK_VERIFICATION_METHODS

_SHA256_PREFIX = "sha256:"


class EndpointOrientation(StrEnum):
    """How a provider-owned reference maps onto semantic link endpoints."""

    OWNER_TO_REFERENCED = "owner_to_referenced"
    REFERENCED_TO_OWNER = "referenced_to_owner"


class ProviderReferenceFormat(StrEnum):
    """Provider reference representation read from the reviewed source path."""

    ARM_ID = "arm_id"
    RESOLVED_NAME = "resolved_name"


class SourceSchemaIdentity(BaseModel):
    """Exact provider payload schema reviewed by one mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    digest: str

    @field_validator("digest")
    @classmethod
    def _validate_digest(cls, value: str) -> str:
        _require_sha256(value, field_name="source schema digest")
        return value


class RelationshipFreshnessPolicy(BaseModel):
    """Finite freshness ceiling for observations produced through a mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_age_seconds: int = Field(ge=1)


class RelationshipCompletenessPolicy(BaseModel):
    """Coverage requirements that must hold before a relationship is verified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    require_complete_generation: bool
    require_source_endpoint: bool
    require_target_endpoint: bool

    @model_validator(mode="after")
    def _require_closed_generation(self) -> RelationshipCompletenessPolicy:
        if not all(
            (
                self.require_complete_generation,
                self.require_source_endpoint,
                self.require_target_endpoint,
            )
        ):
            raise ValueError("relationship mapping completeness policy MUST require a closed graph")
        return self


class RelationshipPredicate(BaseModel):
    """One equality condition correlated with a provider reference path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    property_path: str = Field(min_length=1)
    equals: str = Field(min_length=1)


class ProviderRelationshipMapping(BaseModel):
    """One reviewed provider reference to semantic LinkType mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    provider: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    source_provider_types: tuple[str, ...] = Field(min_length=1)
    source_property_path: str = Field(min_length=1)
    target_provider_types: tuple[str, ...] = Field(min_length=1)
    reference_format: ProviderReferenceFormat = ProviderReferenceFormat.ARM_ID
    predicate: RelationshipPredicate | None = None
    link_type: str = Field(min_length=1)
    endpoint_orientation: EndpointOrientation
    source_schema: SourceSchemaIdentity
    evidence_method: str = Field(min_length=1)
    freshness: RelationshipFreshnessPolicy
    completeness: RelationshipCompletenessPolicy

    @field_validator("source_provider_types", "target_provider_types")
    @classmethod
    def _canonical_provider_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        canonical = tuple(sorted({value.strip().casefold() for value in values if value.strip()}))
        if len(canonical) != len(values):
            raise ValueError("provider types MUST be non-empty and unique")
        return canonical

    @field_validator("evidence_method")
    @classmethod
    def _trusted_evidence_method(cls, value: str) -> str:
        if value not in TRUSTED_LINK_VERIFICATION_METHODS:
            raise ValueError("relationship mapping evidence method MUST be trusted")
        return value


class RelationshipMappingReview(BaseModel):
    """Immutable review receipt and digest for one catalog generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reviewer_identity: str = Field(min_length=1)
    reviewed_at: datetime
    immutable_receipt_ref: str = Field(min_length=1)
    content_hash: str

    @field_validator("reviewed_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("mapping review time MUST be timezone-aware")
        return value

    @field_validator("content_hash")
    @classmethod
    def _content_hash_shape(cls, value: str) -> str:
        _require_sha256(value, field_name="mapping catalog content hash")
        return value


class ProviderRelationshipMappingCatalog(BaseModel):
    """Content-addressed reviewed mappings for one provider schema generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(min_length=1)
    mappings: tuple[ProviderRelationshipMapping, ...] = Field(min_length=1)
    review: RelationshipMappingReview

    @model_validator(mode="after")
    def _reject_ambiguous_mappings(self) -> ProviderRelationshipMappingCatalog:
        seen_ids: set[str] = set()
        seen_routes: dict[tuple[str, str, str, str, str], EndpointOrientation] = {}
        for mapping in self.mappings:
            if mapping.mapping_id in seen_ids:
                raise ValueError(f"duplicate provider relationship mapping {mapping.mapping_id!r}")
            seen_ids.add(mapping.mapping_id)
            for source_type in mapping.source_provider_types:
                for target_type in mapping.target_provider_types:
                    route = (
                        mapping.provider.casefold(),
                        mapping.source_identity.casefold(),
                        source_type,
                        mapping.source_property_path,
                        target_type,
                    )
                    prior = seen_routes.get(route)
                    if prior is not None and prior != mapping.endpoint_orientation:
                        raise ValueError("provider relationship mapping orientation is ambiguous")
                    seen_routes[route] = mapping.endpoint_orientation
        return self


@dataclass(frozen=True, slots=True)
class ProviderRelationshipMappingIssue:
    """One stable catalog validation issue."""

    key: str
    message: str


class ProviderRelationshipMappingCatalogError(ValueError):
    """Aggregate error raised when reviewed relationship mappings are invalid."""

    def __init__(self, issues: list[ProviderRelationshipMappingIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"provider relationship mapping validation failed: {preview}{suffix}")


def provider_relationship_mapping_content_hash(value: Mapping[str, Any]) -> str:
    """Return the canonical digest of catalog content excluding its review envelope."""

    canonical = {key: raw for key, raw in value.items() if key != "review"}
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def load_provider_relationship_mapping_catalog(
    root: Path,
) -> ProviderRelationshipMappingCatalog:
    """Load one reviewed mapping catalog directory or fail before provider startup."""

    issues: list[ProviderRelationshipMappingIssue] = []
    paths = sorted(root.glob("*.yaml"))
    if len(paths) != 1:
        raise ProviderRelationshipMappingCatalogError(
            [
                ProviderRelationshipMappingIssue(
                    key=str(root),
                    message="catalog MUST contain exactly one YAML generation",
                )
            ]
        )
    path = paths[0]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProviderRelationshipMappingCatalogError(
            [ProviderRelationshipMappingIssue(key=path.name, message=str(exc))]
        ) from exc
    if not isinstance(raw, Mapping):
        raise ProviderRelationshipMappingCatalogError(
            [ProviderRelationshipMappingIssue(key=path.name, message="top-level MUST be a mapping")]
        )
    try:
        catalog = ProviderRelationshipMappingCatalog.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for error in errors():
                location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
                issues.append(
                    ProviderRelationshipMappingIssue(
                        key=f"{path.name}:{location}",
                        message=str(error.get("msg", "invalid mapping")),
                    )
                )
        else:
            issues.append(ProviderRelationshipMappingIssue(key=path.name, message=str(exc)))
        raise ProviderRelationshipMappingCatalogError(issues) from exc

    expected_hash = provider_relationship_mapping_content_hash(raw)
    if catalog.review.content_hash != expected_hash:
        raise ProviderRelationshipMappingCatalogError(
            [
                ProviderRelationshipMappingIssue(
                    key=f"{path.name}:review.content_hash",
                    message="content hash does not match canonical mapping content",
                )
            ]
        )
    return catalog


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value.removeprefix(_SHA256_PREFIX)
    if not value.startswith(_SHA256_PREFIX) or len(digest) != 64:
        raise ValueError(f"{field_name} MUST be sha256:<64 lowercase hex>")
    if any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} MUST be sha256:<64 lowercase hex>")


__all__ = [
    "EndpointOrientation",
    "ProviderReferenceFormat",
    "ProviderRelationshipMapping",
    "ProviderRelationshipMappingCatalog",
    "ProviderRelationshipMappingCatalogError",
    "ProviderRelationshipMappingIssue",
    "RelationshipCompletenessPolicy",
    "RelationshipFreshnessPolicy",
    "RelationshipMappingReview",
    "RelationshipPredicate",
    "SourceSchemaIdentity",
    "load_provider_relationship_mapping_catalog",
    "provider_relationship_mapping_content_hash",
]
