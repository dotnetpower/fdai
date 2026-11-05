"""Focused checks for isolated-Executor effect safety helpers."""

from datetime import UTC, datetime, timedelta, tzinfo

import pytest
from fdai_executor_service.effect_safety import deadline_expired


class _UnresolvedTimezone(tzinfo):
    def utcoffset(self, _dt: datetime | None) -> None:
        return None

    def dst(self, _dt: datetime | None) -> None:
        return None


def test_deadline_expires_at_the_exact_boundary() -> None:
    deadline_at = datetime(2026, 9, 11, tzinfo=UTC)

    assert deadline_expired(deadline_at - timedelta(microseconds=1), deadline_at) is False
    assert deadline_expired(deadline_at, deadline_at) is True


@pytest.mark.parametrize(
    ("now", "deadline_at"),
    [
        (datetime(2026, 9, 11), datetime(2026, 9, 12, tzinfo=UTC)),
        (
            datetime(2026, 9, 11, tzinfo=_UnresolvedTimezone()),
            datetime(2026, 9, 12, tzinfo=UTC),
        ),
    ],
)
def test_deadline_rejects_unresolved_timezones(
    now: datetime,
    deadline_at: datetime,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        deadline_expired(now, deadline_at)


def _valid_action() -> object:
    from uuid import UUID

    from fdai_service_contracts.executor import (
        Action,
        ActionStopCondition,
        BlastRadius,
        BlastRadiusScope,
        Mode,
        Operation,
        RollbackKind,
        RollbackRef,
        StopConditionKind,
    )

    now = datetime(2026, 9, 11, tzinfo=UTC)
    return Action(
        schema_version="1.0.0",
        action_id=UUID(int=10),
        idempotency_key="safety-key-1",
        event_id=UUID(int=11),
        action_type="ops.start-vm",
        target_resource_ref="/resourcegroups/example/providers/microsoft.compute/virtualmachines/vm-app",
        operation=Operation.ENABLE,
        params={"resource_group": "example", "vm_name": "vm-app"},
        stop_condition=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=60)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback/example"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.ENFORCE,
        citing_rules=["rule.example"],
        created_at=now,
        executor_identity_ref="identity/resilience",
    )


