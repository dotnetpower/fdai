"""Alert direct-API routing holds alert actions before any generic fallback."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fdai.core.detection.alert_noise.action_types import ALERT_ACTIONS
from fdai.core.executor.direct_api import DirectApiShadowExecutor
from fdai.delivery.alert_noise_direct_api import (
    AlertUnavailableDirectApiExecutionPort,
    UnavailableAlertDirectApiExecutor,
)
from fdai.runtime.control_loop_execution_ports import build_thor_execution_port
from fdai.runtime.providers import (
    _build_resource_lock,
    _build_safeguard_lifecycle_coordinator,
)
from fdai.shared.contracts.execution_outcomes import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.executor.test_direct_api_executor import _action as _direct_action

_ALERT_REASON = "alert provider mutation adapter is not configured"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ENV = (
    "FDAI_DIRECT_API_FAKE",
    "FDAI_DEV_OPERATIONS_GATEWAY_URL",
    "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE",
    "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON",
    "FDAI_STATE_STORE_DSN",
    "FDAI_TOOL_CALL_FAKE",
    "FDAI_GITOPS_TOKEN",
)


class _RecordingPort:
    """Generic direct-API fallback that records every action it receives."""

    def __init__(self) -> None:
        self.actions: list[Action] = []

    async def execute(self, *, action: Action) -> DirectApiExecutionResult:
        self.actions.append(action)
        return DirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=DirectApiExecutionOutcome.DISPATCHED,
            mode=action.mode,
        )


def _alert_action(action_type: str, *, mode: Mode = Mode.SHADOW) -> Action:
    return _direct_action(mode=mode).model_copy(
        update={
            "action_type": action_type,
            "citing_rules": [action_type],
            "params": {"plan_digest": "0" * 64},
        }
    )


def _route(fallback: _RecordingPort | None) -> AlertUnavailableDirectApiExecutionPort:
    return AlertUnavailableDirectApiExecutionPort(
        unavailable=DirectApiShadowExecutor(
            executor=UnavailableAlertDirectApiExecutor(),
            audit_store=InMemoryStateStore(),
            resource_lock=_build_resource_lock({"RUNTIME_ENV": "test"}),
            allow_enforce=True,
        ),
        fallback=fallback,
    )


@pytest.mark.parametrize("mode", [Mode.SHADOW, Mode.ENFORCE])
@pytest.mark.parametrize("action_type", sorted(ALERT_ACTIONS))
async def test_alert_actions_never_reach_the_generic_fallback(action_type: str, mode: Mode) -> None:
    fallback = _RecordingPort()

    result = await _route(fallback).execute(action=_alert_action(action_type, mode=mode))

    assert fallback.actions == []
    assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_PRECONDITION
    assert result.reason == _ALERT_REASON


async def test_non_alert_actions_use_the_bound_fallback() -> None:
    fallback = _RecordingPort()
    action = _direct_action()

    result = await _route(fallback).execute(action=action)

    assert fallback.actions == [action]
    assert result.outcome is DirectApiExecutionOutcome.DISPATCHED


async def test_non_alert_actions_keep_the_unwired_rejection_without_a_fallback() -> None:
    action = _direct_action()

    result = await _route(None).execute(action=action)

    assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
    assert result.reason == "execution_path 'direct_api' has no wired executor"
    assert result.mode is action.mode


async def test_unavailable_adapter_refuses_requests_outside_the_alert_route() -> None:
    result = await DirectApiShadowExecutor(
        executor=UnavailableAlertDirectApiExecutor(),
        audit_store=InMemoryStateStore(),
        resource_lock=_build_resource_lock({"RUNTIME_ENV": "test"}),
    ).execute(action=_direct_action())

    assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_PRECONDITION
    assert result.reason == "request is not an alert-noise action"


@pytest.mark.parametrize("mode", [Mode.SHADOW, Mode.ENFORCE])
async def test_thor_composition_holds_alert_actions_before_an_injected_port(
    monkeypatch: pytest.MonkeyPatch, mode: Mode
) -> None:
    for name in _BACKEND_ENV:
        monkeypatch.delenv(name, raising=False)
    audit = InMemoryStateStore()
    lock = _build_resource_lock({"RUNTIME_ENV": "test"})
    coordinator = _build_safeguard_lifecycle_coordinator(
        audit_store=audit,
        resource_lock=lock,
        process_store=InMemoryProcessRuntimeStore(),
        environment={"RUNTIME_ENV": "test"},
    )
    injected = _RecordingPort()
    port = build_thor_execution_port(
        None,
        container=SimpleNamespace(metric_provider=None, decision_evidence_admission_provider=None),
        audit_store=audit,
        publisher=None,
        renderer=None,
        resource_lock=lock,
        idempotency_store=None,
        safeguard_coordinator=coordinator,
        direct_api_execution_port=injected,
        tool_receipt_observer=None,
        http_client=None,
        identity=None,
        human_access_enabled=False,
        execution_identities=None,
        promotion_registry=None,
        action_types_by_name={},
        ontology_release=None,
        property_semantics=None,
        catalog_root=_REPO_ROOT / "rule-catalog",
    )
    direct = getattr(port, "direct_api", None)
    assert isinstance(direct, AlertUnavailableDirectApiExecutionPort)

    for index, action_type in enumerate(sorted(ALERT_ACTIONS)):
        action = _alert_action(action_type, mode=mode).model_copy(
            update={"idempotency_key": f"alert-route-{mode.value}-{index}"}
        )
        result = await direct.execute(action=action)
        assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_PRECONDITION
        assert result.reason == _ALERT_REASON
    assert injected.actions == []

    generic = _direct_action(mode=mode)
    await direct.execute(action=generic)
    assert injected.actions == [generic]
