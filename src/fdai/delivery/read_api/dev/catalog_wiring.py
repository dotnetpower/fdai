"""Catalog and workflow-authoring composition for the local read API."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fdai.core.tiers.t0_deterministic.opa_evaluator import MissingOpaBinaryError
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LocalCatalogWiring:
    schema_registry: PackageResourceSchemaRegistry
    object_types: tuple[Any, ...]
    link_types: tuple[Any, ...]
    action_types: tuple[Any, ...]
    rules: tuple[Any, ...]
    collected_rules: tuple[Any, ...]
    workflows: tuple[Any, ...]
    workflow_authoring: Any
    policies_root: Path
    remediation_root: Path
    findings_provider: Any
    findings_summary_provider: Any


def build_local_catalog_wiring(repo_root: Path) -> LocalCatalogWiring:
    """Load local ontology, action, rule, collected, and workflow catalogs."""
    registry = PackageResourceSchemaRegistry()
    object_types_root = repo_root / "rule-catalog" / "vocabulary" / "object-types"
    link_types_root = repo_root / "rule-catalog" / "vocabulary" / "link-types"
    action_types_root = repo_root / "rule-catalog" / "action-types"
    object_types: tuple[Any, ...] = ()
    link_types: tuple[Any, ...] = ()
    action_types: tuple[Any, ...] = ()
    if object_types_root.is_dir():
        object_types = load_object_type_catalog(object_types_root, schema_registry=registry)
        if link_types_root.is_dir():
            link_types = load_link_type_catalog(
                link_types_root,
                schema_registry=registry,
                object_types=object_types,
            )
    if action_types_root.is_dir():
        action_types = load_action_type_catalog(
            action_types_root,
            schema_registry=registry,
            probes_root=None,
        )

    policies_root = repo_root / "policies"
    remediation_root = repo_root / "rule-catalog" / "remediation"
    rules = _load_rules(
        repo_root,
        registry=registry,
        action_types=action_types,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    collected_rules = _load_collected_rules(repo_root)
    findings_provider, findings_summary_provider = _build_findings(rules, policies_root)

    workflows: tuple[Any, ...] = ()
    workflow_authoring = None
    if action_types:
        from fdai.delivery.read_api.routes.workflow_authoring import WorkflowAuthoringConfig

        rule_ids = frozenset(rule.id for rule in rules if getattr(rule, "id", None))
        workflows_root = repo_root / "rule-catalog" / "workflows"
        if workflows_root.is_dir():
            try:
                workflows = load_workflow_catalog(
                    workflows_root,
                    schema_registry=registry,
                    action_type_names={item.name for item in action_types},
                    rule_ids=set(rule_ids) if rule_ids else None,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("workflow_catalog_load_failed", exc_info=True)
        workflow_authoring = WorkflowAuthoringConfig(
            schema_registry=registry,
            action_types=action_types,
            rule_ids=rule_ids,
            workflows=workflows,
        )
    return LocalCatalogWiring(
        schema_registry=registry,
        object_types=object_types,
        link_types=link_types,
        action_types=action_types,
        rules=rules,
        collected_rules=collected_rules,
        workflows=workflows,
        workflow_authoring=workflow_authoring,
        policies_root=policies_root,
        remediation_root=remediation_root,
        findings_provider=findings_provider,
        findings_summary_provider=findings_summary_provider,
    )


def _load_rules(
    repo_root: Path,
    *,
    registry: PackageResourceSchemaRegistry,
    action_types: tuple[Any, ...],
    policies_root: Path,
    remediation_root: Path,
) -> tuple[Any, ...]:
    catalog_root = repo_root / "rule-catalog" / "catalog"
    vocabulary_file = repo_root / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    if not (catalog_root.is_dir() and action_types and vocabulary_file.is_file()):
        return ()
    try:
        resource_types = load_resource_type_registry_from_mapping(
            yaml.safe_load(vocabulary_file.read_text(encoding="utf-8"))
        )
        return load_rule_catalog(
            catalog_root,
            schema_registry=registry,
            action_types=action_types,
            resource_types=resource_types,
            policies_root=policies_root if policies_root.is_dir() else None,
            remediation_root=remediation_root if remediation_root.is_dir() else None,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning("rule_catalog_load_failed", exc_info=True)
        return ()


def _load_collected_rules(repo_root: Path) -> tuple[Any, ...]:
    collected_root = repo_root / "rule-catalog" / "collected"
    if not collected_root.is_dir():
        return ()
    collected: list[Any] = []
    for path in sorted(collected_root.rglob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(raw, Mapping):
                collected.append(Rule.model_validate(raw))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("collected_rule_skipped path=%s", path, exc_info=True)
    return tuple(collected)


def _build_findings(rules: tuple[Any, ...], policies_root: Path) -> tuple[Any, Any]:
    if not rules or not policies_root.is_dir():
        return None, None
    try:
        from fdai.delivery.read_api.routes.demo_findings import (
            build_demo_findings_provider,
            build_demo_findings_summary_provider,
        )

        rules_by_id = {rule.id: rule for rule in rules}
        return (
            build_demo_findings_provider(rules_by_id=rules_by_id, policies_root=policies_root),
            build_demo_findings_summary_provider(
                rules_by_id=rules_by_id,
                policies_root=policies_root,
            ),
        )
    except MissingOpaBinaryError:
        _LOGGER.info("demo_findings_disabled_no_opa")
        return None, None


__all__ = ["LocalCatalogWiring", "build_local_catalog_wiring"]