def test_effect_safety_invariants_blast_radius_and_target_binding() -> None:
    from types import SimpleNamespace

    from fdai_executor_service.effect_executor import DirectApiEffectConfig
    from fdai_executor_service.effect_safety import (
        blast_radius_refusal,
        build_direct_api_request,
        missing_safety_invariant,
        target_binding_refusal,
    )
    from fdai_service_contracts.executor import Action, BlastRadius, BlastRadiusScope, RollbackRef

    base: Action = _valid_action()  # type: ignore[assignment]
    assert missing_safety_invariant(base) is None

    no_stop = base.model_construct(**{**base.__dict__, "stop_condition": "   "})
    assert "safety invariant 1" in (missing_safety_invariant(no_stop) or "")

    no_rb = base.model_construct(
        **{**base.__dict__, "rollback_ref": SimpleNamespace(kind="", reference=None)}
    )
    assert "safety invariant 2" in (missing_safety_invariant(no_rb) or "")

    no_br = base.model_construct(**{**base.__dict__, "blast_radius": None})
    assert "safety invariant 3" in (missing_safety_invariant(no_br) or "")

    no_rules = base.model_construct(**{**base.__dict__, "citing_rules": []})
    assert "citing_rules" in (missing_safety_invariant(no_rules) or "")

    ceilings = DirectApiEffectConfig(max_affected_resources=2, max_rate_per_minute=10)
    assert blast_radius_refusal(base, ceilings) is None

    undeclared = base.model_copy(
        update={
            "blast_radius": BlastRadius.model_construct(
                scope=BlastRadiusScope.RESOURCE, count=None, rate_per_minute=None
            )
        }
    )
    assert blast_radius_refusal(undeclared, ceilings) == "blast-radius count is undeclared"

    too_many = base.model_copy(
        update={"blast_radius": BlastRadius(scope=BlastRadiusScope.RESOURCE, count=3)}
    )
    assert "exceeds executor cap 2" in (blast_radius_refusal(too_many, ceilings) or "")

    too_fast = base.model_copy(
        update={
            "blast_radius": BlastRadius(
                scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=11
            )
        }
    )
    assert "exceeds executor cap 10/min" in (blast_radius_refusal(too_fast, ceilings) or "")

    human_bad = base.model_copy(
        update={"action_type": "ops.apply-human-access", "target_resource_ref": "bad"}
    )
    assert "original normalized membership target" in (target_binding_refusal(human_bad) or "")

    human_ok = base.model_copy(
        update={
            "action_type": "ops.apply-human-access",
            "target_resource_ref": "human-membership:" + "a" * 64,
            "executor_identity_ref": "identity/human-access",
        }
    )
    assert target_binding_refusal(human_ok) is None
    req_human = build_direct_api_request(
        human_ok.model_copy(
            update={
                "rollback_ref": RollbackRef(
                    kind=base.rollback_ref.kind,
                    reference=None,
                )
            }
        ),
        deadline_at=None,
    )
    assert "command_deadline_at" not in req_human.metadata
    assert ":" not in req_human.metadata["rollback_ref"]

    tag_action = base.model_copy(
        update={
            "action_type": "remediate.tag-add",
            "target_resource_ref": (
                "scope-0123456789abcdef/resource-group/example/"
                "providers/microsoft.storage/storageaccounts/storage-app"
            ),
            "params": {"tag_name": "env", "tag_value": "dev"},
        }
    )
    assert target_binding_refusal(tag_action) is None

    invalid_azure = base.model_copy(update={"action_type": "ops.unknown", "params": {}})
    assert "canonical Azure target" in (target_binding_refusal(invalid_azure) or "")

    mismatch_azure = base.model_copy(update={"target_resource_ref": "other"})
    assert "MUST exactly match" in (target_binding_refusal(mismatch_azure) or "")


