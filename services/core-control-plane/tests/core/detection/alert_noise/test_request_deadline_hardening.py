"""Round 13: expired or revoked typed requests never advance after delayed dependency I/O."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.delivery.alert_noise_handler import AlertNoiseAgentHandler
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    SignedAlertCommand,
    sign_alert_record,
)

from .test_planning_hardening import routing


@pytest.mark.parametrize("stage", ["before_plan", "evaluation", "artifact"])
@pytest.mark.parametrize("change", ["expired", "revoked"])
async def test_current_request_is_rechecked_before_workflow_handoff(
    evidence: AlertEvidence, now: datetime, stage: str, change: str
) -> None:
    clock = [now]
    evidence = evidence.model_copy(
        update={"stamp": evidence.stamp.model_copy(update={"synthetic": False})}
    )
    key = b"test-only-request-deadline-key-0000"
    command = AlertNoiseCommand(
        operation="alert_noise.propose",
        request_ref="request:deadline",
        requester_ref="principal:example",
        scope_ref="scope:example",
        requested_at=now,
        expires_at=now + timedelta(minutes=5),
        evidence_digest=digest_record(evidence),
        treatment=routing(),
    )
    store = InMemoryStateStore()
    await store.write_state(
        "alert-noise:evidence:" + digest_record(evidence), evidence.model_dump(mode="json")
    )
    workflow, artifact = SimpleNamespace(run=AsyncMock()), SimpleNamespace(prepare=AsyncMock())
    reader = SimpleNamespace(read=AsyncMock(return_value=None))
    handler = AlertNoiseAgentHandler(
        store=store,
        sources={},
        principals={command.requester_ref: frozenset({command.scope_ref})},
        policy=NoisePolicy(),
        transport_key=key,
        workflows=workflow,
        artifacts=artifact,
        evaluations={command.scope_ref: reader},
        clock=lambda: clock[0],
    )
    signal = await handler.observe(
        {
            "producer_principal": "Huginn",
            "alert_noise": SignedAlertCommand(
                command=command, signature=sign_alert_record(command, key)
            ).model_dump(mode="json"),
        }
    )

    def invalidate() -> None:
        if change == "expired":
            clock[0] = command.expires_at
        else:
            handler.principals.clear()

    async def delayed(**_kwargs):
        invalidate()
        return None

    if stage == "before_plan":
        invalidate()
    elif stage == "evaluation":
        reader.read.side_effect = delayed
    else:
        artifact.prepare.side_effect = delayed
    result = await handler.plan({**signal, "producer_principal": "Heimdall"})
    assert result["status"] == "held"
    assert result["reason"] == ("request_expired" if change == "expired" else "scope_denied")
    assert result["plan"] is None
    assert result["recorded_at"] == clock[0].isoformat().replace("+00:00", "Z")
    workflow.run.assert_not_awaited()
    if stage != "artifact":
        artifact.prepare.assert_not_awaited()
