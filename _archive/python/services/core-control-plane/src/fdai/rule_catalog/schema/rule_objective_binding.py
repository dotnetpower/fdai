"""Version-pinned, non-authoritative Rule-to-objective bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.rule_catalog.schema.catalog_digest import canonical_catalog_digest
from fdai.shared.contracts.models import OntologyProvenance

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_REFERENCE_PATTERN = r"^[A-Za-z][A-Za-z0-9._:@/-]{0,255}$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
_MAX_ITEMS = 256


class ObjectiveRelationship(StrEnum):
    REALIZES = "realizes"
    PARTIALLY_REALIZES = "partially_realizes"


class BindingState(StrEnum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    PROMOTED = "promoted"
    RETIRED = "retired"


class VariantDimension(StrEnum):
    THRESHOLD = "threshold"
    UNIT = "unit"
    AGGREGATION_WINDOW = "aggregation_window"
    EXCEPTION_MODEL = "exception_model"
    EVIDENCE_SHAPE = "evidence_shape"
    PROVIDER_MAPPING = "provider_mapping"


class CatalogRecordPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: Annotated[str, Field(pattern=_REFERENCE_PATTERN)]
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class ApplicabilityDelta(BaseModel):
    """Catalog references that narrow applicability without assigning parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        default=(), max_length=_MAX_ITEMS
    )
    resource_subtype_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        default=(), max_length=_MAX_ITEMS
    )
    evidence_shape_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        default=(), max_length=_MAX_ITEMS
    )
    environment_constraint_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = (
        Field(default=(), max_length=_MAX_ITEMS)
    )

    @model_validator(mode="after")
    def require_canonical_references(self) -> ApplicabilityDelta:
        for name, values in (
            ("provider_refs", self.provider_refs),
            ("resource_subtype_refs", self.resource_subtype_refs),
            ("evidence_shape_refs", self.evidence_shape_refs),
            ("environment_constraint_refs", self.environment_constraint_refs),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} MUST be unique and ordered")
        return self


class RuleObjectiveBinding(BaseModel):
    """Immutable search relation that cannot evaluate, approve, or execute."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=_SEMVER_PATTERN)] = "1.0.0"
    id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    objective: CatalogRecordPin
    rule: CatalogRecordPin
    relationship: ObjectiveRelationship
    applicability_delta: ApplicabilityDelta
    variant_dimensions: tuple[VariantDimension, ...] = Field(
        default=(), max_length=len(VariantDimension)
    )
    implementation_signature_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    evidence_signature_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    required_evidence_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        min_length=1, max_length=_MAX_ITEMS
    )
    equivalence_receipt: CatalogRecordPin | None = None
    non_equivalence_reasons: tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...] = (
        Field(default=(), max_length=_MAX_ITEMS)
    )
    reviewer: Annotated[str, Field(min_length=1, max_length=256)]
    state: BindingState = BindingState.CANDIDATE
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    provenance: OntologyProvenance

    @model_validator(mode="after")
    def validate_binding(self) -> RuleObjectiveBinding:
        if self.variant_dimensions != tuple(sorted(set(self.variant_dimensions))):
            raise ValueError("variant_dimensions MUST be unique and ordered")
        if self.required_evidence_refs != tuple(sorted(set(self.required_evidence_refs))):
            raise ValueError("required_evidence_refs MUST be unique and ordered")
        if self.non_equivalence_reasons != tuple(sorted(set(self.non_equivalence_reasons))):
            raise ValueError("non_equivalence_reasons MUST be unique and ordered")
        if self.relationship is ObjectiveRelationship.PARTIALLY_REALIZES:
            if not self.non_equivalence_reasons:
                raise ValueError("partially_realizes MUST record non_equivalence_reasons")
        if self.equivalence_receipt is not None and self.non_equivalence_reasons:
            raise ValueError(
                "equivalence_receipt and non_equivalence_reasons are mutually exclusive"
            )
        return self

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class RuleObjectiveBindingIssue:
    key: str
    message: str


class RuleObjectiveBindingCatalogError(ValueError):
    def __init__(self, issues: list[RuleObjectiveBindingIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"RuleObjectiveBinding validation failed: {preview}{suffix}")


class RuleObjectiveBindingMigrationReport(BaseModel):
    """Count-balanced, non-authoritative accounting for authored Rule migration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authored_rule_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        max_length=_MAX_ITEMS
    )
    bound_rule_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        max_length=_MAX_ITEMS
    )
    intentionally_unbound_rule_refs: tuple[
        Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...
    ] = Field(max_length=_MAX_ITEMS)
    ambiguous_rule_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        max_length=_MAX_ITEMS
    )
    rejected_rule_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        max_length=_MAX_ITEMS
    )

    @model_validator(mode="after")
    def require_canonical_partition(self) -> RuleObjectiveBindingMigrationReport:
        partitions = (
            self.bound_rule_refs,
            self.intentionally_unbound_rule_refs,
            self.ambiguous_rule_refs,
            self.rejected_rule_refs,
        )
        for field_name, values in (
            ("authored_rule_refs", self.authored_rule_refs),
            ("bound_rule_refs", self.bound_rule_refs),
            ("intentionally_unbound_rule_refs", self.intentionally_unbound_rule_refs),
            ("ambiguous_rule_refs", self.ambiguous_rule_refs),
            ("rejected_rule_refs", self.rejected_rule_refs),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field_name} MUST be unique and ordered")
        accounted = tuple(sorted(rule_ref for partition in partitions for rule_ref in partition))
        if accounted != self.authored_rule_refs:
            raise ValueError("migration outcomes MUST partition every authored Rule exactly once")
        return self


