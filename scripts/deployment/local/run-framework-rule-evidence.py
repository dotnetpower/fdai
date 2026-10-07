#!/usr/bin/env python3
"""Run the WAF Rule evidence path against the local active inventory, read-only.

The local development ontology usually has no deployment-owned ``Workload``, so this script binds
one estate scope to every resource of the active complete inventory generation. It reads Forseti's
latest version 2 baseline, its outcomes, and the current Rule activation from the local state
store, builds ``t0-rule-evaluator`` receipts and the scoped coverage record, and assesses the WAF
catalog in process. Nothing is written to PostgreSQL: the record is persisted to an in-memory store
only to prove it round-trips. The output contains counts and digests, never resource identifiers.

``--re-evaluate`` reruns Forseti's bounded baseline worker in memory over the same active inventory
with the repository Rule definitions that the current activation pins and the local ``opa`` binary,
so the repository's baseline semantics are measured without waiting for a Core restart. It also
replays the Azure normalized Rule property projection over each stored raw row, which approximates
a fresh collection without calling Azure: columns the stored row dropped, such as a null
``identity`` or ``zones``, stay unobserved.

``--candidate-activation`` (with ``--re-evaluate``) measures a pending catalog change: it builds an
in-memory activation generation from the repository revisions of the current activation's member
Rules. The candidate is never installed and has its own generation digest.

Usage: ``FDAI_STATE_STORE_DSN`` must point at the loopback development database.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import yaml
from fdai.agents import ForsetiBaselineWorker
from fdai.core.framework_assessment import (
    FrameworkAssessmentRequest,
    FrameworkAssessmentRuntime,
)
from fdai.core.rule_activation.generation import build_rule_activation_generation, rule_digest
from fdai.core.rule_activation.ledger import StateStoreRuleActivationLedger
from fdai.core.tiers.t0_deterministic import RuleGenerationSnapshot, RuleIndex, T0Engine
from fdai.core.tiers.t0_deterministic.opa_evaluator import OpaRegoEvaluator
from fdai.delivery.azure.arm_rule_properties import rule_properties
from fdai.delivery.framework_assessment_cli import _profile, _waf_scope_digest
from fdai.delivery.framework_rule_evidence_source import (
    load_workload_rule_evidence,
    persist_scoped_rule_coverage,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_promoted_inventory_reader import (
    PostgresPromotedInventoryGenerationReader,
)
from fdai.delivery.persistence.postgres_wara_scope import WaraResolvedResource, WaraResolvedScope
from fdai.rule_catalog.schema.framework_assessment import load_framework_assessment_catalog
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory import PromotedInventoryGeneration
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.framework_rule_coverage import (
    FRAMEWORK_RULE_COVERAGE_LATEST_KEY,
    ScopedRuleCoverageRecord,
)
from fdai_service_contracts.rule_activation import RuleActivationGeneration

_ROOT = Path(__file__).resolve().parents[3]
_WAF = _ROOT / "rule-catalog/framework-assessments/generated/azure-waf.json"
_FRESHNESS = timedelta(days=1)
_MAX_RESOURCES = 10_000
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


async def _active_scope(dsn: str, now: datetime) -> WaraResolvedScope:
    async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=10) as connection:
        await connection.set_read_only(True)
        cursor = await connection.execute(
            "SELECT s.id, s.status, s.completed_at FROM inventory_active a "
            "JOIN inventory_snapshot s ON s.id=a.snapshot_id WHERE a.singleton=TRUE"
        )
        snapshot = await cursor.fetchone()
        if snapshot is None or snapshot[1] != "active" or snapshot[2] is None:
            raise SystemExit("no complete active inventory generation")
        if snapshot[2] + _FRESHNESS < now:
            raise SystemExit("active inventory generation is older than one day")
        cursor = await connection.execute(
            "SELECT resource_id, resource_type, provider_ref FROM inventory_snapshot_resource "
            "WHERE snapshot_id=%s ORDER BY resource_id LIMIT %s",
            (snapshot[0], _MAX_RESOURCES + 1),
        )
        rows = await cursor.fetchall()
    if not rows or len(rows) > _MAX_RESOURCES:
        raise SystemExit("active inventory generation is empty or over the resource bound")
    return WaraResolvedScope(
        workload_id="local-active-inventory-estate",
        ontology_release="local-development",
        inventory_generation=str(snapshot[0]),
        resources=tuple(
            WaraResolvedResource(
                neutral_resource_id=str(resource_id),
                provider_resource_id=str(provider_ref or resource_id),
                provider_resource_type=str(resource_type),
            )
            for resource_id, resource_type, provider_ref in rows
        ),
    )


def _activated_rules(
    activation: RuleActivationGeneration, *, candidate: bool = False
) -> tuple[Rule, ...]:
    """Load the repository Rules the activation pins; stop when any member digest differs.

    With ``candidate`` the repository revision of each member is returned even when it differs.
    """

    catalog_root = _ROOT / "rule-catalog"
    registry = PackageResourceSchemaRegistry()

    def mapping(path: Path) -> dict[str, object]:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise SystemExit(f"{path.name} is not a mapping")
        return loaded

    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=load_ontology_catalog(
            catalog_root, schema_registry=registry, probes_root=catalog_root / "probes"
        ).action_types,
        resource_types=load_resource_type_registry_from_mapping(
            mapping(catalog_root / "vocabulary/resource-types.yaml")
        ),
        signal_types=load_signal_type_registry_from_mapping(
            mapping(catalog_root / "vocabulary/signal-types.yaml")
        ),
        policies_root=_ROOT / "policies",
        remediation_root=catalog_root / "remediation",
    )
    by_id = {rule.id: rule for rule in rules}
    selected: list[Rule] = []
    for member in activation.members:
        rule = by_id.get(member.rule_id)
        if rule is None or (not candidate and rule_digest(rule) != member.rule_digest):
            raise SystemExit("repository Rule catalog differs from the active activation")
        selected.append(rule)
    return tuple(selected)


class _ProjectedReader:
    """Read the active generation and add the normalized Rule properties to each stored row."""

    def __init__(self, inner: PostgresPromotedInventoryGenerationReader) -> None:
        self._inner = inner
        self.projected_resources = 0

    async def active_generation_id(self) -> str | None:
        return await self._inner.active_generation_id()

    async def load_active_generation(
        self, *, max_resources: int
    ) -> PromotedInventoryGeneration | None:
        generation = await self._inner.load_active_generation(max_resources=max_resources)
        if generation is None:
            return None
        resources = []
        for resource in generation.resources:
            normalized = {
                key: value
                for key, value in rule_properties(resource.type, resource.props).items()
                if key not in resource.props
            }
            self.projected_resources += bool(normalized)
            resources.append(dataclasses.replace(resource, props={**resource.props, **normalized}))
        return dataclasses.replace(generation, resources=tuple(resources))


async def _re_evaluated_store(
    dsn: str,
    activation: RuleActivationGeneration,
    now: datetime,
) -> InMemoryStateStore:
    rules = _activated_rules(activation)
    engine = T0Engine(
        index=RuleIndex.build(rules),
        evaluator=OpaRegoEvaluator(policies_root=_ROOT / "policies"),
    )
    memory = InMemoryStateStore()
    reader = _ProjectedReader(
        PostgresPromotedInventoryGenerationReader(
            config=PostgresInventorySnapshotStoreConfig(dsn=dsn)
        )
    )

    async def activation_source() -> RuleActivationGeneration:
        return activation

    async def snapshot_source() -> RuleGenerationSnapshot:
        return RuleGenerationSnapshot(
            engine=engine, rules=rules, generation_digest=activation.generation_digest
        )

    result = await ForsetiBaselineWorker(
        state_store=memory,
        reader=reader,
        activation_source=activation_source,
        rule_snapshot_source=snapshot_source,
        owner="local-framework-rule-evidence",
        clock=lambda: now,
    ).run_once()
    print(
        f"re-evaluation: {result}; resources with replayed properties: "
        f"{reader.projected_resources}",
        file=sys.stderr,
    )
    return memory


async def run(dsn: str, *, re_evaluate: bool = False, candidate: bool = False) -> dict[str, object]:
    now = datetime.now(tz=UTC)
    scope = await _active_scope(dsn, now)
    catalog = load_framework_assessment_catalog(_WAF)
    postgres = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    activation = await StateStoreRuleActivationLedger(store=postgres).current_generation()
    store: StateStore = postgres
    changed_members = 0
    if re_evaluate:
        if activation is None:
            raise SystemExit("no current Rule activation")
        if candidate:
            installed = {member.rule_id: member.rule_digest for member in activation.members}
            rules = _activated_rules(activation, candidate=True)
            changed_members = sum(rule_digest(rule) != installed[rule.id] for rule in rules)
            activation = build_rule_activation_generation(
                rules,
                profile_id=activation.profile_id,
                profile_version=activation.profile_version,
                created_at=now,
            )
        store = await _re_evaluated_store(dsn, activation, now)
    scope_digest = _waf_scope_digest(scope)
    evidence = await load_workload_rule_evidence(
        state_store=store,
        activation=activation,
        scope=scope,
        catalog=catalog,
        profile_scope_digest=scope_digest,
        evaluated_at=now,
        source_identity="forseti-baseline-evaluation",
    )
    report: dict[str, object] = {
        "baseline_source": "re_evaluated_in_memory" if re_evaluate else "local_state_store",
        "activation_source": "candidate_in_memory" if candidate else "installed",
        "candidate_changed_members": changed_members,
        "mode": "shadow",
        "execution_authority": False,
        "inventory_generation": scope.inventory_generation,
        "workload_resource_count": len(scope.resources),
        "rule_evidence_status": evidence.status.value,
        "rule_receipt_count": len(evidence.receipts),
    }
    if evidence.coverage_record is None or evidence.pin is None:
        return report
    profile = _profile(
        catalog,
        scope_digest=scope_digest,
        ontology_release=scope.ontology_release,
        reviewer_identity="local-development-reviewer",
        reviewed_at=now,
        inventory_generation=scope.inventory_generation,
        rule_activation=evidence.pin,
    )
    result = FrameworkAssessmentRuntime(catalog).assess(
        FrameworkAssessmentRequest(
            assessment_id="framework-assessment:waf:local-rule-evidence",
            profile=profile,
            evaluated_at=now,
            recorded_at=now,
            evidence=evidence.receipts,
        )
    )
    memory = InMemoryStateStore()
    await persist_scoped_rule_coverage(memory, evidence.coverage_record)
    stored = await memory.read_state(FRAMEWORK_RULE_COVERAGE_LATEST_KEY)
    roundtrip = stored is not None and (
        ScopedRuleCoverageRecord.model_validate(stored) == evidence.coverage_record
    )
    rule_controls = {
        control.control_id
        for control in catalog.controls
        if any(item.kind.value == "rule" for item in control.evidence)
    }
    rule_requirement_results = [
        requirement
        for control in result.controls
        if control.control_id in rule_controls
        for requirement in control.requirements
        if requirement.requirement_id.startswith("rule:")
    ]
    record = evidence.coverage_record
    report.update(
        {
            "rule_activation_generation_id": evidence.pin.generation_id,
            "receipt_outcomes": dict(Counter(item.outcome.value for item in evidence.receipts)),
            "receipt_limitations": dict(
                Counter(code for item in evidence.receipts for code in item.limitations)
            ),
            "rule_controls": len(rule_controls),
            "rule_requirement_results": dict(
                Counter(item.status.value for item in rule_requirement_results)
            ),
            "rule_control_satisfaction": dict(
                Counter(
                    control.satisfaction.value
                    for control in result.controls
                    if control.control_id in rule_controls
                )
            ),
            "coverage_record_digest": record.record_digest,
            "coverage_rule_count": len(record.rules),
            "coverage_eligible_pairs": sum(item.eligible_count for item in record.rules),
            "coverage_violated_pairs": sum(item.violated_count for item in record.rules),
            "coverage_compliant_pairs": sum(item.compliant_count for item in record.rules),
            "coverage_held_pairs": sum(item.abstained_count for item in record.rules),
            "coverage_record_roundtrip": roundtrip,
            "waf_result_digest": result.result_digest,
        }
    )
    return report


def main() -> int:
    dsn = (
        os.environ.get("FDAI_STATE_STORE_DSN", "")
        .strip()
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )
    if not dsn:
        print("FDAI_STATE_STORE_DSN is required", file=sys.stderr)
        return 2
    if urlparse(dsn).hostname not in _LOCAL_HOSTS:
        print("this local evidence run accepts only a loopback database", file=sys.stderr)
        return 2
    flags = set(sys.argv[1:])
    if "--candidate-activation" in flags and "--re-evaluate" not in flags:
        print("--candidate-activation requires --re-evaluate", file=sys.stderr)
        return 2
    report = asyncio.run(
        run(
            dsn,
            re_evaluate="--re-evaluate" in flags,
            candidate="--candidate-activation" in flags,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
