"""Grounded search-document projection for Rule catalog retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from fdai.rule_catalog.schema.rego_semantics import RegoSemantics
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleSemanticManifest,
    RuleSemanticSurface,
)
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.providers.catalog_search import CatalogSearchDocument


def build_discovery_catalog_search_documents(
    rules: Sequence[Rule],
) -> tuple[CatalogSearchDocument, ...]:
    """Project normalized candidates into an inert discovery-only corpus."""

    documents = []
    for rule in sorted(rules, key=lambda item: item.id):
        text = "\n".join(
            (
                rule.id,
                rule.resource_type,
                rule.category.value,
                rule.severity.value,
                rule.source.value,
                rule.check_logic.reference,
                rule.remediates,
                rule.provenance.source_url,
                rule.provenance.source_version or "",
                *rule.triggered_by,
                *rule.evaluates,
            )
        )
        neighbors = tuple(
            sorted(
                {
                    rule.resource_type,
                    rule.remediates,
                    rule.check_logic.reference,
                    rule.source.value,
                    *rule.triggered_by,
                    *rule.evaluates,
                }
            )
        )
        documents.append(
            CatalogSearchDocument(
                rule_id=rule.id,
                text=text,
                neighbor_ids=neighbors,
                corpus="discovery",
            )
        )
    return tuple(documents)


def build_catalog_search_documents(
    *,
    rules: Sequence[Rule],
    action_types: Sequence[OntologyActionType],
    policy_semantics: Mapping[str, RegoSemantics],
    semantic_manifests: Mapping[str, RuleSemanticManifest] | None = None,
    semantic_surfaces: Mapping[str, Sequence[RuleSemanticSurface]] | None = None,
) -> tuple[CatalogSearchDocument, ...]:
    actions = {item.name: item for item in action_types}
    documents = []
    for rule in sorted(rules, key=lambda item: item.id):
        policy = policy_semantics.get(rule.check_logic.reference)
        if policy is None or policy.rule_id != rule.id:
            raise ValueError(f"verified policy semantics unavailable for {rule.id!r}")
        action = actions.get(rule.remediates)
        if action is None:
            raise ValueError(f"ActionType unavailable for {rule.id!r}")
        manifest = semantic_manifests.get(rule.id) if semantic_manifests is not None else None
        if semantic_manifests is not None and manifest is None:
            raise ValueError(f"semantic manifest unavailable for {rule.id!r}")
        surfaces = tuple(semantic_surfaces.get(rule.id, ())) if semantic_surfaces else ()
        if manifest is not None and any(
            item.manifest_digest != manifest.digest for item in surfaces
        ):
            raise ValueError(f"semantic surface manifest mismatch for {rule.id!r}")
        action_description = action.description or ""
        text = "\n".join(
            (
                rule.id,
                rule.resource_type,
                rule.category.value,
                rule.severity.value,
                policy.title,
                policy.description,
                rule.remediates,
                action_description,
                *rule.triggered_by,
                *rule.evaluates,
                *(value for surface in surfaces for value in surface.intent_ids),
                *(value for surface in surfaces for value in surface.concept_refs),
                *(value for surface in surfaces for value in surface.aliases),
                *(value for surface in surfaces for value in surface.training_queries),
            )
        )
        neighbors = tuple(
            sorted(
                {
                    rule.resource_type,
                    rule.remediates,
                    rule.check_logic.reference,
                    *rule.triggered_by,
                    *rule.evaluates,
                    *(value for surface in surfaces for value in surface.intent_ids),
                    *(value for surface in surfaces for value in surface.concept_refs),
                }
            )
        )
        documents.append(
            CatalogSearchDocument(
                rule_id=rule.id,
                text=text,
                neighbor_ids=neighbors,
                manifest_digest=manifest.digest if manifest is not None else None,
                surface_digest=catalog_semantic_surface_digest(surfaces) if surfaces else None,
            )
        )
    return tuple(documents)


def catalog_search_document_digest(document: CatalogSearchDocument) -> str:
    """Hash grounded document content without a provider-specific embedding."""

    payload = {
        "rule_id": document.rule_id,
        "text": document.text,
        "neighbor_ids": document.neighbor_ids,
        "corpus": document.corpus,
        "manifest_digest": document.manifest_digest,
        "surface_digest": document.surface_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def catalog_search_schema_digest() -> str:
    """Return the versioned projection formula identity."""

    return "sha256:" + hashlib.sha256(b"catalog-search-document:v2").hexdigest()


def catalog_semantic_surface_digest(surfaces: Sequence[RuleSemanticSurface]) -> str:
    """Hash the complete promoted surface set attached to one Rule."""

    digests = tuple(sorted(item.digest for item in surfaces))
    if not digests:
        raise ValueError("semantic surface digest requires at least one surface")
    encoded = json.dumps(digests, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def rule_reference_catalog_digest(rules: Sequence[Rule]) -> str:
    """Hash the OPA-free Rule reference fields shared by writers and readers."""

    payload = tuple(
        sorted(
            (
                rule.id,
                str(rule.version),
                rule.provenance.content_hash,
                rule.check_logic.reference,
                rule.remediates,
            )
            for rule in rules
        )
    )
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "build_discovery_catalog_search_documents",
    "build_catalog_search_documents",
    "catalog_search_document_digest",
    "catalog_search_schema_digest",
    "catalog_semantic_surface_digest",
    "rule_reference_catalog_digest",
]
