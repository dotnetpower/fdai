"""Vidar rollback executor readiness is action/contract-specific."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.vidar import Vidar
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def test_vidar_refuses_known_action_without_matching_rollback_executor() -> None:
    called: list[str] = []

    async def route_rollback(command: dict[str, object]) -> str:
        called.append(str(command.get("action_type")))
        return "route:rollback"

    vidar = Vidar(
        executors={"state_forward_only": route_rollback},
        action_executors={("ops.switch-t2-proposer-route", "state_forward_only"): route_rollback},
        rollback_contracts_by_action_type={
            "ops.switch-t2-proposer-route": "state_forward_only",
            "ops.scale-out": "state_forward_only",
        },
        state_store=InMemoryStateStore(),
    )

    asyncio.run(vidar.maintenance_tick())

    health = vidar.health()["rollback_path_validation"]["paths"]
    assert health["ops.switch-t2-proposer-route"]["ready"] is True
    assert health["ops.scale-out"]["ready"] is False
    assert health["ops.scale-out"]["executor_bound"] is False

    run = ActionRun(
        correlation_id="corr-scale-out",
        action_type="ops.scale-out",
        resource_id="aks:deployment:store",
        state=ActionRunState.FAILED,
        verdict="auto",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )
    record = asyncio.run(vidar.rollback({"producer_principal": "Thor", **run.to_dict()}))

    assert record is not None
    assert record.state == "failed"
    assert record.action_type == "ops.scale-out"
    assert "no rollback executor registered" in record.notes
    assert called == []