async def test_effect_executor_guards_dedupe_recovery_and_provider_errors() -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from fdai_executor_service.effect_executor import (
        DirectApiEffectConfig,
        DirectApiEffectOutcome,
        ServiceDirectApiEffectExecutor,
    )
    from fdai_service_contracts.executor import (
        Action,
        BlastRadius,
        BlastRadiusScope,
        DirectApiAuthenticationError,
        DirectApiError,
        DirectApiNetworkDeniedError,
        DirectApiOutcome,
        DirectApiPermissionDeniedError,
        DirectApiPolicyDeniedError,
        DirectApiPreconditionError,
        DirectApiPromotionError,
        DirectApiReceipt,
        DirectApiRequest,
        Mode,
    )

    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    base: Action = _valid_action()  # type: ignore[assignment]

    class _Lock:
        @asynccontextmanager
        async def acquire(self, _key: str) -> AsyncIterator[None]:
            yield

    class _AuditStore:
        def __init__(self) -> None:
            self.entries: list[dict[str, object]] = []

        async def append_audit_entry(self, entry: object) -> None:
            self.entries.append(dict(entry))  # type: ignore[arg-type]

        async def read_state(self, _key: str) -> None:
            return None

    class _Idempotency:
        def __init__(self) -> None:
            self.records: dict[str, dict[str, object]] = {}

        async def seen(self, key: str) -> dict[str, object] | None:
            return self.records.get(key)

        async def record(self, key: str, payload: object) -> bool:
            self.records[key] = dict(payload)  # type: ignore[arg-type]
            return True

    class _Provider:
        def __init__(self) -> None:
            self.mode = "ok"
            self.status_mode = "none"

        async def execute(self, _request: DirectApiRequest) -> DirectApiReceipt:
            if isinstance(self.mode, Exception):
                raise self.mode
            if self.mode == "boom":
                raise ValueError("uncontrolled")
            return DirectApiReceipt(
                outcome=DirectApiOutcome(self.mode)
                if self.mode != "ok"
                else DirectApiOutcome.SUCCEEDED,
                receipt_ref="r:1",
            )

        async def operation_status(self, _request: DirectApiRequest) -> DirectApiReceipt | None:
            if isinstance(self.status_mode, Exception):
                raise self.status_mode
            if self.status_mode == "boom":
                raise ValueError("uncontrolled status")
            if self.status_mode == "none":
                return None
            return DirectApiReceipt(
                outcome=DirectApiOutcome.ALREADY_APPLIED,
                receipt_ref="r:status",
            )

    provider = _Provider()
    audit = _AuditStore()
    idem = _Idempotency()

    shadow_only = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,  # type: ignore[arg-type]
        resource_lock=_Lock(),
        idempotency=idem,
        allow_enforce=False,
        clock=lambda: now,
    )
    assert (await shadow_only.execute(action=base)).outcome is DirectApiEffectOutcome.REJECTED_MODE
    assert await shadow_only.recover(action=base) is None

    service = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,  # type: ignore[arg-type]
        resource_lock=_Lock(),
        idempotency=idem,
        allow_enforce=True,
        config=DirectApiEffectConfig(
            max_affected_resources=2, max_rate_per_minute=10, max_dedupe_entries=1
        ),
        clock=lambda: now,
    )

    bad_inv = base.model_construct(**{**base.__dict__, "stop_condition": ""})
    assert (
        await service.execute(action=bad_inv)
    ).outcome is DirectApiEffectOutcome.REJECTED_INVARIANT
    assert await service.recover(action=bad_inv) is None

    bad_target = base.model_copy(update={"target_resource_ref": "wrong"})
    assert (
        await service.execute(action=bad_target)
    ).outcome is DirectApiEffectOutcome.REJECTED_INVARIANT
    assert (
        await service.recover(action=bad_target)
    ).outcome is DirectApiEffectOutcome.REJECTED_INVARIANT  # type: ignore[union-attr]

    big_blast = base.model_copy(
        update={"blast_radius": BlastRadius(scope=BlastRadiusScope.RESOURCE, count=5)}
    )
    assert (
        await service.execute(action=big_blast)
    ).outcome is DirectApiEffectOutcome.ABSTAINED_BLAST_RADIUS

    shadow_act = base.model_copy(update={"mode": Mode.SHADOW, "idempotency_key": "shadow-1"})
    assert (
        await service.execute(action=shadow_act, upstream_target_lock_held=True)
    ).outcome is DirectApiEffectOutcome.DISPATCHED

    dispatched = await service.execute(action=base, deadline_at=now + timedelta(seconds=30))
    assert dispatched.outcome is DirectApiEffectOutcome.DISPATCHED
    assert (await service.execute(action=base)) == dispatched
    assert (await service.recover(action=base)) == dispatched

    conflict = base.model_copy(update={"citing_rules": ["rule.other"]})
    assert (
        await service.execute(action=conflict)
    ).outcome is DirectApiEffectOutcome.REJECTED_IDEMPOTENCY_CONFLICT

    service._dedupe.clear()
    assert (await service.execute(action=base)).outcome is DirectApiEffectOutcome.DISPATCHED
    service._dedupe.clear()
    assert (await service.recover(action=base)).outcome is DirectApiEffectOutcome.DISPATCHED  # type: ignore[union-attr]

    # Eviction and key replacement in _remember
    act2 = base.model_copy(update={"idempotency_key": "key-2"})
    await service.execute(action=act2)
    service._remember("key-2::enforce", dispatched)

    # Expired deadline with provider status recovery vs no status recovery
    exp_act = base.model_copy(update={"idempotency_key": "exp-1"})
    provider.status_mode = "none"
    assert (
        await service.execute(action=exp_act, deadline_at=now - timedelta(seconds=1))
    ).outcome is DirectApiEffectOutcome.EXPIRED
    provider.status_mode = "ok"
    assert (
        await service.execute(action=exp_act, deadline_at=now - timedelta(seconds=1))
    ).outcome is DirectApiEffectOutcome.ALREADY_APPLIED

    # Recover paths through provider status
    rec_act = base.model_copy(update={"idempotency_key": "rec-1"})
    provider.status_mode = "none"
    assert await service.recover(action=rec_act) is None
    provider.status_mode = DirectApiPermissionDeniedError("denied")
    assert (
        await service.recover(action=rec_act)
    ).outcome is DirectApiEffectOutcome.PERMISSION_DENIED  # type: ignore[union-attr]
    provider.status_mode = "boom"
    assert (await service.recover(action=rec_act)).outcome is DirectApiEffectOutcome.FAILED  # type: ignore[union-attr]

    # Naive deadline handling inside execute
    naive_service = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,  # type: ignore[arg-type]
        resource_lock=_Lock(),
        idempotency=None,
        allow_enforce=True,
        clock=lambda: datetime(2026, 9, 11, 12, 0),
    )
    assert (
        await naive_service.execute(action=rec_act, deadline_at=now)
    ).outcome is DirectApiEffectOutcome.REJECTED_INVARIANT

    # All classified provider errors + uncontrolled error
    for idx, (err, expected) in enumerate(
        [
            (DirectApiPromotionError("p"), DirectApiEffectOutcome.REJECTED_MODE),
            (DirectApiPreconditionError("p"), DirectApiEffectOutcome.ABSTAINED_PRECONDITION),
            (DirectApiAuthenticationError("p"), DirectApiEffectOutcome.AUTHENTICATION_FAILED),
            (DirectApiPermissionDeniedError("p"), DirectApiEffectOutcome.PERMISSION_DENIED),
            (DirectApiPolicyDeniedError("p"), DirectApiEffectOutcome.POLICY_DENIED),
            (DirectApiNetworkDeniedError("p"), DirectApiEffectOutcome.NETWORK_DENIED),
            (DirectApiError("code", "p"), DirectApiEffectOutcome.FAILED),
            ("boom", DirectApiEffectOutcome.FAILED),
        ]
    ):
        provider.mode = err  # type: ignore[assignment]
        err_act = base.model_copy(update={"idempotency_key": f"err-{idx}"})
        res = await service.execute(action=err_act)
        assert res.outcome is expected


