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
from fdai.delivery.authoritative_catalog_persistence import write_catalog_snapshots_atomic
from fdai.delivery.authoritative_framework_projection import (
    _best_practice_snapshot,
    _caf_snapshot,
    _mcsb_snapshot,
    _wara_snapshot,
)
from fdai.delivery.authoritative_ontology_projection import (
    action_type_palette as _action_type_palette,
)
from fdai.delivery.authoritative_ontology_projection import (
    ontology_declaration_snapshot as _ontology_declaration_snapshot,
)
from fdai.delivery.authoritative_ontology_projection import (
    ontology_snapshot as _ontology_snapshot,
)
from fdai.delivery.authoritative_rule_projection import (
    load_collected_rules as _load_collected_rules,
)
from fdai.delivery.authoritative_rule_projection import (
    rule_snapshot as _rule_snapshot,
)
from fdai.delivery.authoritative_stewardship_projection import (
    _stewardship_snapshot,
)
from fdai.delivery.authoritative_workflow_projection import (
    _workflow_catalog,
)
from fdai.delivery.ontology_console_projection import (
    build_catalog_topology,
)
from fdai.delivery.ontology_evidence_health_projection import (
    OntologyEvidenceSourceStatus,
    build_object_type_evidence_health_projection,
)
from fdai.delivery.ontology_release_diff_projection import build_release_diff_registry
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_assessment import (
    load_framework_assessment_catalog,
)
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalog, load_mcsb_catalogs
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.probe import load_probe_catalog, probe_ids
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.rule_catalog.schema.wara_assessment import (
    load_wara_assessment_catalog,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import (
    load_wara_evaluator_bindings,
)
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyRelease,
    RequirementKind,
    Rule,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from psycopg.rows import dict_row

RULE_LIST_KEY = "operator-projection:workflow:rule.list"
BEST_PRACTICE_LIST_KEY = "operator-projection:workflow:best-practice.list"
CAF_LIST_KEY = "operator-projection:workflow:caf.list"
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
CATALOG_STATEMENT_TIMEOUT_MS = 300_000
CATALOG_CONNECT_TIMEOUT_S = 60


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
    framework_assessments = {
        framework_id: load_framework_assessment_catalog(
            catalog_root / f"framework-assessments/generated/{framework_id}.json"
        )
        for framework_id in ("azure-waf", "azure-caf")
    }
    caf_framework = next(item for item in frameworks if item.id == "azure-caf")
    wara_framework = next(item for item in frameworks if item.id == "azure-wara")
    wara_assessment, wara_queries = load_wara_assessment_catalog(
        catalog_root / "collected/wara-aprl/assessment/crosswalk.json",
        catalog_root / "collected/wara-aprl/assessment/queries.json",
        framework=wara_framework,
        framework_path=catalog_root / "collected/wara-aprl/azure-wara.json",
    )
    wara_evaluators = load_wara_evaluator_bindings(
        catalog_root / "collected/wara-aprl/assessment/evaluator-bindings.json",
        catalog=wara_assessment,
        queries=wara_queries,
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
        BEST_PRACTICE_LIST_KEY: _revisioned(
            _best_practice_snapshot(
                best_practices,
                framework_assessments["azure-waf"],
            )
        ),
        CAF_LIST_KEY: _revisioned(
            _caf_snapshot(
                caf_framework,
                framework_assessments["azure-caf"],
            )
        ),
        WARA_LIST_KEY: _revisioned(
            _wara_snapshot(wara_framework, wara_assessment, wara_evaluators)
        ),
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
    """Read the current document with a safe loader and require a mapping root."""
    source = path.read_text(encoding="utf-8")
    if hasattr(yaml, "CSafeLoader"):
        raw = yaml.load(source, Loader=yaml.CSafeLoader)
    else:
        raw = yaml.safe_load(source)
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
    """Publish one complete immutable Operator catalog generation atomically."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    snapshots = catalog_snapshots(repo_root)
    configured_scopes = (
        os.environ.get("FDAI_INVENTORY_SCOPES", "").strip()
        or os.environ.get("FDAI_AZURE_READER_SUBSCRIPTION_ID", "").strip()
    )
    if configured_scopes:
        snapshots[SCOPE_KEY] = _scope_snapshot(configured_scopes)
    releases, releases_truncated = await _retained_ontology_releases(dsn)
    snapshots[ONTOLOGY_RELEASE_DIFF_KEY] = build_release_diff_registry(
        releases=releases,
        truncated=releases_truncated,
    )
    snapshots[ONTOLOGY_EVIDENCE_HEALTH_KEY] = await _ontology_evidence_health(
        dsn,
        ontology_snapshot=snapshots[ONTOLOGY_GRAPH_KEY],
    )
    await write_catalog_snapshots_atomic(
        dsn=dsn,
        snapshots=snapshots,
        statement_timeout_ms=CATALOG_STATEMENT_TIMEOUT_MS,
        connect_timeout_s=CATALOG_CONNECT_TIMEOUT_S,
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
    resource_source, resource_unavailable_reason = _inventory_ontology_evidence_source(
        status_row=status_row,
        manifest_row=manifest_row,
        inventory_row=inventory_row,
        count_row=count_row,
        release_digest=release_digest,
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


def _inventory_ontology_evidence_source(
    *,
    status_row: Mapping[str, Any] | None,
    manifest_row: Mapping[str, Any] | None,
    inventory_row: Mapping[str, Any] | None,
    count_row: Mapping[str, Any] | None,
    release_digest: str,
) -> tuple[OntologyEvidenceSourceStatus | None, str]:
    unavailable_reason = "inventory_ontology_projection_not_bound"
    if not status_row or not manifest_row or not inventory_row or not count_row:
        return None, unavailable_reason
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
        return None, "stale_ontology_projection_release"
    if status.get("status") != "available":
        return None, "inventory_ontology_projection_unavailable"
    if inventory_row["completed_at"] is None:
        return None, "inventory_observation_cutoff_unavailable"
    generation = str(status.get("generation") or "")
    if not generation:
        return None, "inventory_generation_unavailable"
    if generation != str(inventory_row["id"]) or manifest.get("generation") != generation:
        return None, "inventory_ontology_generation_mismatch"
    return (
        OntologyEvidenceSourceStatus(
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
        ),
        unavailable_reason,
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
