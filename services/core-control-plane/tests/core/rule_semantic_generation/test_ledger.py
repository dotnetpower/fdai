"""Durable Rule semantic generation activation outbox tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rule_semantic_generation import (
    RuleGenerationLedgerConflictError,
    RuleGenerationLedgerCorruptionError,
    StateStoreRuleGenerationOutboxLedger,
)
from fdai.delivery.catalog_search.rule_generation import build_rule_semantic_generation
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationResultEvent,
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


def _result() -> RuleGenerationActivationResultEvent:
    request = RuleGenerationBuildRequestEvent.create(
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
    metadata = build_rule_semantic_generation(
        documents=(CatalogSearchDocument(rule_id="rule-a", text="rule a", neighbor_ids=()),),
        corpus="active",
        catalog_digest=DIGEST_A,
        semantic_schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
    ).metadata
    build = RuleGenerationBuildResultEvent.create(
        request=request,
        metadata=metadata,
        built_at=NOW,
    )
    validation = RuleGenerationValidationResultEvent.create_valid(
        build_result=build,
        validation_receipt_digest=DIGEST_D,
        validator_artifact_digest=DIGEST_E,
        validated_at=NOW,
    )
    command = RuleGenerationActivationCommandEvent.create(
        validation_result=validation,
        expected_active_generation=None,
        commanded_at=NOW,
    )
    return RuleGenerationActivationResultEvent.create(
        command=command,
        status=RuleGenerationActivationStatus.ACTIVATED,
        completed_at=NOW,
    )


def _request_id(result: RuleGenerationActivationResultEvent) -> str:
    return result.command.validation_result.build_result.request.generation_request_id


async def test_terminal_result_and_outbox_commit_atomically_and_deduplicate() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = _result()

    assert await ledger.commit_result(result) == result
    assert await ledger.commit_result(result) == result
    assert len(tuple(store.audit_entries)) == 1
    assert (
        await ledger.claim_outbox(
            claimant_id="publisher-a",
            now=NOW,
            lease_until=NOW + timedelta(seconds=10),
        )
        == result
    )


async def test_restart_replays_released_result_then_persists_acknowledgement() -> None:
    store = InMemoryStateStore()
    result = _result()
    first = StateStoreRuleGenerationOutboxLedger(store=store)
    await first.commit_result(result)
    assert (
        await first.claim_outbox(
            claimant_id="publisher-a",
            now=NOW,
            lease_until=NOW + timedelta(seconds=10),
        )
        == result
    )
    await first.release_outbox(
        _request_id(result),
        result.idempotency_key,
        claimant_id="publisher-a",
        available_at=NOW + timedelta(seconds=5),
        error="broker_unavailable",
    )

    restarted = StateStoreRuleGenerationOutboxLedger(store=store)
    assert (
        await restarted.claim_outbox(
            claimant_id="publisher-b",
            now=NOW + timedelta(seconds=4),
            lease_until=NOW + timedelta(seconds=14),
        )
        is None
    )
    assert (
        await restarted.claim_outbox(
            claimant_id="publisher-b",
            now=NOW + timedelta(seconds=5),
            lease_until=NOW + timedelta(seconds=15),
        )
        == result
    )
    await restarted.complete_outbox(
        _request_id(result),
        result.idempotency_key,
        claimant_id="publisher-b",
        published_at=NOW + timedelta(seconds=6),
    )
    assert (
        await StateStoreRuleGenerationOutboxLedger(store=store).claim_outbox(
            claimant_id="publisher-c",
            now=NOW + timedelta(minutes=1),
            lease_until=NOW + timedelta(minutes=2),
        )
        is None
    )
    assert await store.verify_chain()


async def test_expired_lease_is_reclaimed_and_claimants_are_fenced() -> None:
    ledger = StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore())
    result = await ledger.commit_result(_result())
    await ledger.claim_outbox(
        claimant_id="publisher-a",
        now=NOW,
        lease_until=NOW + timedelta(seconds=10),
    )
    assert (
        await ledger.claim_outbox(
            claimant_id="publisher-b",
            now=NOW + timedelta(seconds=9),
            lease_until=NOW + timedelta(seconds=19),
        )
        is None
    )
    assert (
        await ledger.claim_outbox(
            claimant_id="publisher-b",
            now=NOW + timedelta(seconds=10),
            lease_until=NOW + timedelta(seconds=20),
        )
        == result
    )

    with pytest.raises(RuleGenerationLedgerConflictError, match="not owned"):
        await ledger.complete_outbox(
            _request_id(result),
            result.idempotency_key,
            claimant_id="publisher-a",
            published_at=NOW + timedelta(seconds=11),
        )
    with pytest.raises(RuleGenerationLedgerConflictError, match="not current"):
        await ledger.complete_outbox(
            _request_id(result),
            result.idempotency_key,
            claimant_id="publisher-b",
            published_at=NOW + timedelta(seconds=21),
        )


async def test_concurrent_claim_has_one_winner() -> None:
    ledger = StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore())
    result = await ledger.commit_result(_result())

    claims = await asyncio.gather(
        ledger.claim_outbox(
            claimant_id="publisher-a",
            now=NOW,
            lease_until=NOW + timedelta(seconds=10),
        ),
        ledger.claim_outbox(
            claimant_id="publisher-b",
            now=NOW,
            lease_until=NOW + timedelta(seconds=10),
        ),
    )

    assert claims.count(result) == 1
    assert claims.count(None) == 1


async def test_request_identity_conflict_and_corrupt_state_fail_closed() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleGenerationOutboxLedger(store=store)
    result = await ledger.commit_result(_result())
    target = result.command.validation_result.build_result.generation
    conflicting_command = RuleGenerationActivationCommandEvent.create(
        validation_result=result.command.validation_result,
        expected_active_generation=target.model_copy(
            update={"generation_id": "rule-search:active:prior"}
        ),
        commanded_at=NOW,
    )
    conflicting = RuleGenerationActivationResultEvent.create(
        command=conflicting_command,
        status=RuleGenerationActivationStatus.ACTIVATED,
        completed_at=NOW,
    )
    with pytest.raises(RuleGenerationLedgerConflictError, match="another activation command"):
        await ledger.commit_result(conflicting)

    key = f"rule-semantic-generation:activation:{_request_id(result)}"
    raw = await store.read_state(key)
    assert raw is not None
    await store.write_state(key, {**raw, "outbox": {}})
    with pytest.raises(RuleGenerationLedgerCorruptionError):
        await StateStoreRuleGenerationOutboxLedger(store=store).claim_outbox(
            claimant_id="publisher-a",
            now=NOW,
            lease_until=NOW + timedelta(seconds=10),
        )


async def test_lease_and_release_inputs_are_bounded() -> None:
    ledger = StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore())
    result = await ledger.commit_result(_result())
    with pytest.raises(ValueError, match="timezone-aware"):
        await ledger.claim_outbox(
            claimant_id="publisher-a",
            now=NOW.replace(tzinfo=None),
            lease_until=NOW + timedelta(seconds=10),
        )
    await ledger.claim_outbox(
        claimant_id="publisher-a",
        now=NOW,
        lease_until=NOW + timedelta(seconds=10),
    )
    with pytest.raises(ValueError):
        await ledger.release_outbox(
            _request_id(result),
            result.idempotency_key,
            claimant_id="publisher-a",
            available_at=NOW + timedelta(seconds=5),
            error="x" * 129,
        )
