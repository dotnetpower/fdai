"""Sanitized execution, explanation, and coverage evidence for resource discovery."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from pydantic import Field, model_validator

from fdai_service_contracts.discovery import (
    DiscoveryBackend,
    DiscoveryCoverageStatus,
    DiscoveryMappingStatus,
    DiscoveryScopeKind,
    DiscoveryUniverse,
)
from fdai_service_contracts.ontology_query import QueryContract, content_digest

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ID_PATTERN = r"^[a-z][a-z0-9_.-]{0,127}$"
_PROVIDER_TYPE_PATTERN = r"^[A-Za-z][A-Za-z0-9.]{0,127}/[A-Za-z0-9._/-]{1,255}$"
_SENSITIVE_TEXT = re.compile(
    r"(?i)((?:^|\s)/subscriptions/|access[_-]?token|authorization:|bearer\s|client[_-]?secret|"
    r"password|\$skiptoken|continuation[_-]?token|provider[_-]?error)"
)
_GUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_SHELL_CONTROL = re.compile(r"[\x00-\x1f\x7f`$;&|]|\$\(")


class ProviderResourceObservation(QueryContract):
    """Bounded provider observation retained before optional semantic type governance."""

    provider_ref_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    provider_type: Annotated[str, Field(pattern=_PROVIDER_TYPE_PATTERN)]
    scope_kind: DiscoveryScopeKind
    mapping_status: DiscoveryMappingStatus
    semantic_type: Annotated[str, Field(pattern=_ID_PATTERN)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    evidence_ref: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def _mapping_is_consistent(self) -> ProviderResourceObservation:
        if self.mapping_status is DiscoveryMappingStatus.MAPPED and self.semantic_type is None:
            raise ValueError("mapped provider observation MUST name a semantic type")
        if (
            self.mapping_status is DiscoveryMappingStatus.UNMAPPED
            and self.semantic_type is not None
        ):
            raise ValueError("unmapped provider observation MUST NOT name a semantic type")
        if self.name is not None and _SHELL_CONTROL.search(self.name):
            raise ValueError("provider observation name MUST NOT contain executable text")
        return self


class DiscoveryPlanResult(QueryContract):
    """Bounded normalized output and completeness receipt for one exact plan."""

    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    universe: DiscoveryUniverse
    backend: DiscoveryBackend
    status: DiscoveryCoverageStatus
    complete: bool
    truncated: bool
    observations: Annotated[tuple[ProviderResourceObservation, ...], Field(max_length=10_000)] = ()
    observed_at: datetime
    reason_code: Annotated[str, Field(pattern=_ID_PATTERN)] | None = None

    @model_validator(mode="after")
    def _result_is_consistent(self) -> DiscoveryPlanResult:
        if self.observed_at.tzinfo is None:
            raise ValueError("discovery result observed_at MUST include a timezone")
        if self.complete == self.truncated:
            raise ValueError("discovery result completeness and truncation are inconsistent")
        if self.status in {DiscoveryCoverageStatus.COVERED, DiscoveryCoverageStatus.FALLBACK}:
            if not self.complete or self.reason_code is not None:
                raise ValueError("covered discovery result MUST be complete without a reason")
        elif self.reason_code is None:
            raise ValueError("incomplete discovery result MUST include a reason code")
        refs = tuple(item.provider_ref_digest for item in self.observations)
        if len(refs) != len(set(refs)):
            raise ValueError("one discovery plan MUST NOT repeat provider observations")
        return self


class MergedDiscoveryResult(QueryContract):
    """Canonical multi-plan result preserving every plan's completeness receipt."""

    observations: Annotated[tuple[ProviderResourceObservation, ...], Field(max_length=10_000)]
    plan_results: Annotated[tuple[DiscoveryPlanResult, ...], Field(min_length=1, max_length=16)]
    complete: bool
    execution_authority: Literal[False] = False
    result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _merged_result_is_canonical(self) -> MergedDiscoveryResult:
        expected_complete = all(item.complete and not item.truncated for item in self.plan_results)
        if self.complete != expected_complete:
            raise ValueError("merged discovery completeness does not match plan receipts")
        expected = content_digest(self.model_dump(mode="json", exclude={"result_digest"}))
        if self.result_digest != expected:
            raise ValueError("merged discovery result digest does not match its content")
        return self


