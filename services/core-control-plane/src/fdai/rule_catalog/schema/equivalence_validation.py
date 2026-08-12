"""Independent, non-authoritative Rule equivalence validation receipts."""

from __future__ import annotations

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


class EquivalenceValidationResult(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class EquivalenceReceiptState(StrEnum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    RETIRED = "retired"


class RuleVersionPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_ref: Annotated[str, Field(pattern=_REFERENCE_PATTERN)]
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class EquivalenceClaims(BaseModel):
    """Independent claims; sharing an objective proves none of the others."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    same_objective: Annotated[bool, Field(strict=True)]
    same_applicability: Annotated[bool, Field(strict=True)]
    same_behavior: Annotated[bool, Field(strict=True)]
    same_implementation: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def require_implementation_behavior_consistency(self) -> EquivalenceClaims:
        if self.same_implementation and not self.same_behavior:
            raise ValueError("same_implementation requires same_behavior")
        return self


class ParameterDomain(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    domain_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class CounterexampleSetPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: Annotated[str, Field(pattern=_REFERENCE_PATTERN)]
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    case_count: Annotated[int, Field(strict=True, ge=1, le=100_000)]


class ValidatorPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class EquivalenceValidationReceipt(BaseModel):
    """Frozen evidence about relations between two exact Rule versions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=_SEMVER_PATTERN)] = "1.0.0"
    id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    compared_rules: tuple[RuleVersionPin, RuleVersionPin]
    normalized_predicate_digests: tuple[
        Annotated[str, Field(pattern=_DIGEST_PATTERN)],
        Annotated[str, Field(pattern=_DIGEST_PATTERN)],
    ]
    required_evidence_refs: tuple[Annotated[str, Field(pattern=_REFERENCE_PATTERN)], ...] = Field(
        min_length=1, max_length=_MAX_ITEMS
    )
    parameter_domains: tuple[ParameterDomain, ...] = Field(max_length=_MAX_ITEMS)
    counterexamples: CounterexampleSetPin
    validator: ValidatorPin
    result: EquivalenceValidationResult
    claims: EquivalenceClaims
    failures: tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...] = Field(
        default=(), max_length=_MAX_ITEMS
    )
    reviewer: Annotated[str, Field(min_length=1, max_length=256)]
    state: EquivalenceReceiptState = EquivalenceReceiptState.CANDIDATE
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    provenance: OntologyProvenance

    @model_validator(mode="after")
    def validate_receipt(self) -> EquivalenceValidationReceipt:
        if self.compared_rules[0].rule_ref >= self.compared_rules[1].rule_ref:
            raise ValueError("compared_rules MUST contain two unique Rule refs in order")
        if self.required_evidence_refs != tuple(sorted(set(self.required_evidence_refs))):
            raise ValueError("required_evidence_refs MUST be unique and ordered")
        parameter_names = tuple(domain.name for domain in self.parameter_domains)
        if parameter_names != tuple(sorted(set(parameter_names))):
            raise ValueError("parameter_domains MUST use unique names in order")
        if self.result is not EquivalenceValidationResult.VALIDATED and not self.failures:
            raise ValueError("rejected or inconclusive validation MUST record failures")
        return self

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class EquivalenceValidationIssue:
    key: str
    message: str


