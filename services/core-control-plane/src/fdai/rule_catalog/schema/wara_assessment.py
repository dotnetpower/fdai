"""Strict schema and safety checks for the derived WARA assessment catalog."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition

_SHA256 = r"^sha256:[a-f0-9]{64}$"
_UUID = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
_GIT_REF = r"^[a-f0-9]{40}$"
_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,255}$"
_ALLOWED_TABLES = frozenset(
    {
        "advisorresources",
        "maintenanceresources",
        "recoveryservicesresources",
        "resourcecontainers",
        "resources",
    }
)
_FORBIDDEN_QUERY_PATTERNS = (
    ("mutation_command", re.compile(r"(?i)\b(delete|drop|alter|create|update|patch)\b")),
    ("control_command", re.compile(r"(?im)^\s*(set|execute|invoke)\b")),
    (
        "dynamic_endpoint",
        re.compile(r"(?i)\b(externaldata|http_request|cluster\s*\(|database\s*\()"),
    ),
    ("unsupported_join", re.compile(r"(?i)\b(join|union)\b")),
)


def canonical_digest(value: object) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible value."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class WaraDisposition(StrEnum):
    EXISTING_RULE = "existing_rule"
    NEW_RULE_CANDIDATE = "new_rule_candidate"
    MANUAL_EVIDENCE = "manual_evidence"
    CONDITIONAL_NOT_APPLICABLE = "conditional_not_applicable"
    AMBIGUOUS_OR_BLOCKED = "ambiguous_or_blocked"


class WaraMappingState(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    UNMAPPED = "unmapped"


class ResourceTypeDisposition(StrEnum):
    CANONICAL = "canonical"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


class QuerySafetyClassification(StrEnum):
    READ_ONLY_BOUNDED = "read_only_bounded"
    BLOCKED = "blocked"


class WaraQuerySafetyReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_ref: Annotated[str, Field(min_length=1, max_length=256)]
    body_digest: Annotated[str, Field(pattern=_SHA256)]
    safety_classification: QuerySafetyClassification
    declared_tables: tuple[str, ...]
    query_resource_types: tuple[str, ...]
    maximum_rows: Annotated[int, Field(ge=1, le=1000)]
    timeout_seconds: Annotated[int, Field(ge=1, le=60)]
    evidence_freshness_ceiling_seconds: Annotated[
        int,
        Field(ge=60, le=31_536_000),
    ]
    evaluator_ref: str | None
    blocked_reasons: tuple[Annotated[str, Field(pattern=_IDENTIFIER)], ...]

    @model_validator(mode="after")
    def validate_review(self) -> WaraQuerySafetyReview:
        if self.declared_tables != tuple(sorted(set(self.declared_tables))):
            raise ValueError("declared_tables MUST be unique and ordered")
        if self.query_resource_types != tuple(sorted(set(self.query_resource_types))):
            raise ValueError("query_resource_types MUST be unique and ordered")
        if self.evaluator_ref is None and not self.blocked_reasons:
            raise ValueError("WARA query review requires an evaluator or blocked reason")
        if (
            self.safety_classification is QuerySafetyClassification.BLOCKED
            and not self.blocked_reasons
        ):
            raise ValueError("blocked WARA query requires a reason")
        if self.evaluator_ref is not None and "missing_exact_evaluator" in self.blocked_reasons:
            raise ValueError("mapped evaluator cannot be marked missing")
        return self


class WaraManualEvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Annotated[str, Field(pattern=_IDENTIFIER)]
    authoritative_producer: Annotated[str, Field(pattern=_IDENTIFIER)]
    scope_contract: Annotated[str, Field(pattern=_IDENTIFIER)]
    freshness_ceiling_seconds: Annotated[int, Field(ge=60, le=31_536_000)]
    digest_required: bool
    failure_behavior: Annotated[str, Field(pattern=r"^unknown$")]
    accountable_owner_slot: Annotated[str, Field(pattern=_IDENTIFIER)]
    blocked_reason: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None


class WaraApplicabilityMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_provider_type: Annotated[str, Field(min_length=1, max_length=256)]
    disposition: ResourceTypeDisposition
    canonical_resource_type: str | None
    parent_provider_type: str | None
    requires_exact_child_scope: bool

    @model_validator(mode="after")
    def validate_mapping(self) -> WaraApplicabilityMapping:
        if (self.disposition is ResourceTypeDisposition.CANONICAL) != (
            self.canonical_resource_type is not None
        ):
            raise ValueError("canonical disposition MUST match canonical_resource_type presence")
        if self.requires_exact_child_scope != (self.parent_provider_type is not None):
            raise ValueError("child-scope flag MUST match parent provider type presence")
        return self


class WaraRecommendationCrosswalk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aprl_guid: Annotated[str, Field(pattern=_UUID)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    recommendation_control: Annotated[str, Field(min_length=1, max_length=64)]
    impact: Annotated[str, Field(pattern=r"^(Low|Medium|High)$")]
    provider_resource_type: Annotated[str, Field(min_length=1, max_length=256)]
    source_path: Annotated[str, Field(min_length=1, max_length=512)]
    source_digest: Annotated[str, Field(pattern=_SHA256)]
    workload_tags: tuple[str, ...]
    automation_available: bool
    product_group_verified: bool
    disposition: WaraDisposition
    mapping_state: WaraMappingState
    rule_refs: tuple[str, ...]
    objective_refs: tuple[str, ...]
    applicability: WaraApplicabilityMapping
    query_review: WaraQuerySafetyReview | None
    manual_evidence: WaraManualEvidenceRequirement | None
    reviewer: Annotated[str, Field(pattern=_IDENTIFIER)]
    review_state: Annotated[str, Field(pattern=r"^reviewed-conservative$")]
    implementation_digest: Annotated[str, Field(pattern=_SHA256)]

    @model_validator(mode="after")
    def validate_axes(self) -> WaraRecommendationCrosswalk:
        if self.workload_tags != tuple(sorted(set(self.workload_tags))):
            raise ValueError("workload_tags MUST be unique and ordered")
        if self.automation_available != (self.query_review is not None):
            raise ValueError("automation_available MUST match query_review presence")
        if self.automation_available == (self.manual_evidence is not None):
            raise ValueError("non-automated recommendations require manual_evidence")
        if self.mapping_state is WaraMappingState.FULL and not (
            self.rule_refs or self.objective_refs
        ):
            raise ValueError("full mappings require a Rule or ControlObjective reference")
        if self.mapping_state is WaraMappingState.UNMAPPED and (
            self.rule_refs or self.objective_refs
        ):
            raise ValueError("unmapped recommendations cannot carry mapping references")
        material = self.model_dump(mode="json")
        material.pop("implementation_digest")
        if self.implementation_digest != canonical_digest(material):
            raise ValueError(f"{self.aprl_guid}: implementation_digest mismatch")
        return self


class WaraResourceTypeMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_provider_type: Annotated[str, Field(min_length=1, max_length=256)]
    disposition: ResourceTypeDisposition
    canonical_resource_type: str | None
    parent_provider_type: str | None
    requires_exact_child_scope: bool
    reviewer: Annotated[str, Field(pattern=_IDENTIFIER)]


class WaraUmbrellaRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aprl_guid: Annotated[str, Field(pattern=_UUID)]
    waf_control_ref: Annotated[str, Field(pattern=r"^azure-waf:RE:\d{2}$")]
    relation: Annotated[str, Field(pattern=r"^specializes$")]
    semantic_equivalence: Annotated[bool, Field()]
    counting: Annotated[str, Field(pattern=r"^independent_aprl_guid$")]

    @model_validator(mode="after")
    def reject_equivalence(self) -> WaraUmbrellaRelation:
        if self.semantic_equivalence:
            raise ValueError("WAF umbrella relation cannot assert semantic equivalence")
        return self


class WaraExpectedCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_recommendations: Annotated[int, Field(ge=1)]
    disabled_recommendations: Annotated[int, Field(ge=0)]
    resource_types: Annotated[int, Field(ge=1)]
    automated_recommendations: Annotated[int, Field(ge=0)]
    manual_recommendations: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_partition(self) -> WaraExpectedCounts:
        if (
            self.automated_recommendations + self.manual_recommendations
            != self.active_recommendations
        ):
            raise ValueError("automated and manual counts MUST partition active recommendations")
        return self


class WaraAssessmentCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1\.0\.0$")]
    framework_id: Annotated[str, Field(pattern=r"^azure-wara$")]
    framework_version: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    source_revision: Annotated[str, Field(pattern=_GIT_REF)]
    source_license: Annotated[str, Field(pattern=r"^MIT$")]
    redistribution: Annotated[str, Field(pattern=r"^embeddable$")]
    source_catalog_digest: Annotated[str, Field(pattern=_SHA256)]
    published_active_digest: Annotated[str, Field(pattern=_SHA256)]
    queries_digest: Annotated[str, Field(pattern=_SHA256)]
    expected_counts: WaraExpectedCounts
    resource_type_mappings: tuple[WaraResourceTypeMapping, ...]
    umbrella_relations: tuple[WaraUmbrellaRelation, ...]
    recommendations: tuple[WaraRecommendationCrosswalk, ...]
    crosswalk_digest: Annotated[str, Field(pattern=_SHA256)]


class WaraQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aprl_guid: Annotated[str, Field(pattern=_UUID)]
    body_digest: Annotated[str, Field(pattern=_SHA256)]
    body_base64: Annotated[str, Field(min_length=1, max_length=32_768)]

    @model_validator(mode="after")
    def validate_digest(self) -> WaraQueryBody:
        body = self.decoded_body()
        digest = f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
        if self.body_digest != digest:
            raise ValueError(f"{self.aprl_guid}: query body digest mismatch")
        return self

    def decoded_body(self) -> str:
        """Decode the exact external UTF-8 query body from ASCII storage."""

        try:
            return base64.b64decode(self.body_base64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(f"{self.aprl_guid}: query body base64 is invalid") from exc


class WaraQueryCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1\.0\.0$")]
    source_revision: Annotated[str, Field(pattern=_GIT_REF)]
    published_active_digest: Annotated[str, Field(pattern=_SHA256)]
    queries: tuple[WaraQueryBody, ...]
    queries_digest: Annotated[str, Field(pattern=_SHA256)]


def classify_wara_query(
    query: str,
    *,
    declared_provider_type: str | None = None,
) -> tuple[
    QuerySafetyClassification,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Classify one external ARG query without executing it."""

    reasons = [name for name, pattern in _FORBIDDEN_QUERY_PATTERNS if pattern.search(query)]
    tables = tuple(
        sorted(
            {
                match.casefold()
                for match in re.findall(
                    r"(?im)^\s*(advisorresources|maintenanceresources|"
                    r"recoveryservicesresources|resourcecontainers|resources)\b",
                    query,
                )
            }
        )
    )
    if not tables:
        reasons.append("missing_declared_table")
    if set(tables) - _ALLOWED_TABLES:
        reasons.append("undeclared_table")
    resource_types = tuple(
        sorted(
            {
                item.casefold()
                for item in re.findall(
                    r"(?i)\b(?:microsoft|oracle)\.[a-z0-9.]+(?:/[a-z0-9._-]+)+",
                    query,
                )
            }
        )
    )
    if declared_provider_type is not None and any(
        item != declared_provider_type.casefold() for item in resource_types
    ):
        reasons.append("undeclared_resource_type")
    classification = (
        QuerySafetyClassification.BLOCKED
        if reasons
        else QuerySafetyClassification.READ_ONLY_BOUNDED
    )
    return classification, tuple(sorted(set(reasons))), tables, resource_types


