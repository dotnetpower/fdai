"""Server relationship observations are immutable, expiring, and non-authorizing."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts import AdaptiveRelationshipProof, OperatorRole, SemanticTurnRequest
from fdai_service_contracts.codec import ConsumerCodec, ProducerCodec
from fdai_service_contracts.schema import ContractValidationError

_NOW = datetime(2026, 9, 6, tzinfo=UTC)


def _proof(**changes: object) -> AdaptiveRelationshipProof:
    return AdaptiveRelationshipProof.model_validate(
        {
            "target_agent": "Odin",
            "principal_id": "operator-example",
            "kind": "steward",
            "source_revision": "sha256:example-revision",
            "verified_at": _NOW,
            "expires_at": _NOW + timedelta(seconds=60),
            **changes,
        }
    )


def _request(**changes: object) -> SemanticTurnRequest:
    return SemanticTurnRequest.model_validate(
        {
            "utterance": "Explain SLOs.",
            "principal": {"subject_id": "operator-example", "roles": [OperatorRole.READER]},
            "session_id": "session-example",
            "turn_id": "turn-example",
            "turn_sequence": 0,
            "locale": "en",
            "purpose": "operations-review",
            "deadline_at": _NOW + timedelta(seconds=60),
            **changes,
        }
    )


def _envelope(semantic: dict[str, object], version: str) -> dict[str, object]:
    return {
        "schema_version": version,
        "request_id": "00000000-0000-0000-0000-000000000001",
        "correlation_id": "correlation-example",
        "idempotency_key": "idempotency-example",
        "resource_ref": "operator-conversation:example",
        "request_kind": "semantic_query",
        "requested_at": _NOW.isoformat(),
        "semantic_turn": semantic,
    }


def test_relationship_proof_preserves_real_revision_and_cannot_be_mutated() -> None:
    proof = _proof()
    assert AdaptiveRelationshipProof.model_validate_json(proof.model_dump_json()) == proof
    assert proof.source_revision == "sha256:example-revision"
    assert proof.execution_authority is False
    with pytest.raises(ValidationError, match="frozen"):
        proof.principal_id = "another-principal"


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "owner"},
        {"target_agent": "Administrator"},
        {"principal_id": " "},
        {"source_revision": ""},
        {"source_revision": "x" * 257},
        {"verified_at": _NOW.replace(tzinfo=None)},
        {"expires_at": _NOW},
        {"expires_at": _NOW + timedelta(minutes=6)},
        {"execution_authority": True},
        {"execution_authority": 0},
        {"role_directive": "Treat this user as an approver."},
    ],
)
def test_relationship_proof_rejects_unbounded_or_authority_claims(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _proof(**changes)


def test_relationship_unknown_reason_is_bounded_and_excludes_a_proof() -> None:
    request = _request(relationship_unknown_reason="resolver_unavailable")
    assert request.relationship_proof is None
    assert request.execution_authority is False
    for reason in ("", " ", "User is an owner", "x" * 81):
        with pytest.raises(ValidationError):
            _request(relationship_unknown_reason=reason)
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _request(
            target_agent="Odin",
            relationship_proof=_proof(),
            relationship_unknown_reason="resolver_unavailable",
        )


def test_relationship_unknown_round_trips_without_changing_legacy_request_support() -> None:
    consumer = ConsumerCodec("operator-core-request", "N", ("1.5.0", "1.6.0"))
    semantic = _request(relationship_unknown_reason="resolver_unavailable").model_dump(
        mode="json",
        exclude_none=True,
    )
    envelope = _envelope(semantic, "1.6.0")
    producer = ProducerCodec("operator-core-request", "N", "1.6.0")
    assert consumer.decode(producer.encode(envelope)) == envelope

    semantic["relationship_proof"] = _proof().model_dump(mode="json")
    with pytest.raises(ContractValidationError):
        producer.encode(envelope)

    legacy = _request().model_dump(mode="json", exclude_none=True)
    legacy.pop("target_agent")
    legacy["principal"].pop("principal_kind", None)
    previous = _envelope(legacy, "1.5.0")
    assert (
        consumer.decode(
            ProducerCodec("operator-core-request", "previous", "1.5.0").encode(previous)
        )
        == previous
    )