class EquivalenceValidationCatalogError(ValueError):
    def __init__(self, issues: list[EquivalenceValidationIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"equivalence receipt validation failed: {preview}{suffix}")


def equivalence_validation_content_hash(receipt: EquivalenceValidationReceipt) -> str:
    return canonical_catalog_digest(receipt)


def load_equivalence_validation_from_mapping(
    raw: Mapping[str, Any],
    *,
    rule_digests: Mapping[str, str],
    origin: str = "<mapping>",
) -> EquivalenceValidationReceipt:
    """Validate one receipt, its exact Rule pins, and both content digests."""

    try:
        receipt = EquivalenceValidationReceipt.model_validate(raw)
    except ValueError as exc:
        raise EquivalenceValidationCatalogError(_pydantic_issues(exc, origin)) from exc

    issues: list[EquivalenceValidationIssue] = []
    for index, rule in enumerate(receipt.compared_rules):
        expected_rule_digest = rule_digests.get(rule.rule_ref)
        if expected_rule_digest is None:
            issues.append(
                EquivalenceValidationIssue(
                    key=f"{origin}:compared_rules[{index}].rule_ref",
                    message=f"unknown Rule version {rule.rule_ref!r}",
                )
            )
        elif rule.content_digest != expected_rule_digest:
            issues.append(
                EquivalenceValidationIssue(
                    key=f"{origin}:compared_rules[{index}].content_digest",
                    message=(
                        f"Rule digest mismatch for {rule.rule_ref!r}: "
                        f"expected {expected_rule_digest}, got {rule.content_digest}"
                    ),
                )
            )
    expected_digest = equivalence_validation_content_hash(receipt)
    if receipt.content_digest != expected_digest:
        issues.append(
            EquivalenceValidationIssue(
                key=f"{origin}:content_digest",
                message=f"content_digest mismatch: expected {expected_digest}",
            )
        )
    if receipt.provenance.content_hash != expected_digest:
        issues.append(
            EquivalenceValidationIssue(
                key=f"{origin}:provenance.content_hash",
                message=f"provenance.content_hash mismatch: expected {expected_digest}",
            )
        )
    if issues:
        raise EquivalenceValidationCatalogError(issues)
    return receipt


def load_equivalence_validation_catalog(
    root: Path,
    *,
    rule_digests: Mapping[str, str],
) -> tuple[EquivalenceValidationReceipt, ...]:
    issues: list[EquivalenceValidationIssue] = []
    loaded: list[EquivalenceValidationReceipt] = []
    seen_refs: set[str] = set()
    for path in _iter_yaml_files(root):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(EquivalenceValidationIssue(path.name, f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(EquivalenceValidationIssue(path.name, "top-level must be a mapping"))
            continue
        try:
            receipt = load_equivalence_validation_from_mapping(
                raw, rule_digests=rule_digests, origin=path.name
            )
        except EquivalenceValidationCatalogError as exc:
            issues.extend(exc.issues)
            continue
        if receipt.ref in seen_refs:
            issues.append(
                EquivalenceValidationIssue(path.name, f"duplicate receipt ref {receipt.ref!r}")
            )
            continue
        seen_refs.add(receipt.ref)
        loaded.append(receipt)
    if issues:
        raise EquivalenceValidationCatalogError(issues)
    return tuple(sorted(loaded, key=lambda receipt: receipt.ref))


def validate_equivalence_receipt_transition(
    previous: EquivalenceValidationReceipt,
    current: EquivalenceValidationReceipt,
) -> None:
    if previous.ref != current.ref:
        raise ValueError("equivalence receipt transition MUST retain the exact receipt ref")
    allowed = {
        EquivalenceReceiptState.CANDIDATE: {
            EquivalenceReceiptState.REVIEWED,
            EquivalenceReceiptState.RETIRED,
        },
        EquivalenceReceiptState.REVIEWED: {EquivalenceReceiptState.RETIRED},
        EquivalenceReceiptState.RETIRED: set(),
    }
    if current.state != previous.state and current.state not in allowed[previous.state]:
        raise ValueError(
            f"equivalence receipt state transition {previous.state.value!r} -> "
            f"{current.state.value!r} is not allowed"
        )


def _pydantic_issues(exc: ValueError, origin: str) -> list[EquivalenceValidationIssue]:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return [EquivalenceValidationIssue(f"{origin}:<root>", str(exc))]
    return [
        EquivalenceValidationIssue(
            key=f"{origin}:{'.'.join(str(part) for part in error.get('loc', ())) or '<root>'}",
            message=error["msg"],
        )
        for error in errors()
    ]


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("*.yaml"))


__all__ = [
    "CounterexampleSetPin",
    "EquivalenceClaims",
    "EquivalenceReceiptState",
    "EquivalenceValidationCatalogError",
    "EquivalenceValidationIssue",
    "EquivalenceValidationReceipt",
    "EquivalenceValidationResult",
    "ParameterDomain",
    "RuleVersionPin",
    "ValidatorPin",
    "equivalence_validation_content_hash",
    "load_equivalence_validation_catalog",
    "load_equivalence_validation_from_mapping",
    "validate_equivalence_receipt_transition",
]
