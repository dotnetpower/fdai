"""Focused tests for production reconciliation artifact and observation adapters."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fdai.core.ontology_platform.reconciliation_events import EffectReconciliationRequestEvent
from fdai.delivery.reconciliation import (
    IndependentObservationContextVerifier,
    LocalReconciliationArtifactResolver,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from tests.core.ontology_platform.test_reconciliation import (
    CREATED_AT,
    _authenticated_context,
    _fixture,
    _request,
)


class _TargetReader:
    def __init__(self, record: OntologyObjectRecord, *, block: bool = False) -> None:
        self.record = record
        self.block = block

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        assert object_id == self.record.id
        if self.block:
            await asyncio.Event().wait()
        return self.record


class _Authenticator:
    def __init__(self, *, replacement=None, block: bool = False) -> None:
        self.replacement = replacement
        self.block = block

    async def authenticate(self, *, evidence, claimed_context):
        del evidence
        if self.block:
            await asyncio.Event().wait()
        return self.replacement or claimed_context


def _event_fixture():
    release, target, plan, action_type = _fixture()
    request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
    )
    context = _authenticated_context(request)
    event = EffectReconciliationRequestEvent.from_request(
        request,
        observation_context=context,
    )
    return release, target, plan, action_type, context, event


async def test_artifact_resolver_restores_exact_bodies_and_rejects_stale_target() -> None:
    release, target, plan, action_type, _, event = _event_fixture()
    resolver = LocalReconciliationArtifactResolver(
        active_release=release,
        action_types=(action_type,),
        plans=(plan,),
        target_reader=_TargetReader(target),
    )

    resolved = await resolver.resolve(event)

    assert resolved.plan == plan
    assert resolved.action_type == action_type
    assert resolved.active_release == release

    stale_target = OntologyObjectRecord(
        id=target.id,
        object_type=target.object_type,
        properties=target.properties,
        revision=target.revision + 1,
        type_ref=target.type_ref,
    )
    stale_resolver = LocalReconciliationArtifactResolver(
        active_release=release,
        action_types=(action_type,),
        plans=(plan,),
        target_reader=_TargetReader(stale_target),
    )
    with pytest.raises(ValueError, match="is stale"):
        await stale_resolver.resolve(event)


async def test_artifact_resolver_rejects_substitution_stale_release_and_timeout() -> None:
    release, target, plan, action_type, _, event = _event_fixture()
    substituted = plan.model_copy(update={"planner_ref": "function:substituted"})
    with pytest.raises(ValueError, match="digest does not match local body"):
        LocalReconciliationArtifactResolver(
            active_release=release,
            action_types=(action_type,),
            plans=(substituted,),
            target_reader=_TargetReader(target),
        )

    stale_event = event.model_copy(
        update={
            "ontology_release_ref": event.ontology_release_ref.model_copy(
                update={"digest": "sha256:" + "f" * 64}
            )
        }
    )
    resolver = LocalReconciliationArtifactResolver(
        active_release=release,
        action_types=(action_type,),
        plans=(plan,),
        target_reader=_TargetReader(target),
    )
    with pytest.raises(ValueError, match="release is stale"):
        await resolver.resolve(stale_event)

    blocked = LocalReconciliationArtifactResolver(
        active_release=release,
        action_types=(action_type,),
        plans=(plan,),
        target_reader=_TargetReader(target, block=True),
        timeout_seconds=0.01,
    )
    with pytest.raises(TimeoutError):
        await blocked.resolve(event)


async def test_observation_verifier_enforces_identity_and_credential_independence() -> None:
    release, target, plan, action_type, context, event = _event_fixture()
    verifier = IndependentObservationContextVerifier(authenticator=_Authenticator())

    assert await verifier.verify(evidence=event.evidence, claimed_context=context) == context

    shared_identity_request = _request(
        release=release,
        target=target,
        plan=plan,
        action_type=action_type,
        execution_identity="heimdall-observer",
    )
    shared_identity_context = _authenticated_context(shared_identity_request).model_copy(
        update={"executor_credential_lineage": "credential:shared-executor:1"}
    )
    with pytest.raises(ValueError, match="observation identities MUST be distinct"):
        await IndependentObservationContextVerifier(authenticator=_Authenticator()).verify(
            evidence=shared_identity_request.evidence,
            claimed_context=shared_identity_context,
        )

    shared_lineage = context.model_copy(
        update={"source_credential_lineage": context.executor_credential_lineage}
    )
    with pytest.raises(ValueError, match="credential lineages MUST be distinct"):
        await IndependentObservationContextVerifier(authenticator=_Authenticator()).verify(
            evidence=event.evidence, claimed_context=shared_lineage
        )


async def test_observation_verifier_rejects_substitution_and_honors_budget() -> None:
    _, _, _, _, context, event = _event_fixture()
    substituted = context.model_copy(
        update={"source_credential_lineage": "credential:substituted:1"}
    )
    verifier = IndependentObservationContextVerifier(
        authenticator=_Authenticator(replacement=substituted)
    )
    with pytest.raises(ValueError, match="differs from claimed"):
        await verifier.verify(evidence=event.evidence, claimed_context=context)

    blocked = IndependentObservationContextVerifier(
        authenticator=_Authenticator(block=True),
        timeout_seconds=0.01,
    )
    with pytest.raises(TimeoutError):
        await blocked.verify(evidence=event.evidence, claimed_context=context)

    assert event.deadline == CREATED_AT + timedelta(minutes=5)