def build_rule_objective_binding_migration_report(
    *,
    authored_rule_refs: frozenset[str],
    bindings: tuple[RuleObjectiveBinding, ...],
    intentionally_unbound_rule_refs: frozenset[str] = frozenset(),
    ambiguous_rule_refs: frozenset[str] = frozenset(),
    rejected_rule_refs: frozenset[str] = frozenset(),
) -> RuleObjectiveBindingMigrationReport:
    """Build a complete migration partition without treating candidates as bound."""

    bound_rule_refs = {
        binding.rule.ref
        for binding in bindings
        if binding.state in {BindingState.REVIEWED, BindingState.PROMOTED}
    }
    named_partitions = {
        "bound": bound_rule_refs,
        "intentionally_unbound": set(intentionally_unbound_rule_refs),
        "ambiguous": set(ambiguous_rule_refs),
        "rejected": set(rejected_rule_refs),
    }
    issues: list[RuleObjectiveBindingIssue] = []
    seen: dict[str, str] = {}
    for partition_name, rule_refs in named_partitions.items():
        for rule_ref in sorted(rule_refs):
            if rule_ref not in authored_rule_refs:
                issues.append(
                    RuleObjectiveBindingIssue(
                        key=f"migration:{partition_name}:{rule_ref}",
                        message=f"migration outcome references unknown authored Rule {rule_ref!r}",
                    )
                )
            previous_partition = seen.get(rule_ref)
            if previous_partition is not None:
                issues.append(
                    RuleObjectiveBindingIssue(
                        key=f"migration:{rule_ref}",
                        message=(
                            f"authored Rule {rule_ref!r} appears in both "
                            f"{previous_partition!r} and {partition_name!r} outcomes"
                        ),
                    )
                )
            else:
                seen[rule_ref] = partition_name
    for rule_ref in sorted(authored_rule_refs - seen.keys()):
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"migration:unaccounted:{rule_ref}",
                message=f"authored Rule {rule_ref!r} has no migration outcome",
            )
        )
    if issues:
        raise RuleObjectiveBindingCatalogError(issues)

    return RuleObjectiveBindingMigrationReport(
        authored_rule_refs=tuple(sorted(authored_rule_refs)),
        bound_rule_refs=tuple(sorted(bound_rule_refs)),
        intentionally_unbound_rule_refs=tuple(sorted(intentionally_unbound_rule_refs)),
        ambiguous_rule_refs=tuple(sorted(ambiguous_rule_refs)),
        rejected_rule_refs=tuple(sorted(rejected_rule_refs)),
    )