async def test_effect_and_shadow_services_handle_all_branches() -> None:
    from uuid import UUID

    from fdai_executor_service.bundle_validation import (
        BundleValidationRefusal,
        ResolvedSafeguardBundle,
    )
    from fdai_executor_service.effect_executor import DirectApiEffectOutcome, DirectApiEffectResult
    from fdai_executor_service.service import (
        ExecutorCommandConflictError,
        IsolatedExecutorEffectService,
        IsolatedExecutorShadowService,
        _attempt_key,
        _decode_state_record,
        _delivery_key,
        _legacy_attempt_key,
    )
    from fdai_service_contracts.execution_safeguards import (
        SafeguardProof,
        SafeguardProofBundle,
        SafeguardProofKind,
    )
    from fdai_service_contracts.executor import (
        Action,
        ExecutionPath,
        ExecutorCommand,
        ExecutorEffectReceiptStatus,
        ExecutorShadowReceiptStatus,
        Mode,
        SafeguardBoundExecutorCommand,
    )
    from fdai_service_contracts.executor_models import executor_action_fingerprint
    from fdai_service_contracts.schema import (
        JsonSchemaContractValidator,
        PackageResourceSchemaRegistry,
    )

    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    base: Action = _valid_action()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="executor instance id"):
        IsolatedExecutorEffectService(
            direct_api_executor=object(),  # type: ignore[arg-type]
            contract_validator=validator,
            executor_instance_id="",
        )
    with pytest.raises(ValueError, match="executor instance id"):
        IsolatedExecutorShadowService(
            state_store=object(),  # type: ignore[arg-type]
            contract_validator=validator,
            executor_instance_id="",
        )

    class _DirectExec:
        def __init__(self) -> None:
            self.recovered: DirectApiEffectResult | None = None

        async def execute(self, **_kwargs: object) -> DirectApiEffectResult:
            return DirectApiEffectResult(
                action_id=str(base.action_id),
                outcome=DirectApiEffectOutcome.DISPATCHED,
                mode=Mode.ENFORCE,
                receipt_ref="r:ok",
            )

        async def recover(self, **_kwargs: object) -> DirectApiEffectResult | None:
            return self.recovered

    fp = "sha256:" + executor_action_fingerprint(
        action_payload=base.model_dump(mode="json", exclude_none=False),
        execution_path=ExecutionPath.DIRECT_API.value,
    )
    stale_bundle = SafeguardProofBundle.create(
        action_id=base.action_id,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint=fp,
        source_revision="commit:" + "b" * 40,
        recorded_at=now - timedelta(days=2),
        proofs=tuple(
            SafeguardProof(kind=k, proof_digest="sha256:" + f"{i:x}" * 64)
            for i, k in enumerate(SafeguardProofKind, start=1)
        ),
    )

    class _BundleStore:
        async def resolve_bundle(self, _d: str) -> SafeguardProofBundle | None:
            return stale_bundle

        async def resolve_bundle_context(self, _d: str) -> ResolvedSafeguardBundle | None:
            return ResolvedSafeguardBundle(bundle=stale_bundle, reservation_attempt=1)

    direct_exec = _DirectExec()
    eff_svc = IsolatedExecutorEffectService(
        direct_api_executor=direct_exec,
        contract_validator=validator,
        executor_instance_id="exec-1",
        bundle_store=_BundleStore(),
        allow_legacy_unbound_commands=True,
        clock=lambda: now,
    )

    # Expired + stale bundle -> REJECTED_INVARIANT; with recovered -> DISPATCHED
    expired_bound = SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=20),
        action=base,
        execution_path=ExecutionPath.DIRECT_API,
        safeguard_proof_bundle_digest=stale_bundle.bundle_digest,
        source_revision="commit:" + "b" * 40,
        attempt=1,
        issued_at=now - timedelta(minutes=5),
        deadline_at=now - timedelta(minutes=1),
    )
    r_stale_exp = await eff_svc.handle(expired_bound)
    assert r_stale_exp.status is ExecutorEffectReceiptStatus.REJECTED_INVARIANT

    direct_exec.recovered = DirectApiEffectResult(
        action_id=str(base.action_id),
        outcome=DirectApiEffectOutcome.ALREADY_APPLIED,
        mode=Mode.ENFORCE,
        receipt_ref="r:rec",
    )
    r_rec = await eff_svc.handle(expired_bound)
    assert r_rec.status is ExecutorEffectReceiptStatus.ALREADY_APPLIED

    # Not expired + stale bundle -> REJECTED_INVARIANT
    active_bound = SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=21),
        action=base,
        execution_path=ExecutionPath.DIRECT_API,
        safeguard_proof_bundle_digest=stale_bundle.bundle_digest,
        source_revision="commit:" + "b" * 40,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    assert (
        await eff_svc.handle(active_bound)
    ).status is ExecutorEffectReceiptStatus.REJECTED_INVARIANT

    # Legacy unbound non-DIRECT_API path -> REJECTED_INVARIANT
    pr_cmd = ExecutorCommand.from_action(
        command_id=UUID(int=22),
        action=base,
        execution_path=ExecutionPath.PR_NATIVE,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    assert (await eff_svc.handle(pr_cmd)).status is ExecutorEffectReceiptStatus.REJECTED_INVARIANT

    # Shadow service tests
    class _MemStateStore:
        def __init__(self) -> None:
            self.data: dict[str, dict[str, object]] = {}
            self.fail_write = False

        async def read_state(self, key: str) -> dict[str, object] | None:
            return self.data.get(key)

        async def write_state_with_audit_if_absent(
            self, key: str, val: object, _aud: object
        ) -> bool:
            if self.fail_write or key in self.data:
                return False
            self.data[key] = dict(val)  # type: ignore[arg-type]
            return True

        async def append_audit_entry(self, _entry: object) -> None:
            return None

    mem_store = _MemStateStore()
    shadow_svc = IsolatedExecutorShadowService(
        state_store=mem_store,
        contract_validator=validator,
        executor_instance_id="shadow-1",
        clock=lambda: now,
    )
    shadow_act = base.model_copy(update={"mode": Mode.SHADOW})
    cmd1 = ExecutorCommand.from_action(
        command_id=UUID(int=30),
        action=shadow_act,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    rec1 = await shadow_svc.handle(cmd1)
    assert rec1.status is ExecutorShadowReceiptStatus.SHADOWED
    assert await shadow_svc.handle(cmd1) == rec1

    # Same action intent, different command_id/attempt -> DUPLICATE + replay secondary
    cmd1_retry = ExecutorCommand.from_action(
        command_id=UUID(int=31),
        action=shadow_act,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=2,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    dup_rec = await shadow_svc.handle(cmd1_retry)
    assert dup_rec.status is ExecutorShadowReceiptStatus.DUPLICATE
    assert await shadow_svc.handle(cmd1_retry) == dup_rec

    # Conflicting envelope on same delivery key -> ExecutorCommandConflictError
    deliv_key = _delivery_key(cmd1_retry.idempotency_key, str(cmd1_retry.command_id))
    mem_store.data[deliv_key]["command"] = cmd1.model_dump(mode="json")
    with pytest.raises(ExecutorCommandConflictError):
        await shadow_svc.handle(cmd1_retry)

    # Different action payload on same idempotency_key -> REJECTED
    other_act = shadow_act.model_copy(update={"action_id": UUID(int=99)})
    cmd_conflict = ExecutorCommand.from_action(
        command_id=UUID(int=32),
        action=other_act,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    rej_rec = await shadow_svc.handle(cmd_conflict)
    assert rej_rec.status is ExecutorShadowReceiptStatus.REJECTED

    # Enforce command and expired command in shadow service
    enf_cmd = ExecutorCommand.from_action(
        command_id=UUID(int=33),
        action=base.model_copy(update={"idempotency_key": "enf-shadow"}),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    assert (await shadow_svc.handle(enf_cmd)).status is ExecutorShadowReceiptStatus.REJECTED

    exp_cmd = ExecutorCommand.from_action(
        command_id=UUID(int=34),
        action=shadow_act.model_copy(update={"idempotency_key": "exp-shadow"}),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now - timedelta(minutes=5),
        deadline_at=now - timedelta(minutes=1),
    )
    assert (await shadow_svc.handle(exp_cmd)).status is ExecutorShadowReceiptStatus.EXPIRED

    # Legacy key readback & disappeared after atomic claim
    legacy_only_cmd = ExecutorCommand.from_action(
        command_id=UUID(int=35),
        action=shadow_act.model_copy(update={"idempotency_key": "leg-shadow"}),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    mem_store.data[_legacy_attempt_key("leg-shadow")] = mem_store.data[
        _attempt_key(cmd1.idempotency_key)
    ]
    assert (await shadow_svc.handle(legacy_only_cmd)).status is ExecutorShadowReceiptStatus.REJECTED

    mem_store.fail_write = True
    disappear_cmd = ExecutorCommand.from_action(
        command_id=UUID(int=36),
        action=shadow_act.model_copy(update={"idempotency_key": "vanish-shadow"}),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now - timedelta(minutes=1),
        deadline_at=now + timedelta(minutes=5),
    )
    with pytest.raises(RuntimeError, match="disappeared after atomic claim"):
        await shadow_svc.handle(disappear_cmd)

    with pytest.raises(RuntimeError, match="malformed"):
        _decode_state_record({"command": "bad"})
    assert BundleValidationRefusal("a", "b").reason == "b"
