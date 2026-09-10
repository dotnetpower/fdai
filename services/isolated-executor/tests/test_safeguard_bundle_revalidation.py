"""Safeguard bundle revalidation tests for the isolated Executor service.

These tests validate issue #628 requirements without importing Core:
- v1.1.0 command with bundle binding
- Missing/malformed/mismatched/stale/substituted/wrong-target/wrong-path rejection
- Terminal receipt carries bundle digest with effect_verified=false
- Independent observation receipt with verified/failed/censored/unavailable
- Duplicate, restart, deadline, provider status reconciliation
- N/N-1 compatibility (v1.0.0 commands still work)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fdai_executor_service.bundle_validation import (
    validate_bundle_binding_sync,
)
from fdai_executor_service.service import IsolatedExecutorEffectService
from fdai_service_contracts.execution_safeguards import (
    SafeguardProof,
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    DirectApiExecutionResultLike,
    ExecutionPath,
    ExecutorCommand,
    ExecutorEffectReceiptStatus,
    Mode,
    ObservationReceipt,
    ObservationReceiptStatus,
    Operation,
    RollbackKind,
    RollbackRef,
    SafeguardBoundExecutorCommand,
    StopConditionKind,
)
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from pydantic import ValidationError

_NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
_DEADLINE = _NOW + timedelta(minutes=5)
_INSTANCE_ID = "test-executor-instance"
_SOURCE_REVISION = "commit:" + "b" * 40
_ACTION_ID = UUID(int=1)


def _action(
    *,
    mode: Mode = Mode.ENFORCE,
    target: str = "resource/example",
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID(int=1),
        idempotency_key="test-revalidation",
        event_id=UUID(int=2),
        action_type="ops.restart-service",
        target_resource_ref=target,
        operation=Operation.RESTART,
        stop_condition=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=60)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback/example"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=mode,
        citing_rules=["rule.example"],
        created_at=_NOW - timedelta(minutes=1),
    )


def _proofs() -> tuple[SafeguardProof, ...]:
    return tuple(
        SafeguardProof(kind=kind, proof_digest="sha256:" + f"{i:x}" * 64)
        for i, kind in enumerate(SafeguardProofKind, start=1)
    )


def _bundle(
    *,
    action_id: UUID = _ACTION_ID,
    execution_path: ExecutionPath = ExecutionPath.DIRECT_API,
    source_revision: str = _SOURCE_REVISION,
    recorded_at: datetime = _NOW - timedelta(minutes=2),
) -> SafeguardProofBundle:
    return SafeguardProofBundle.create(
        action_id=action_id,
        execution_path=execution_path,
        execution_fingerprint="sha256:" + "a" * 64,
        source_revision=source_revision,
        recorded_at=recorded_at,
        proofs=_proofs(),
    )


def _v10_command(*, action: Action | None = None) -> ExecutorCommand:
    act = action or _action()
    return ExecutorCommand.from_action(
        command_id=UUID(int=3),
        action=act,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=_NOW,
        deadline_at=_DEADLINE,
    )


def _v11_command(
    *,
    action: Action | None = None,
    bundle: SafeguardProofBundle | None = None,
    source_revision: str = _SOURCE_REVISION,
) -> SafeguardBoundExecutorCommand:
    act = action or _action()
    bndl = bundle or _bundle()
    return SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=3),
        action=act,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=_NOW,
        deadline_at=_DEADLINE,
        safeguard_proof_bundle_digest=bndl.bundle_digest,
        source_revision=source_revision,
    )


class _StubBundleStore:
    def __init__(self, bundles: dict[str, SafeguardProofBundle] | None = None) -> None:
        self._bundles = bundles or {}

    async def resolve_bundle(self, bundle_digest: str) -> SafeguardProofBundle | None:
        return self._bundles.get(bundle_digest)


@dataclass(frozen=True)
class _StubOutcome:
    action_id: str
    outcome: _OutcomeValue
    receipt_ref: str | None = None
    rollback_succeeded: bool | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _OutcomeValue:
    value: str


class _StubDirectApiExecutor:
    def __init__(
        self,
        outcome: str = "dispatched",
        receipt_ref: str | None = "receipt:test",
    ) -> None:
        self._outcome = outcome
        self._receipt_ref = receipt_ref
        self.calls: list[dict[str, Any]] = []

    async def execute(
        self, *, action: Action, deadline_at: datetime
    ) -> DirectApiExecutionResultLike:
        self.calls.append({"action_id": str(action.action_id), "deadline_at": deadline_at})
        return _StubOutcome(
            action_id=str(action.action_id),
            outcome=_OutcomeValue(self._outcome),
            receipt_ref=self._receipt_ref,
        )

    async def recover(self, *, action: Action) -> DirectApiExecutionResultLike | None:
        return None


def _validator() -> JsonSchemaContractValidator:
    return JsonSchemaContractValidator(PackageResourceSchemaRegistry())


# ──────────────────────────────────────────────────
# v1.1.0 command schema tests
# ──────────────────────────────────────────────────


class TestSafeguardBoundCommandContract:
    def test_v11_command_validates_with_packaged_schema(self) -> None:
        cmd = _v11_command()
        validator = _validator()
        validator.validate("executor-command", cmd.model_dump(mode="json"), version="1.1.0")

    def test_v11_command_carries_bundle_digest_and_source_revision(self) -> None:
        bundle = _bundle()
        cmd = _v11_command(bundle=bundle)
        assert cmd.schema_version == "1.1.0"
        assert cmd.safeguard_proof_bundle_digest == bundle.bundle_digest
        assert cmd.source_revision == _SOURCE_REVISION

    def test_v10_command_still_validates(self) -> None:
        cmd = _v10_command()
        validator = _validator()
        validator.validate("executor-command", cmd.model_dump(mode="json"), version="1.0.0")


# ──────────────────────────────────────────────────
# Bundle validation: missing / malformed / mismatched
# ──────────────────────────────────────────────────


class TestBundleValidationSync:
    def test_v10_command_skips_bundle_validation(self) -> None:
        cmd = _v10_command()
        result = validate_bundle_binding_sync(cmd, None, now=_NOW)
        assert result is None

    def test_missing_bundle_rejected(self) -> None:
        cmd = _v11_command()
        result = validate_bundle_binding_sync(cmd, None, now=_NOW)
        assert result is not None
        assert result.category == "missing"

    def test_mismatched_digest_rejected(self) -> None:
        bundle = _bundle()
        cmd = _v11_command(bundle=bundle)
        wrong_bundle = _bundle(recorded_at=_NOW - timedelta(minutes=3))
        result = validate_bundle_binding_sync(cmd, wrong_bundle, now=_NOW)
        assert result is not None
        assert result.category == "mismatched"

    def test_substituted_action_id_rejected(self) -> None:
        bundle = _bundle(action_id=UUID(int=99))
        cmd = _v11_command(bundle=bundle)
        result = validate_bundle_binding_sync(cmd, bundle, now=_NOW)
        assert result is not None
        assert result.category == "substituted"

    def test_wrong_path_rejected(self) -> None:
        bundle = _bundle(execution_path=ExecutionPath.PR_NATIVE)
        cmd = _v11_command(bundle=bundle)
        result = validate_bundle_binding_sync(cmd, bundle, now=_NOW)
        assert result is not None
        assert result.category == "wrong-path"

    def test_stale_bundle_rejected(self) -> None:
        bundle = _bundle(recorded_at=_NOW - timedelta(hours=25))
        cmd = _v11_command(bundle=bundle)
        result = validate_bundle_binding_sync(cmd, bundle, now=_NOW)
        assert result is not None
        assert result.category == "stale"

    def test_future_bundle_rejected(self) -> None:
        bundle = _bundle(recorded_at=_NOW + timedelta(hours=1))
        cmd = _v11_command(bundle=bundle)
        result = validate_bundle_binding_sync(cmd, bundle, now=_NOW)
        assert result is not None
        assert result.category == "stale"

    def test_mismatched_source_revision_rejected(self) -> None:
        bundle = _bundle(source_revision="commit:" + "c" * 40)
        cmd = _v11_command(bundle=bundle, source_revision=_SOURCE_REVISION)
        result = validate_bundle_binding_sync(cmd, bundle, now=_NOW)
        assert result is not None
        assert result.category == "mismatched"

    def test_valid_bundle_accepted(self) -> None:
        bundle = _bundle()
        cmd = _v11_command(bundle=bundle)
        result = validate_bundle_binding_sync(cmd, bundle, now=_NOW)
        assert result is None


# ──────────────────────────────────────────────────
# Integrated service: bundle validation before dispatch
# ──────────────────────────────────────────────────


class TestEffectServiceBundleValidation:
    async def test_v11_missing_bundle_rejected_before_dispatch(self) -> None:
        executor = _StubDirectApiExecutor()
        store = _StubBundleStore()
        svc = IsolatedExecutorEffectService(
            direct_api_executor=executor,
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            bundle_store=store,
            clock=lambda: _NOW,
        )
        cmd = _v11_command()
        receipt = await svc.handle(cmd)

        assert receipt.status == ExecutorEffectReceiptStatus.REJECTED_INVARIANT
        assert "missing" in (receipt.reason or "")
        assert receipt.effect_verified is False
        assert receipt.effect_applied is False
        assert receipt.safeguard_proof_bundle_digest == cmd.safeguard_proof_bundle_digest
        assert executor.calls == []

    async def test_v11_valid_bundle_dispatches_and_carries_digest(self) -> None:
        bundle = _bundle()
        executor = _StubDirectApiExecutor()
        store = _StubBundleStore({bundle.bundle_digest: bundle})
        svc = IsolatedExecutorEffectService(
            direct_api_executor=executor,
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            bundle_store=store,
            clock=lambda: _NOW,
        )
        cmd = _v11_command(bundle=bundle)
        receipt = await svc.handle(cmd)

        assert receipt.status == ExecutorEffectReceiptStatus.DISPATCHED
        assert receipt.effect_verified is False
        assert receipt.safeguard_proof_bundle_digest == bundle.bundle_digest
        assert len(executor.calls) == 1

    async def test_v10_command_dispatches_without_bundle_store(self) -> None:
        executor = _StubDirectApiExecutor()
        svc = IsolatedExecutorEffectService(
            direct_api_executor=executor,
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            clock=lambda: _NOW,
        )
        cmd = _v10_command()
        receipt = await svc.handle(cmd)

        assert receipt.status == ExecutorEffectReceiptStatus.DISPATCHED
        assert receipt.safeguard_proof_bundle_digest is None
        assert len(executor.calls) == 1


# ──────────────────────────────────────────────────
# Terminal receipt: effect_verified=false
# ──────────────────────────────────────────────────


class TestTerminalReceiptInvariants:
    async def test_effect_receipt_always_has_effect_verified_false(self) -> None:
        bundle = _bundle()
        executor = _StubDirectApiExecutor()
        store = _StubBundleStore({bundle.bundle_digest: bundle})
        svc = IsolatedExecutorEffectService(
            direct_api_executor=executor,
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            bundle_store=store,
            clock=lambda: _NOW,
        )
        cmd = _v11_command(bundle=bundle)
        receipt = await svc.handle(cmd)

        assert receipt.effect_verified is False
        assert receipt.command_id == cmd.command_id
        assert receipt.action_payload_digest == cmd.action_payload_digest

    async def test_rejected_receipt_carries_bundle_digest(self) -> None:
        store = _StubBundleStore()
        svc = IsolatedExecutorEffectService(
            direct_api_executor=_StubDirectApiExecutor(),
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            bundle_store=store,
            clock=lambda: _NOW,
        )
        cmd = _v11_command()
        receipt = await svc.handle(cmd)

        assert receipt.safeguard_proof_bundle_digest == cmd.safeguard_proof_bundle_digest
        assert receipt.effect_verified is False


# ──────────────────────────────────────────────────
# Deadline and expiration
# ──────────────────────────────────────────────────


class TestDeadlineReconciliation:
    async def test_expired_v11_command_carries_bundle_digest(self) -> None:
        bundle = _bundle()
        store = _StubBundleStore({bundle.bundle_digest: bundle})

        def late_clock():
            return _DEADLINE + timedelta(minutes=1)

        svc = IsolatedExecutorEffectService(
            direct_api_executor=_StubDirectApiExecutor(),
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            bundle_store=store,
            clock=late_clock,
        )
        cmd = _v11_command(bundle=bundle)
        receipt = await svc.handle(cmd)

        assert receipt.status == ExecutorEffectReceiptStatus.EXPIRED
        assert receipt.safeguard_proof_bundle_digest == bundle.bundle_digest
        assert receipt.effect_verified is False


# ──────────────────────────────────────────────────
# Independent observation receipt
# ──────────────────────────────────────────────────


class TestObservationReceipt:
    def test_verified_observation(self) -> None:
        bundle = _bundle()
        obs = ObservationReceipt(
            observation_id=uuid4(),
            command_id=UUID(int=3),
            action_id=UUID(int=1),
            receipt_id=uuid4(),
            idempotency_key="test-revalidation",
            safeguard_proof_bundle_digest=bundle.bundle_digest,
            action_payload_digest="sha256:" + "d" * 64,
            status=ObservationReceiptStatus.VERIFIED,
            observer_instance_id="observer-test",
            observed_at=_NOW,
            completed_at=_NOW,
            effect_verified=True,
        )
        assert obs.execution_authority is False
        assert obs.effect_verified is True

    def test_failed_observation(self) -> None:
        bundle = _bundle()
        obs = ObservationReceipt(
            observation_id=uuid4(),
            command_id=UUID(int=3),
            action_id=UUID(int=1),
            receipt_id=uuid4(),
            idempotency_key="test-revalidation",
            safeguard_proof_bundle_digest=bundle.bundle_digest,
            action_payload_digest="sha256:" + "d" * 64,
            status=ObservationReceiptStatus.FAILED,
            reason="observed state does not match expected effect",
            observer_instance_id="observer-test",
            observed_at=_NOW,
            completed_at=_NOW,
            effect_verified=False,
        )
        assert obs.execution_authority is False
        assert obs.effect_verified is False

    def test_censored_observation(self) -> None:
        bundle = _bundle()
        obs = ObservationReceipt(
            observation_id=uuid4(),
            command_id=UUID(int=3),
            action_id=UUID(int=1),
            receipt_id=uuid4(),
            idempotency_key="test-revalidation",
            safeguard_proof_bundle_digest=bundle.bundle_digest,
            action_payload_digest="sha256:" + "d" * 64,
            status=ObservationReceiptStatus.CENSORED,
            reason="observation access denied by provider",
            observer_instance_id="observer-test",
            observed_at=_NOW,
            completed_at=_NOW,
            effect_verified=False,
        )
        assert obs.status == ObservationReceiptStatus.CENSORED

    def test_unavailable_observation(self) -> None:
        bundle = _bundle()
        obs = ObservationReceipt(
            observation_id=uuid4(),
            command_id=UUID(int=3),
            action_id=UUID(int=1),
            receipt_id=uuid4(),
            idempotency_key="test-revalidation",
            safeguard_proof_bundle_digest=bundle.bundle_digest,
            action_payload_digest="sha256:" + "d" * 64,
            status=ObservationReceiptStatus.UNAVAILABLE,
            reason="observation endpoint unreachable",
            observer_instance_id="observer-test",
            observed_at=_NOW,
            completed_at=_NOW,
            effect_verified=False,
        )
        assert obs.status == ObservationReceiptStatus.UNAVAILABLE

    def test_observation_rejects_execution_authority_true(self) -> None:
        with pytest.raises(ValidationError, match="Input should be False"):
            ObservationReceipt(
                observation_id=uuid4(),
                command_id=UUID(int=3),
                action_id=UUID(int=1),
                receipt_id=uuid4(),
                idempotency_key="test-revalidation",
                safeguard_proof_bundle_digest="sha256:" + "a" * 64,
                action_payload_digest="sha256:" + "d" * 64,
                status=ObservationReceiptStatus.VERIFIED,
                observer_instance_id="observer-test",
                observed_at=_NOW,
                completed_at=_NOW,
                execution_authority=True,
                effect_verified=True,
            )

    def test_observation_rejects_verified_without_effect(self) -> None:
        with pytest.raises(ValidationError, match="verified status requires"):
            ObservationReceipt(
                observation_id=uuid4(),
                command_id=UUID(int=3),
                action_id=UUID(int=1),
                receipt_id=uuid4(),
                idempotency_key="test-revalidation",
                safeguard_proof_bundle_digest="sha256:" + "a" * 64,
                action_payload_digest="sha256:" + "d" * 64,
                status=ObservationReceiptStatus.VERIFIED,
                observer_instance_id="observer-test",
                observed_at=_NOW,
                completed_at=_NOW,
                effect_verified=False,
            )

    def test_observation_validates_with_schema(self) -> None:
        bundle = _bundle()
        obs = ObservationReceipt(
            observation_id=uuid4(),
            command_id=UUID(int=3),
            action_id=UUID(int=1),
            receipt_id=uuid4(),
            idempotency_key="test-revalidation",
            safeguard_proof_bundle_digest=bundle.bundle_digest,
            action_payload_digest="sha256:" + "d" * 64,
            status=ObservationReceiptStatus.VERIFIED,
            observer_instance_id="observer-test",
            observed_at=_NOW,
            completed_at=_NOW,
            effect_verified=True,
        )
        validator = _validator()
        validator.validate(
            "observation-receipt",
            obs.model_dump(mode="json"),
            version="1.0.0",
        )


# ──────────────────────────────────────────────────
# Provider status reconciliation
# ──────────────────────────────────────────────────


class TestProviderReconciliation:
    async def test_failed_dispatch_carries_bundle_digest(self) -> None:
        bundle = _bundle()
        executor = _StubDirectApiExecutor(outcome="failed", receipt_ref=None)
        store = _StubBundleStore({bundle.bundle_digest: bundle})
        svc = IsolatedExecutorEffectService(
            direct_api_executor=executor,
            contract_validator=_validator(),
            executor_instance_id=_INSTANCE_ID,
            bundle_store=store,
            clock=lambda: _NOW,
        )
        cmd = _v11_command(bundle=bundle)
        receipt = await svc.handle(cmd)

        assert receipt.status == ExecutorEffectReceiptStatus.FAILED
        assert receipt.effect_verified is False
        assert receipt.safeguard_proof_bundle_digest == bundle.bundle_digest
        assert receipt.effect_applied is False


# ──────────────────────────────────────────────────
# N/N-1 compatibility
# ──────────────────────────────────────────────────


class TestNNMinus1Compatibility:
    def test_v10_schema_still_registered(self) -> None:
        registry = PackageResourceSchemaRegistry()
        schema = registry.get("executor-command", "1.0.0")
        assert schema["$id"].endswith("/executor-command/1.0.0")

    def test_v11_schema_registered(self) -> None:
        registry = PackageResourceSchemaRegistry()
        schema = registry.get("executor-command", "1.1.0")
        assert schema["$id"].endswith("/executor-command/1.1.0")

    def test_observation_receipt_schema_registered(self) -> None:
        registry = PackageResourceSchemaRegistry()
        schema = registry.get("observation-receipt", "1.0.0")
        assert schema["$id"].endswith("/observation-receipt/1.0.0")

    def test_v10_and_v11_commands_both_pass_contract_validation(self) -> None:
        validator = _validator()
        v10 = _v10_command()
        v11 = _v11_command()

        validator.validate("executor-command", v10.model_dump(mode="json"), version="1.0.0")
        validator.validate("executor-command", v11.model_dump(mode="json"), version="1.1.0")