def rule_objective_binding_content_hash(binding: RuleObjectiveBinding) -> str:
    return canonical_catalog_digest(binding)


def evidence_signature_digest(required_evidence_refs: tuple[str, ...]) -> str:
    """Hash the canonical ordered evidence identities required by a binding."""

    encoded = json.dumps(
        required_evidence_refs,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_rule_objective_binding_from_mapping(
    raw: Mapping[str, Any],
    *,
    objective_digests: Mapping[str, str],
    rule_digests: Mapping[str, str],
    rule_implementation_digests: Mapping[str, str],
    evidence_refs: frozenset[str],
    equivalence_receipt_digests: Mapping[str, str] | None = None,
    reviewed_equivalence_receipt_refs: frozenset[str] = frozenset(),
    origin: str = "<mapping>",
) -> RuleObjectiveBinding:
    """Validate one binding and aggregate stale or unknown catalog pins."""

    try:
        binding = RuleObjectiveBinding.model_validate(raw)
    except ValueError as exc:
        raise RuleObjectiveBindingCatalogError(_pydantic_issues(exc, origin)) from exc

    issues: list[RuleObjectiveBindingIssue] = []
    _check_pin(binding.objective, objective_digests, "objective", origin, issues)
    _check_pin(binding.rule, rule_digests, "rule", origin, issues)
    expected_implementation_digest = rule_implementation_digests.get(binding.rule.ref)
    if expected_implementation_digest is None:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:implementation_signature_digest",
                message=f"missing implementation signature for {binding.rule.ref!r}",
            )
        )
    elif binding.implementation_signature_digest != expected_implementation_digest:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:implementation_signature_digest",
                message=(
                    f"implementation signature mismatch for {binding.rule.ref!r}: "
                    f"expected {expected_implementation_digest}, "
                    f"got {binding.implementation_signature_digest}"
                ),
            )
        )
    for index, evidence_ref in enumerate(binding.required_evidence_refs):
        if evidence_ref not in evidence_refs:
            issues.append(
                RuleObjectiveBindingIssue(
                    key=f"{origin}:required_evidence_refs[{index}]",
                    message=f"unknown evidence reference {evidence_ref!r}",
                )
            )
    expected_evidence_digest = evidence_signature_digest(binding.required_evidence_refs)
    if binding.evidence_signature_digest != expected_evidence_digest:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:evidence_signature_digest",
                message=(
                    f"evidence signature mismatch: expected {expected_evidence_digest}, "
                    f"got {binding.evidence_signature_digest}"
                ),
            )
        )
    if binding.equivalence_receipt is not None:
        _check_pin(
            binding.equivalence_receipt,
            equivalence_receipt_digests or {},
            "equivalence_receipt",
            origin,
            issues,
        )
        if binding.equivalence_receipt.ref not in reviewed_equivalence_receipt_refs:
            issues.append(
                RuleObjectiveBindingIssue(
                    key=f"{origin}:equivalence_receipt.ref",
                    message=(
                        f"equivalence receipt {binding.equivalence_receipt.ref!r} "
                        "is not independently reviewed"
                    ),
                )
            )

    expected_digest = rule_objective_binding_content_hash(binding)
    if binding.content_digest != expected_digest:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:content_digest",
                message=f"content_digest mismatch: expected {expected_digest}",
            )
        )
    if binding.provenance.content_hash != expected_digest:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:provenance.content_hash",
                message=f"provenance.content_hash mismatch: expected {expected_digest}",
            )
        )
    if issues:
        raise RuleObjectiveBindingCatalogError(issues)
    return binding


