"""Off-path indexing service for shipped catalog search documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from fdai.rule_catalog.schema.catalog_search import (
    build_catalog_search_documents,
    catalog_search_document_digest,
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.rego_semantics import RegoSemantics, load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.rule_semantic_generation import CatalogSearchGeneration
from fdai.rule_catalog.schema.rule_semantic_manifest import build_rego_semantic_manifest
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleCorpus,
    RuleSemanticManifest,
    RuleSemanticSurface,
)
from fdai.rule_catalog.schema.rule_semantic_surface_catalog import (
    load_promoted_semantic_surfaces,
)
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    CatalogSemanticIndex,
)


@dataclass(frozen=True, slots=True)
class ShippedCatalogReferenceSources:
    """Validated Rule references loaded without OPA or embedding I/O."""

    rules: tuple[Rule, ...]
    action_types: tuple[OntologyActionType, ...]
    ontology_release_digest: str


@dataclass(frozen=True, slots=True)
class ShippedCatalogSearchSources:
    rules: tuple[Rule, ...]
    action_types: tuple[OntologyActionType, ...]
    policy_semantics: Mapping[str, RegoSemantics]
    semantic_manifests: Mapping[str, RuleSemanticManifest]
    semantic_surfaces: Mapping[str, tuple[RuleSemanticSurface, ...]]


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
        semantic_manifests=sources.semantic_manifests,
        semantic_surfaces=sources.semantic_surfaces,
    )


def load_shipped_catalog_reference_sources(*, repo_root: Path) -> ShippedCatalogReferenceSources:
    """Load strict catalog references without parsing policies through OPA."""

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
    release = build_ontology_release(
        object_types=ontology.object_types,
        link_types=ontology.link_types,
        action_types=ontology.action_types,
    )
    return ShippedCatalogReferenceSources(
        rules=rules,
        action_types=ontology.action_types,
        ontology_release_digest=release.digest,
    )


def load_shipped_catalog_search_sources(
    *,
    repo_root: Path,
    opa_binary: str = "opa",
) -> ShippedCatalogSearchSources:
    """Return the validated source artifacts used by indexing and projections."""

    references = load_shipped_catalog_reference_sources(repo_root=repo_root)
    policy_semantics: dict[str, RegoSemantics] = {}
    for rule in references.rules:
        reference = rule.check_logic.reference
        policy_path = _policy_path(repo_root=repo_root, reference=reference)
        policy_semantics[reference] = load_rego_semantics(
            policy_path,
            opa_binary=opa_binary,
        )
    semantic_manifests = {
        rule.id: build_rego_semantic_manifest(
            rule,
            policy_semantics[rule.check_logic.reference],
            ontology_release_digest=references.ontology_release_digest,
        )
        for rule in references.rules
    }
    loaded_surfaces = load_promoted_semantic_surfaces(
        repo_root / "rule-catalog" / "semantic-surfaces",
        manifests=semantic_manifests,
    )
    rule_id_by_manifest = {item.digest: rule_id for rule_id, item in semantic_manifests.items()}
    surfaces_by_rule: dict[str, list[RuleSemanticSurface]] = {}
    for surface in loaded_surfaces:
        rule_id = rule_id_by_manifest[surface.manifest_digest]
        surfaces_by_rule.setdefault(rule_id, []).append(surface)
    return ShippedCatalogSearchSources(
        rules=references.rules,
        action_types=references.action_types,
        policy_semantics=policy_semantics,
        semantic_manifests=semantic_manifests,
        semantic_surfaces={
            rule_id: tuple(sorted(items, key=lambda item: item.surface_id))
            for rule_id, items in surfaces_by_rule.items()
        },
    )


async def publish_shipped_catalog_generation(
    *,
    index: CatalogSemanticIndex,
    repo_root: Path,
    validation_receipt_digest: str,
    embedding_space_id: str,
    embedding_model_version: str,
    embedding_dimension: int,
    activated_at: datetime,
    opa_binary: str = "opa",
) -> CatalogGenerationMetadata:
    """Build, stage, and atomically activate one validated active generation."""

    sources = load_shipped_catalog_search_sources(repo_root=repo_root, opa_binary=opa_binary)
    documents = build_catalog_search_documents(
        rules=sources.rules,
        action_types=sources.action_types,
        policy_semantics=sources.policy_semantics,
        semantic_manifests=sources.semantic_manifests,
        semantic_surfaces=sources.semantic_surfaces,
    )
    catalog_digest = rule_reference_catalog_digest(sources.rules)
    document_digests = tuple(sorted(catalog_search_document_digest(item) for item in documents))
    ontology_release_digests = {
        item.ontology_release_digest for item in sources.semantic_manifests.values()
    }
    if len(ontology_release_digests) != 1:
        raise ValueError("shipped semantic manifests MUST use one ontology release")
    generation_id = f"catalog-search:active:{catalog_digest[7:31]}"
    generation = CatalogSearchGeneration(
        generation_id=generation_id,
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=catalog_digest,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=next(iter(ontology_release_digests)),
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        document_digests=document_digests,
        validation_receipt_digest=validation_receipt_digest,
    )
    metadata = CatalogGenerationMetadata(
        generation_id=generation.generation_id,
        generation_digest=generation.digest,
        corpus=generation.corpus.value,
        catalog_digest=generation.catalog_digest,
        semantic_schema_digest=generation.semantic_schema_digest,
        ontology_release_digest=generation.ontology_release_digest,
        embedding_space_id=generation.embedding_space_id,
        embedding_model_version=generation.embedding_model_version,
        embedding_dimension=generation.embedding_dimension,
        validation_receipt_digest=generation.validation_receipt_digest,
    )
    await index.stage_generation(metadata, documents)
    return await index.activate_generation(
        generation.generation_id,
        expected_generation_digest=generation.digest,
        activated_at=activated_at,
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
    "ShippedCatalogReferenceSources",
    "ShippedCatalogSearchSources",
    "load_shipped_catalog_reference_sources",
    "index_shipped_catalog",
    "load_shipped_catalog_search_documents",
    "load_shipped_catalog_search_sources",
    "publish_shipped_catalog_generation",
]
