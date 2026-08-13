from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.delivery.catalog_search.rule_generation import (
    bind_rule_semantic_generation_validation,
    build_rule_semantic_generation,
    publish_rule_semantic_generation,
    validate_rule_semantic_generation,
)
from fdai.rule_catalog.schema.catalog_search import (
    build_catalog_search_documents,
    build_discovery_catalog_search_documents,
    catalog_search_document_digest,
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.rule_catalog.schema.control_objective import (
    ControlObjective,
    control_objective_content_hash,
)
from fdai.rule_catalog.schema.discovery_rule import load_discovery_rule_catalog
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import RuleCatalogError, load_rule_catalog
from fdai.rule_catalog.schema.rule_objective_binding import (
    RuleObjectiveBinding,
    rule_objective_binding_content_hash,
)
from fdai.rule_catalog.schema.rule_semantic_evaluation import (
    EvaluationQueryOrigin,
    RetrievalEvaluationCase,
    RetrievalEvaluationPolicy,
    evaluate_semantic_surface,
)
from fdai.rule_catalog.schema.rule_semantic_generation import build_document_digest_manifest
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleSemanticSurface,
    SurfaceOrigin,
    ValidationDecision,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
    catalog_generation_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
RULE_CATALOG_ROOT = REPO_ROOT / "rule-catalog"
DISCOVERY_ROOT = REPO_ROOT / "rule-catalog" / "collected"
OBJECTIVE_PATH = (
    RULE_CATALOG_ROOT / "control-objectives" / "reliability.node-pool.zone-failure-tolerance.yaml"
)
BINDING_PATH = (
    RULE_CATALOG_ROOT / "rule-objective-bindings" / "binding.node-pool-zone-resilience.yaml"
)
NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _generation_metadata(
    *,
    corpus: CatalogCorpus,
    catalog_digest: str,
    ontology_release_digest: str,
    documents: tuple[CatalogSearchDocument, ...],
) -> CatalogGenerationMetadata:
    document_digests = tuple(catalog_search_document_digest(item) for item in documents)
    manifest = build_document_digest_manifest(document_digests)
    generation_digest = catalog_generation_digest(
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="lexical-only-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=manifest,
    )
    return CatalogGenerationMetadata(
        generation_id=f"rule-search:{corpus}:{generation_digest[7:31]}",
        generation_digest=generation_digest,
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="lexical-only-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        document_digest_manifest=manifest,
        validation_receipt_digest=_digest(f"validated\0{generation_digest}"),
    )


class _ActiveCatalogRetriever:
    def __init__(
        self,
        index: InMemoryCatalogSemanticIndex,
        *,
        catalog_digest: str,
    ) -> None:
        self._index = index
        self._catalog_digest = catalog_digest

    async def search(self, query: str, *, k: int) -> tuple[str, ...]:
        results = await self._index.search(
            query,
            k=k,
            corpus="active",
            expected_catalog_digest=self._catalog_digest,
        )
        return tuple(item.rule_id for item in results)


def _load_active_corpus(
    *,
    control_objectives: tuple[ControlObjective, ...] = (),
    objective_bindings: tuple[RuleObjectiveBinding, ...] = (),
) -> tuple[
    tuple[CatalogSearchDocument, ...],
    CatalogGenerationMetadata,
]:
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        RULE_CATALOG_ROOT,
        schema_registry=registry,
        probes_root=RULE_CATALOG_ROOT / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (RULE_CATALOG_ROOT / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = load_rule_catalog(
        RULE_CATALOG_ROOT / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=RULE_CATALOG_ROOT / "remediation",
    )
    policy_semantics = {
        rule.check_logic.reference: load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        for rule in rules
    }
    documents = build_catalog_search_documents(
        rules=rules,
        action_types=ontology.action_types,
        policy_semantics=policy_semantics,
        control_objectives=control_objectives,
        objective_bindings=objective_bindings,
    )
    return documents, _generation_metadata(
        corpus="active",
        catalog_digest=rule_reference_catalog_digest(rules),
        ontology_release_digest=ontology.build_release().digest,
        documents=documents,
    )


def _reviewed_policy_abstractions() -> tuple[ControlObjective, RuleObjectiveBinding]:
    objective_raw = yaml.safe_load(OBJECTIVE_PATH.read_text(encoding="utf-8"))
    objective_raw["state"] = "reviewed"
    objective_draft = ControlObjective.model_validate(objective_raw)
    objective_digest = control_objective_content_hash(objective_draft)
    objective_raw["content_digest"] = objective_digest
    objective_raw["provenance"]["content_hash"] = objective_digest
    objective = ControlObjective.model_validate(objective_raw)

    binding_raw = yaml.safe_load(BINDING_PATH.read_text(encoding="utf-8"))
    binding_raw["state"] = "reviewed"
    binding_raw["objective"]["content_digest"] = objective.content_digest
    binding_draft = RuleObjectiveBinding.model_validate(binding_raw)
    binding_digest = rule_objective_binding_content_hash(binding_draft)
    binding_raw["content_digest"] = binding_digest
    binding_raw["provenance"]["content_hash"] = binding_digest
    binding = RuleObjectiveBinding.model_validate(binding_raw)
    return objective, binding


def test_candidate_policy_abstractions_do_not_change_active_rule_projection() -> None:
    baseline, _ = _load_active_corpus()
    objective = ControlObjective.model_validate(
        yaml.safe_load(OBJECTIVE_PATH.read_text(encoding="utf-8"))
    )
    binding = RuleObjectiveBinding.model_validate(
        yaml.safe_load(BINDING_PATH.read_text(encoding="utf-8"))
    )

    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        RULE_CATALOG_ROOT,
        schema_registry=registry,
        probes_root=RULE_CATALOG_ROOT / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (RULE_CATALOG_ROOT / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = load_rule_catalog(
        RULE_CATALOG_ROOT / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=RULE_CATALOG_ROOT / "remediation",
    )
    policy_semantics = {
        rule.check_logic.reference: load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        for rule in rules
    }

    projected = build_catalog_search_documents(
        rules=rules,
        action_types=ontology.action_types,
        policy_semantics=policy_semantics,
        control_objectives=(objective,),
        objective_bindings=(binding,),
    )

    assert projected == baseline


def test_reviewed_policy_abstractions_annotate_exact_rule_projection() -> None:
    objective, binding = _reviewed_policy_abstractions()
    projected, _ = _load_active_corpus()
    enriched, _ = _load_active_corpus(
        control_objectives=(objective,),
        objective_bindings=(binding,),
    )

    baseline = next(item for item in projected if item.rule_id == "kubernetes-node-pool.multi-zone")
    annotated = next(item for item in enriched if item.rule_id == baseline.rule_id)

    assert annotated.document_kind == "rule"
    assert objective.ref in annotated.text
    assert objective.title in annotated.text
    assert objective.ref in annotated.neighbor_ids
    assert annotated != baseline


def test_reviewed_binding_with_stale_rule_pin_fails_projection() -> None:
    objective, binding = _reviewed_policy_abstractions()
    binding_raw = binding.model_dump(mode="json")
    binding_raw["rule"]["content_digest"] = f"sha256:{'f' * 64}"
    binding_draft = RuleObjectiveBinding.model_validate(binding_raw)
    binding_digest = rule_objective_binding_content_hash(binding_draft)
    binding_raw["content_digest"] = binding_digest
    binding_raw["provenance"]["content_hash"] = binding_digest
    stale_binding = RuleObjectiveBinding.model_validate(binding_raw)

    with pytest.raises(ValueError, match="Rule pin mismatch"):
        _load_active_corpus(
            control_objectives=(objective,),
            objective_bindings=(stale_binding,),
        )


def test_complete_discovery_corpus_materializes_with_replayable_identity() -> None:
    rules = load_discovery_rule_catalog(
        DISCOVERY_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
    )
    documents = build_discovery_catalog_search_documents(rules)
    document_digests = tuple(catalog_search_document_digest(item) for item in documents)
    manifest = build_document_digest_manifest(document_digests)

    assert len(rules) == 8_487
    assert len(documents) == len(rules)
    assert tuple(item.rule_id for item in documents) == tuple(sorted(rule.id for rule in rules))
    assert all(item.corpus == "discovery" for item in documents)
    assert manifest.document_count == 8_487
    assert len(manifest.chunks) == 34
    assert sum(chunk.document_count for chunk in manifest.chunks) == 8_487

    repeated = build_discovery_catalog_search_documents(rules)
    repeated_digests = tuple(catalog_search_document_digest(item) for item in repeated)
    assert build_document_digest_manifest(repeated_digests) == manifest


def test_discovery_loader_rejects_empty_catalog(tmp_path: Path) -> None:
    with pytest.raises(RuleCatalogError, match="contains no Rule YAML files"):
        load_discovery_rule_catalog(
            tmp_path,
            schema_registry=PackageResourceSchemaRegistry(),
        )


def test_discovery_loader_rejects_invalid_and_duplicate_records(tmp_path: Path) -> None:
    raw = yaml.safe_load(next(DISCOVERY_ROOT.rglob("*.yaml")).read_text(encoding="utf-8"))
    (tmp_path / "first.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "duplicate.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "invalid.yaml").write_text("schema_version: 1.0.0\n", encoding="utf-8")

    with pytest.raises(RuleCatalogError) as raised:
        load_discovery_rule_catalog(
            tmp_path,
            schema_registry=PackageResourceSchemaRegistry(),
        )

    assert any("duplicate rule id" in issue.message for issue in raised.value.issues)
    assert any(issue.key.startswith("invalid.yaml:") for issue in raised.value.issues)


async def test_real_active_and_discovery_corpora_have_isolated_lifecycles() -> None:
    active_documents, active_metadata = _load_active_corpus()
    discovery_rules = load_discovery_rule_catalog(
        DISCOVERY_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
    )
    discovery_documents = build_discovery_catalog_search_documents(discovery_rules)
    discovery_first = _generation_metadata(
        corpus="discovery",
        catalog_digest=rule_reference_catalog_digest(discovery_rules),
        ontology_release_digest=active_metadata.ontology_release_digest,
        documents=discovery_documents,
    )
    changed_discovery_documents = (
        replace(discovery_documents[0], text=f"{discovery_documents[0].text}\ncandidate-refresh"),
        *discovery_documents[1:],
    )
    discovery_second = _generation_metadata(
        corpus="discovery",
        catalog_digest=discovery_first.catalog_digest,
        ontology_release_digest=active_metadata.ontology_release_digest,
        documents=changed_discovery_documents,
    )
    index = InMemoryCatalogSemanticIndex()

    assert await index.stage_generation(active_metadata, active_documents) == 62
    assert await index.stage_generation(discovery_first, discovery_documents) == 8_487
    assert await index.active_generation("active") is None
    assert await index.active_generation("discovery") is None
    staged_generations: tuple[tuple[CatalogCorpus, CatalogGenerationMetadata], ...] = (
        ("active", active_metadata),
        ("discovery", discovery_first),
    )
    for corpus, metadata in staged_generations:
        with pytest.raises(CatalogGenerationStaleError, match="unavailable"):
            await index.search(
                "staged-document",
                corpus=corpus,
                expected_catalog_digest=metadata.catalog_digest,
            )

    active = await index.activate_generation(
        active_metadata.generation_id,
        expected_generation_digest=active_metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
    )
    first = await index.activate_generation(
        discovery_first.generation_id,
        expected_generation_digest=discovery_first.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
    )
    active_rule_id = active_documents[0].rule_id
    discovery_rule_id = discovery_documents[0].rule_id
    active_results = await index.search(active_rule_id, corpus="active", k=1)
    first_results = await index.search(discovery_rule_id, corpus="discovery", k=1)
    assert {item.generation_id for item in active_results} == {active.generation_id}
    assert {item.generation_id for item in first_results} == {first.generation_id}
    assert all(item.corpus == "active" for item in active_results)
    assert all(item.corpus == "discovery" for item in first_results)

    assert await index.stage_generation(discovery_second, changed_discovery_documents) == 8_487
    second = await index.activate_generation(
        discovery_second.generation_id,
        expected_generation_digest=discovery_second.generation_digest,
        expected_active_generation_id=first.generation_id,
        expected_active_generation_digest=first.generation_digest,
        activated_at=datetime(2026, 8, 13, 2, tzinfo=UTC),
    )
    assert await index.active_generation("active") == active
    assert await index.search(active_rule_id, corpus="active", k=1) == active_results
    second_results = await index.search(discovery_rule_id, corpus="discovery", k=1)
    assert {item.generation_id for item in second_results} == {second.generation_id}

    compatibility = OntologyGenerationCompatibilityReceipt(
        previous_release_digest=first.ontology_release_digest,
        candidate_release_digest=second.ontology_release_digest,
        checked_declarations=(),
        added_declarations=(),
    )
    rollback = await index.rollback_generation(
        first.generation_id,
        expected_active_generation_id=second.generation_id,
        expected_active_generation_digest=second.generation_digest,
        expected_target_generation_digest=first.generation_digest,
        expected_validation_receipt_digest=first.validation_receipt_digest or "",
        ontology_compatibility_receipt=compatibility,
        rolled_back_at=datetime(2026, 8, 13, 3, tzinfo=UTC),
    )

    assert rollback.reactivated_generation_id == first.generation_id
    assert await index.active_generation("active") == active
    assert await index.search(active_rule_id, corpus="active", k=1) == active_results
    rolled_back_results = await index.search(discovery_rule_id, corpus="discovery", k=1)
    assert {item.generation_id for item in rolled_back_results} == {first.generation_id}


async def test_real_active_rule_corpus_uses_validated_exact_generation() -> None:
    documents, expected = _load_active_corpus()
    build = build_rule_semantic_generation(
        documents=documents,
        corpus="active",
        catalog_digest=expected.catalog_digest,
        semantic_schema_digest=expected.semantic_schema_digest,
        ontology_release_digest=expected.ontology_release_digest,
        embedding_space_id=expected.embedding_space_id,
        embedding_model_version=expected.embedding_model_version,
        embedding_dimension=expected.embedding_dimension,
    )
    validator_artifact_digest = _digest("rule-generation-validator-v1")
    receipt = validate_rule_semantic_generation(
        build=build,
        corpus="active",
        catalog_digest=expected.catalog_digest,
        semantic_schema_digest=expected.semantic_schema_digest,
        ontology_release_digest=expected.ontology_release_digest,
        embedding_space_id=expected.embedding_space_id,
        embedding_model_version=expected.embedding_model_version,
        embedding_dimension=expected.embedding_dimension,
        validator_artifact_digest=validator_artifact_digest,
    )
    validated = bind_rule_semantic_generation_validation(build, receipt)
    index = InMemoryCatalogSemanticIndex()

    active = await publish_rule_semantic_generation(
        index=index,
        build=validated,
        activated_at=NOW,
    )
    results = await index.search(
        documents[0].rule_id,
        corpus="active",
        expected_catalog_digest=expected.catalog_digest,
        k=1,
    )

    assert len(build.documents) == 62
    assert build.metadata.generation_digest == expected.generation_digest
    assert receipt.validator_artifact_digest == validator_artifact_digest
    assert active.validation_receipt_digest == receipt.receipt_digest
    assert active.catalog_digest == expected.catalog_digest
    assert active.semantic_schema_digest == catalog_search_schema_digest()
    assert active.ontology_release_digest == expected.ontology_release_digest
    assert [item.rule_id for item in results] == [documents[0].rule_id]
    assert all(item.generation_digest == active.generation_digest for item in results)


async def test_shipped_active_catalog_holds_without_korean_semantic_surfaces() -> None:
    documents, metadata = _load_active_corpus()
    target_rule_id = "kubernetes-node-pool.multi-zone"
    index = InMemoryCatalogSemanticIndex()
    assert await index.stage_generation(metadata, documents) == 62
    await index.activate_generation(
        metadata.generation_id,
        expected_generation_digest=metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
    )
    surface = RuleSemanticSurface(
        surface_id="surface.assurance.kubernetes-node-pool.multi-zone.ko",
        manifest_digest=_digest(f"manifest\0{target_rule_id}"),
        locale="ko",
        origin=SurfaceOrigin.AUTHORED,
        intent_ids=("require-multi-zone-node-pool",),
        concept_refs=("kubernetes-node-pool",),
        aliases=(),
        training_queries=("노드 풀 가용 영역 적용",),
        hard_negative_queries=("데이터베이스 연결 수 제한",),
        producer_ref="assurance:shipped-catalog-ko@1",
        evidence_refs=(f"rule:{target_rule_id}",),
    )
    cases = (
        RetrievalEvaluationCase(
            "exact-rule-id-en",
            target_rule_id,
            "en-exact",
            (target_rule_id,),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "paraphrase-ko",
            "노드 풀이 여러 가용 영역을 사용하도록 요구하는 규칙은 무엇인가요?",
            "ko-positive",
            (target_rule_id,),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "no-match-ko",
            "데이터베이스 연결 풀 크기를 조정하는 규칙은 무엇인가요?",
            "ko-negative",
            (),
            EvaluationQueryOrigin.ASSURANCE_GENERATED,
            generator_ref="assurance:shipped-catalog-ko@1",
        ),
    )
    policy = RetrievalEvaluationPolicy(
        top_k=5,
        min_recall_at_k=1.0,
        min_mean_reciprocal_rank=1.0,
        min_no_match_precision=1.0,
    )

    receipt = await evaluate_semantic_surface(
        surface,
        cases,
        retriever=_ActiveCatalogRetriever(
            index,
            catalog_digest=metadata.catalog_digest,
        ),
        policy=policy,
        evaluator_ref="heimdall:shipped-catalog-ko@1",
    )
    metrics = {(item.cohort, item.metric): item.value for item in receipt.cohort_metrics}

    assert receipt.decision is ValidationDecision.HOLD
    assert receipt.failure_codes == (
        "ko-positive-mrr-below-threshold",
        "ko-positive-recall-below-threshold",
    )
    assert metrics[("en-exact", "recall-at-5")] == 1.0
    assert metrics[("ko-positive", "recall-at-5")] == 0.0
    assert metrics[("ko-negative", "no-match-precision")] == 1.0
    assert receipt.validation_authority == "validation_only"
    assert surface.execution_authority is False
