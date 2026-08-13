"""Immutable no-authority contracts for bounded provider resource discovery."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal, cast

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract, content_digest

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ID_PATTERN = r"^[a-z][a-z0-9_.-]{0,127}$"
_PROVIDER_TYPE_PATTERN = r"^[A-Za-z][A-Za-z0-9.]{0,127}/[A-Za-z0-9._/-]{1,255}$"
_VERSION_REF_PATTERN = r"^[a-z][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_EXECUTABLE_CONTROL = re.compile(r"[\x00-\x1f\x7f`$;&|<>]|\$\(|\b(?:eval|exec|source)\b")


class DiscoveryResultKind(StrEnum):
    """Supported result shapes for resource discovery."""

    LIST = "list"
    COUNT = "count"
    TYPES = "types"
    RELATIONSHIPS = "relationships"
    COVERAGE = "coverage"


class DiscoveryUniverse(StrEnum):
    """Finite discovery domains whose completeness is measured independently."""

    RESOURCE_CONTAINERS = "resource_containers"
    ARM_RESOURCES = "arm_resources"
    ARM_CHILD_RESOURCES = "arm_child_resources"
    ARG_SPECIALIZED = "arg_specialized"
    RESOURCE_DETAILS = "resource_details"
    TENANT_DIRECTORY = "tenant_directory"
    SERVICE_DATA_PLANE = "service_data_plane"


class DiscoveryScopeKind(StrEnum):
    """Provider-neutral scope kinds accepted by discovery profiles."""

    TENANT = "tenant"
    MANAGEMENT_GROUP = "management_group"
    SUBSCRIPTION = "subscription"
    RESOURCE_GROUP = "resource_group"
    RESOURCE = "resource"
    DATA_PLANE = "data_plane"


class DiscoveryPredicateField(StrEnum):
    """Allowlisted resource fields that a deterministic compiler may filter."""

    NAME = "name"
    PROVIDER_TYPE = "provider_type"
    SEMANTIC_TYPE = "semantic_type"
    RESOURCE_GROUP = "resource_group"
    LOCATION = "location"
    TAG = "tag"
    STATUS = "status"
    LINK = "link"


class DiscoveryPredicateOperator(StrEnum):
    """Bounded predicate operators with backend-independent meaning."""

    EQ = "eq"
    CONTAINS = "contains"
    IN = "in"
    EXISTS = "exists"


class DiscoveryBackend(StrEnum):
    """Registered backend families in priority order."""

    PROMOTED_INVENTORY = "promoted_inventory"
    RESOURCE_GRAPH = "resource_graph"
    GENERIC_ARM = "generic_arm"
    TYPED_ARM = "typed_arm"
    REGISTERED_CLI = "registered_cli"
    TYPED_DATA_PLANE = "typed_data_plane"


class DiscoveryMappingStatus(StrEnum):
    """Whether governance reviewed a provider-to-semantic type mapping."""

    MAPPED = "mapped"
    UNMAPPED = "unmapped"


class DiscoveryCoverageStatus(StrEnum):
    """Terminal accounting state for one plan or reconciled coverage row."""

    COVERED = "covered"
    FALLBACK = "fallback"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    UNMAPPED = "unmapped"


class DiscoveryPredicate(QueryContract):
    """One normalized predicate containing scalar data, never executable syntax."""

    field: DiscoveryPredicateField
    operator: DiscoveryPredicateOperator
    values: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...],
        Field(max_length=32),
    ] = ()

    @model_validator(mode="after")
    def _values_are_bounded_data(self) -> DiscoveryPredicate:
        if self.operator is DiscoveryPredicateOperator.EXISTS:
            if self.values:
                raise ValueError("exists predicate MUST NOT carry values")
        elif not self.values:
            raise ValueError("value predicate MUST carry at least one value")
        if len(self.values) != len(set(self.values)):
            raise ValueError("predicate values MUST be unique")
        for value in self.values:
            if _EXECUTABLE_CONTROL.search(value):
                raise ValueError("predicate values MUST NOT contain executable text")
        return self


class DiscoveryLimits(QueryContract):
    """Server-owned ceilings applied before any provider request."""

    max_results: Annotated[int, Field(strict=True, ge=1, le=10_000)] = 1_000
    max_pages: Annotated[int, Field(strict=True, ge=1, le=100)] = 10
    max_bytes: Annotated[int, Field(strict=True, ge=1_024, le=67_108_864)] = 8_388_608
    timeout_ms: Annotated[int, Field(strict=True, ge=100, le=120_000)] = 30_000
    max_fan_out: Annotated[int, Field(strict=True, ge=1, le=16)] = 4
    freshness_seconds: Annotated[int, Field(strict=True, ge=0, le=31_536_000)] = 3_600


class DiscoveryIntent(QueryContract):
    """Verified resource-discovery meaning without provider query or command text."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    result_kind: DiscoveryResultKind
    universes: Annotated[tuple[DiscoveryUniverse, ...], Field(min_length=1, max_length=7)]
    scope_kind: DiscoveryScopeKind
    scope_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    predicates: Annotated[tuple[DiscoveryPredicate, ...], Field(max_length=8)] = ()
    limits: DiscoveryLimits = DiscoveryLimits()
    include_command_explanation: bool = False
    unresolved_modifiers: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()
    execution_authority: Literal[False] = False
    intent_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _intent_is_canonical(self) -> DiscoveryIntent:
        if self.unresolved_modifiers:
            raise ValueError("discovery intent MUST NOT contain unresolved modifiers")
        if len(self.universes) != len(set(self.universes)):
            raise ValueError("discovery universes MUST be unique")
        expected = content_digest(
            self.model_dump(
                mode="json",
                exclude={"intent_digest", "unresolved_modifiers"},
            )
        )
        if self.intent_digest != expected:
            raise ValueError("discovery intent digest does not match its content")
        return self


