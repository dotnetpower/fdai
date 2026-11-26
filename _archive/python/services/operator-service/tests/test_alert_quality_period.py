"""Exact period selection remains a scoped read request, never historical or action authority."""

import pytest
from fdai_operator_service.alert_quality_command import command_from_record

from .test_alert_quality import HEADERS, NOW, SCOPE, _client, _harness, _proposal, _seed


@pytest.mark.parametrize("period", [3600, 86400, 604800])
async def test_assessment_period_is_retained_by_the_actual_outbox_command(period):
    _, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess",
            headers=HEADERS,
            json={"scope_ref": SCOPE, "period_seconds": period},
        )
        assert response.status_code == 202
        proposal = next(iter(writer.proposals.values()))
        record = {
            "payload": {
                "operation": proposal.operation,
                "principal_id": proposal.principal_id,
                "idempotency_key": proposal.idempotency_key,
                "payload": proposal.payload,
            },
            "principal_id": proposal.principal_id,
            "idempotency_key": proposal.idempotency_key,
            "operation": proposal.operation,
            "accepted_at": NOW.isoformat(),
        }
        assert command_from_record(record).period_seconds == period
        conflict = await client.post(
            "/alert-quality/assess",
            headers=HEADERS,
            json={"scope_ref": SCOPE, "period_seconds": 7200},
        )
        assert conflict.status_code == 409 and len(writer.proposals) == 1


@pytest.mark.parametrize("period", [0, -3600, 3601, 608400, True, "3600", 3600.0])
async def test_invalid_period_cannot_reach_the_writer(period):
    _, writer, dependencies = _harness()
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/assess",
            headers=HEADERS,
            json={"scope_ref": SCOPE, "period_seconds": period},
        )
    assert response.status_code == 400 and not writer.proposals


async def test_period_cannot_change_a_frozen_proposal():
    _, writer, dependencies = _harness()
    await _seed(dependencies)
    async with _client(dependencies) as client:
        response = await client.post(
            "/alert-quality/proposals",
            headers=HEADERS,
            json=_proposal(period_seconds=3600),
        )
    assert response.status_code == 400 and not writer.proposals
