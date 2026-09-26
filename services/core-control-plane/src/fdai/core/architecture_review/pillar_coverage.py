"""Read-only definition accounting for the pinned WAF architecture-review pillars."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkCrosswalkKind,
    FrameworkRelationshipState,
    canonical_digest,
    load_framework_assessment_catalog,
)
from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition
from fdai.shared.contracts.models import BestPractice

_PILLAR_COUNTS = {
    "reliability": (10, 39),
    "security": (12, 51),
    "cost-optimization": (14, 32),
    "operational-excellence": (11, 32),
    "performance-efficiency": (12, 32),
}
_EXPECTED_CONTROL_COUNT = 59
_EXPECTED_EVIDENCE_COUNT = 186


@dataclass(frozen=True, slots=True)
class PillarDefinitionCoverage:
    """Identities of catalog definitions, not observed workload outcomes."""

    pillar: str
    control_ids: tuple[str, ...]
    evidence_keys: tuple[tuple[str, str], ...]

    @property
    def control_count(self) -> int:
        return len(self.control_ids)

    @property
    def evidence_count(self) -> int:
        return len(self.evidence_keys)


@dataclass(frozen=True, slots=True)
class PillarCoverageReport:
    """Complete five-pillar definition inventory pinned to the reviewed catalog."""

    catalog_digest: str
    framework_definition_digest: str
    pillars: tuple[PillarDefinitionCoverage, ...]

    @property
    def control_count(self) -> int:
        return sum(pillar.control_count for pillar in self.pillars)

    @property
    def evidence_count(self) -> int:
        return sum(pillar.evidence_count for pillar in self.pillars)


def load_pillar_definition_coverage(repo_root: Path) -> PillarCoverageReport:
    """Load the generated WAF inventory; reject drift from its pinned source definition."""

    catalog_root = repo_root / "rule-catalog"
    framework_path = catalog_root / "frameworks/azure-waf.yaml"
    catalog = load_framework_assessment_catalog(
        catalog_root / "framework-assessments/generated/azure-waf.json"
    )
    framework = FrameworkDefinition.model_validate(
        yaml.safe_load(framework_path.read_text(encoding="utf-8"))
    )
    framework_digest = f"sha256:{hashlib.sha256(framework_path.read_bytes()).hexdigest()}"
    source_revision_digest = canonical_digest(
        sorted({item.resolved_ref for item in framework.resolved_controls()})
    )
    if (
        catalog.framework_definition_digest != framework_digest
        or catalog.source_revision_digest != source_revision_digest
        or catalog.framework_version != framework.version
    ):
        raise ValueError("WAF assessment catalog identity differs from pinned framework source")
    practices = load_best_practice_catalog(catalog_root / "best-practices", strict=False)
    return assess_pillar_definition_coverage(catalog, framework=framework, practices=practices)


def assess_pillar_definition_coverage(
    catalog: FrameworkAssessmentCatalog,
    *,
    framework: FrameworkDefinition,
    practices: tuple[BestPractice, ...],
) -> PillarCoverageReport:
    """Account for every control and typed evidence definition, without evaluating evidence."""

    if (
        catalog.framework_id != "azure-waf"
        or framework.id != catalog.framework_id
        or framework.version != catalog.framework_version
        or framework.scope != catalog.framework_scope.value
        or catalog.expected_control_count != _EXPECTED_CONTROL_COUNT
    ):
        raise ValueError("pinned WAF assessment identity or control count mismatch")

    source_controls = {item.control.id: item for item in framework.resolved_controls()}
    source_practices = {
        item.control_id: item for item in practices if item.framework == catalog.framework_id
    }
    catalog_controls = {item.control_id: item for item in catalog.controls}
    if (
        len(source_controls) != _EXPECTED_CONTROL_COUNT
        or len(source_practices) != _EXPECTED_CONTROL_COUNT
        or len(catalog.controls) != _EXPECTED_CONTROL_COUNT
        or len(catalog_controls) != _EXPECTED_CONTROL_COUNT
        or source_controls.keys() != source_practices.keys()
        or source_controls.keys() != catalog_controls.keys()
    ):
        raise ValueError("WAF controls must be complete and uniquely defined in every catalog")
    if set(_PILLAR_COUNTS) != {area.id for area in framework.areas}:
        raise ValueError("WAF framework has a missing or unsupported pillar")

    evidence_total = 0
    coverage: list[PillarDefinitionCoverage] = []
    for pillar, (control_count, evidence_count) in _PILLAR_COUNTS.items():
        controls = [item for item in catalog.controls if item.area == pillar]
        source_ids = {
            control_id for control_id, item in source_controls.items() if item.area == pillar
        }
        if len(controls) != control_count or {item.control_id for item in controls} != source_ids:
            raise ValueError(f"{pillar}: missing, misplaced, or unsupported control definitions")
        keys: list[tuple[str, str]] = []
        for control in controls:
            source = source_controls[control.control_id]
            practice = source_practices[control.control_id]
            practice_ref = f"{practice.id}@{practice.version}"
            if (
                source.control.best_practice_ref != practice_ref
                or not practice.id.startswith(f"azure-waf.{pillar}.")
                or practice.title != control.title
                or source.control.title != control.title
                or control.requirement_mode != practice.requirement_mode.value
                or practice.provenance.source_url != source.source_url
                or practice.provenance.source_version != source.source_version
                or practice.provenance.resolved_ref != source.resolved_ref
            ):
                raise ValueError(f"{control.control_id}: ambiguous or stale WAF control definition")

            expected_evidence = {
                (requirement.kind.value, requirement.ref) for requirement in practice.requirements
            }
            requirements = {
                (requirement.kind.value, requirement.ref): requirement
                for requirement in practice.requirements
            }
            actual_evidence = {(item.kind.value, item.source_ref) for item in control.evidence}
            requirement_ids = {item.requirement_id for item in control.evidence}
            owner_slots = sorted(
                requirement.ref
                for requirement in practice.requirements
                if requirement.kind.value == "approval"
            )
            if (
                not owner_slots
                or control.owner_slot != owner_slots[0]
                or len(control.evidence) != len(expected_evidence)
                or actual_evidence != expected_evidence
                or len(requirement_ids) != len(control.evidence)
                or any(
                    item.requirement_id != f"{item.kind.value}:{item.source_ref}"
                    or item.scope_contract != "exact-workload"
                    or not item.completeness_required
                    or item.failure_behavior != "unknown"
                    or item.owner_slot
                    != (item.source_ref if item.kind.value == "approval" else control.owner_slot)
                    or (
                        (days := requirements[(item.kind.value, item.source_ref)].freshness_days)
                        is not None
                        and item.freshness_ceiling_seconds != days * 86_400
                    )
                    for item in control.evidence
                )
            ):
                raise ValueError(f"{control.control_id}: missing or ambiguous evidence definitions")

            expected_crosswalk = {
                (
                    FrameworkCrosswalkKind.BEST_PRACTICE,
                    practice_ref,
                    FrameworkRelationshipState.FULL,
                ),
                *(
                    (
                        FrameworkCrosswalkKind.RULE
                        if requirement.kind.value == "rule"
                        else FrameworkCrosswalkKind.MANUAL_EVIDENCE,
                        requirement.ref,
                        FrameworkRelationshipState.PARTIAL,
                    )
                    for requirement in practice.requirements
                ),
                *(
                    (
                        FrameworkCrosswalkKind.CONTROL_OBJECTIVE,
                        ref,
                        FrameworkRelationshipState.PARTIAL,
                    )
                    for ref in source.control.objective_refs
                ),
            }
            actual_crosswalk = {
                (item.target_kind, item.target_ref, item.relationship) for item in control.crosswalk
            }
            if actual_crosswalk != expected_crosswalk or len(control.crosswalk) != len(
                expected_crosswalk
            ):
                raise ValueError(f"{control.control_id}: ambiguous WAF crosswalk definitions")
            keys.extend((control.control_id, item.requirement_id) for item in control.evidence)

        if len(keys) != evidence_count or len(set(keys)) != len(keys):
            raise ValueError(f"{pillar}: evidence definition accounting mismatch")
        evidence_total += len(keys)
        coverage.append(
            PillarDefinitionCoverage(
                pillar=pillar,
                control_ids=tuple(sorted(source_ids)),
                evidence_keys=tuple(sorted(keys)),
            )
        )
    if evidence_total != _EXPECTED_EVIDENCE_COUNT:
        raise ValueError("WAF evidence definition count differs from the pinned 186")
    return PillarCoverageReport(
        catalog_digest=catalog.catalog_digest,
        framework_definition_digest=catalog.framework_definition_digest,
        pillars=tuple(coverage),
    )


__all__ = [
    "PillarCoverageReport",
    "PillarDefinitionCoverage",
    "assess_pillar_definition_coverage",
    "load_pillar_definition_coverage",
]