class ProviderExecutionPreview(QueryContract):
    """One display-safe resource preview with no provider identifier or error field."""

    name: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    type: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    resource_group: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    status: Annotated[str, Field(min_length=1, max_length=128)] | None = None

    @model_validator(mode="after")
    def _preview_is_safe(self) -> ProviderExecutionPreview:
        values = tuple(value for value in self.model_dump().values() if value is not None)
        if not values:
            raise ValueError("provider execution preview MUST contain a display field")
        for value in values:
            if _SENSITIVE_TEXT.search(value) or _GUID.search(value) or "\n" in value:
                raise ValueError("provider execution preview contains sensitive text")
        return self


class ProviderExecutionResult(QueryContract):
    """Bounded count and preview summary derived from ephemeral provider output."""

    count: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
    preview: Annotated[tuple[ProviderExecutionPreview, ...], Field(max_length=10)] = ()
    truncated: bool

    @model_validator(mode="after")
    def _truncation_is_consistent(self) -> ProviderExecutionResult:
        if len(self.preview) > self.count:
            raise ValueError("provider execution preview MUST NOT exceed count")
        if self.truncated != (self.count > len(self.preview)):
            raise ValueError("provider execution truncation does not match preview count")
        return self


class ProviderExecutionCommand(QueryContract):
    """Catalog-rendered Azure CLI display command and optional bounded result."""

    label: Literal["resource_groups", "resources"]
    language: Literal["azure_cli"] = "azure_cli"
    command_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    command: Annotated[str, Field(min_length=1, max_length=4096)]
    result: ProviderExecutionResult | None = None

    @model_validator(mode="after")
    def _command_is_safe(self) -> ProviderExecutionCommand:
        _require_sanitized_cli(self.command)
        return self


class ProviderExecutionReceipt(QueryContract):
    """Server-owned Console receipt without credentials, raw ids, tokens, or provider errors."""

    transport: Literal["azure_cli"] = "azure_cli"
    backend: Literal["azure_resource_graph", "azure_resource_manager"]
    executed: Literal[True] = True
    redacted: Literal[True] = True
    page_count: Annotated[int, Field(strict=True, ge=1, le=100)]
    commands: Annotated[tuple[ProviderExecutionCommand, ...], Field(min_length=1, max_length=4)]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _receipt_is_canonical(self) -> ProviderExecutionReceipt:
        expected = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("provider execution receipt digest does not match its content")
        return self


class CommandExplanation(QueryContract):
    """Sanitized reproduction evidence derived from one registered discovery plan."""

    command_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    catalog_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    backend: DiscoveryBackend
    scope_kind: DiscoveryScopeKind
    cli_argv: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...],
        Field(min_length=1, max_length=32),
    ]
    kql_template: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    cli_version: Annotated[str, Field(min_length=1, max_length=32)]
    extension_prerequisites: Annotated[
        tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...], Field(max_length=8)
    ] = ()
    result_limit: Annotated[int, Field(strict=True, ge=1, le=10_000)]
    max_pages: Annotated[int, Field(strict=True, ge=1, le=100)]
    validation_status: Literal["validated"] = "validated"
    validated_at: datetime
    substitution_instructions: Annotated[
        tuple[Annotated[str, Field(pattern=_ID_PATTERN)], ...], Field(min_length=1, max_length=8)
    ]
    equivalent_command: bool
    redacted: Literal[True] = True
    execution_authority: Literal[False] = False
    explanation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _explanation_is_canonical(self) -> CommandExplanation:
        if self.validated_at.tzinfo is None:
            raise ValueError("command explanation validated_at MUST include a timezone")
        for argument in self.cli_argv:
            _require_sanitized_cli(argument)
        if self.kql_template is not None:
            if _SENSITIVE_TEXT.search(self.kql_template) or _GUID.search(self.kql_template):
                raise ValueError("command explanation KQL contains sensitive text")
            if ";" in self.kql_template or "\n" in self.kql_template:
                raise ValueError("command explanation KQL contains executable controls")
        expected = content_digest(self.model_dump(mode="json", exclude={"explanation_digest"}))
        if self.explanation_digest != expected:
            raise ValueError("command explanation digest does not match its content")
        return self