def load_rule_objective_binding_catalog(
    root: Path,
    *,
    objective_digests: Mapping[str, str],
    rule_digests: Mapping[str, str],
    rule_implementation_digests: Mapping[str, str],
    evidence_refs: frozenset[str],
    equivalence_receipt_digests: Mapping[str, str] | None = None,
    reviewed_equivalence_receipt_refs: frozenset[str] = frozenset(),
    required_reviewed_rule_refs: frozenset[str] = frozenset(),
) -> tuple[RuleObjectiveBinding, ...]:
    issues: list[RuleObjectiveBindingIssue] = []
    loaded: list[RuleObjectiveBinding] = []
    seen_refs: set[str] = set()
    for path in _iter_yaml_files(root):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(RuleObjectiveBindingIssue(path.name, f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(RuleObjectiveBindingIssue(path.name, "top-level must be a mapping"))
            continue
        try:
            binding = load_rule_objective_binding_from_mapping(
                raw,
                objective_digests=objective_digests,
                rule_digests=rule_digests,
                rule_implementation_digests=rule_implementation_digests,
                evidence_refs=evidence_refs,
                equivalence_receipt_digests=equivalence_receipt_digests,
                reviewed_equivalence_receipt_refs=reviewed_equivalence_receipt_refs,
                origin=path.name,
            )
        except RuleObjectiveBindingCatalogError as exc:
            issues.extend(exc.issues)
            continue
        if binding.ref in seen_refs:
            issues.append(
                RuleObjectiveBindingIssue(path.name, f"duplicate binding ref {binding.ref!r}")
            )
            continue
        seen_refs.add(binding.ref)
        loaded.append(binding)
    reviewed_rule_refs = {
        binding.rule.ref
        for binding in loaded
        if binding.state in {BindingState.REVIEWED, BindingState.PROMOTED}
    }
    for rule_ref in sorted(required_reviewed_rule_refs - reviewed_rule_refs):
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"reviewed_coverage:{rule_ref}",
                message=f"missing reviewed binding for authored Rule {rule_ref!r}",
            )
        )
    if issues:
        raise RuleObjectiveBindingCatalogError(issues)
    return tuple(sorted(loaded, key=lambda binding: binding.ref))


def validate_rule_objective_binding_transition(
    previous: RuleObjectiveBinding,
    current: RuleObjectiveBinding,
) -> None:
    if previous.ref != current.ref:
        raise ValueError("RuleObjectiveBinding transition MUST retain the exact binding ref")
    allowed = {
        BindingState.CANDIDATE: {BindingState.REVIEWED, BindingState.RETIRED},
        BindingState.REVIEWED: {BindingState.PROMOTED, BindingState.RETIRED},
        BindingState.PROMOTED: {BindingState.RETIRED},
        BindingState.RETIRED: set(),
    }
    if current.state != previous.state and current.state not in allowed[previous.state]:
        raise ValueError(
            f"RuleObjectiveBinding state transition {previous.state.value!r} -> "
            f"{current.state.value!r} is not allowed"
        )


def _check_pin(
    pin: CatalogRecordPin,
    known_digests: Mapping[str, str],
    field: str,
    origin: str,
    issues: list[RuleObjectiveBindingIssue],
) -> None:
    expected = known_digests.get(pin.ref)
    if expected is None:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:{field}.ref",
                message=f"unknown {field} version {pin.ref!r}",
            )
        )
    elif pin.content_digest != expected:
        issues.append(
            RuleObjectiveBindingIssue(
                key=f"{origin}:{field}.content_digest",
                message=(
                    f"{field} digest mismatch for {pin.ref!r}: "
                    f"expected {expected}, got {pin.content_digest}"
                ),
            )
        )


def _pydantic_issues(exc: ValueError, origin: str) -> list[RuleObjectiveBindingIssue]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [RuleObjectiveBindingIssue(f"{origin}:<root>", str(exc))]
    return [
        RuleObjectiveBindingIssue(
            key=f"{origin}:{'.'.join(str(part) for part in error.get('loc', ())) or '<root>'}",
            message=error["msg"],
        )
        for error in errors()
    ]


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


__all__ = [
    "ApplicabilityDelta",
    "BindingState",
    "CatalogRecordPin",
    "ObjectiveRelationship",
    "RuleObjectiveBinding",
    "RuleObjectiveBindingCatalogError",
    "RuleObjectiveBindingIssue",
    "RuleObjectiveBindingMigrationReport",
    "VariantDimension",
    "build_rule_objective_binding_migration_report",
    "evidence_signature_digest",
    "load_rule_objective_binding_catalog",
    "load_rule_objective_binding_from_mapping",
    "rule_objective_binding_content_hash",
    "validate_rule_objective_binding_transition",
]