class DiscoveryFallback(QueryContract):
    """One ineligible higher-priority backend recorded without provider error text."""

    backend: DiscoveryBackend
    reason_code: Annotated[str, Field(pattern=_ID_PATTERN)]


class DiscoveryOperationProfile(QueryContract):
    """Registered provider operation metadata without query, URL, argv, or shell text."""

    operation_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    backend: DiscoveryBackend
    universes: Annotated[tuple[DiscoveryUniverse, ...], Field(min_length=1, max_length=7)]
    result_kinds: Annotated[tuple[DiscoveryResultKind, ...], Field(min_length=1, max_length=5)]
    scope_kinds: Annotated[tuple[DiscoveryScopeKind, ...], Field(min_length=1, max_length=6)]
    predicate_fields: Annotated[tuple[DiscoveryPredicateField, ...], Field(max_length=8)] = ()
    predicate_operators: Annotated[tuple[DiscoveryPredicateOperator, ...], Field(max_length=4)] = ()
    projection: Annotated[
        tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...], Field(min_length=1, max_length=32)
    ]
    output_schema_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    normalization_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    validation_versions: Annotated[
        tuple[Annotated[str, Field(pattern=_VERSION_REF_PATTERN)], ...],
        Field(min_length=1, max_length=8),
    ]
    equivalence_key: Annotated[str, Field(pattern=_ID_PATTERN)]
    identity_profile: Annotated[str, Field(pattern=_ID_PATTERN)]
    priority: Annotated[int, Field(strict=True, ge=1, le=100)]
    command_template_id: Annotated[str, Field(pattern=_ID_PATTERN)] | None = None

    @model_validator(mode="after")
    def _operation_is_canonical(self) -> DiscoveryOperationProfile:
        for name, values in (
            ("universes", self.universes),
            ("result_kinds", self.result_kinds),
            ("scope_kinds", self.scope_kinds),
            ("predicate_fields", self.predicate_fields),
            ("predicate_operators", self.predicate_operators),
            ("projection", self.projection),
            ("validation_versions", self.validation_versions),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"discovery operation {name} MUST be unique")
        return self