class DiscoveryCoverageReceipt(QueryContract):
    """One replay-stable coverage row from a fixture or governed read-only canary."""

    cloud: Annotated[str, Field(pattern=_ID_PATTERN)]
    provider_type: Annotated[str, Field(pattern=_PROVIDER_TYPE_PATTERN)]
    universe: DiscoveryUniverse
    scope_kind: DiscoveryScopeKind
    backend: DiscoveryBackend
    profile_revision: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    platform_version: Annotated[str, Field(min_length=1, max_length=64)]
    state: DiscoveryCoverageStatus
    scope_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    execution_receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observed_provider_types: Annotated[
        tuple[Annotated[str, Field(pattern=_PROVIDER_TYPE_PATTERN)], ...], Field(max_length=256)
    ] = ()
    discovered_count: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
    complete: bool
    truncated: bool
    source: Literal["deterministic_fixture", "live_canary"]
    observed_at: datetime
    execution_authority: Literal[False] = False
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _coverage_is_canonical(self) -> DiscoveryCoverageReceipt:
        if self.observed_at.tzinfo is None:
            raise ValueError("discovery coverage observed_at MUST include a timezone")
        if self.complete == self.truncated:
            raise ValueError("discovery coverage completeness and truncation are inconsistent")
        if self.state in {DiscoveryCoverageStatus.COVERED, DiscoveryCoverageStatus.FALLBACK}:
            if not self.complete:
                raise ValueError("covered discovery coverage receipt MUST be complete")
        elif self.complete:
            raise ValueError("incomplete discovery coverage state MUST NOT claim completeness")
        expected = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("discovery coverage receipt digest does not match its content")
        return self


def merged_discovery_result_digest(**values: object) -> str:
    """Return the canonical digest for fields accepted by :class:`MergedDiscoveryResult`."""

    candidate = MergedDiscoveryResult.model_construct(
        result_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"result_digest"}))


def provider_execution_receipt_digest(**values: object) -> str:
    """Return the canonical digest for a provider execution receipt body."""

    candidate = ProviderExecutionReceipt.model_construct(
        receipt_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"receipt_digest"}))


def command_explanation_digest(**values: object) -> str:
    """Return the canonical digest for a command explanation body."""

    candidate = CommandExplanation.model_construct(
        explanation_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"explanation_digest"}))


def discovery_coverage_receipt_digest(**values: object) -> str:
    """Return the canonical digest for a discovery coverage receipt body."""

    candidate = DiscoveryCoverageReceipt.model_construct(
        receipt_digest="",
        **cast(dict[str, Any], values),
    )
    return content_digest(candidate.model_dump(mode="json", exclude={"receipt_digest"}))


def _require_sanitized_cli(value: str) -> None:
    if _SHELL_CONTROL.search(value) or _SENSITIVE_TEXT.search(value) or _GUID.search(value):
        raise ValueError("Azure CLI display text contains executable or sensitive content")


__all__ = [
    "CommandExplanation",
    "DiscoveryCoverageReceipt",
    "DiscoveryPlanResult",
    "MergedDiscoveryResult",
    "ProviderExecutionCommand",
    "ProviderExecutionPreview",
    "ProviderExecutionReceipt",
    "ProviderExecutionResult",
    "ProviderResourceObservation",
    "command_explanation_digest",
    "discovery_coverage_receipt_digest",
    "merged_discovery_result_digest",
    "provider_execution_receipt_digest",
]
