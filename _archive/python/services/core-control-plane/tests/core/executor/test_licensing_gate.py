"""Shared Thor execution-port capability licensing tests."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from fdai.core.capability_catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
    ExecutorOutcome,
    InProcessThorExecutionPort,
    LicenseGatedThorExecutionPort,
    ShadowExecutor,
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.executor.executor import ExecutionResult
from fdai.core.executor.port import DirectApiExecutionPort
from fdai.core.licensing import (
    Entitlement,
    LicenseClaims,
    LicenseEntitlementAuthority,
    LicenseStatus,
    encode_license_token,
)
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ExecutionPath,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    Rule,
    StopConditionKind,
)
from fdai.shared.providers.testing import InMemoryStateStore

_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class _AcceptAll:
    def verify(self, document: bytes, signature: bytes) -> bool:
        return True


class _RejectAll:
    def verify(self, document: bytes, signature: bytes) -> bool:
        return False


class _FailingAuditStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.append_attempts = 0

    async def append_audit_entry(self, entry: object) -> None:
        del entry
        self.append_attempts += 1
        raise RuntimeError("simulated audit outage")


@dataclass
class _PrNativeDelegate:
    calls: int = 0

    async def execute(
        self,
        *,
        action: Action,
        rule: Rule,
        execution_path: ExecutionPath = ExecutionPath.PR_NATIVE,
    ) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(
            action_id=str(action.action_id),
            outcome=ExecutorOutcome.PUBLISHED,
            mode=action.mode,
        )


@dataclass
class _DirectApiDelegate:
    calls: int = 0

    async def execute(self, *, action: Action) -> DirectApiExecutionResult:
        self.calls += 1
        return DirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=DirectApiExecutionOutcome.DISPATCHED,
            mode=action.mode,
        )


@dataclass
class _ToolCallDelegate:
    calls: int = 0

    async def execute(self, *, action: Action) -> ToolCallExecutionResult:
        self.calls += 1
        return ToolCallExecutionResult(
            action_id=str(action.action_id),
            outcome=ToolCallExecutionOutcome.DISPATCHED,
            mode=action.mode,
        )


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            Capability(
                capability_id="observability.resource-discovery",
                name="Resource discovery",
                category=CapabilityCategory.DETECTION,
                summary="Read resources.",
                side_effect_class=SideEffectClass.READ,
            ),
            Capability(
                capability_id="operations.typed-mutation",
                name="Typed mutation",
                category=CapabilityCategory.REMEDIATION,
                summary="Run governed changes.",
                side_effect_class=SideEffectClass.EXECUTE,
            ),
        )
    )


def _action() -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        event_id=UUID("00000000-0000-0000-0000-000000000011"),
        action_type="ops.restart-service",
        target_resource_ref="resource:example/rg/vm1",
        operation=Operation.RESTART,
        params={},
        mode=Mode.SHADOW,
        idempotency_key="example-license-gate",
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rb-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        citing_rules=["ops.restart-service"],
        created_at=_NOW,
    )


def _port() -> tuple[
    InProcessThorExecutionPort,
    _PrNativeDelegate,
    _DirectApiDelegate,
    _ToolCallDelegate,
]:
    pr_native = _PrNativeDelegate()
    direct_api = _DirectApiDelegate()
    tool_call = _ToolCallDelegate()
    return (
        InProcessThorExecutionPort(
            pr_native=cast(ShadowExecutor, pr_native),
            direct_api=cast(DirectApiExecutionPort, direct_api),
            tool_call=cast(ToolCallShadowExecutor, tool_call),
        ),
        pr_native,
        direct_api,
        tool_call,
    )


async def test_trial_blocks_all_three_ports_before_delegate_io() -> None:
    base, pr_native, direct_api, tool_call = _port()
    store = InMemoryStateStore()
    gated = LicenseGatedThorExecutionPort(
        delegate=base,
        authority=LicenseEntitlementAuthority(
            catalog=_catalog(),
            token=None,
            verifier=_RejectAll(),
        ),
        audit_store=store,
        clock=lambda: _NOW,
    )
    rule = cast(Rule, object())
    action = _action()

    pr_result = await gated.pr_native.execute(action=action, rule=rule)
    assert gated.direct_api is not None
    direct_result = await gated.direct_api.execute(action=action)
    assert gated.tool_call is not None
    tool_result = await gated.tool_call.execute(action=action)

    assert pr_result.outcome is ExecutorOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert direct_result.outcome is DirectApiExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert tool_result.outcome is ToolCallExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert (pr_native.calls, direct_api.calls, tool_call.calls) == (0, 0, 0)
    entries = [record["entry"] for record in store.audit_entries]
    assert len(entries) == 3
    assert {entry["execution_path"] for entry in entries} == {
        "pr_native",
        "direct_api",
        "tool_call",
    }
    assert all(entry["license_status"] == "absent" for entry in entries)
    assert "FDAI_LICENSE_TOKEN" not in str(entries)


@dataclass
class _OffLoopTrial:
    """Grant an active Trial only when consulted away from the event loop."""

    catalog: CapabilityCatalog
    threads: list[int] = field(default_factory=list)

    def resolve(self, *, now: datetime) -> Entitlement:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.threads.append(threading.get_ident())
            return Entitlement(
                status=LicenseStatus.ACTIVE,
                available_capability_ids=frozenset(
                    capability.capability_id for capability in self.catalog.list()
                ),
                reason="active Trial window",
            )
        raise AssertionError("durable Trial state was observed on the event loop")


async def test_durable_trial_is_resolved_off_the_event_loop() -> None:
    base, _pr_native, direct_api, _tool_call = _port()
    trial = _OffLoopTrial(_catalog())
    gated = LicenseGatedThorExecutionPort(
        delegate=base,
        authority=LicenseEntitlementAuthority(
            catalog=_catalog(),
            token=None,
            verifier=_RejectAll(),
            trial=trial,
        ),
        audit_store=InMemoryStateStore(),
        clock=lambda: _NOW,
    )
    assert gated.direct_api is not None

    result = await gated.direct_api.execute(action=_action())

    assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert direct_api.calls == 1
    assert len(trial.threads) == 1
    assert trial.threads[0] != threading.get_ident()


async def test_verified_issuer_workstation_delegates_all_three_ports() -> None:
    base, pr_native, direct_api, tool_call = _port()
    gated = LicenseGatedThorExecutionPort(
        delegate=base,
        authority=LicenseEntitlementAuthority(
            catalog=_catalog(),
            token="ignored-invalid-token",
            verifier=_RejectAll(),
            issuer_workstation=True,
        ),
        audit_store=InMemoryStateStore(),
        clock=lambda: _NOW,
    )
    action = _action()

    await gated.pr_native.execute(action=action, rule=cast(Rule, object()))
    assert gated.direct_api is not None
    await gated.direct_api.execute(action=action)
    assert gated.tool_call is not None
    await gated.tool_call.execute(action=action)

    assert (pr_native.calls, direct_api.calls, tool_call.calls) == (1, 1, 1)


async def test_audit_failure_keeps_all_three_paths_terminal_and_blocked() -> None:
    base, pr_native, direct_api, tool_call = _port()
    store = _FailingAuditStore()
    gated = LicenseGatedThorExecutionPort(
        delegate=base,
        authority=LicenseEntitlementAuthority(
            catalog=_catalog(),
            token=None,
            verifier=_RejectAll(),
        ),
        audit_store=store,
        clock=lambda: _NOW,
    )
    action = _action()

    pr_result = await gated.pr_native.execute(action=action, rule=cast(Rule, object()))
    assert gated.direct_api is not None
    direct_result = await gated.direct_api.execute(action=action)
    assert gated.tool_call is not None
    tool_result = await gated.tool_call.execute(action=action)

    assert pr_result.outcome is ExecutorOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert direct_result.outcome is DirectApiExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert tool_result.outcome is ToolCallExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert pr_result.audit_context["audit_persisted"] is False
    assert direct_result.audit_context["audit_persisted"] is False
    assert tool_result.audit_context["audit_persisted"] is False
    assert (pr_native.calls, direct_api.calls, tool_call.calls) == (0, 0, 0)
    assert store.append_attempts == 3


async def test_active_token_is_rechecked_and_blocked_after_expiration() -> None:
    base, _pr_native, direct_api, _tool_call = _port()
    claims = LicenseClaims(
        license_id="lic-0001",
        distribution_id="example-distribution",
        capability_ids=("operations.typed-mutation",),
        not_before=_NOW - timedelta(days=1),
        not_after=_NOW + timedelta(days=1),
    )
    token = encode_license_token(claims.canonical_document(), b"s" * 64)
    current = [_NOW]
    gated = LicenseGatedThorExecutionPort(
        delegate=base,
        authority=LicenseEntitlementAuthority(
            catalog=_catalog(),
            token=token,
            verifier=_AcceptAll(),
        ),
        audit_store=InMemoryStateStore(),
        clock=lambda: current[0],
    )
    assert gated.direct_api is not None

    active_result = await gated.direct_api.execute(action=_action())
    current[0] = _NOW + timedelta(days=2)
    expired_result = await gated.direct_api.execute(action=_action())

    assert active_result.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert expired_result.outcome is DirectApiExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE
    assert expired_result.audit_context["license_status"] == "expired"
    assert direct_api.calls == 1
