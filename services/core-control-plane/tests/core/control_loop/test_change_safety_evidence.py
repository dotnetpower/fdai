from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.control_loop.change_safety_evidence import (
    ChangeSafetyEvidenceStatus,
    ChangeSafetyPreAuthorityEvidence,
    evaluate_change_safety_pre_authority,
)
from fdai.shared.contracts.models import Action, Event, Mode

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _event() -> Event:
    return Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000001",
        idempotency_key="event-a",
        source="azure.activity_log",
        event_type="change",
        resource_ref="resource-a",
        detected_at=NOW,
        ingested_at=NOW,
        mode=Mode.SHADOW,
    )


def _action() -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000002",
            "idempotency_key": "action-a",
            "event_id": str(_event().event_id),
            "action_type": "remediate.tag-add",
            "target_resource_ref": "resource-a",
            "operation": "update",
            "params": {},
            "stop_condition": "time_box_exceeded_seconds",
            "stop_conditions": [{"kind": "time_box_exceeded_seconds", "seconds": 300}],
            "rollback_ref": {"kind": "pr_revert"},
            "blast_radius": {"scope": "resource", "count": None},
            "mode": "shadow",
            "citing_rules": ["rule-a"],
            "created_at": NOW,
        }
    )


class _Provider:
    def __init__(self, evidence: ChangeSafetyPreAuthorityEvidence) -> None:
        self.evidence = evidence

    async def evaluate(self, *, event: Event, action: Action):
        del event, action
        return self.evidence


def _evidence() -> ChangeSafetyPreAuthorityEvidence:
    return ChangeSafetyPreAuthorityEvidence(
        schema_version="1.0.0",
        event_id=str(_event().event_id),
        action_id=str(_action().action_id),
        drift_status=ChangeSafetyEvidenceStatus.PASSED,
        what_if_status=ChangeSafetyEvidenceStatus.PASSED,
        drift_evidence_ref="drift:report-a",
        what_if_evidence_ref="what-if:report-a",
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        affected_count=7,
    )


@pytest.mark.asyncio
async def test_ready_evidence_enriches_blast_count_for_risk_only() -> None:
    decision = await evaluate_change_safety_pre_authority(
        _Provider(_evidence()),
        event=_event(),
        action=_action(),
        evaluated_at=NOW,
    )
    assert decision.ready_for_risk is True
    assert decision.action.blast_radius.count == 7
    assert decision.finding_preserved is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    [
        replace(_evidence(), drift_status=ChangeSafetyEvidenceStatus.CONFLICT),
        replace(_evidence(), what_if_status=ChangeSafetyEvidenceStatus.UNAVAILABLE),
        replace(
            _evidence(),
            observed_at=NOW - timedelta(minutes=2),
            expires_at=NOW - timedelta(seconds=1),
        ),
        replace(_evidence(), synthetic=True),
    ],
)
async def test_unresolved_evidence_holds_without_rewriting_the_action(
    evidence: ChangeSafetyPreAuthorityEvidence,
) -> None:
    action = _action()
    decision = await evaluate_change_safety_pre_authority(
        _Provider(evidence),
        event=_event(),
        action=action,
        evaluated_at=NOW,
    )
    assert decision.ready_for_risk is False
    assert decision.action == action
    assert decision.finding_preserved is True


@pytest.mark.asyncio
async def test_missing_or_failed_provider_holds() -> None:
    missing = await evaluate_change_safety_pre_authority(
        None,
        event=_event(),
        action=_action(),
        evaluated_at=NOW,
    )

    class _Failed:
        async def evaluate(self, *, event: Event, action: Action):
            del event, action
            raise RuntimeError("provider failed")

    failed = await evaluate_change_safety_pre_authority(
        _Failed(),
        event=_event(),
        action=_action(),
        evaluated_at=NOW,
    )
    assert missing.ready_for_risk is False
    assert failed.ready_for_risk is False
    assert failed.reason == "change_safety_evidence_provider_failed:RuntimeError"
