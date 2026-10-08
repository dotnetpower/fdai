"""Strict loader for the code-security catalog under ``rule-catalog/code-security/``.

The catalog holds four versioned data files and the remediation-pack templates:

- ``weakness-classes.yaml`` - CWE grouping, impact range, and fix strategy per weakness class;
- ``severity-rubric.yaml`` - the deterministic fact table that derives severity bands;
- ``priority-policy.yaml`` - the first-match rules that order remediation work;
- ``remediation-policy.yaml`` - pack limits and the diff-guard patterns;
- ``remediation-pack/`` - the conversational prompt and coding-agent adapters.

Loading fails closed. Unknown keys, unknown enum values, a CWE id claimed by two classes, an
invalid regular expression, or a missing template raise :class:`CodeSecurityCatalogError`. The
catalog grants no authority; it only parameterizes deterministic evaluation.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_CLASS_ID = r"^[a-z][a-z0-9_]{2,63}$"
_RULE_ID = r"^[a-z][a-z0-9-]{2,63}$"
_MAX_TEMPLATE_BYTES = 64_000
PACK_TEMPLATE_FILES = (
    "REMEDIATE.prompt.md",
    "README.md",
    "adapters/copilot.prompt.md",
    "adapters/claude-command.md",
    "adapters/AGENTS.snippet.md",
)


class CodeSecurityCatalogError(ValueError):
    """Raised when the code-security catalog is missing, malformed, or inconsistent."""


class SeverityBand(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


BAND_ORDER: dict[SeverityBand, int] = {
    SeverityBand.LOW: 1,
    SeverityBand.MEDIUM: 2,
    SeverityBand.HIGH: 3,
    SeverityBand.CRITICAL: 4,
}


class Impact(StrEnum):
    CODE_EXECUTION = "code_execution"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DATA_WRITE = "data_write"
    DATA_READ = "data_read"
    DENIAL_OF_SERVICE = "denial_of_service"
    INFO_DISCLOSURE = "info_disclosure"
    LIMITED = "limited"


class AttackVector(StrEnum):
    NETWORK = "network"
    ADJACENT = "adjacent"
    LOCAL = "local"
    PHYSICAL = "physical"


class AttackComplexity(StrEnum):
    """Conditions beyond the attacker's control, aligned with the CVSS AC concept."""

    LOW = "low"
    HIGH = "high"


