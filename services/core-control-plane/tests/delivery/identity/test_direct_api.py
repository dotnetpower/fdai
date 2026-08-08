from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import pytest
from fdai.core.human_assignment import (
    HumanAccessApplyCoordinator,
    HumanAccessExecution,
    HumanAccessExecutionOutcome,
)
from fdai.delivery.direct_api_router import RoutedDirectApiExecutor
from fdai.delivery.identity.direct_api import (
    APPLY_HUMAN_ACCESS_ACTION,
    REVOKE_HUMAN_ACCESS_ACTION,
    HumanAccessDirectApiExecutor,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from fdai.shared.providers.human_access import HumanAccessOperation, HumanAccessPlan


def _request(
    *,
    action_type: str = APPLY_HUMAN_ACCESS_ACTION,
    mode: Mode = Mode.SHADOW,
    arguments: dict[str, object] | None = None,
) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=uuid4(),
        idempotency_key="direct-human-access-1",
        action_type_name=action_type,
        rule_ids=("rule:human-access",),
        resource_ref="human-assignment:case-1",
        arguments=arguments or {"case_id": "case-1", "expected_revision": 4},
        mode=mode,
    )


@dataclass
class _RecordingCoordinator:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def execute(self, **kwargs: Any) -> HumanAccessExecution:
        self.calls.append(dict(kwargs))
        return HumanAccessExecution(
            HumanAccessExecutionOutcome.PLANNED,
            HumanAccessPlan(
                case_id=str(kwargs["case_id"]),
                subject_id="target-1",
                group_id="group-reader",
                operation=HumanAccessOperation.GRANT,
                idempotency_key="human-access:case-1",
            ),
        )


@dataclass
class _RecordingExecutor:
    name: str
    calls: list[DirectApiRequest] = field(default_factory=list)

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        self.calls.append(request)
        return DirectApiReceipt(DirectApiOutcome.SUCCEEDED, f"receipt:{self.name}")


async def test_human_access_direct_api_projects_shadow_plan_only() -> None:
    coordinator = _RecordingCoordinator()
    executor = HumanAccessDirectApiExecutor(cast(HumanAccessApplyCoordinator, coordinator))

    receipt = await executor.execute(_request())

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert "no Graph mutation" in str(receipt.detail)
    assert coordinator.calls == [
        {
            "case_id": "case-1",
            "expected_revision": 4,
            "actor_ref": "Thor",
            "mode": Mode.SHADOW,
        }
    ]


async def test_human_access_direct_api_rejects_enforce_revoke_and_extra_arguments() -> None:
    coordinator = _RecordingCoordinator()
    executor = HumanAccessDirectApiExecutor(cast(HumanAccessApplyCoordinator, coordinator))

    with pytest.raises(DirectApiPromotionError):
        await executor.execute(_request(mode=Mode.ENFORCE))
    with pytest.raises(DirectApiPreconditionError, match="replacement-coverage"):
        await executor.execute(_request(action_type=REVOKE_HUMAN_ACCESS_ACTION))
    with pytest.raises(DirectApiPreconditionError, match="contain only"):
        await executor.execute(
            _request(
                arguments={
                    "case_id": "case-1",
                    "expected_revision": 4,
                    "group_id": "arbitrary-group",
                }
            )
        )

    assert coordinator.calls == []


async def test_direct_api_router_freezes_routes_and_preserves_fallback() -> None:
    human = _RecordingExecutor("human")
    fallback = _RecordingExecutor("fallback")
    routes = {APPLY_HUMAN_ACCESS_ACTION: human}
    router = RoutedDirectApiExecutor(routes=routes, fallback=fallback)
    routes[APPLY_HUMAN_ACCESS_ACTION] = fallback

    human_receipt = await router.execute(_request())
    fallback_receipt = await router.execute(_request(action_type="ops.restart-service"))

    assert human_receipt.receipt_ref == "receipt:human"
    assert fallback_receipt.receipt_ref == "receipt:fallback"
    assert len(human.calls) == 1
    assert len(fallback.calls) == 1
