"""Azure Container Apps executed-action observation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import fdai.delivery.azure.executed_action_observation as observation_module
import pytest
from fdai.core.ontology_platform.reconciliation_binding import (
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectObservationEnvelope,
    ObservationVerificationReceipt,
)
from fdai.delivery.azure.executed_action_observation import (
    AzureContainerAppScaleOutObservationCollector,
)
from fdai.delivery.azure.operational_evidence import AzureOperationalSnapshot
from fdai.shared.contracts.models import Action, Mode

from tests.core.ontology_platform.test_reconciliation import _fixture
from tests.delivery.test_reconciliation_request import _action


class _Snapshots:
    def __init__(self, snapshot: AzureOperationalSnapshot | None) -> None:
        self.snapshot = snapshot

    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
        del resource_ref
        return self.snapshot


class _Issuer:
    def __init__(self, *, mismatch_source: bool = False) -> None:
        self.mismatch_source = mismatch_source

    async def issue(
        self,
        *,
        evidence: EffectObservationEnvelope,
    ) -> AuthenticatedObservationContext:
        receipt = ObservationVerificationReceipt.create(
            observation_id=evidence.observation_id,
            observation_digest=evidence.content_digest(),
            verifier_identity="observation-authenticator",
            verifier_credential_lineage="credential:observation-authenticator:1",
            verified_at=evidence.recorded_at,
            signature_algorithm="ed25519",
            signature="base64:c2lnbmVkLW9ic2VydmF0aW9uLXJlY2VpcHQ",
        )
        return AuthenticatedObservationContext(
            source_authority=evidence.source_authority,
            observer_identity=evidence.observer_identity,
            observer_credential_lineage="credential:heimdall-observer:1",
            executor_identity=evidence.execution_identity,
            executor_credential_lineage="credential:thor-executor:1",
            source_identity=(
                "substituted-source" if self.mismatch_source else evidence.source_identity
            ),
            source_credential_lineage="credential:azure-monitor:1",
            verification_receipt=receipt,
            signature_verified=True,
        )


def _inputs() -> tuple[ResolvedReconciliationArtifacts, Action, AzureOperationalSnapshot]:
    release, target, plan, action_type = _fixture()
    artifacts = ResolvedReconciliationArtifacts(plan, action_type, release)
    action = _action(artifacts).model_copy(
        update={"mode": Mode.ENFORCE, "executor_identity_ref": "executor:thor:1"}
    )
    snapshot = AzureOperationalSnapshot(
        resource_ref=target.id,
        resource_type="microsoft.app/containerapps",
        topology_roles=("workload",),
        ownership_shape=("resource-group-contains-workload",),
        graph_digest="a" * 64,
        owner_digest="b" * 64,
        observed_at=plan.created_at + timedelta(minutes=1),
        evidence_refs=("c" * 64,),
        resource_revision=2,
        metric_values={"replicas": 3.0},
    )
    return artifacts, action, snapshot


async def test_collects_exact_plan_declared_scale_out_property(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, action, snapshot = _inputs()
    monkeypatch.setattr(observation_module, "_ACTION_TYPE", action.action_type)
    collector = AzureContainerAppScaleOutObservationCollector(
        snapshots=_Snapshots(snapshot),
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:1",
        source_identity="source:azure-monitor:1",
        clock=lambda: snapshot.observed_at + timedelta(seconds=1),
    )

    observation = await collector.collect(
        action=action,
        artifacts=artifacts,
        execution_outcome="succeeded",
        execution_completed_at=snapshot.observed_at - timedelta(seconds=1),
        execution_receipt_ref="receipt:provider:1",
        correlation_id="correlation-1",
    )

    assert observation is not None
    assert observation.evidence.records[0].to_record().properties == {"replicas": 3.0}
    assert observation.observation_context.signature_verified is True


async def test_shadow_action_does_not_create_observed_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, action, snapshot = _inputs()
    monkeypatch.setattr(observation_module, "_ACTION_TYPE", action.action_type)
    collector = AzureContainerAppScaleOutObservationCollector(
        snapshots=_Snapshots(snapshot),
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:1",
        source_identity="source:azure-monitor:1",
        clock=lambda: snapshot.observed_at + timedelta(seconds=1),
    )

    assert (
        await collector.collect(
            action=action.model_copy(update={"mode": Mode.SHADOW}),
            artifacts=artifacts,
            execution_outcome="succeeded",
            execution_completed_at=snapshot.observed_at - timedelta(seconds=1),
            execution_receipt_ref=None,
            correlation_id="correlation-1",
        )
        is None
    )


async def test_missing_expected_metric_remains_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, action, snapshot = _inputs()
    monkeypatch.setattr(observation_module, "_ACTION_TYPE", action.action_type)
    collector = AzureContainerAppScaleOutObservationCollector(
        snapshots=_Snapshots(replace(snapshot, metric_values={})),
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:1",
        source_identity="source:azure-monitor:1",
        clock=lambda: snapshot.observed_at + timedelta(seconds=1),
    )

    assert (
        await collector.collect(
            action=action,
            artifacts=artifacts,
            execution_outcome="succeeded",
            execution_completed_at=snapshot.observed_at - timedelta(seconds=1),
            execution_receipt_ref=None,
            correlation_id="correlation-1",
        )
        is None
    )


async def test_substituted_snapshot_target_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, action, snapshot = _inputs()
    monkeypatch.setattr(observation_module, "_ACTION_TYPE", action.action_type)
    collector = AzureContainerAppScaleOutObservationCollector(
        snapshots=_Snapshots(replace(snapshot, resource_ref="other-workload")),
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:1",
        source_identity="source:azure-monitor:1",
        clock=lambda: snapshot.observed_at + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="target or type changed"):
        await collector.collect(
            action=action,
            artifacts=artifacts,
            execution_outcome="succeeded",
            execution_completed_at=snapshot.observed_at - timedelta(seconds=1),
            execution_receipt_ref=None,
            correlation_id="correlation-1",
        )


async def test_substituted_signed_context_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, action, snapshot = _inputs()
    monkeypatch.setattr(observation_module, "_ACTION_TYPE", action.action_type)
    collector = AzureContainerAppScaleOutObservationCollector(
        snapshots=_Snapshots(snapshot),
        context_issuer=_Issuer(mismatch_source=True),
        observer_identity="observer:heimdall:1",
        source_identity="source:azure-monitor:1",
        clock=lambda: snapshot.observed_at + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="signed context does not match"):
        await collector.collect(
            action=action,
            artifacts=artifacts,
            execution_outcome="succeeded",
            execution_completed_at=snapshot.observed_at - timedelta(seconds=1),
            execution_receipt_ref=None,
            correlation_id="correlation-1",
        )


async def test_snapshot_before_terminal_action_is_not_effect_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, action, snapshot = _inputs()
    monkeypatch.setattr(observation_module, "_ACTION_TYPE", action.action_type)
    collector = AzureContainerAppScaleOutObservationCollector(
        snapshots=_Snapshots(snapshot),
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:1",
        source_identity="source:azure-monitor:1",
        clock=lambda: snapshot.observed_at + timedelta(minutes=1),
    )

    assert (
        await collector.collect(
            action=action,
            artifacts=artifacts,
            execution_outcome="succeeded",
            execution_completed_at=snapshot.observed_at + timedelta(seconds=1),
            execution_receipt_ref=None,
            correlation_id="correlation-1",
        )
        is None
    )