class PrivilegesRequired(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class UserInteraction(StrEnum):
    NONE = "none"
    REQUIRED = "required"


class FixClass(StrEnum):
    DEPENDENCY_BUMP = "dependency_bump"
    LOCAL_CODE_FIX = "local_code_fix"
    CONFIG_CHANGE = "config_change"
    SECRET_REMOVAL = "secret_removal"  # noqa: S105 - fix class id, not a credential
    DESIGN_CHANGE = "design_change"


class AutofixEligibility(StrEnum):
    AUTO = "auto"
    ASSISTED = "assisted"
    MANUAL = "manual"


class RemediationDepth(StrEnum):
    D0 = "D0"
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"
    PLAN_ONLY = "plan_only"


class Confidence(StrEnum):
    """Detection-evidence strength, weakest first in :data:`CONFIDENCE_ORDER`."""

    HYPOTHESIS = "hypothesis"
    REPORTED = "reported"
    CORROBORATED = "corroborated"
    VERIFIED = "verified"
    PROVEN = "proven"


CONFIDENCE_ORDER: dict[Confidence, int] = {
    Confidence.HYPOTHESIS: 1,
    Confidence.REPORTED: 2,
    Confidence.CORROBORATED: 3,
    Confidence.VERIFIED: 4,
    Confidence.PROVEN: 5,
}


class Exposure(StrEnum):
    EXPOSED = "exposed"
    INTERNAL = "internal"
    NOT_DEPLOYED = "not_deployed"
    UNKNOWN = "unknown"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WeaknessClass(_Strict):
    title: Annotated[str, Field(min_length=3, max_length=120)]
    cwe: Annotated[tuple[int, ...], Field(min_length=1)]
    impact_range: Annotated[tuple[Impact, ...], Field(min_length=1)]
    fix_class: FixClass
    autofix_eligibility: AutofixEligibility
    max_depth: RemediationDepth
    guidance: Annotated[str, Field(min_length=10, max_length=600)]

    @model_validator(mode="after")
    def _manual_is_plan_only(self) -> WeaknessClass:
        manual = self.autofix_eligibility is AutofixEligibility.MANUAL
        if manual != (self.max_depth is RemediationDepth.PLAN_ONLY):
            raise ValueError("manual eligibility and plan_only depth must be declared together")
        return self


class WeaknessClassCatalog(_Strict):
    schema_version: Literal[1]
    catalog_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    classes: dict[Annotated[str, Field(pattern=_CLASS_ID)], WeaknessClass]

    @model_validator(mode="after")
    def _unique_cwe_owner(self) -> WeaknessClassCatalog:
        owners: dict[int, str] = {}
        for class_id, entry in self.classes.items():
            for cwe in entry.cwe:
                if cwe in owners:
                    raise ValueError(f"CWE-{cwe} is listed by both {owners[cwe]} and {class_id}")
                owners[cwe] = class_id
        return self

    def class_for_cwe(self, cwe: int) -> str | None:
        """Return the class id that lists ``cwe`` exactly, or ``None``."""
        for class_id, entry in self.classes.items():
            if cwe in entry.cwe:
                return class_id
        return None


class BandThreshold(_Strict):
    band: SeverityBand
    min_points: Annotated[float, Field(gt=0, le=10)]


class ScoreThreshold(_Strict):
    band: SeverityBand
    min_score: Annotated[float, Field(gt=0, le=10)]


class SeverityRubric(_Strict):
    schema_version: Literal[1]
    rubric_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    bands: Annotated[tuple[BandThreshold, ...], Field(min_length=4, max_length=4)]
    advisory_score_bands: Annotated[tuple[ScoreThreshold, ...], Field(min_length=4, max_length=4)]
    impact_points: dict[Impact, Annotated[float, Field(ge=0, le=10)]]
    attack_vector_penalty: dict[AttackVector, Annotated[float, Field(ge=0, le=10)]]
    attack_complexity_penalty: dict[AttackComplexity, Annotated[float, Field(ge=0, le=10)]]
    privileges_required_penalty: dict[PrivilegesRequired, Annotated[float, Field(ge=0, le=10)]]
    user_interaction_penalty: dict[UserInteraction, Annotated[float, Field(ge=0, le=10)]]

    @model_validator(mode="after")
    def _complete_and_descending(self) -> SeverityRubric:
        for name, table, enum in (
            ("impact_points", self.impact_points, Impact),
            ("attack_vector_penalty", self.attack_vector_penalty, AttackVector),
            ("attack_complexity_penalty", self.attack_complexity_penalty, AttackComplexity),
            ("privileges_required_penalty", self.privileges_required_penalty, PrivilegesRequired),
            ("user_interaction_penalty", self.user_interaction_penalty, UserInteraction),
        ):
            if set(table) != set(enum):
                raise ValueError(f"{name} must define every value of {enum.__name__}")
        for thresholds in (
            [t.min_points for t in self.bands],
            [t.min_score for t in self.advisory_score_bands],
        ):
            if thresholds != sorted(thresholds, reverse=True) or len(set(thresholds)) != 4:
                raise ValueError("band thresholds must be strictly descending")
        expected = [SeverityBand.CRITICAL, SeverityBand.HIGH, SeverityBand.MEDIUM, SeverityBand.LOW]
        if [t.band for t in self.bands] != expected:
            raise ValueError("bands must be ordered critical, high, medium, low")
        if [t.band for t in self.advisory_score_bands] != expected:
            raise ValueError("advisory_score_bands must be ordered critical, high, medium, low")
        return self


class PriorityCondition(_Strict):
    kev: bool | None = None
    exposure_in: tuple[Exposure, ...] | None = None
    floor_at_least: SeverityBand | None = None
    ceiling_at_least: SeverityBand | None = None
    confidence_at_least: Confidence | None = None


class PriorityRule(_Strict):
    id: Annotated[str, Field(pattern=_RULE_ID)]
    when: PriorityCondition
    priority: Priority
    due_days: Annotated[int, Field(ge=1, le=365)]


class PriorityDefault(_Strict):
    priority: Priority
    due_days: Annotated[int, Field(ge=1, le=365)]


class PriorityPolicy(_Strict):
    schema_version: Literal[1]
    policy_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    rules: Annotated[tuple[PriorityRule, ...], Field(min_length=1, max_length=64)]
    default: PriorityDefault

    @model_validator(mode="after")
    def _unique_ids(self) -> PriorityPolicy:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("priority rule ids must be unique")
        return self


class PackLimits(_Strict):
    max_issues: Annotated[int, Field(ge=1, le=500)]
    max_groups: Annotated[int, Field(ge=1, le=200)]
    expiry_days: Annotated[int, Field(ge=1, le=90)]
    max_groups_per_session: Annotated[int, Field(ge=1, le=50)]
    max_fix_attempts: Annotated[int, Field(ge=0, le=5)]
    max_diff_bytes: Annotated[int, Field(ge=1_000, le=50_000_000)]


class ForbiddenPath(_Strict):
    id: Annotated[str, Field(pattern=_RULE_ID)]
    globs: Annotated[tuple[str, ...], Field(min_length=1)]
    description: Annotated[str, Field(min_length=3, max_length=200)]


class ForbiddenPattern(_Strict):
    id: Annotated[str, Field(pattern=_RULE_ID)]
    pattern: Annotated[str, Field(min_length=2, max_length=600)]
    description: Annotated[str, Field(min_length=3, max_length=200)]

    @model_validator(mode="after")
    def _compiles(self) -> ForbiddenPattern:
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"pattern {self.id} does not compile: {exc}") from exc
        return self