def _json_object(path: Path) -> dict[str, Any]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return raw


def load_wara_assessment_catalog(
    path: Path,
    queries_path: Path,
    *,
    framework: FrameworkDefinition | None = None,
    framework_path: Path | None = None,
) -> tuple[WaraAssessmentCatalog, WaraQueryCatalog]:
    """Load and reconcile the crosswalk, query bodies, and pinned framework."""

    raw_catalog = _json_object(path)
    stored_crosswalk_digest = raw_catalog.get("crosswalk_digest")
    digest_material = dict(raw_catalog)
    digest_material.pop("crosswalk_digest", None)
    if stored_crosswalk_digest != canonical_digest(digest_material):
        raise ValueError("WARA crosswalk digest mismatch")
    catalog = WaraAssessmentCatalog.model_validate(raw_catalog)

    raw_queries = _json_object(queries_path)
    stored_queries_digest = raw_queries.get("queries_digest")
    query_material = dict(raw_queries)
    query_material.pop("queries_digest", None)
    if stored_queries_digest != canonical_digest(query_material):
        raise ValueError("WARA query catalog digest mismatch")
    queries = WaraQueryCatalog.model_validate(raw_queries)
    if catalog.queries_digest != queries.queries_digest:
        raise ValueError("WARA crosswalk and query catalog digests differ")
    if catalog.source_revision != queries.source_revision:
        raise ValueError("WARA crosswalk and query source revisions differ")

    records = catalog.recommendations
    ids = tuple(item.aprl_guid for item in records)
    if len(ids) != len(set(ids)):
        raise ValueError("WARA crosswalk APRL GUIDs MUST be unique")
    expected = catalog.expected_counts
    if len(records) != expected.active_recommendations:
        raise ValueError("WARA active recommendation count mismatch")
    automated = sum(item.automation_available for item in records)
    if automated != expected.automated_recommendations:
        raise ValueError("WARA automated recommendation count mismatch")
    if len(records) - automated != expected.manual_recommendations:
        raise ValueError("WARA manual recommendation count mismatch")
    normalized_types = {item.applicability.normalized_provider_type for item in records}
    if len(normalized_types) != expected.resource_types:
        raise ValueError("WARA resource type count mismatch")
    mapping_types = {item.normalized_provider_type for item in catalog.resource_type_mappings}
    if mapping_types != normalized_types:
        raise ValueError("WARA resource type mapping coverage mismatch")

    query_by_id = {item.aprl_guid: item for item in queries.queries}
    if len(query_by_id) != len(queries.queries):
        raise ValueError("WARA query GUIDs MUST be unique")
    automated_ids = {item.aprl_guid for item in records if item.automation_available}
    if set(query_by_id) != automated_ids:
        raise ValueError("WARA query bodies MUST exactly cover automated recommendations")
    for record in records:
        if record.query_review is not None:
            query = query_by_id[record.aprl_guid]
            if record.query_review.body_digest != query.body_digest:
                raise ValueError(f"{record.aprl_guid}: crosswalk query digest mismatch")
            classification, reasons, tables, resource_types = classify_wara_query(
                query.decoded_body(),
                declared_provider_type=record.applicability.normalized_provider_type,
            )
            review = record.query_review
            if (
                review.safety_classification is not classification
                or review.declared_tables != tables
                or review.query_resource_types != resource_types
            ):
                raise ValueError(f"{record.aprl_guid}: query safety review mismatch")
            expected_reasons = set(reasons)
            if review.evaluator_ref is None:
                expected_reasons.add("missing_exact_evaluator")
            if set(review.blocked_reasons) != expected_reasons:
                raise ValueError(f"{record.aprl_guid}: query blocked reasons mismatch")

    if framework is not None:
        _validate_framework_alignment(catalog, framework)
    if framework_path is not None:
        digest = f"sha256:{hashlib.sha256(framework_path.read_bytes()).hexdigest()}"
        if catalog.source_catalog_digest != digest:
            raise ValueError("WARA source catalog byte digest mismatch")
    return catalog, queries