class DiscoveryProfile(QueryContract):
    """Versioned provider mapping and registered-operation catalog entry."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    profile_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    revision: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    cloud: Annotated[str, Field(pattern=_ID_PATTERN)]
    provider_type: Annotated[str, Field(pattern=_PROVIDER_TYPE_PATTERN)]
    semantic_type: Annotated[str, Field(pattern=_ID_PATTERN)] | None = None
    operations: Annotated[tuple[DiscoveryOperationProfile, ...], Field(min_length=1, max_length=32)]
    limits: DiscoveryLimits
    provenance_refs: Annotated[
        tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...], Field(min_length=1, max_length=16)
    ]
    profile_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _profile_is_canonical(self) -> DiscoveryProfile:
        operation_ids = tuple(item.operation_id for item in self.operations)
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("discovery profile operation ids MUST be unique")
        if len(self.provenance_refs) != len(set(self.provenance_refs)):
            raise ValueError("discovery profile provenance refs MUST be unique")
        expected = content_digest(self.model_dump(mode="json", exclude={"profile_digest"}))
        if self.profile_digest != expected:
            raise ValueError("discovery profile digest does not match its content")
        return self


class DiscoveryQueryPlan(QueryContract):
    """Immutable registered backend plan that cannot carry operator-authored execution text."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    plan_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    intent_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    profile_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    profile_revision: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    universes: Annotated[tuple[DiscoveryUniverse, ...], Field(min_length=1, max_length=7)]
    backend: DiscoveryBackend
    operation_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    equivalence_key: Annotated[str, Field(pattern=_ID_PATTERN)]
    scope_kind: DiscoveryScopeKind
    scope_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authorization_ceiling_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    predicates: Annotated[tuple[DiscoveryPredicate, ...], Field(max_length=8)] = ()
    projection: Annotated[
        tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...], Field(min_length=1, max_length=32)
    ]
    limits: DiscoveryLimits
    fallback_history: Annotated[tuple[DiscoveryFallback, ...], Field(max_length=6)] = ()
    output_schema_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    normalization_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    validation_versions: Annotated[
        tuple[Annotated[str, Field(pattern=_VERSION_REF_PATTERN)], ...],
        Field(min_length=1, max_length=8),
    ]
    execution_authority: Literal[False] = False
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _plan_is_canonical(self) -> DiscoveryQueryPlan:
        if len(self.universes) != len(set(self.universes)):
            raise ValueError("discovery plan universes MUST be unique")
        if len(self.projection) != len(set(self.projection)):
            raise ValueError("discovery projection fields MUST be unique")
        if len(self.validation_versions) != len(set(self.validation_versions)):
            raise ValueError("discovery validation versions MUST be unique")
        if len({item.backend for item in self.fallback_history}) != len(self.fallback_history):
            raise ValueError("discovery fallback backends MUST be unique")
        if self.backend in {item.backend for item in self.fallback_history}:
            raise ValueError("selected backend MUST NOT appear in fallback history")
        expected = content_digest(self.model_dump(mode="json", exclude={"plan_digest"}))
        if self.plan_digest != expected:
            raise ValueError("discovery query plan digest does not match its content")
        return self


def discovery_intent_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by :class:`DiscoveryIntent`."""

    candidate = DiscoveryIntent.model_construct(
        intent_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(
        candidate.model_dump(
            mode="json",
            exclude={"intent_digest", "unresolved_modifiers"},
        )
    )


def discovery_plan_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by :class:`DiscoveryQueryPlan`."""

    candidate = DiscoveryQueryPlan.model_construct(
        plan_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"plan_digest"}))


def discovery_profile_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by :class:`DiscoveryProfile`."""

    candidate = DiscoveryProfile.model_construct(
        profile_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"profile_digest"}))


__all__ = [
    "DiscoveryBackend",
    "DiscoveryCoverageStatus",
    "DiscoveryFallback",
    "DiscoveryIntent",
    "DiscoveryLimits",
    "DiscoveryMappingStatus",
    "DiscoveryOperationProfile",
    "DiscoveryPredicate",
    "DiscoveryPredicateField",
    "DiscoveryPredicateOperator",
    "DiscoveryProfile",
    "DiscoveryQueryPlan",
    "DiscoveryResultKind",
    "DiscoveryScopeKind",
    "DiscoveryUniverse",
    "discovery_intent_digest",
    "discovery_plan_digest",
    "discovery_profile_digest",
]
