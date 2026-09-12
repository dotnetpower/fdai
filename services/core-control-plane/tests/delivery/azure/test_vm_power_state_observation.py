"""Tests for independent ``ops.start-vm`` effect observation."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fdai.core.ontology_platform.kinetics import ReconciliationStatus
from fdai.core.ontology_platform.reconciliation import (
    EffectReconciliationCoordinator,
    EffectReconciliationRequest,
    InMemoryReconciliationLedger,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectObservationEnvelope,
    ObservationVerificationReceipt,
)
from fdai.delivery.azure.vm_power_state import AzureVmPowerStateReading
from fdai.delivery.azure.vm_power_state_observation import (
    AzureVmStartObservationCollector,
)
from fdai.shared.contracts.models import Mode

from tests.delivery.azure.vm_power_state_fixtures import (
    CREATED_AT,
    RESOURCE_REF,
    vm_start_fixture,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"


class _Source:
    def __init__(self, reading: AzureVmPowerStateReading) -> None:
        self.reading = reading
        self.calls: list[tuple[str, int]] = []

    async def observe(
        self,
        *,
        resource_ref: str,
        target_revision: int,
    ) -> AzureVmPowerStateReading:
        self.calls.append((resource_ref, target_revision))
        return self.reading


class _Issuer:
    def __init__(self, *, substitute_source: bool = False) -> None:
        self.substitute_source = substitute_source

    async def issue(
        self,
        *,
        evidence: EffectObservationEnvelope,
    ) -> AuthenticatedObservationContext:
        receipt = ObservationVerificationReceipt.create(
            observation_id=evidence.observation_id,
            observation_digest=evidence.content_digest(),
            verifier_identity="observer-verifier",
            verifier_credential_lineage="credential:observer-verifier:1",
            verified_at=evidence.recorded_at,
            signature_algorithm="ed25519",
            signature="base64:c3ludGhldGljLXNpZ25hdHVyZQ",
        )
        return AuthenticatedObservationContext(
            source_authority=evidence.source_authority,
            observer_identity=evidence.observer_identity,
            observer_credential_lineage="credential:heimdall:1",
            executor_identity=evidence.execution_identity,
            executor_credential_lineage="credential:thor:1",
            source_identity=(
                "source:substituted" if self.substitute_source else evidence.source_identity
            ),
            source_credential_lineage="credential:azure-reader:1",
            verification_receipt=receipt,
            signature_verified=True,
        )


def _reading(
    *,
    state: str | None = "running",
    complete: bool = True,
    conflicts: tuple[str, ...] = (),
    censoring_refs: tuple[str, ...] = (),
    fresh_for: timedelta = timedelta(minutes=1),
) -> AzureVmPowerStateReading:
    observed_at = CREATED_AT + timedelta(seconds=30)
    return AzureVmPowerStateReading(
        resource_ref=RESOURCE_REF.casefold(),
        target_revision=3,
        state=state,
        observed_at=observed_at,
        recorded_at=observed_at,
        fresh_until=observed_at + fresh_for,
        complete=complete,
        conflicts=conflicts,
        censoring_refs=censoring_refs,
        evidence_refs=("sha256:" + "e" * 64,),
    )


async def _outcome(
    reading: AzureVmPowerStateReading,
    *,
    now_offset: timedelta = timedelta(seconds=31),
):
    artifacts, action = vm_start_fixture()
    collector = AzureVmStartObservationCollector(
        source=_Source(reading),
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:vm-power",
        source_identity="source:azure-arm:vm-power",
        clock=lambda: CREATED_AT + now_offset,
    )
    observation = await collector.collect(
        action=action,
        artifacts=artifacts,
        execution_outcome="succeeded",
        execution_completed_at=CREATED_AT + timedelta(seconds=1),
        execution_receipt_ref="provider-receipt-cannot-prove-effect",
        correlation_id="correlation:vm-start",
    )
    assert observation is not None
    request = EffectReconciliationRequest.create(
        correlation_id="correlation:vm-start",
        plan=artifacts.plan,
        action_type=artifacts.action_type,
        evidence=observation.evidence,
        deadline=observation.deadline,
        evaluated_at=observation.evaluated_at,
    )
    outcome = await EffectReconciliationCoordinator(
        ledger=InMemoryReconciliationLedger()
    ).coordinate(
        request,
        observation_context=observation.observation_context,
        active_release=artifacts.active_release,
    )
    return artifacts, action, observation, outcome


async def test_running_power_state_closes_as_matched() -> None:
    _artifacts, _action, observation, outcome = await _outcome(_reading())

    assert outcome.receipt.status is ReconciliationStatus.MATCHED
    assert observation.evidence.records[0].to_record().properties == {"power_state": "running"}
    assert "provider-receipt-cannot-prove-effect" not in observation.evidence.evidence_refs


async def test_non_running_power_state_is_retained_as_mismatched() -> None:
    _artifacts, _action, _observation, outcome = await _outcome(_reading(state="stopped"))

    assert outcome.receipt.status is ReconciliationStatus.MISMATCHED
    assert outcome.receipt.mismatches == (f"{RESOURCE_REF}:power_state",)


async def test_starting_state_remains_held_until_a_later_running_read() -> None:
    artifacts, action = vm_start_fixture()
    source = _Source(_reading(state="starting"))
    collector = AzureVmStartObservationCollector(
        source=source,
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:vm-power",
        source_identity="source:azure-arm:vm-power",
        clock=lambda: CREATED_AT + timedelta(seconds=31),
    )
    args = dict(
        action=action,
        artifacts=artifacts,
        execution_outcome="succeeded",
        execution_completed_at=CREATED_AT + timedelta(seconds=1),
        execution_receipt_ref=None,
        correlation_id="correlation:vm-start",
    )

    assert await collector.collect(**args) is None
    source.reading = _reading(state="running")
    assert await collector.collect(**args) is not None
    assert len(source.calls) == 2


@pytest.mark.parametrize(
    ("reading", "reason_code"),
    [
        (
            _reading(state=None, complete=False),
            "observation_incomplete",
        ),
        (
            _reading(
                state=None,
                complete=True,
                conflicts=("conflicting_power_state:running",),
            ),
            "observation_conflicted",
        ),
        (
            _reading(fresh_for=timedelta(0)),
            "observation_stale",
        ),
        (
            _reading(censoring_refs=("intervention:later-action",)),
            "observation_censored",
        ),
    ],
)
async def test_unusable_evidence_remains_unscorable(
    reading: AzureVmPowerStateReading,
    reason_code: str,
) -> None:
    _artifacts, _action, _observation, outcome = await _outcome(reading)

    assert outcome.receipt.status is ReconciliationStatus.UNSCORABLE
    assert outcome.recommendation.reason_code == reason_code


async def test_late_evaluation_is_timed_out() -> None:
    _artifacts, _action, _observation, outcome = await _outcome(
        _reading(fresh_for=timedelta(minutes=10)),
        now_offset=timedelta(minutes=6),
    )

    assert outcome.receipt.status is ReconciliationStatus.TIMED_OUT


async def test_shadow_or_failed_execution_is_not_observed() -> None:
    artifacts, action = vm_start_fixture()
    source = _Source(_reading())
    collector = AzureVmStartObservationCollector(
        source=source,
        context_issuer=_Issuer(),
        observer_identity="observer:heimdall:vm-power",
        source_identity="source:azure-arm:vm-power",
        clock=lambda: CREATED_AT + timedelta(seconds=31),
    )
    args = dict(
        artifacts=artifacts,
        execution_completed_at=CREATED_AT + timedelta(seconds=1),
        execution_receipt_ref=None,
        correlation_id="correlation:vm-start",
    )

    assert (
        await collector.collect(
            action=action.model_copy(update={"mode": Mode.SHADOW}),
            execution_outcome="succeeded",
            **args,
        )
        is None
    )
    assert (
        await collector.collect(
            action=action,
            execution_outcome="failed",
            **args,
        )
        is None
    )
    assert source.calls == []


async def test_signed_context_substitution_is_rejected() -> None:
    artifacts, action = vm_start_fixture()
    collector = AzureVmStartObservationCollector(
        source=_Source(_reading()),
        context_issuer=_Issuer(substitute_source=True),
        observer_identity="observer:heimdall:vm-power",
        source_identity="source:azure-arm:vm-power",
        clock=lambda: CREATED_AT + timedelta(seconds=31),
    )

    with pytest.raises(ValueError, match="does not match evidence"):
        await collector.collect(
            action=action,
            artifacts=artifacts,
            execution_outcome="succeeded",
            execution_completed_at=CREATED_AT + timedelta(seconds=1),
            execution_receipt_ref=None,
            correlation_id="correlation:vm-start",
        )


def test_reading_rejects_incomplete_observed_state() -> None:
    with pytest.raises(ValueError, match="completeness"):
        replace(_reading(), complete=False)


def test_vm_power_state_observer_is_not_runtime_wired() -> None:
    forbidden = (
        "fdai.delivery.azure.vm_power_state",
        "fdai.delivery.azure.vm_power_state_observation",
    )
    roots = ("composition", "core/control_loop", "runtime")
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        candidates = (path,) if path.is_file() else path.rglob("*.py")
        for candidate in candidates:
            tree = ast.parse(candidate.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                else:
                    modules = ()
                if any(module.startswith(prefix) for module in modules for prefix in forbidden):
                    violations.append(str(candidate.relative_to(SOURCE_ROOT)))
    assert violations == []
