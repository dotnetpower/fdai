"""Build deterministic WAF, CAF, WARA, and MCSB Operator projections."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkControlSpecification,
    FrameworkRelationshipState,
)
from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition
from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalog
from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog
from fdai.rule_catalog.schema.wara_evaluator_binding import WaraEvaluatorBindingCatalog
from fdai.shared.contracts.models import BestPractice


def _best_practice_snapshot(
    controls: Sequence[BestPractice],
    assessment: FrameworkAssessmentCatalog,
) -> dict[str, object]:
    specifications = {item.control_id: item for item in assessment.controls}
    entries = [
        _best_practice_entry(control, specifications[control.control_id])
        for control in sorted(controls, key=lambda item: item.id)
    ]
    return {
        "controls": entries,
        "evaluation_source": "repository-catalog",
        "framework_id": assessment.framework_id,
        "framework_version": assessment.framework_version,
        "catalog_digest": assessment.catalog_digest,
        "source_revision_digest": assessment.source_revision_digest,
        "framework_definition_digest": assessment.framework_definition_digest,
    }


def _best_practice_entry(
    control: BestPractice,
    specification: FrameworkControlSpecification,
) -> dict[str, object]:
    pillar = (
        control.id.split(".", 2)[1].replace("-", "_")
        if "." in control.id
        else control.category.value
    )
    requirements: list[dict[str, object]] = [
        {
            "kind": requirement.kind.value,
            "ref": requirement.ref,
            "freshness_days": requirement.freshness_days,
            "status": "unknown",
            "evidence_refs": [],
        }
        for requirement in control.requirements
    ]
    return {
        "id": control.id,
        "version": str(control.version),
        "framework": control.framework,
        "control_id": control.control_id,
        "title": control.title,
        "rationale": control.rationale,
        "severity": control.severity.value,
        "category": control.category.value,
        "pillar": pillar,
        "requirement_mode": control.requirement_mode.value,
        "requirement_count": len(requirements),
        "owner": specification.owner_slot,
        "cadence_days": specification.cadence_days,
        "catalog_status": "present",
        "mapping_status": "mapped",
        "evaluation_status": "not_evaluated",
        "applicability": "unknown",
        "satisfaction": "unknown",
        "evaluation_scope": None,
        "evaluated_at": None,
        "status": "unknown",
        "satisfied_requirement_count": 0,
        "evaluation_source": "not_connected",
        "profile_id": None,
        "profile_digest": None,
        "approved_exception": None,
        "evidence_refs": [],
        "evidence_digests": [],
        "limitations": ["not_evaluated"],
        "tradeoffs": [],
        "execution_authority": False,
        "evidence_specifications": [
            item.model_dump(mode="json") for item in specification.evidence
        ],
        "requirements": requirements,
        "provenance": control.provenance.model_dump(mode="json"),
    }


def _caf_snapshot(
    framework: FrameworkDefinition,
    assessment: FrameworkAssessmentCatalog,
) -> dict[str, object]:
    specifications = {item.control_id: item for item in assessment.controls}
    controls: list[dict[str, object]] = []
    for resolved in framework.resolved_controls():
        control = resolved.control
        specification = specifications[control.id]
        relationships = {item.relationship for item in specification.crosswalk}
        mapping_state = (
            "full"
            if FrameworkRelationshipState.FULL in relationships
            else "partial"
            if relationships - {FrameworkRelationshipState.UNMAPPED}
            else "unmapped"
        )
        controls.append(
            {
                "control_id": control.id,
                "title": control.title,
                "description": control.description,
                "area": specification.area,
                "reference_state": "present",
                "mapping_state": mapping_state,
                "applicability": "unknown",
                "evaluation_status": "not_evaluated",
                "satisfaction": "unknown",
                "owner_slot": specification.owner_slot,
                "cadence_days": specification.cadence_days,
                "evaluation_scope": None,
                "evaluated_at": None,
                "profile_id": None,
                "profile_digest": None,
                "approved_exception": None,
                "evidence_complete": False,
                "evidence_refs": [],
                "evidence_digests": [],
                "limitations": ["not_evaluated"],
                "evidence_specifications": [
                    item.model_dump(mode="json") for item in specification.evidence
                ],
                "crosswalk": [item.model_dump(mode="json") for item in specification.crosswalk],
                "source_url": resolved.source_url,
                "source_version": resolved.source_version,
                "source_revision": resolved.resolved_ref,
                "execution_authority": False,
            }
        )
    return {
        "framework_id": assessment.framework_id,
        "framework_version": assessment.framework_version,
        "catalog_digest": assessment.catalog_digest,
        "source_revision_digest": assessment.source_revision_digest,
        "framework_definition_digest": assessment.framework_definition_digest,
        "evaluation_source": "not_connected",
        "controls": sorted(controls, key=lambda item: str(item["control_id"])),
    }


def _mcsb_snapshot(catalogs: Sequence[McsbCatalog]) -> dict[str, object]:
    return {
        "catalogs": [
            _mcsb_catalog_entry(catalog)
            for catalog in sorted(catalogs, key=lambda item: item.benchmark_version)
        ],
        "evaluation_source": "catalog-crosswalk",
    }


def _wara_snapshot(
    framework: Any,
    assessment: WaraAssessmentCatalog,
    evaluator_bindings: WaraEvaluatorBindingCatalog,
) -> dict[str, object]:
    crosswalk = {item.aprl_guid: item for item in assessment.recommendations}
    controls: list[dict[str, object]] = []
    for resolved in framework.resolved_controls():
        control = resolved.control
        metadata = control.wara
        if metadata is None:
            continue
        mapping = crosswalk.get(control.id)
        query_review = mapping.query_review if mapping is not None else None
        evaluator_binding = (
            evaluator_bindings.resolve(control.id, query_review.body_digest)
            if query_review is not None
            else None
        )
        limitations = (
            ["disabled_catalog_history"]
            if metadata.state == "Disabled"
            else ["manual_evidence_required"]
            if mapping is not None and mapping.manual_evidence is not None
            else ["not_evaluated"]
            if evaluator_binding is not None
            else sorted(query_review.blocked_reasons)
            if query_review is not None
            else ["crosswalk_missing"]
        )
        manual_evidence = mapping.manual_evidence if mapping is not None else None
        controls.append(
            {
                "id": control.id,
                "title": control.title,
                "recommendation_control": metadata.control,
                "impact": metadata.impact,
                "resource_type": metadata.resource_type,
                "lifecycle": metadata.state.casefold(),
                "product_group_verified": metadata.product_group_verified,
                "automation_available": metadata.automation_available,
                "mapping_disposition": (
                    mapping.disposition.value if mapping is not None else "unmapped"
                ),
                "mapping_state": (
                    mapping.mapping_state.value if mapping is not None else "unmapped"
                ),
                "applicability": "unknown",
                "evaluation_status": "not_evaluated",
                "satisfaction": "unknown",
                "evaluation_scope": None,
                "evaluated_at": None,
                "evidence_complete": False,
                "evidence_refs": [],
                "evidence_digests": [],
                "source_url": resolved.source_url,
                "source_revision": resolved.resolved_ref,
                "source_version": resolved.source_version,
                "retrieved_at": resolved.retrieved_at,
                "source_path": metadata.source_path,
                "source_digest": metadata.source_digest,
                "source_license": assessment.source_license,
                "learn_more_name": metadata.learn_more_name,
                "learn_more_url": (
                    str(metadata.learn_more_url) if metadata.learn_more_url is not None else None
                ),
                "query_digest": metadata.query_digest,
                "evaluator_ref": (
                    evaluator_binding.evaluator_ref
                    if evaluator_binding is not None
                    else query_review.evaluator_ref
                    if query_review is not None
                    else None
                ),
                "manual_evidence": (
                    {
                        "kind": manual_evidence.kind,
                        "authoritative_producer": manual_evidence.authoritative_producer,
                        "scope_contract": manual_evidence.scope_contract,
                        "freshness_ceiling_seconds": (manual_evidence.freshness_ceiling_seconds),
                        "accountable_owner_slot": manual_evidence.accountable_owner_slot,
                        "blocked_reason": manual_evidence.blocked_reason,
                    }
                    if manual_evidence is not None
                    else None
                ),
                "workload_tags": list(metadata.tags),
                "limitations": limitations,
                "execution_authority": False,
            }
        )
    return {
        "controls": sorted(controls, key=lambda item: str(item["id"])),
        "inventory": assessment.expected_counts.model_dump(mode="json"),
        "evaluation_source": "not_connected",
        "source_revision": assessment.source_revision,
        "crosswalk_digest": assessment.crosswalk_digest,
    }


def _mcsb_catalog_entry(catalog: McsbCatalog) -> dict[str, object]:
    mappings = {mapping.control_id: mapping for mapping in catalog.mappings}
    controls: list[dict[str, object]] = []
    for control in catalog.controls:
        mapping = mappings.get(control.id)
        if mapping is None:
            raise RuntimeError(f"MCSB mapping missing for {catalog.benchmark_version}:{control.id}")
        controls.append(
            {
                "control_id": control.id,
                "title": control.title,
                "domain": control.domain,
                "coverage": mapping.coverage.value,
                "rule_count": len(mapping.rule_ids),
                "runtime_observation_count": len(mapping.runtime_observation_ids),
                "manual_evidence_count": len(mapping.manual_evidence_refs),
                "benchmark_version": catalog.benchmark_version,
                "rule_ids": list(mapping.rule_ids),
                "runtime_observation_ids": list(mapping.runtime_observation_ids),
                "manual_evidence_refs": list(mapping.manual_evidence_refs),
                "source": {
                    "source_url": catalog.source.source_url,
                    "artifact_url": catalog.source.artifact_url,
                    "resolved_ref": catalog.source.resolved_ref,
                    "content_hash": catalog.source.content_hash,
                    "license": catalog.source.license,
                    "redistribution": catalog.source.redistribution,
                    "retrieved_at": catalog.source.retrieved_at,
                },
                "evaluation_source": "catalog-crosswalk",
            }
        )
    return {
        "benchmark": {
            "benchmark_version": catalog.benchmark_version,
            "title": catalog.title,
            "status": catalog.status,
            "control_import_status": catalog.control_import_status,
            "control_count": len(controls),
            "coverage_counts": catalog.coverage_counts(),
            "policy_profiles": [
                {
                    "profile_id": profile.profile_id,
                    "policy_ref_count": profile.policy_ref_count,
                }
                for profile in catalog.policy_profiles
            ],
        },
        "controls": controls,
    }
