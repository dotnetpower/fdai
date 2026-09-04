#!/usr/bin/env python3
"""Materialize immutable repository catalog projections for the Operator API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import psycopg
import yaml
from fdai.agents import PANTHEON_SPECS
from fdai.core.capability_catalog.defaults import default_capability_catalog
from fdai.core.measurement.promotion_gate import (
    InMemoryShadowVerdictSource,
    PromotionGateEvaluator,
)
from fdai.core.onboarding import default_onboarding_spec
from fdai.core.ontology_explorer import render_ontology_mermaid
from fdai.core.stewardship.coverage import build_coverage_report
from fdai.core.stewardship.model import StewardshipMap
from fdai.core.stewardship.resolver import load_stewardship_from_yaml
from fdai.delivery.ontology_console_projection import (
    build_catalog_topology,
    semantic_model_profile,
)
from fdai.delivery.ontology_declaration_projection import (
    build_action_type_detail_projection,
    build_link_type_detail_projection,
    build_object_type_detail_projection,
)
from fdai.delivery.ontology_dependents_projection import (
    build_declaration_dependents_projection,
)
from fdai.delivery.ontology_evidence_health_projection import (
    OntologyEvidenceSourceStatus,
    build_object_type_evidence_health_projection,
)
from fdai.delivery.ontology_release_diff_projection import build_release_diff_registry
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalog, load_mcsb_catalogs
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.rule_catalog.schema.probe import load_probe_catalog, probe_ids
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.rule_catalog.schema.wara_assessment import (
    WaraAssessmentCatalog,
    load_wara_assessment_catalog,
)
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import (
    BestPractice,
    CeilingRole,
    OntologyRelease,
    RequirementKind,
    Rule,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from psycopg.rows import dict_row

RULE_LIST_KEY = "operator-projection:workflow:rule.list"
BEST_PRACTICE_LIST_KEY = "operator-projection:workflow:best-practice.list"
WARA_LIST_KEY = "operator-projection:workflow:wara.list"
MCSB_LIST_KEY = "operator-projection:workflow:mcsb.list"
PROMOTION_GATE_LIST_KEY = "operator-projection:workflow:promotion-gate.list"
CAPABILITY_LIST_KEY = "operator-projection:operations:capabilities"
ONBOARDING_KEY = "operator-projection:operations:onboarding"
WORKFLOW_APPS_KEY = "operator-projection:operations:process.apps"
SCOPE_KEY = "operator-projection:operations:scope.effective"
ONTOLOGY_GRAPH_KEY = "operator-projection:operations:ontology.graph"
ONTOLOGY_DECLARATION_KEYS = {
    role: f"operator-projection:operations:ontology.declaration.detail.{role.value}"
    for role in CeilingRole
}
ONTOLOGY_RELEASE_DIFF_KEY = "operator-projection:operations:ontology.release.diff"
ONTOLOGY_EVIDENCE_HEALTH_KEY = "operator-projection:operations:ontology.evidence.health"
STEWARDSHIP_KEY = "operator-projection:operations:stewardship.coverage"
ACTION_TYPE_LIST_KEY = "operator-projection:workflow:workflow.action-type-list"
WORKFLOW_CATALOG_KEY = "operator-projection:workflow:workflow.catalog"
MAX_BODY_BYTES = 512_000
CATALOG_STATEMENT_TIMEOUT_MS = 300_000
CATALOG_CONNECT_TIMEOUT_S = 60
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def catalog_snapshots(repo_root: Path) -> dict[str, dict[str, object]]:
    """Load reviewed declarations and return deterministic JSON-only projections."""
    catalog_root = repo_root / "rule-catalog"
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_type_documents = _mapping_list(
        _yaml_mapping(catalog_root / "vocabulary/resource-types.yaml").get("types"),
        field="resource-types.types",
    )
    resource_types = load_resource_type_registry_from_mapping(
        _yaml_mapping(catalog_root / "vocabulary/resource-types.yaml")
    )
    signal_types = load_signal_type_registry_from_mapping(
        _yaml_mapping(catalog_root / "vocabulary/signal-types.yaml")
    )
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policies_root=repo_root / "policies",
        remediation_root=catalog_root / "remediation",
    )
    collected_rules = _load_collected_rules(catalog_root / "collected")
    architecture_review = _yaml_mapping(repo_root / "config/architecture-review.yaml")
    best_practices = load_best_practice_catalog(
        catalog_root / "best-practices",
        known_refs=_best_practice_reference_registries(
            rules=(*rules, *collected_rules),
            catalog_root=catalog_root,
            architecture_review=architecture_review,
        ),
    )
    frameworks = load_framework_catalog(
        catalog_root / "frameworks",
        best_practices=best_practices,
        objective_refs=frozenset({"reliability.node-pool.zone-failure-tolerance@1.0.0"}),
        additional_roots=(catalog_root / "collected/wara-aprl",),
    )
    wara_framework = next(item for item in frameworks if item.id == "azure-wara")
    wara_assessment, _ = load_wara_assessment_catalog(
        catalog_root / "collected/wara-aprl/assessment/crosswalk.json",
        catalog_root / "collected/wara-aprl/assessment/queries.json",
        framework=wara_framework,
        framework_path=catalog_root / "collected/wara-aprl/azure-wara.json",
    )
    mcsb_catalogs = load_mcsb_catalogs(
        catalog_root / "compliance/mcsb",
        strict=False,
    )
    _validate_mcsb_projection_references(
        mcsb_catalogs,
        known_rule_ids={rule.id for rule in (*rules, *collected_rules)},
        known_policy_profiles=_policy_profile_counts(catalog_root / "profiles/collected"),
        known_manual_evidence_refs=_architecture_review_evidence_ids(architecture_review),
    )
    rule_documents = [
        _yaml_mapping(path) for path in sorted((catalog_root / "catalog").glob("*.yaml"))
    ]
    workflow_documents = [
        _yaml_mapping(path) for path in sorted((catalog_root / "workflows").glob("*.yaml"))
    ]
    workflows = load_workflow_catalog(
        catalog_root / "workflows",
        schema_registry=registry,
        action_type_names={action.name for action in ontology.action_types},
        rule_ids={rule.id for rule in rules},
    )
    agent_documents = [
        {
            "name": spec.name,
            "layer": spec.layer.value,
            "reports_to": spec.reports_to,
            "owns": sorted(spec.owns),
            "actions": sorted(set(spec.executes) | set(spec.initiates)),
        }
        for spec in PANTHEON_SPECS
    ]
    topology = build_catalog_topology(
        ontology=ontology,
        resource_types=resource_type_documents,
        rules=rule_documents,
        workflows=workflow_documents,
        agents=agent_documents,
    )
    snapshots = {
        RULE_LIST_KEY: _revisioned(
            _rule_snapshot(
                rules,
                collected_rules=collected_rules,
                policies_root=repo_root / "policies",
                remediation_root=catalog_root / "remediation",
            )
        ),
        BEST_PRACTICE_LIST_KEY: _revisioned(_best_practice_snapshot(best_practices)),
        WARA_LIST_KEY: _revisioned(_wara_snapshot(wara_framework, wara_assessment)),
        MCSB_LIST_KEY: _revisioned(_mcsb_snapshot(mcsb_catalogs)),
        PROMOTION_GATE_LIST_KEY: _revisioned(_promotion_gate_snapshot(ontology.action_types)),
        CAPABILITY_LIST_KEY: _revisioned(_capability_snapshot()),
        ONBOARDING_KEY: _revisioned(_onboarding_snapshot()),
        WORKFLOW_APPS_KEY: _revisioned(
            _workflow_apps_snapshot(workflows=workflows, catalog_root=catalog_root)
        ),
        ONTOLOGY_GRAPH_KEY: _revisioned(
            _ontology_snapshot(
                ontology,
                resource_types=resource_type_documents,
                rules=rule_documents,
                workflows=workflow_documents,
                agents=agent_documents,
                topology=topology,
            )
        ),
        STEWARDSHIP_KEY: _revisioned(_stewardship_snapshot(repo_root)),
        ACTION_TYPE_LIST_KEY: _revisioned(_action_type_palette(ontology.action_types)),
        WORKFLOW_CATALOG_KEY: _revisioned(_workflow_catalog(workflows, catalog_root=catalog_root)),
    }
    snapshots.update(
        {
            key: _revisioned(_ontology_declaration_snapshot(ontology, topology=topology, role=role))
            for role, key in ONTOLOGY_DECLARATION_KEYS.items()
        }
    )
    return snapshots


def _best_practice_reference_registries(
    *,
    rules: Sequence[Rule],
    catalog_root: Path,
    architecture_review: Mapping[str, Any],
) -> dict[RequirementKind, set[str]]:
    evidence_ids = _architecture_review_evidence_ids_by_kind(architecture_review)
    owner_ids = _architecture_review_owner_ids(architecture_review)
    return {
        RequirementKind.RULE: {rule.id for rule in rules},
        RequirementKind.PROBE: probe_ids(load_probe_catalog(catalog_root / "probes")),
        RequirementKind.ARTIFACT: evidence_ids[RequirementKind.ARTIFACT],
        RequirementKind.METRIC: evidence_ids[RequirementKind.METRIC],
        RequirementKind.DRILL: evidence_ids[RequirementKind.DRILL],
        RequirementKind.APPROVAL: owner_ids,
    }


def _architecture_review_evidence_ids_by_kind(
    raw: Mapping[str, Any],
) -> dict[RequirementKind, set[str]]:
    review = raw.get("architecture_review")
    if not isinstance(review, Mapping):
        raise RuntimeError("architecture_review MUST be a mapping")
    artifacts = review.get("artifacts")
    gate = review.get("production_gate")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise RuntimeError("architecture_review.artifacts MUST be a sequence")
    if not isinstance(gate, Mapping):
        raise RuntimeError("architecture_review.production_gate MUST be a mapping")
    required = gate.get("checklist_required_evidence")
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        raise RuntimeError(
            "architecture_review.production_gate.checklist_required_evidence MUST be a sequence"
        )
    evidence_kinds = gate.get("evidence_kinds")
    if not isinstance(evidence_kinds, Mapping):
        raise RuntimeError("architecture_review.production_gate.evidence_kinds MUST be a mapping")
    required_ids = {str(value) for value in required}
    if set(evidence_kinds) != required_ids:
        raise RuntimeError(
            "evidence_kinds MUST classify every checklist_required_evidence id exactly once"
        )
    by_kind = {
        RequirementKind.ARTIFACT: {
            str(artifact["id"])
            for artifact in artifacts
            if isinstance(artifact, Mapping) and isinstance(artifact.get("id"), str)
        },
        RequirementKind.METRIC: set(),
        RequirementKind.DRILL: set(),
    }
    for ref, raw_kind in evidence_kinds.items():
        kind = RequirementKind(str(raw_kind))
        if kind not in by_kind:
            raise RuntimeError(f"unsupported architecture-review evidence kind {kind.value!r}")
        by_kind[kind].add(str(ref))
    return by_kind


def _architecture_review_evidence_ids(raw: Mapping[str, Any]) -> set[str]:
    return set().union(*_architecture_review_evidence_ids_by_kind(raw).values())


def _architecture_review_owner_ids(raw: Mapping[str, Any]) -> set[str]:
    review = raw.get("architecture_review")
    if not isinstance(review, Mapping):
        raise RuntimeError("architecture_review MUST be a mapping")
    gate = review.get("production_gate")
    if not isinstance(gate, Mapping):
        raise RuntimeError("architecture_review.production_gate MUST be a mapping")
    owners = gate.get("required_owner_slots")
    if not isinstance(owners, Sequence) or isinstance(owners, (str, bytes)):
        raise RuntimeError(
            "architecture_review.production_gate.required_owner_slots MUST be a sequence"
        )
    return {str(value) for value in owners}


def _policy_profile_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(root.glob("*.yaml")):
        raw = _yaml_mapping(path)
        profile_id = raw.get("id")
        rules = raw.get("rules")
        if not isinstance(profile_id, str) or not profile_id:
            raise RuntimeError(f"policy profile id MUST be non-empty: {path}")
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
            raise RuntimeError(f"policy profile rules MUST be a sequence: {path}")
        counts[profile_id] = len(rules)
    return counts


def _validate_mcsb_projection_references(
    catalogs: Sequence[McsbCatalog],
    *,
    known_rule_ids: set[str],
    known_policy_profiles: Mapping[str, int],
    known_manual_evidence_refs: set[str],
) -> None:
    for catalog in catalogs:
        for profile in catalog.policy_profiles:
            if known_policy_profiles.get(profile.profile_id) != profile.policy_ref_count:
                raise RuntimeError(
                    "MCSB policy profile is stale: "
                    f"{catalog.benchmark_version}:{profile.profile_id}"
                )
        for mapping in catalog.mappings:
            unknown_rules = sorted(set(mapping.rule_ids) - known_rule_ids)
            unknown_evidence = sorted(
                set(mapping.manual_evidence_refs) - known_manual_evidence_refs
            )
            if unknown_rules:
                raise RuntimeError(
                    f"MCSB mapping has unknown Rule ids: {catalog.benchmark_version}:"
                    f"{mapping.control_id}:{','.join(unknown_rules)}"
                )
            if unknown_evidence:
                raise RuntimeError(
                    f"MCSB mapping has unknown evidence refs: {catalog.benchmark_version}:"
                    f"{mapping.control_id}:{','.join(unknown_evidence)}"
                )


def _best_practice_snapshot(controls: Sequence[BestPractice]) -> dict[str, object]:
    entries = [
        _best_practice_entry(control) for control in sorted(controls, key=lambda item: item.id)
    ]
    return {
        "controls": entries,
        "evaluation_source": "repository-catalog",
    }


def _best_practice_entry(control: BestPractice) -> dict[str, object]:
    pillar = (
        control.id.split(".", 2)[1].replace("-", "_")
        if "." in control.id
        else control.category.value
    )
    requirements = [
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
        "owner": None,
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
        "requirements": requirements,
        "provenance": control.provenance.model_dump(mode="json"),
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
) -> dict[str, object]:
    crosswalk = {item.aprl_guid: item for item in assessment.recommendations}
    controls: list[dict[str, object]] = []
    for resolved in framework.resolved_controls():
        control = resolved.control
        metadata = control.wara
        if metadata is None:
            continue
        mapping = crosswalk.get(control.id)
        limitations = (
            ["disabled_catalog_history"]
            if metadata.state == "Disabled"
            else ["manual_evidence_required"]
            if mapping is not None and mapping.manual_evidence is not None
            else sorted(mapping.query_review.blocked_reasons)
            if mapping is not None and mapping.query_review is not None
            else ["crosswalk_missing"]
        )
        manual_evidence = mapping.manual_evidence if mapping is not None else None
        query_review = mapping.query_review if mapping is not None else None
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
                "evaluator_ref": query_review.evaluator_ref if query_review is not None else None,
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


def _capability_snapshot() -> dict[str, object]:
    capabilities = list(default_capability_catalog().as_console_view())
    return {
        "source": "default-capability-catalog",
        "execution_eligibility": False,
        "count": len(capabilities),
        "capabilities": capabilities,
    }


def _onboarding_snapshot() -> dict[str, object]:
    spec = default_onboarding_spec()
    return {
        "probe_mode": "not-configured",
        "ready": False,
        "blocked": False,
        "missing_resources": [
            resource.kind.value for resource in spec.resources if resource.required
        ],
        "missing_role_assignments": [
            list(assignment.key) for assignment in spec.role_assignments if assignment.required
        ],
        "present_resource_count": 0,
        "present_role_count": 0,
        "error": None,
    }


def _promotion_gate_snapshot(action_types: Sequence[Any]) -> dict[str, object]:
    rows = PromotionGateEvaluator().evaluate_many(
        action_types,
        InMemoryShadowVerdictSource(),
    )
    return {
        "window_days": None,
        "rows": [row.as_json() for row in rows],
        "ready_count": sum(row.ready for row in rows),
        "blocked_count": sum(not row.ready for row in rows),
    }


def _workflow_apps_snapshot(
    *,
    workflows: Sequence[Any],
    catalog_root: Path,
) -> dict[str, object]:
    workflow_names = {workflow.name for workflow in workflows}
    items: list[dict[str, object]] = []
    for order, path in enumerate(sorted((catalog_root / "views").glob("*.yaml")), start=1):
        raw = _yaml_mapping(path)
        applies_to = raw.get("applies_to")
        workflow_ref = applies_to.get("workflow_ref") if isinstance(applies_to, Mapping) else None
        view_id = raw.get("id")
        if not isinstance(view_id, str) or not view_id:
            raise RuntimeError(f"workflow view id MUST be non-empty: {path}")
        if not isinstance(workflow_ref, str) or workflow_ref not in workflow_names:
            raise RuntimeError(f"workflow view references an unknown workflow: {path}")
        name = raw.get("name")
        description = raw.get("description")
        if not isinstance(name, str) or not name:
            raise RuntimeError(f"workflow view name MUST be non-empty: {path}")
        if not isinstance(description, str) or not description:
            raise RuntimeError(f"workflow view description MUST be non-empty: {path}")
        items.append(
            {
                "id": view_id,
                "workflow_ref": workflow_ref,
                "view_ref": view_id,
                "lifecycle": "published",
                "audience": "reader",
                "label": {"en": name, "ko": name},
                "description": {"en": description, "ko": description},
                "route": f"/workflow-apps/{view_id}",
                "group": "operations",
                "order": order,
            }
        )
    return {"items": items, "count": len(items)}


def _rule_snapshot(
    active_rules: Sequence[Rule],
    *,
    collected_rules: Sequence[Rule],
    policies_root: Path,
    remediation_root: Path,
) -> dict[str, object]:
    entries = [
        *((rule, "active") for rule in active_rules),
        *((rule, "collected") for rule in collected_rules),
    ]
    ordered = sorted(
        entries,
        key=lambda entry: (
            -_SEVERITY_RANK.get(entry[0].severity.value, 0),
            entry[0].id,
            entry[1],
        ),
    )
    summaries = [_rule_summary(rule, origin=origin) for rule, origin in ordered]
    details = {
        f"{origin}:{rule.id}": _rule_detail(
            rule,
            origin=origin,
            policies_root=policies_root,
            remediation_root=remediation_root,
        )
        for rule, origin in sorted(entries, key=lambda entry: (entry[1], entry[0].id))
    }
    return {"rules": summaries, "details": details}


def _load_collected_rules(root: Path) -> tuple[Rule, ...]:
    """Load the inert reference corpus without applying active-catalog cross-references."""
    loaded: list[Rule] = []
    for path in sorted(root.rglob("*.yaml")):
        try:
            loaded.append(Rule.model_validate(_yaml_mapping(path)))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise RuntimeError(f"invalid collected Rule document: {path}") from exc
    return tuple(loaded)


def _rule_summary(rule: Rule, *, origin: str) -> dict[str, object]:
    provenance = rule.provenance
    return {
        "id": rule.id,
        "origin": origin,
        "version": str(rule.version),
        "source": rule.source.value,
        "severity": rule.severity.value,
        "category": rule.category.value,
        "resource_type": rule.resource_type,
        "check_logic": rule.check_logic.model_dump(mode="json"),
        "remediation": rule.remediation.model_dump(mode="json"),
        "remediates": rule.remediates,
        "provenance": {
            "source_url": provenance.source_url,
            "license": provenance.license,
            "redistribution": provenance.redistribution.value,
        },
    }


def _rule_detail(
    rule: Rule,
    *,
    origin: str,
    policies_root: Path,
    remediation_root: Path,
) -> dict[str, object]:
    check_logic_body = _read_reference(
        policies_root,
        rule.check_logic.reference,
        prefix="policies/",
    )
    detail = _rule_summary(rule, origin=origin)
    detail.update(
        {
            "schema_version": str(rule.schema_version),
            "alternatives": list(rule.alternatives),
            "parameters": dict(rule.parameters),
            "applies_to": {"resource_types": list(rule.applies_to)},
            "check_logic_body": check_logic_body,
            "remediation_body": _read_reference(
                remediation_root,
                rule.remediation.template_ref,
                prefix="remediation/",
            ),
            "explanation": _rule_explanation(rule, check_logic_body),
            "provenance": rule.provenance.model_dump(mode="json"),
        }
    )
    return detail


def _rule_explanation(rule: Rule, check_logic_body: str | None) -> dict[str, object]:
    metadata = _rego_metadata(check_logic_body) if check_logic_body else None
    if metadata and (metadata.get("title") or metadata.get("description")):
        return {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "source": "rego_metadata",
            "details": {},
        }
    parameters = rule.parameters
    if "azure_policy_display_name" in parameters:
        return {
            "title": parameters.get("azure_policy_display_name"),
            "description": None,
            "source": "azure_policy",
            "details": {
                key: parameters[key]
                for key in ("azure_policy_effect_default", "azure_policy_category")
                if parameters.get(key) is not None
            },
        }
    if "kube_bench_id" in parameters:
        return {
            "title": (
                f"CIS {parameters.get('kube_bench_ruleset', '')} "
                f"{parameters.get('kube_bench_id', '')}"
            ).strip(),
            "description": None,
            "source": "kube_bench",
            "details": {
                key: parameters[key]
                for key in ("kube_bench_audit", "kube_bench_scored")
                if parameters.get(key) is not None
            },
        }
    return {"title": None, "description": None, "source": None, "details": {}}


def _rego_metadata(body: str) -> Mapping[str, Any] | None:
    lines = body.splitlines()
    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if line.strip() in {"# METADATA", "#METADATA"}
        )
    except StopIteration:
        return None
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            break
        content = stripped[1:]
        collected.append(content[1:] if content.startswith(" ") else content)
    if not collected:
        return None
    try:
        parsed = yaml.safe_load("\n".join(collected))
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _read_reference(root: Path, reference: str, *, prefix: str) -> str | None:
    if not reference.startswith(prefix):
        return None
    relative = Path(reference.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        return None
    try:
        with candidate.open("rb") as stream:
            raw = stream.read(MAX_BODY_BYTES + 1)
    except OSError:
        return None
    truncated = len(raw) > MAX_BODY_BYTES
    body = raw[:MAX_BODY_BYTES].decode("utf-8", errors="replace")
    return body + "\n... [truncated]" if truncated else body


def _ontology_snapshot(
    ontology: OntologyCatalog,
    *,
    resource_types: Sequence[Mapping[str, object]],
    rules: Sequence[Mapping[str, object]],
    workflows: Sequence[Mapping[str, object]],
    agents: Sequence[Mapping[str, object]],
    topology: Mapping[str, object],
) -> dict[str, object]:
    object_types = sorted(ontology.object_types, key=lambda item: item.name)
    interface_types = sorted(ontology.interface_types, key=lambda item: item.name)
    link_types = sorted(ontology.link_types, key=lambda item: item.name)
    action_types = sorted(ontology.action_types, key=lambda item: item.name)
    function_types = sorted(ontology.function_types, key=lambda item: item.name)
    release = ontology.build_release()
    rendered = render_ontology_mermaid(object_types, link_types)
    return {
        "schema_version": "2.0.0",
        "ontology_release_digest": release.digest,
        "mutation_authority": False,
        "complete": True,
        "limitations": {
            "source_coverage": [],
            "query_truncation": [],
            "access_redaction": [],
            "presentation_omission": [],
        },
        "semantic_model": semantic_model_profile(ontology),
        "catalog_topology": topology,
        "mermaid": rendered.mermaid,
        "object_type_count": len(object_types),
        "interface_type_count": len(interface_types),
        "link_type_count": len(link_types),
        "action_type_count": len(action_types),
        "function_type_count": len(function_types),
        "object_types": [item.name for item in object_types],
        "interface_types": [
            item.model_dump(mode="json", exclude_none=True) for item in interface_types
        ],
        "link_types": [item.name for item in link_types],
        "action_types": [item.model_dump(mode="json", exclude_none=True) for item in action_types],
        "function_types": [
            item.model_dump(mode="json", exclude_none=True) for item in function_types
        ],
        "nodes": [
            {
                "name": item.name,
                "key": item.key,
                "property_count": len(item.properties),
                "properties": sorted(item.properties),
                "description": item.description,
                "lifecycle": (
                    item.lifecycle.model_dump(mode="json", exclude_none=True)
                    if item.lifecycle is not None
                    else None
                ),
            }
            for item in object_types
        ],
        "edges": [
            {
                "name": item.name,
                "from_type": item.from_type,
                "to_type": item.to_type,
                "cardinality": item.cardinality.value,
                "is_transitive": item.is_transitive,
                "is_causal": item.is_causal,
                "temporal_order": item.temporal_order,
                "forward_role": item.forward_role,
                "reverse_role": item.reverse_role,
                "semantic_traits": [trait.value for trait in item.semantic_traits],
                "description": item.description,
            }
            for item in link_types
        ],
    }


def _ontology_declaration_snapshot(
    ontology: OntologyCatalog,
    *,
    topology: Mapping[str, object],
    role: CeilingRole,
) -> dict[str, object]:
    """Build one purpose-bound detail bundle for an ordinary Operator role."""

    purpose = "operations-review"
    release_digest = ontology.build_release().digest
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "role": role.value,
        "purpose": purpose,
        "mutation_authority": False,
        "details": {
            "object-types": {
                object_type.name: build_object_type_detail_projection(
                    ontology=ontology,
                    name=object_type.name,
                    role=role,
                    purpose=purpose,
                    expected_release_digest=release_digest,
                )
                for object_type in sorted(ontology.object_types, key=lambda item: item.name)
            },
            "link-types": {
                link_type.name: build_link_type_detail_projection(
                    ontology=ontology,
                    name=link_type.name,
                    expected_release_digest=release_digest,
                )
                for link_type in sorted(ontology.link_types, key=lambda item: item.name)
            },
            "action-types": {
                action_type.name: build_action_type_detail_projection(
                    ontology=ontology,
                    name=action_type.name,
                    expected_release_digest=release_digest,
                )
                for action_type in sorted(ontology.action_types, key=lambda item: item.name)
            },
        },
        "dependents": {
            "object-types": {
                object_type.name: build_declaration_dependents_projection(
                    topology=topology,
                    declaration_kind="object-types",
                    declaration_name=object_type.name,
                )
                for object_type in sorted(ontology.object_types, key=lambda item: item.name)
            }
        },
    }


def _action_type_palette(action_types: Sequence[Any]) -> dict[str, object]:
    """Project reviewed ActionType declarations into the builder palette."""
    entries = [
        {
            "name": action.name,
            "operation": str(action.operation),
            "category": None if action.category is None else str(action.category),
            "rollback_contract": str(action.rollback_contract),
            "irreversible": action.irreversible,
            "default_mode": str(action.default_mode),
            "execution_path": None if action.execution_path is None else str(action.execution_path),
            "env_scope": str(action.env_scope),
            "hil_tiers": _hil_tiers(action),
            "description": action.description,
        }
        for action in sorted(action_types, key=lambda item: item.name)
    ]
    return {"action_types": entries, "count": len(entries)}


def _hil_tiers(action: Any) -> list[str]:
    ceilings = action.ceiling_by_tier
    if ceilings is None:
        return []
    return [
        tier
        for tier in ("T0", "T1", "T2")
        if _ceiling_requires_hil(getattr(ceilings, tier.lower(), None))
    ]


def _ceiling_requires_hil(ceiling: Any) -> bool:
    return ceiling is not None and str(ceiling.max_autonomy) == "enforce_hil"


def _workflow_catalog(workflows: Sequence[Any], *, catalog_root: Path) -> dict[str, object]:
    """Project reviewed workflow declarations with their reviewed YAML source."""
    entries = [
        _workflow_entry(workflow, catalog_root=catalog_root)
        for workflow in sorted(workflows, key=lambda item: item.name)
    ]
    return {"workflows": entries, "count": len(entries)}


def _workflow_entry(workflow: Any, *, catalog_root: Path) -> dict[str, object]:
    source = catalog_root / "workflows" / f"{workflow.name}.yaml"
    gate = workflow.promotion_gate
    entry: dict[str, object] = {
        "schema_version": str(workflow.schema_version),
        "name": workflow.name,
        "version": str(workflow.version),
        "trigger": _workflow_trigger(workflow.trigger),
        "default_mode": str(workflow.default_mode),
        "promotion_gate": {
            "min_shadow_days": gate.min_shadow_days,
            "min_samples": gate.min_samples,
            "min_accuracy": gate.min_accuracy,
            "max_policy_escapes": gate.max_policy_escapes,
        },
        "steps": [_workflow_step(step) for step in workflow.steps],
        "step_count": len(workflow.steps),
        "yaml": source.read_text(encoding="utf-8") if source.is_file() else "",
    }
    if workflow.description is not None:
        entry["description"] = workflow.description
    anti_scope = getattr(workflow, "anti_scope", None)
    if anti_scope is not None:
        entry["anti_scope"] = anti_scope
    return entry


def _workflow_trigger(trigger: Any) -> dict[str, object]:
    projected: dict[str, object] = {"kind": str(trigger.kind)}
    signal_type = getattr(trigger, "signal_type", None)
    if signal_type is not None:
        projected["signal_type"] = str(signal_type)
    schedule = getattr(trigger, "schedule", None)
    if schedule is not None:
        projected["schedule"] = str(schedule)
    return projected


def _workflow_step(step: Any) -> dict[str, object]:
    projected: dict[str, object] = {"id": step.id}
    # A structured step (for example ``parallel``) carries branches, not an ActionType.
    action_type_ref = getattr(step, "action_type_ref", None)
    if action_type_ref is not None:
        projected["action_type_ref"] = str(action_type_ref)
    kind = getattr(step, "kind", None)
    if kind is not None:
        projected["kind"] = str(kind)
    branches = getattr(step, "branches", None)
    if branches:
        projected["branches"] = [str(branch) for branch in branches]
    outcomes = getattr(step, "outcomes", None)
    if outcomes:
        projected["outcomes"] = [str(outcome) for outcome in outcomes]
    for field in (
        "guard_rule_ref",
        "gate_ref",
        "compensated_by",
        "on_failure",
        "wait_for",
        "timeout_seconds",
        "approval_role",
    ):
        value = getattr(step, field, None)
        if value is not None:
            projected[field] = str(value)
    if kind is not None and str(kind) == "approval":
        projected["timeout_seconds"] = step.timeout_seconds
        projected["quorum"] = step.quorum
        projected["no_self_approval"] = step.no_self_approval
    elif kind is not None and str(kind) == "wait":
        projected["timeout_seconds"] = step.timeout_seconds
    params = getattr(step, "params", None)
    if params:
        projected["params"] = {key: params[key] for key in sorted(params)}
    return projected


def _stewardship_snapshot(repo_root: Path) -> dict[str, object]:
    """Project the reviewed stewardship declaration and its computed coverage."""
    stewardship = load_stewardship_from_yaml(repo_root / "config" / "agent-stewardship.yaml")
    report = build_coverage_report(stewardship)
    return {
        "map": _stewardship_map(stewardship),
        "coverage": {
            "is_clean": report.is_clean,
            "total_agents": report.total_agents,
            "autonomous_agents": report.autonomous_agents,
            "maintainer_count": report.maintainer_count,
            "findings": [
                {
                    "code": finding.code,
                    "severity": str(finding.severity),
                    "message": finding.message,
                    "agent": finding.agent,
                }
                for finding in report.findings
            ],
        },
        # No identity directory is bound here, so no directory health is claimed.
        # `finding_count` stays absent: an explicit null is not a measured count.
        "identity_health": {"status": "not_configured", "checked_at": None},
    }


def _stewardship_map(stewardship: StewardshipMap) -> dict[str, object]:
    maintainers = list(stewardship.maintainer_oids)
    return {
        "version": stewardship.version,
        "maintainers": maintainers,
        "maintainer_count": len(maintainers),
        "hop_timeout_seconds": stewardship.hop_timeout_seconds,
        "over_assigned_max": stewardship.over_assigned_max,
        "agents": [_stewardship_agent(stewardship, spec.name) for spec in PANTHEON_SPECS],
    }


def _stewardship_agent(stewardship: StewardshipMap, name: str) -> dict[str, object]:
    agent = stewardship.agent(name)
    return {
        "name": name,
        "autonomous": agent.is_autonomous,
        "accept_autonomous_reason": agent.accept_autonomous_reason,
        "bus_factor": len({(subject.kind, subject.id) for subject in agent.accountable}),
        "stewards": [
            {
                "kind": str(subject.kind),
                "id": subject.id,
                "responsibility": str(subject.responsibility),
                "duty": None if subject.duty is None else str(subject.duty),
            }
            for subject in agent.stewards
        ],
    }


def _revisioned(payload: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {"_revision": "sha256:" + hashlib.sha256(encoded).hexdigest(), **payload}


def _yaml_mapping(path: Path) -> Mapping[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise RuntimeError(f"catalog document MUST be a mapping: {path}")
    return raw


def _mapping_list(value: object, *, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise RuntimeError(f"{field} MUST be a list of mappings")
    return value


def _scope_snapshot(configured_scopes: str) -> dict[str, object]:
    entries = [_scope_entry(value) for value in configured_scopes.split(",") if value.strip()]
    return {
        "monitoring": {"axis": "monitoring", "entries": entries},
        "action": {"axis": "action", "entries": []},
        "executor_boundary": {
            "resource_groups": [],
            "note": "Execution scope is governed separately from inventory observation scope.",
        },
    }


def _scope_entry(value: str) -> dict[str, object]:
    address = value.strip()
    segments = [segment for segment in address.split("/") if segment]
    lowered = [segment.lower() for segment in segments]
    if "subscriptions" in lowered:
        subscription_index = lowered.index("subscriptions")
        if subscription_index + 1 >= len(segments):
            raise RuntimeError("configured inventory scope has no subscription identity")
        subscription = segments[subscription_index + 1]
    else:
        subscription = address
    resource_group: str | None = None
    if "resourcegroups" in lowered:
        resource_group_index = lowered.index("resourcegroups")
        if resource_group_index + 1 >= len(segments):
            raise RuntimeError("configured inventory scope has no resource-group identity")
        resource_group = segments[resource_group_index + 1]
    return {
        "address": address,
        "level": "resource_group" if resource_group is not None else "subscription",
        "subscription": subscription,
        "resource_group": resource_group,
        "state": "included",
    }


async def materialize(repo_root: Path) -> None:
    """Write both immutable snapshots to their Operator projection keys."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    store = PostgresStateStore(
        config=PostgresStateStoreConfig(
            dsn=dsn,
            statement_timeout_ms=CATALOG_STATEMENT_TIMEOUT_MS,
            connect_timeout_s=CATALOG_CONNECT_TIMEOUT_S,
        )
    )
    snapshots = catalog_snapshots(repo_root)
    for key, payload in snapshots.items():
        await store.write_state(key, payload)
    configured_scopes = (
        os.environ.get("FDAI_INVENTORY_SCOPES", "").strip()
        or os.environ.get("FDAI_AZURE_READER_SUBSCRIPTION_ID", "").strip()
    )
    if configured_scopes:
        await store.write_state(SCOPE_KEY, _scope_snapshot(configured_scopes))
    releases, releases_truncated = await _retained_ontology_releases(dsn)
    await store.write_state(
        ONTOLOGY_RELEASE_DIFF_KEY,
        build_release_diff_registry(
            releases=releases,
            truncated=releases_truncated,
        ),
    )
    await store.write_state(
        ONTOLOGY_EVIDENCE_HEALTH_KEY,
        await _ontology_evidence_health(
            dsn,
            ontology_snapshot=snapshots[ONTOLOGY_GRAPH_KEY],
        ),
    )


