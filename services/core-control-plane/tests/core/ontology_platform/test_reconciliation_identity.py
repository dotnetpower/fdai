"""Observer identity attribution and timeout classification for reconciliation."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fdai.core.ontology_platform.kinetics import ReconciliationStatus
from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    InMemoryReconciliationLedger,
    ReconciliationNextStep,
    ReconciliationOutcome,
)
from fdai.core.ontology_platform.reconciliation_identity import (
    ObserverIdentityRecord,
    observer_identity_handle,
)
from pydantic import ValidationError
from tests.core.ontology_platform.test_reconciliation import (
    CREATED_AT,
    DEADLINE,
    _authenticated_context,
    _coordinate,
    _fixture,
    _request,
)


def _coordinator() -> EffectReconciliationCoordinator:
    return EffectReconciliationCoordinator(ledger=InMemoryReconciliationLedger())


async def test_outcome_retains_a_bound_independent_observer_identity_record() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(release=release, target=target, plan=plan, action_type=action_type)

    outcome = await _coordinate(_coordinator(), request, release=release)

    record = outcome.observer_identity
    assert record == _authenticated_context(request).identity_record()
    assert record.identities_independent is True
    assert record.credentials_independent is True
    assert record.verifier_independent_of_executor is True
    assert record.distinct_identities == 3
    assert record.distinct_credentials == 3
    assert record.source_authority == "provider"
    assert record.grants_authority is False
    assert record.observer_handle == observer_identity_handle("Heimdall-Observer ")


async def test_observer_identity_record_carries_no_raw_principal_value() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(release=release, target=target, plan=plan, action_type=action_type)

    outcome = await _coordinate(_coordinator(), request, release=release)

    encoded = json.dumps(outcome.observer_identity.model_dump(mode="json"))
    for principal in (
        "heimdall-observer",
        "thor-executor",
        "provider-readback",
        "observation-authenticator",
    ):
        assert principal not in encoded


async def test_dependent_identities_are_recorded_as_not_independent() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        source_identity="thor-executor",
    )
    context = _authenticated_context(request).model_copy(
        update={"source_credential_lineage": "credential:thor-executor:1"}
    )

    outcome = await _coordinator().coordinate(
        request,
        observation_context=context,
        active_release=release,
    )

    record = outcome.observer_identity
    assert record.identities_independent is False
    assert record.credentials_independent is False
    assert record.distinct_identities == 2
    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.reason_code == "observation_not_independent"


async def test_outcome_rejects_an_observer_identity_record_from_another_context() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(release=release, target=target, plan=plan, action_type=action_type)
    outcome = await _coordinate(_coordinator(), request, release=release)
    other = ObserverIdentityRecord.from_identities(
        source_authority="provider",
        observer_identity="other-observer",
        observer_credential_lineage="credential:other-observer:1",
        executor_identity="thor-executor",
        executor_credential_lineage="credential:thor-executor:1",
        source_identity="provider-readback",
        source_credential_lineage="credential:provider-readback:1",
        verifier_identity="observation-authenticator",
        verifier_credential_lineage="credential:observation-authenticator:1",
        signature_algorithm="ed25519",
        verified_at=request.evidence.recorded_at,
    )

    with pytest.raises(ValidationError, match="observer identity record does not match"):
        payload = outcome.model_dump(mode="json")
        payload["observer_identity"] = other.model_dump(mode="json")
        ReconciliationOutcome.model_validate(payload)


async def test_observer_identity_record_rejects_a_tampered_independence_finding() -> None:
    release, target, plan, action_type = _fixture()
    request = _request(release=release, target=target, plan=plan, action_type=action_type)
    payload = _authenticated_context(request).identity_record().model_dump(mode="json")
    payload["identities_independent"] = False

    with pytest.raises(ValidationError, match="independence finding does not match"):
        ObserverIdentityRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("kwargs", "reason_code"),
    (
        ({}, "timed_out_evaluation_late"),
        ({"complete": False}, "timed_out_evidence_incomplete"),
        ({"synthetic": True}, "timed_out_evidence_synthetic"),
        ({"conflicts": ("conflict:replica-count:1",)}, "timed_out_evidence_conflicted"),
        (
            {"fresh_until": CREATED_AT + timedelta(minutes=2)},
            "timed_out_evidence_stale",
        ),
    ),
)
async def test_timed_out_episodes_carry_a_deterministic_classification(
    kwargs: dict[str, object],
    reason_code: str,
) -> None:
    release, target, plan, action_type = _fixture()
    late = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        evaluated_at=DEADLINE + timedelta(minutes=1),
        **kwargs,
    )

    outcome = await _coordinate(_coordinator(), late, release=release)

    assert outcome.receipt.status is ReconciliationStatus.TIMED_OUT
    assert outcome.recommendation.next_step is ReconciliationNextStep.REQUEST_VIDAR_RECOVERY
    assert outcome.recommendation.target_agent == "vidar"
    assert outcome.recommendation.reason_code == reason_code


async def test_mismatched_episode_keeps_its_own_reason_code() -> None:
    release, target, plan, action_type = _fixture()
    mismatched = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        replicas=1,
    )

    outcome = await _coordinate(_coordinator(), mismatched, release=release)

    assert outcome.receipt.status is ReconciliationStatus.MISMATCHED
    assert outcome.recommendation.reason_code == "effects_mismatched"