def _validate_framework_alignment(
    catalog: WaraAssessmentCatalog,
    framework: FrameworkDefinition,
) -> None:
    if framework.id != catalog.framework_id or framework.version != catalog.framework_version:
        raise ValueError("WARA framework identity does not match crosswalk")
    if framework.inventory is None:
        raise ValueError("WARA framework inventory is required")
    inventory = framework.inventory
    expected = catalog.expected_counts
    if (
        inventory.active_controls != expected.active_recommendations
        or inventory.disabled_controls != expected.disabled_recommendations
        or inventory.resource_type_count != expected.resource_types
        or inventory.automated_active_controls != expected.automated_recommendations
        or inventory.published_active_digest != catalog.published_active_digest
    ):
        raise ValueError("WARA framework inventory does not match crosswalk counts")
    source_revision = next(
        (source.resolved_ref for source in framework.sources if source.id == "aprl"),
        None,
    )
    if source_revision != catalog.source_revision:
        raise ValueError("WARA source revision does not match crosswalk")
    controls = tuple(
        resolved.control
        for resolved in framework.resolved_controls()
        if resolved.control.wara is not None and resolved.control.wara.state == "Active"
    )
    active_ids = {control.id for control in controls}
    if active_ids != {item.aprl_guid for item in catalog.recommendations}:
        raise ValueError("WARA framework active GUIDs do not match crosswalk")
    disabled = sum(
        resolved.control.wara is not None and resolved.control.wara.state == "Disabled"
        for resolved in framework.resolved_controls()
    )
    if disabled != expected.disabled_recommendations:
        raise ValueError("WARA disabled recommendations entered active accounting")


__all__ = [
    "QuerySafetyClassification",
    "ResourceTypeDisposition",
    "WaraAssessmentCatalog",
    "WaraDisposition",
    "WaraManualEvidenceRequirement",
    "WaraMappingState",
    "WaraQueryCatalog",
    "WaraRecommendationCrosswalk",
    "canonical_digest",
    "classify_wara_query",
    "load_wara_assessment_catalog",
]