class RemediationPolicy(_Strict):
    schema_version: Literal[1]
    policy_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    limits: PackLimits
    test_path_globs: Annotated[tuple[str, ...], Field(min_length=1)]
    forbidden_paths: tuple[ForbiddenPath, ...]
    forbidden_added_patterns: tuple[ForbiddenPattern, ...]
    test_assertion_patterns: Annotated[tuple[str, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _assertions_compile(self) -> RemediationPolicy:
        for pattern in self.test_assertion_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"test assertion pattern does not compile: {exc}") from exc
        return self

    def guard_document(self) -> dict[str, object]:
        """Return the JSON-ready policy consumed by the stdlib pack helper and server guard."""
        return self.model_dump(mode="json")


class CodeSecurityCatalog(_Strict):
    weakness_classes: WeaknessClassCatalog
    severity_rubric: SeverityRubric
    priority_policy: PriorityPolicy
    remediation_policy: RemediationPolicy
    pack_templates: dict[str, str]

    def version_stamp(self) -> dict[str, str]:
        """Return the catalog versions recorded in every pack manifest."""
        return {
            "weakness_classes": self.weakness_classes.version,
            "severity_rubric": self.severity_rubric.version,
            "priority_policy": self.priority_policy.version,
            "remediation_policy": self.remediation_policy.version,
        }


def _load_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodeSecurityCatalogError(f"missing code-security catalog file: {path.name}") from exc
    except yaml.YAMLError as exc:
        raise CodeSecurityCatalogError(f"invalid YAML in {path.name}: {exc}") from exc


def _load_templates(root: Path) -> dict[str, str]:
    templates: dict[str, str] = {}
    for relative in PACK_TEMPLATE_FILES:
        path = root / "remediation-pack" / relative
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise CodeSecurityCatalogError(f"missing pack template: {relative}") from exc
        if len(data) > _MAX_TEMPLATE_BYTES:
            raise CodeSecurityCatalogError(f"pack template too large: {relative}")
        templates[relative] = data.decode("utf-8")
    return templates


def load_code_security_catalog(root: Path) -> CodeSecurityCatalog:
    """Load and validate the code-security catalog rooted at ``root``.

    ``root`` is the ``rule-catalog/code-security`` directory. Raises
    :class:`CodeSecurityCatalogError` on any missing file or validation failure.
    """
    try:
        return CodeSecurityCatalog(
            weakness_classes=WeaknessClassCatalog.model_validate(
                _load_yaml(root / "weakness-classes.yaml")
            ),
            severity_rubric=SeverityRubric.model_validate(
                _load_yaml(root / "severity-rubric.yaml")
            ),
            priority_policy=PriorityPolicy.model_validate(
                _load_yaml(root / "priority-policy.yaml")
            ),
            remediation_policy=RemediationPolicy.model_validate(
                _load_yaml(root / "remediation-policy.yaml")
            ),
            pack_templates=_load_templates(root),
        )
    except ValidationError as exc:
        raise CodeSecurityCatalogError(f"invalid code-security catalog: {exc}") from exc
