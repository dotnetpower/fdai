"""Supply WARA Rule evidence from Forseti's verified baseline through reviewed exact bindings."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml
from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.core.framework_rule_evidence.wara import build_wara_rule_receipts
from fdai.core.wara import WaraAssessmentRequest
from fdai.delivery.framework_rule_evidence_source import (
    WorkloadRuleEvidenceStatus,
    load_scoped_rule_coverage,
)
from fdai.delivery.persistence.postgres_wara_scope import WaraResolvedScope
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog, WaraQueryCatalog
from fdai.rule_catalog.schema.wara_rule_binding import (
    WaraRuleBindingCatalog,
    load_wara_rule_bindings,
)
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.state_store import StateStore

WARA_FRAMEWORK_ID = "azure-wara"


def load_release_wara_rule_bindings(
    repo_root: Path,
    *,
    catalog: WaraAssessmentCatalog,
    queries: WaraQueryCatalog,
) -> WaraRuleBindingCatalog:
    """Load the reviewed overlay and validate it against the release's Rule catalog."""

    return load_wara_rule_bindings(
        repo_root / "rule-catalog/collected/wara-aprl/assessment/rule-bindings.json",
        catalog=catalog,
        queries=queries,
        rules=_release_rules(repo_root),
    )


async def with_wara_rule_evidence(
    request: WaraAssessmentRequest,
    *,
    state_store: StateStore,
    activation: RuleActivationGeneration | None,
    scope: WaraResolvedScope,
    catalog: WaraAssessmentCatalog,
    bindings: WaraRuleBindingCatalog,
) -> tuple[WaraAssessmentRequest, WorkloadRuleEvidenceStatus]:
    """Return ``request`` pinned to the Rule overlay, with decisive Rule receipts added.

    Without a verified baseline for this exact scope the request keeps its other evidence, so
    every Rule-bound recommendation stays ``unknown``.
    """

    pinned = replace(request, rule_bindings_digest=bindings.overlay_digest)
    loaded = await load_scoped_rule_coverage(
        state_store=state_store,
        activation=activation,
        scope=scope,
        framework_id=WARA_FRAMEWORK_ID,
        scope_digest=pinned.scope_digest,
        evaluated_at=pinned.evaluated_at,
    )
    if loaded.scoped is None or activation is None:
        return pinned, loaded.status
    receipts = build_wara_rule_receipts(
        bindings=bindings,
        catalog=catalog,
        coverage=loaded.scoped,
        activation=activation,
        scope_digest=pinned.scope_digest,
    )
    # Coverage is recorded at the assessment time, so it stays inside the request cutoff.
    admissible = tuple(
        item
        for item in receipts
        if item.observed_at <= pinned.evaluated_at and item.recorded_at <= pinned.recorded_at
    )
    return replace(pinned, evidence=(*pinned.evidence, *admissible)), loaded.status


def _release_rules(repo_root: Path) -> tuple[Rule, ...]:
    catalog_root = repo_root / "rule-catalog"
    registry = PackageResourceSchemaRegistry()

    def mapping(path: Path) -> dict[str, object]:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{path.name} MUST be a mapping")
        return loaded

    return load_rule_catalog(
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
        policies_root=repo_root / "policies",
        remediation_root=catalog_root / "remediation",
    )


__all__ = [
    "WARA_FRAMEWORK_ID",
    "load_release_wara_rule_bindings",
    "with_wara_rule_evidence",
]
