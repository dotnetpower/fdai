"""Durable Rule semantic generation worker tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.catalog_search import (
    ExactRuleGenerationDocumentResolver,
    InMemoryCatalogSemanticIndex,
    RuleGenerationBuildWorker,
    RuleGenerationValidationWorker,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationBuildRequestEvent,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.providers.catalog_search import CatalogSearchDocument
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 13, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
VALIDATOR_DIGEST = "sha256:" + "d" * 64


class _Resolver:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve(
        self,
        request: RuleGenerationBuildRequestEvent,
    ) -> tuple[CatalogSearchDocument, ...]:
        self.calls += 1
        await asyncio.sleep(0)
        return (
            CatalogSearchDocument(
                rule_id="rule-a",
                text=f"rule for {request.corpus.value}",
                neighbor_ids=(),
            ),
        )


class _FailingIndex(InMemoryCatalogSemanticIndex):
    async def stage_generation(self, *args: object, **kwargs: object) -> int:
        del args, kwargs
        raise RuntimeError("synthetic provider failure")


class _CountingIndex(InMemoryCatalogSemanticIndex):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot_reads = 0

    async def generation_validation_snapshot(self, generation_id: str):  # type: ignore[no-untyped-def]
        self.snapshot_reads += 1
        return await super().generation_validation_snapshot(generation_id)


def _request() -> RuleGenerationBuildRequestEvent:
    return RuleGenerationBuildRequestEvent.create(
        correlation_id="catalog-revision-42",
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=DIGEST_A,
        semantic_schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
        requested_at=NOW,
    )


async def test_exact_resolver_rejects_identity_drift_before_returning_documents() -> None:
    active = (CatalogSearchDocument(rule_id="active-rule", text="active", neighbor_ids=()),)
    discovery = (
        CatalogSearchDocument(
            rule_id="discovery-rule",
            text="discovery",
            neighbor_ids=(),
            corpus="discovery",
        ),
    )
    resolver = ExactRuleGenerationDocumentResolver(
        active_documents=active,
        discovery_documents=discovery,
        catalog_digest=DIGEST_A,
        semantic_schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
    )

    assert await resolver.resolve(_request()) == active
    stale = _request().model_copy(update={"catalog_digest": VALIDATOR_DIGEST})
    with pytest.raises(ValueError, match="catalog_digest"):
        await resolver.resolve(stale)


async def test_build_worker_stages_once_and_restart_reuses_exact_result() -> None:
    request = _request()
    index = InMemoryCatalogSemanticIndex()
    resolver = _Resolver()
    store = InMemoryStateStore()
    first = RuleGenerationBuildWorker(
        index=index,
        resolver=resolver,
        store=store,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    result = await first.handle(request)
    restarted = RuleGenerationBuildWorker(
        index=index,
        resolver=resolver,
        store=store,
        clock=lambda: NOW + timedelta(hours=1),
    )
    replay = await restarted.handle(request)

    assert replay == result
    assert resolver.calls == 1
    assert result.grants_authority is False
    snapshot = await index.generation_validation_snapshot(result.generation.generation_id)
    assert snapshot is not None
    assert snapshot.metadata.generation_digest == result.generation.generation_digest
    assert await store.verify_chain()


async def test_concurrent_build_workers_return_one_durable_result() -> None:
    request = _request()
    index = InMemoryCatalogSemanticIndex()
    resolver = _Resolver()
    store = InMemoryStateStore()
    first = RuleGenerationBuildWorker(
        index=index,
        resolver=resolver,
        store=store,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    second = RuleGenerationBuildWorker(
        index=index,
        resolver=resolver,
        store=store,
        clock=lambda: NOW + timedelta(seconds=2),
    )

    left, right = await asyncio.gather(first.handle(request), second.handle(request))

    assert left == right
    assert resolver.calls == 2
    assert await store.verify_chain()


async def test_build_provider_failure_does_not_close_durable_result() -> None:
    request = _request()
    store = InMemoryStateStore()
    worker = RuleGenerationBuildWorker(
        index=_FailingIndex(),
        resolver=_Resolver(),
        store=store,
    )

    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        await worker.handle(request)

    assert (
        await store.read_state(f"rule-semantic-generation:build:{request.generation_request_id}")
        is None
    )


async def test_validation_receipt_binding_is_exact_idempotent_and_conflict_safe() -> None:
    index = InMemoryCatalogSemanticIndex()
    build_result = await RuleGenerationBuildWorker(
        index=index,
        resolver=_Resolver(),
        store=InMemoryStateStore(),
        clock=lambda: NOW,
    ).handle(_request())
    target = build_result.generation

    with pytest.raises(ValueError, match="sha256"):
        await index.bind_generation_validation(
            target.generation_id,
            expected_generation_digest=target.generation_digest,
            validation_receipt_digest="invalid",
        )
    bound = await index.bind_generation_validation(
        target.generation_id,
        expected_generation_digest=target.generation_digest,
        validation_receipt_digest=VALIDATOR_DIGEST,
    )
    replay = await index.bind_generation_validation(
        target.generation_id,
        expected_generation_digest=target.generation_digest,
        validation_receipt_digest=VALIDATOR_DIGEST,
    )

    assert replay == bound
    assert bound.validation_receipt_digest == VALIDATOR_DIGEST
    with pytest.raises(ValueError, match="receipt conflict"):
        await index.bind_generation_validation(
            target.generation_id,
            expected_generation_digest=target.generation_digest,
            validation_receipt_digest=DIGEST_C,
        )
    active = await index.activate_generation(
        target.generation_id,
        expected_generation_digest=target.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        expected_validation_receipt_digest=VALIDATOR_DIGEST,
        activated_at=NOW,
    )
    assert (
        await index.bind_generation_validation(
            target.generation_id,
            expected_generation_digest=target.generation_digest,
            validation_receipt_digest=VALIDATOR_DIGEST,
        )
        == active
    )
    with pytest.raises(ValueError, match="only staged"):
        await index.generation_validation_snapshot(target.generation_id)


async def test_validation_worker_recomputes_snapshot_and_restart_is_read_free() -> None:
    index = _CountingIndex()
    store = InMemoryStateStore()
    build_result = await RuleGenerationBuildWorker(
        index=index,
        resolver=_Resolver(),
        store=store,
        clock=lambda: NOW,
    ).handle(_request())
    first = RuleGenerationValidationWorker(
        index=index,
        store=store,
        validator_artifact_digest=VALIDATOR_DIGEST,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    validation = await first.handle(build_result)
    restarted = RuleGenerationValidationWorker(
        index=index,
        store=store,
        validator_artifact_digest=VALIDATOR_DIGEST,
        clock=lambda: NOW + timedelta(hours=1),
    )
    replay = await restarted.handle(build_result)

    assert validation.valid is True
    assert validation.validation_receipt_digest is not None
    assert validation.grants_authority is False
    assert replay == validation
    assert index.snapshot_reads == 1
    assert await store.verify_chain()


async def test_validation_worker_closes_missing_and_tampered_snapshot_as_invalid() -> None:
    request = _request()
    source_index = InMemoryCatalogSemanticIndex()
    build_result = await RuleGenerationBuildWorker(
        index=source_index,
        resolver=_Resolver(),
        store=InMemoryStateStore(),
        clock=lambda: NOW,
    ).handle(request)

    missing = await RuleGenerationValidationWorker(
        index=InMemoryCatalogSemanticIndex(),
        store=InMemoryStateStore(),
        validator_artifact_digest=VALIDATOR_DIGEST,
        clock=lambda: NOW,
    ).handle(build_result)
    assert missing.valid is False
    assert missing.failure_reason == "generation_unavailable"

    metadata, documents = source_index._generations[build_result.generation.generation_id]
    source_index._generations[build_result.generation.generation_id] = (
        metadata,
        (replace(documents[0], text="tampered"),),
    )
    with pytest.raises(ValueError, match="manifest"):
        await RuleGenerationValidationWorker(
            index=source_index,
            store=InMemoryStateStore(),
            validator_artifact_digest=VALIDATOR_DIGEST,
            clock=lambda: NOW,
        ).handle(build_result)
