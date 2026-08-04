"""Off-path indexing service for shipped catalog search documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fdai.rule_catalog.schema.catalog_search import build_catalog_search_documents
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.rego_semantics import RegoSemantics, load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.catalog_search import CatalogSearchDocument, CatalogSemanticIndex


@dataclass(frozen=True, slots=True)
class ShippedCatalogSearchSources:
    rules: tuple[Rule, ...]
    action_types: tuple[OntologyActionType, ...]
    policy_semantics: Mapping[str, RegoSemantics]


async def index_shipped_catalog(
    *,
    index: CatalogSemanticIndex,
    repo_root: Path,
    opa_binary: str = "opa",
) -> int:
    """Build grounded shipped-catalog documents and upsert the changed rows."""

    documents = load_shipped_catalog_search_documents(
        repo_root=repo_root,
        opa_binary=opa_binary,
    )
    return await index.synchronize(documents)


def load_shipped_catalog_search_documents(
    *,
    repo_root: Path,
    opa_binary: str = "opa",
) -> tuple[CatalogSearchDocument, ...]:
    """Load and cross-check shipped Rule, Rego, and ActionType artifacts."""

    sources = load_shipped_catalog_search_sources(
        repo_root=repo_root,
        opa_binary=opa_binary,
    )
    return build_catalog_search_documents(
        rules=sources.rules,
        action_types=sources.action_types,
        policy_semantics=sources.policy_semantics,
    )


def load_shipped_catalog_search_sources(
    *,
    repo_root: Path,
    opa_binary: str = "opa",
) -> ShippedCatalogSearchSources:
    """Return the validated source artifacts used by indexing and projections."""

    catalog_root = repo_root / "rule-catalog"
    policies_root = repo_root / "policies"
    remediation_root = catalog_root / "remediation"
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_types_raw = yaml.safe_load(
        (catalog_root / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(resource_types_raw, Mapping):
        raise ValueError("resource type vocabulary MUST be a mapping")
    resource_types = load_resource_type_registry_from_mapping(_string_mapping(resource_types_raw))
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    policy_semantics: dict[str, RegoSemantics] = {}
    for rule in rules:
        reference = rule.check_logic.reference
        policy_path = _policy_path(repo_root=repo_root, reference=reference)
        policy_semantics[reference] = load_rego_semantics(
            policy_path,
            opa_binary=opa_binary,
        )
    return ShippedCatalogSearchSources(
        rules=rules,
        action_types=ontology.action_types,
        policy_semantics=policy_semantics,
    )


def _policy_path(*, repo_root: Path, reference: str) -> Path:
    relative = Path(reference)
    if not reference.startswith("policies/") or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"catalog policy reference is not repository-relative: {reference!r}")
    path = repo_root / relative
    if not path.is_file():
        raise ValueError(f"catalog policy reference is unavailable: {reference!r}")
    return path


def _string_mapping(raw: Mapping[object, object]) -> Mapping[str, Any]:
    return {str(key): value for key, value in raw.items()}


__all__ = [
    "ShippedCatalogSearchSources",
    "index_shipped_catalog",
    "load_shipped_catalog_search_documents",
    "load_shipped_catalog_search_sources",
]
