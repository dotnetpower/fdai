"""Exact startup snapshot for production Rule semantic generation workers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fdai.agents import RuleGenerationWorkerBindings
from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel
from fdai.delivery.catalog_search import (
    RULE_GENERATION_VALIDATOR_ARTIFACT_DIGEST,
    ExactRuleGenerationDocumentResolver,
    RuleGenerationBuildWorker,
    RuleGenerationValidationWorker,
)
from fdai.rule_catalog.schema.catalog_search import (
    build_catalog_search_documents,
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.rule_semantic_evaluation_policy import (
    load_retrieval_evaluation_policy_from_json,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationBuildRequestEvent,
)
from fdai.rule_catalog.schema.rule_semantic_manifest import build_rego_semantic_manifest
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleCorpus,
    RuleSemanticManifest,
    RuleSemanticSurface,
)
from fdai.rule_catalog.schema.rule_semantic_surface_catalog import (
    load_promoted_semantic_surfaces,
)
from fdai.rule_catalog.schema.rule_semantic_validation_receipt_catalog import (
    load_semantic_validation_receipts,
)
from fdai.shared.contracts.models import OntologyActionType, OntologyRelease, Rule
from fdai.shared.providers.catalog_search import (
    CatalogSemanticIndex,
    build_document_digest_manifest,
    catalog_search_document_digest,
)
from fdai.shared.providers.state_store import StateStore

_REQUEST_KEY_PREFIX = "rule-semantic-generation:reconciliation-request:"


class RuleGenerationDocumentsUnavailableError(RuntimeError):
    """Raised when startup cannot prove one complete generation snapshot."""


@dataclass(frozen=True, slots=True)
class RuleGenerationReconciliation:
    """Production worker bindings plus an optional exact startup request."""

    workers: RuleGenerationWorkerBindings
    request: RuleGenerationBuildRequestEvent | None


def build_rule_generation_document_resolver(
    *,
    catalog_root: Path,
    rules: Sequence[Rule],
    action_types: Sequence[OntologyActionType],
    ontology_release: OntologyRelease,
    embedder: EmbeddingModel,
) -> ExactRuleGenerationDocumentResolver:
    """Load strict governed inputs and freeze one active-corpus document set."""

    embedding_space_id = _required_embedding_identity(embedder, "embedding_space_id")
    embedding_model_version = _required_embedding_identity(
        embedder,
        "embedding_model_version",
    )
    if not 1 <= embedder.dim <= 4096:
        raise RuleGenerationDocumentsUnavailableError(
            "embedding dimension is outside the generation contract"
        )

    repo_root = catalog_root.parent
    policy_semantics = {
        rule.check_logic.reference: load_rego_semantics(repo_root / rule.check_logic.reference)
        for rule in rules
    }
    manifests = {
        rule.id: build_rego_semantic_manifest(
            rule,
            policy_semantics[rule.check_logic.reference],
            ontology_release_digest=ontology_release.digest,
        )
        for rule in rules
    }
    policy = load_retrieval_evaluation_policy_from_json(
        (repo_root / "config/rule-semantic-evaluation.json").read_text(encoding="utf-8")
    )
    surfaces = load_promoted_semantic_surfaces(
        catalog_root / "surfaces",
        manifests=manifests,
        validation_receipts=load_semantic_validation_receipts(
            catalog_root / "surface-validation-receipts"
        ),
        evaluation_policy_digest=policy.digest,
    )
    surfaces_by_rule = _surfaces_by_rule(surfaces, manifests=manifests)
    documents = build_catalog_search_documents(
        rules=rules,
        action_types=action_types,
        policy_semantics=policy_semantics,
        semantic_manifests=manifests,
        semantic_surfaces=surfaces_by_rule,
    )
    return ExactRuleGenerationDocumentResolver(
        active_documents=documents,
        discovery_documents=(),
        catalog_digest=rule_reference_catalog_digest(rules),
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release.digest,
        embedding_space_id=embedding_space_id,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedder.dim,
    )


async def get_or_create_rule_generation_request(
    *,
    resolver: ExactRuleGenerationDocumentResolver,
    store: StateStore,
    requested_at: datetime,
) -> RuleGenerationBuildRequestEvent:
    """Persist one replay-identical Mimir build request before publication."""

    document_manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in resolver.active_documents)
    )
    candidate = RuleGenerationBuildRequestEvent.create(
        correlation_id=(
            f"catalog-semantic-reconciliation:{document_manifest.document_digest_root[7:]}"
        ),
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=resolver.catalog_digest,
        semantic_schema_digest=resolver.semantic_schema_digest,
        ontology_release_digest=resolver.ontology_release_digest,
        embedding_space_id=resolver.embedding_space_id,
        embedding_model_version=resolver.embedding_model_version,
        embedding_dimension=resolver.embedding_dimension,
        requested_at=requested_at,
    )
    key = f"{_REQUEST_KEY_PREFIX}{candidate.generation_request_id}"
    existing = await store.read_state(key)
    if existing is not None:
        return RuleGenerationBuildRequestEvent.model_validate(existing)

    payload = candidate.model_dump(mode="json")
    created = await store.write_state_with_audit_if_absent(
        key,
        payload,
        {
            "kind": "rule_semantic_generation_reconciliation_request",
            "generation_request_id": candidate.generation_request_id,
            "request_digest": candidate.request_digest,
            "grants_execution_authority": False,
        },
    )
    if created:
        return candidate
    raced = await store.read_state(key)
    if raced is None:
        raise RuntimeError("Rule generation request first-write result is unavailable")
    return RuleGenerationBuildRequestEvent.model_validate(raced)


async def build_rule_generation_reconciliation(
    *,
    catalog_root: Path,
    rules: Sequence[Rule],
    action_types: Sequence[OntologyActionType],
    ontology_release: OntologyRelease,
    embedder: EmbeddingModel,
    index: CatalogSemanticIndex,
    store: StateStore,
    request_generation: bool,
    requested_at: datetime,
) -> RuleGenerationReconciliation:
    """Compose production workers and persist a request only when reconciliation is due."""

    resolver = build_rule_generation_document_resolver(
        catalog_root=catalog_root,
        rules=rules,
        action_types=action_types,
        ontology_release=ontology_release,
        embedder=embedder,
    )
    request = (
        await get_or_create_rule_generation_request(
            resolver=resolver,
            store=store,
            requested_at=requested_at,
        )
        if request_generation
        else None
    )
    return RuleGenerationReconciliation(
        workers=RuleGenerationWorkerBindings(
            build=RuleGenerationBuildWorker(
                index=index,
                resolver=resolver,
                store=store,
            ),
            validation=RuleGenerationValidationWorker(
                index=index,
                store=store,
                validator_artifact_digest=RULE_GENERATION_VALIDATOR_ARTIFACT_DIGEST,
            ),
        ),
        request=request,
    )


def _required_embedding_identity(embedder: EmbeddingModel, field: str) -> str:
    value = getattr(embedder, field, None)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise RuleGenerationDocumentsUnavailableError(
            f"embedder does not expose a governed {field}"
        )
    return value


def _surfaces_by_rule(
    surfaces: Sequence[RuleSemanticSurface],
    *,
    manifests: Mapping[str, RuleSemanticManifest],
) -> dict[str, tuple[RuleSemanticSurface, ...]]:
    rule_by_manifest = {manifest.digest: rule_id for rule_id, manifest in manifests.items()}
    grouped: dict[str, list[RuleSemanticSurface]] = {}
    for surface in surfaces:
        rule_id = rule_by_manifest.get(surface.manifest_digest)
        if rule_id is None:
            raise RuleGenerationDocumentsUnavailableError(
                "promoted semantic surface references an unknown manifest"
            )
        grouped.setdefault(rule_id, []).append(surface)
    return {
        rule_id: tuple(sorted(values, key=lambda item: item.surface_id))
        for rule_id, values in grouped.items()
    }


__all__ = [
    "RuleGenerationDocumentsUnavailableError",
    "RuleGenerationReconciliation",
    "build_rule_generation_document_resolver",
    "build_rule_generation_reconciliation",
    "get_or_create_rule_generation_request",
]
