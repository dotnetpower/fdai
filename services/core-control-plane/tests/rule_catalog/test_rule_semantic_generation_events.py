"""Typed Rule semantic generation event contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.delivery.catalog_search.rule_generation import build_rule_semantic_generation
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationResultEvent,
    RuleGenerationActivationStatus,
    RuleGenerationBuildRequestEvent,
    RuleGenerationBuildResultEvent,
    RuleGenerationIdentity,
    RuleGenerationOutboxDeliveryState,
    RuleGenerationOutboxRecord,
    RuleGenerationValidationResultEvent,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.providers.catalog_search import CatalogSearchDocument

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 13, tzinfo=UTC)
RECEIPT_DIGEST = "sha256:" + "d" * 64
VALIDATOR_DIGEST = "sha256:" + "e" * 64


def _request() -> RuleGenerationBuildRequestEvent:
    return RuleGenerationBuildRequestEvent.create(
        correlation_id="catalog-revision-42",
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=DIGEST,
        semantic_schema_digest="sha256:" + "b" * 64,
        ontology_release_digest="sha256:" + "c" * 64,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
        requested_at=NOW,
    )


def _metadata():
    return build_rule_semantic_generation(
        documents=(
            CatalogSearchDocument(
                rule_id="rule-a",
                text="rule a",
                neighbor_ids=(),
            ),
        ),
        corpus="active",
        catalog_digest=DIGEST,
        semantic_schema_digest="sha256:" + "b" * 64,
        ontology_release_digest="sha256:" + "c" * 64,
        embedding_space_id="rule-semantic-v1",
        embedding_model_version="embed-v1",
        embedding_dimension=384,
    ).metadata


def _build_result() -> RuleGenerationBuildResultEvent:
    return RuleGenerationBuildResultEvent.create(
        request=_request(),
        metadata=_metadata(),
        built_at=NOW,
    )


def _valid_result() -> RuleGenerationValidationResultEvent:
    return RuleGenerationValidationResultEvent.create_valid(
        build_result=_build_result(),
        validation_receipt_digest=RECEIPT_DIGEST,
        validator_artifact_digest=VALIDATOR_DIGEST,
        validated_at=NOW,
    )


def test_build_request_and_result_round_trip_with_exact_bounded_identity() -> None:
    request = _request()
    result = RuleGenerationBuildResultEvent.create(
        request=request,
        metadata=_metadata(),
        built_at=NOW,
    )

    assert RuleGenerationBuildRequestEvent.model_validate(request.model_dump()) == request
    assert RuleGenerationBuildResultEvent.model_validate(result.model_dump()) == result
    assert result.request == request
    assert result.generation.document_count == 1
    assert result.generation.corpus is RuleCorpus.ACTIVE
    assert result.grants_authority is False


def test_event_contracts_reject_tamper_and_naive_time() -> None:
    request = _request()
    tampered = request.model_dump()
    tampered["embedding_dimension"] = 1536
    with pytest.raises(ValueError, match="request id"):
        RuleGenerationBuildRequestEvent.model_validate(tampered)

    naive = request.model_dump()
    naive["requested_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        RuleGenerationBuildRequestEvent.model_validate(naive)


def test_generation_identity_rejects_manifest_summary_tamper() -> None:
    identity = RuleGenerationIdentity.from_metadata(_metadata())
    tampered = identity.model_dump()
    tampered["document_count"] = 2

    with pytest.raises(ValueError, match="manifest digest"):
        RuleGenerationIdentity.model_validate(tampered)


def test_build_result_rejects_generation_from_another_request() -> None:
    request = _request()
    mismatched_request = request.model_copy(
        update={
            "embedding_dimension": 1536,
            "request_digest": "sha256:" + "d" * 64,
        }
    )
    result = RuleGenerationBuildResultEvent.create(
        request=request,
        metadata=_metadata(),
        built_at=NOW,
    )
    payload = result.model_dump()
    payload["request"] = mismatched_request.model_dump()

    with pytest.raises(ValueError):
        RuleGenerationBuildResultEvent.model_validate(payload)


def test_validation_results_enforce_receipt_reason_exclusivity() -> None:
    valid = _valid_result()
    invalid = RuleGenerationValidationResultEvent.create_invalid(
        build_result=_build_result(),
        validator_artifact_digest=VALIDATOR_DIGEST,
        failure_reason="manifest_mismatch",
        validated_at=NOW,
    )

    assert RuleGenerationValidationResultEvent.model_validate(valid.model_dump()) == valid
    assert RuleGenerationValidationResultEvent.model_validate(invalid.model_dump()) == invalid
    assert invalid.validation_receipt_digest is None
    assert invalid.failure_reason == "manifest_mismatch"

    invalid_with_receipt = invalid.model_dump()
    invalid_with_receipt["validation_receipt_digest"] = RECEIPT_DIGEST
    with pytest.raises(ValueError, match="exactly one receipt"):
        RuleGenerationValidationResultEvent.model_validate(invalid_with_receipt)

    valid_with_reason = valid.model_dump()
    valid_with_reason["failure_reason"] = "unexpected"
    with pytest.raises(ValueError, match="exactly one reason"):
        RuleGenerationValidationResultEvent.model_validate(valid_with_reason)


def test_activation_command_binds_expected_prior_active_generation() -> None:
    validation = _valid_result()
    command = RuleGenerationActivationCommandEvent.create(
        validation_result=validation,
        expected_active_generation=None,
        commanded_at=NOW,
    )
    assert RuleGenerationActivationCommandEvent.model_validate(command.model_dump()) == command

    prior_identity = RuleGenerationIdentity.from_metadata(
        replace(_metadata(), generation_id="rule-search:active:prior")
    )
    command_with_prior = RuleGenerationActivationCommandEvent.create(
        validation_result=validation,
        expected_active_generation=prior_identity,
        commanded_at=NOW,
    )
    substituted = command_with_prior.model_dump()
    substituted["expected_active_generation"] = None
    with pytest.raises(ValueError, match="command digest"):
        RuleGenerationActivationCommandEvent.model_validate(substituted)


def test_nested_chain_and_terminal_activation_result_fail_closed() -> None:
    command = RuleGenerationActivationCommandEvent.create(
        validation_result=_valid_result(),
        expected_active_generation=None,
        commanded_at=NOW,
    )
    result = RuleGenerationActivationResultEvent.create(
        command=command,
        status=RuleGenerationActivationStatus.ACTIVATED,
        completed_at=NOW,
    )
    assert RuleGenerationActivationResultEvent.model_validate(result.model_dump()) == result
    assert result.projection_only is True
    assert result.grants_execution_authority is False

    tampered = result.model_dump()
    tampered["command"]["validation_result"]["validator_artifact_digest"] = DIGEST
    with pytest.raises(ValueError):
        RuleGenerationActivationResultEvent.model_validate(tampered)

    failed_without_reason = result.model_dump()
    failed_without_reason["status"] = RuleGenerationActivationStatus.FAILED
    with pytest.raises(ValueError, match="exactly one reason"):
        RuleGenerationActivationResultEvent.model_validate(failed_without_reason)


def test_lifecycle_events_reject_reverse_time_and_invalid_activation() -> None:
    earlier = datetime(2026, 8, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="precede its request"):
        RuleGenerationBuildResultEvent.create(
            request=_request(),
            metadata=_metadata(),
            built_at=earlier,
        )

    invalid = RuleGenerationValidationResultEvent.create_invalid(
        build_result=_build_result(),
        validator_artifact_digest=VALIDATOR_DIGEST,
        failure_reason="manifest_mismatch",
        validated_at=NOW,
    )
    with pytest.raises(ValueError, match="cannot authorize activation"):
        RuleGenerationActivationCommandEvent.create(
            validation_result=invalid,
            expected_active_generation=None,
            commanded_at=NOW,
        )


def test_outbox_record_enforces_lease_and_acknowledgement_state() -> None:
    command = RuleGenerationActivationCommandEvent.create(
        validation_result=_valid_result(),
        expected_active_generation=None,
        commanded_at=NOW,
    )
    event = RuleGenerationActivationResultEvent.create(
        command=command,
        status=RuleGenerationActivationStatus.ACTIVATED,
        completed_at=NOW,
    )
    pending = RuleGenerationOutboxRecord(event=event)
    claimed = RuleGenerationOutboxRecord(
        event=event,
        state=RuleGenerationOutboxDeliveryState.CLAIMED,
        attempts=1,
        claimant_id="publisher-1",
        claimed_at=NOW,
        lease_until=NOW.replace(second=1),
    )
    published = RuleGenerationOutboxRecord(
        event=event,
        state=RuleGenerationOutboxDeliveryState.PUBLISHED,
        attempts=1,
        published_at=NOW,
    )

    assert pending.state is RuleGenerationOutboxDeliveryState.PENDING
    assert RuleGenerationOutboxRecord.model_validate(claimed.model_dump()) == claimed
    assert RuleGenerationOutboxRecord.model_validate(published.model_dump()) == published

    with pytest.raises(ValueError, match="live lease"):
        RuleGenerationOutboxRecord(
            event=event,
            state=RuleGenerationOutboxDeliveryState.CLAIMED,
            attempts=1,
        )
    with pytest.raises(ValueError, match="clean acknowledgement"):
        RuleGenerationOutboxRecord(
            event=event,
            state=RuleGenerationOutboxDeliveryState.PUBLISHED,
            attempts=1,
        )
    with pytest.raises(ValueError, match="exactly one error"):
        RuleGenerationOutboxRecord(event=event, attempts=1)
