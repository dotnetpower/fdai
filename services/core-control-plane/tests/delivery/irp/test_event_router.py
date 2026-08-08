from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.investigation import Priority
from fdai.core.irp import MitigationProposal
from fdai.delivery.irp import EventBusIrpProposalRouter


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
        self.published.append((topic, key, payload))


async def test_router_reenters_proposal_as_typed_operator_request() -> None:
    bus = _Bus()
    router = EventBusIrpProposalRouter(bus=bus, topic="events")  # type: ignore[arg-type]
    await router.route(
        MitigationProposal(
            proposal_id="proposal-1",
            alert_id="alert-1",
            remediation_ref="appgw.scale_backend_pool",
            detail="Scale the affected backend pool.",
            priority=Priority.P1,
            approver_role="approver",
            citations=("metric:healthy_host_count",),
            requested_at=datetime.now(tz=UTC),
            target_resource_ref="appgw-1",
        )
    )

    topic, key, payload = bus.published[0]
    assert topic == "events"
    assert key == "appgw-1"
    assert payload["event_type"] == "operator_request"
    assert payload["action_type"] == "tool.file-irp-followup"
    assert payload["operator_initiated"] is True
    assert payload["params"] == {
        "alert_id": "alert-1",
        "remediation_ref": "appgw.scale_backend_pool",
        "resource_ref": "appgw-1",
        "priority": "p1",
        "detail": "Scale the affected backend pool.",
    }