async def _retained_ontology_releases(
    dsn: str,
) -> tuple[tuple[OntologyRelease, ...], bool]:
    """Read a bounded chronological release window through the Core-owned DSN."""

    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as connection:
        cursor = await connection.execute(
            "SELECT manifest FROM ontology_release ORDER BY created_at DESC, digest DESC LIMIT 17"
        )
        rows = await cursor.fetchall()
    truncated = len(rows) > 16
    selected = reversed(rows[:16])
    return (
        tuple(OntologyRelease.model_validate(row["manifest"]) for row in selected),
        truncated,
    )


async def _ontology_evidence_health(
    dsn: str,
    *,
    ontology_snapshot: Mapping[str, object],
) -> dict[str, object]:
    """Read sanitized inventory projection health without returning instance payloads."""

    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as connection:
        status_cursor = await connection.execute(
            "SELECT value, updated_at FROM state_kv WHERE key='inventory-ontology:status'"
        )
        manifest_cursor = await connection.execute(
            "SELECT value FROM state_kv WHERE key='inventory-ontology:manifest'"
        )
        inventory_cursor = await connection.execute(
            "SELECT snapshot.id, snapshot.observation_kind, snapshot.completed_at "
            "FROM inventory_active AS active "
            "JOIN inventory_snapshot AS snapshot ON snapshot.id=active.snapshot_id "
            "WHERE active.singleton=TRUE"
        )
        count_cursor = await connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM ontology_resource WHERE object_type='Resource') "
            "AS object_count, "
            "(SELECT COUNT(DISTINCT link.id) FROM ontology_link AS link "
            "JOIN ontology_resource AS source ON source.id=link.from_id "
            "JOIN ontology_resource AS target ON target.id=link.to_id "
            "WHERE source.object_type='Resource' OR target.object_type='Resource') "
            "AS link_count"
        )
        status_row = await status_cursor.fetchone()
        manifest_row = await manifest_cursor.fetchone()
        inventory_row = await inventory_cursor.fetchone()
        count_row = await count_cursor.fetchone()

    release_digest = str(ontology_snapshot["ontology_release_digest"])
    object_types = _runtime_string_sequence(
        ontology_snapshot["object_types"],
        field="ontology object_types",
    )
    resource_source: OntologyEvidenceSourceStatus | None = None
    resource_unavailable_reason = "inventory_ontology_projection_not_bound"
    if status_row and manifest_row and inventory_row and count_row:
        status = _runtime_mapping(status_row["value"], field="inventory ontology status")
        manifest = _runtime_mapping(
            manifest_row["value"],
            field="inventory ontology manifest",
        )
        dropped = _runtime_string_sequence(
            manifest.get("dropped_reasons", ()),
            field="inventory ontology dropped_reasons",
        )
        if status.get("ontology_release_digest") != release_digest:
            resource_unavailable_reason = "stale_ontology_projection_release"
        elif status.get("status") != "available":
            resource_unavailable_reason = "inventory_ontology_projection_unavailable"
        elif inventory_row["completed_at"] is None:
            resource_unavailable_reason = "inventory_observation_cutoff_unavailable"
        else:
            generation = str(status.get("generation") or "")
            if not generation:
                resource_unavailable_reason = "inventory_generation_unavailable"
            else:
                resource_source = OntologyEvidenceSourceStatus(
                    source_kind="provider_observation",
                    source_identity_alias="inventory-projection",
                    generation=generation,
                    ontology_release_digest=release_digest,
                    observed_at=inventory_row["completed_at"],
                    recorded_at=status_row["updated_at"],
                    freshness_ceiling_seconds=None,
                    complete=manifest.get("complete") is True and not dropped,
                    truncated=any("truncat" in reason for reason in dropped),
                    synthetic=inventory_row["observation_kind"] != "observed",
                    conflicts=tuple(reason for reason in dropped if "conflict" in reason),
                    drop_reasons=dropped,
                    visible_instance_count=int(count_row["object_count"]),
                    visible_link_count=int(count_row["link_count"]),
                    evidence_refs=(
                        f"inventory-ontology:manifest@{generation}",
                        f"inventory-snapshot:{inventory_row['id']}",
                    ),
                )
    now = datetime.now(UTC)
    health = {
        name: build_object_type_evidence_health_projection(
            object_type=name,
            ontology_release_digest=release_digest,
            now=now,
            source=resource_source if name == "Resource" else None,
            unavailable_reason=(
                resource_unavailable_reason
                if name == "Resource"
                else "object_type_evidence_source_not_bound"
            ),
        )
        for name in object_types
    }
    return _revisioned(
        {
            "schema_version": "1.0.0",
            "ontology_release_digest": release_digest,
            "mutation_authority": False,
            "evidence_health": health,
        }
    )


def _runtime_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field} MUST be a mapping")
    return value


def _runtime_string_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RuntimeError(f"{field} MUST be a sequence")
    if any(not isinstance(item, str) or not item for item in value):
        raise RuntimeError(f"{field} values MUST be non-empty strings")
    return cast(tuple[str, ...], tuple(value))


def main() -> int:
    """Materialize repository catalogs without emitting deployment values."""
    repo_root = Path(__file__).resolve().parents[3]
    asyncio.run(materialize(repo_root))
    print("authoritative Rule, control, and ontology catalog projections refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
