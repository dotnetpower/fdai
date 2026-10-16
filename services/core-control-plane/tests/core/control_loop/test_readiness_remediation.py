from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.control_loop import _process
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.control_loop.readiness_remediation import process_readiness_remediation
from fdai.core.executor.action_builder import ActionBuildError
from fdai.shared.contracts.models import Action, Event, Rule


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000102",
            "idempotency_key": "orr-remediation:" + "a" * 32,
            "correlation_id": "orr-remediation-example",
            "source": "operational_readiness",
            "event_type": "readiness_remediation_request",
            "resource_ref": "resource:storage/account/example",
            "payload": {},
            "detected_at": "2026-10-15T09:00:00Z",
            "ingested_at": "2026-10-15T09:00:00Z",
            "mode": "shadow",
        }
    )


def _action() -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000103",
            "idempotency_key": "orr-remediation:" + "a" * 32,
            "event_id": "00000000-0000-0000-0000-000000000102",
            "action_type": "remediate.tag-add",
            "target_resource_ref": "resource:storage/account/example",
            "operation": "tag",
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 1},
            "mode": "shadow",
            "citing_rules": ["readiness.owner-tag.required"],
            "created_at": "2026-10-15T09:00:00Z",
        }
    )


def _rule(*, revision: str = "revision-7") -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "readiness.owner-tag.required",
            "version": "1.0.0",
            "source": "custom",
            "severity": "high",
            "category": "config_drift",
            "resource_type": "operational-readiness",
            "check_logic": {"kind": "expression", "reference": "evidence:orr:owner-tag"},
            "remediation": {"template_ref": "operational-readiness"},
            "remediates": "remediate.tag-add",
            "provenance": {
                "source_url": "https://fdai.dev/operational-readiness",
                "resolved_ref": revision,
                "content_hash": "sha256:" + "a" * 64,
                "license": "LicenseRef-runtime",
                "redistribution": "embeddable",
                "retrieved_at": "2026-10-15T09:00:00Z",
            },
        }
    )


def _host(*, revision: str | None = "revision-7") -> MagicMock:
    host = MagicMock()
    host._action_builder.build_from_readiness_remediation.return_value = (
        _action(),
        _rule(revision=revision or "revision-7"),
    )
    host._audit_store.append_audit_entry = AsyncMock()
    host._emit_stage = AsyncMock()
    host._notify_decision = AsyncMock()
    host._dispatch_action = AsyncMock()
    return host


async def test_readiness_remediation_reaches_risk_gate_but_never_dispatches() -> None:
    host = _host()
    unified = MagicMock(is_denied=False, requires_hil=False, decision="auto")
    host._evaluate_and_audit = AsyncMock(return_value=unified)
    event = _event()

    result = await process_readiness_remediation(
        host,
        event=event,
        event_id=str(event.event_id),
        correlation_id=event.correlation_id or str(event.event_id),
    )

    assert result.outcome is ControlLoopOutcome.READINESS_REMEDIATION_LOGGED
    assert result.decision == "shadow"
    assert result.citing_rule_ids == ("readiness.owner-tag.required",)
    host._evaluate_and_audit.assert_awaited_once_with(
        event=event,
        action=_action(),
        rule=_rule(),
    )
    host._dispatch_action.assert_not_awaited()


async def test_readiness_remediation_abstains_on_malformed_request() -> None:
    host = _host()
    host._action_builder.build_from_readiness_remediation.side_effect = ActionBuildError(
        "readiness remediation request is malformed"
    )
    host._evaluate_and_audit = AsyncMock()
    event = _event()

    result = await process_readiness_remediation(
        host,
        event=event,
        event_id=str(event.event_id),
        correlation_id=event.correlation_id or str(event.event_id),
    )

    assert result.outcome is ControlLoopOutcome.ABSTAINED_ACTION_BUILD
    assert result.reason == "readiness_remediation_action_build_failed"
    host._audit_store.append_audit_entry.assert_awaited_once()
    host._evaluate_and_audit.assert_not_awaited()


async def test_normalized_readiness_remediation_uses_dedicated_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event()
    expected = ControlLoopResult(
        outcome=ControlLoopOutcome.READINESS_REMEDIATION_LOGGED,
        tier="t0",
        decision="shadow",
        resource_type="operational-readiness",
    )
    processor = AsyncMock(return_value=expected)
    monkeypatch.setattr(_process, "process_readiness_remediation", processor)
    host = MagicMock()
    host._correlate_incident_id.return_value = None
    host._emit_stage = AsyncMock()
    host._maybe_fire_workflows = AsyncMock()

    result = await _process._process_normalized_event(host, event)

    assert result is expected
    processor.assert_awaited_once_with(
        host,
        event=event,
        event_id=str(event.event_id),
        correlation_id=event.correlation_id,
    )
    host._trust_router.route.assert_not_called()
