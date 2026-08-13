"""Exact Rule semantic generation activation binding tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.rule_semantic_generation import (
    RuleGenerationActivationBinder,
    StateStoreRuleGenerationOutboxLedger,
)
from fdai.delivery.catalog_search.in_memory import InMemoryCatalogSemanticIndex
from fdai.delivery.catalog_search.rule_generation import build_rule_semantic_generation
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationStatus,
    RuleGenerationBuildRequestEvent,
    RuleGenerationBuildResultEvent,
    RuleGenerationValidationResultEvent,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.providers.catalog_search import CatalogSearchDocument
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 13, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64


class _CountingIndex(InMemoryCatalogSemanticIndex):
    def __init__(self) -> None:
        super().__init__()
        self.activation_attempts = 0

    async def activate_generation(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self.activation_attempts += 1
        return await super().activate_generation(*args, **kwargs)  # type: ignore[arg-type]


def _command(
    *,
    rule_id: str = "rule-a",
    correlation_id: str = "catalog-revision-42",
    commanded_at: datetime = NOW,
    expected_active=None,  # type: ignore[no-untyped-def]
):
    request = RuleGenerationBuildRequestEvent.create(
        correlation_id=correlation_id,
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=DIGEST_A,
        semantic_schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
        requested_at=NOW,
    )
    build = build_rule_semantic_generation(
        documents=(CatalogSearchDocument(rule_id=rule_id, text=rule_id, neighbor_ids=()),),
        corpus="active",
        catalog_digest=DIGEST_A,
        semantic_schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
    )
    metadata = replace(build.metadata, validation_receipt_digest=DIGEST_D)
    build_result = RuleGenerationBuildResultEvent.create(
        request=request,
        metadata=metadata,
        built_at=NOW,
    )
    validation = RuleGenerationValidationResultEvent.create_valid(
        build_result=build_result,
        validation_receipt_digest=DIGEST_D,
        validator_artifact_digest=DIGEST_E,
        validated_at=NOW,
    )
    command = RuleGenerationActivationCommandEvent.create(
        validation_result=validation,
        expected_active_generation=expected_active,
        commanded_at=commanded_at,
    )
    return command, metadata, build.documents


async def test_first_activation_closes_exact_terminal_result() -> None:
    index = _CountingIndex()
    ledger = StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore())
    command, metadata, documents = _command()
    await index.stage_generation(metadata, documents)
    binder = RuleGenerationActivationBinder(
        index=index,
        ledger=ledger,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    result = await binder.handle(command)

    assert result.status is RuleGenerationActivationStatus.ACTIVATED
    assert result.failure_reason is None
    assert await ledger.result_for(command) == result
    assert (await index.active_generation()) == replace(
        metadata,
        state="active",
        activated_at=NOW,
    )


async def test_restart_replay_does_not_touch_provider_after_successor_activation() -> None:
    index = _CountingIndex()
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    command, metadata, documents = _command()
    await index.stage_generation(metadata, documents)
    first = await RuleGenerationActivationBinder(index=index, ledger=ledger).handle(command)

    successor_command, successor, successor_documents = _command(
        rule_id="rule-b",
        correlation_id="catalog-revision-43",
        commanded_at=NOW + timedelta(hours=1),
        expected_active=command.validation_result.build_result.generation,
    )
    await index.stage_generation(successor, successor_documents)
    await index.activate_generation(
        successor.generation_id,
        expected_generation_digest=successor.generation_digest,
        expected_active_generation_id=metadata.generation_id,
        expected_active_generation_digest=metadata.generation_digest,
        activated_at=successor_command.commanded_at,
        expected_validation_receipt_digest=DIGEST_D,
    )
    attempts_before_replay = index.activation_attempts

    replay = await RuleGenerationActivationBinder(
        index=index,
        ledger=StateStoreRuleGenerationOutboxLedger(store=store),
    ).handle(command)

    assert replay == first
    assert index.activation_attempts == attempts_before_replay
    assert (await index.active_generation()).generation_id == successor.generation_id  # type: ignore[union-attr]


async def test_exact_preexisting_target_is_projection_only_already_active() -> None:
    index = _CountingIndex()
    command, metadata, documents = _command(commanded_at=NOW + timedelta(minutes=1))
    await index.stage_generation(metadata, documents)
    await index.activate_generation(
        metadata.generation_id,
        expected_generation_digest=metadata.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
        expected_validation_receipt_digest=DIGEST_D,
    )

    result = await RuleGenerationActivationBinder(
        index=index,
        ledger=StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore()),
    ).handle(command)

    assert result.status is RuleGenerationActivationStatus.ALREADY_ACTIVE


async def test_prior_mismatch_and_substituted_receipt_fail_without_pointer_change() -> None:
    index = _CountingIndex()
    prior_command, prior, prior_documents = _command()
    await index.stage_generation(prior, prior_documents)
    await index.activate_generation(
        prior.generation_id,
        expected_generation_digest=prior.generation_digest,
        expected_active_generation_id=None,
        expected_active_generation_digest=None,
        activated_at=NOW,
        expected_validation_receipt_digest=DIGEST_D,
    )
    target_command, target, target_documents = _command(
        rule_id="rule-b",
        correlation_id="catalog-revision-43",
        commanded_at=NOW + timedelta(minutes=1),
    )
    await index.stage_generation(target, target_documents)

    mismatch = await RuleGenerationActivationBinder(
        index=index,
        ledger=StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore()),
    ).handle(target_command)

    assert mismatch.status is RuleGenerationActivationStatus.FAILED
    assert mismatch.failure_reason == "active_generation_identity_mismatch"
    assert (await index.active_generation()).generation_id == prior.generation_id  # type: ignore[union-attr]

    empty_index = _CountingIndex()
    substituted = replace(target, validation_receipt_digest="sha256:" + "f" * 64)
    await empty_index.stage_generation(substituted, target_documents)
    rejected = await RuleGenerationActivationBinder(
        index=empty_index,
        ledger=StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore()),
    ).handle(target_command.model_copy(update={"expected_active_generation": None}))
    assert rejected.status is RuleGenerationActivationStatus.FAILED
    assert rejected.failure_reason == "target_activation_precondition_failed"
    assert await empty_index.active_generation() is None


async def test_concurrent_duplicate_returns_one_stable_terminal_result() -> None:
    index = _CountingIndex()
    ledger = StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore())
    command, metadata, documents = _command()
    await index.stage_generation(metadata, documents)
    binder = RuleGenerationActivationBinder(index=index, ledger=ledger)

    first, second = await asyncio.gather(binder.handle(command), binder.handle(command))

    assert first == second
    assert first.status is RuleGenerationActivationStatus.ACTIVATED
    assert (await index.active_generation()).generation_id == metadata.generation_id  # type: ignore[union-attr]
