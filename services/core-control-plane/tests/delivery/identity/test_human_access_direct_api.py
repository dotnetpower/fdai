from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fdai.core.human_assignment import (
    HumanAccessApplyCoordinator,
    HumanAccessExecution,
    HumanAccessExecutionOutcome,
)
from fdai.delivery.identity import (
    APPLY_HUMAN_ACCESS_ACTION,
    REVOKE_HUMAN_ACCESS_ACTION,
    HumanAccessDirectApiExecutor,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiRequest,
)
from fdai.shared.providers.human_access import HumanAccessOperation, HumanAccessPlan


class RecordingCoordinator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, **kwargs: object) -> HumanAccessExecution:
        self.calls.append(kwargs)
        return HumanAccessExecution(
            HumanAccessExecutionOutcome.PLANNED,
            HumanAccessPlan(
                case_id=str(kwargs["case_id"]),
                subject_id="subject-1",
                group_id="group-reader",
                operation=HumanAccessOperation.GRANT,
                idempotency_key="human-access:case-1",
            ),
        )


def _request(
    *,
    action_type: str = APPLY_HUMAN_ACCESS_ACTION,
    mode: Mode = Mode.SHADOW,
    resource_ref: str = "human-assignment:case-1",
) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=uuid4(),
        idempotency_key="action:case-1",
        action_type_name=action_type,
        rule_ids=("assignment.reviewed",),
        resource_ref=resource_ref,
        arguments={"case_id": "case-1", "expected_revision": 4},
        labels=(mode.value,),
        mode=mode,
    )


async def test_shadow_apply_routes_to_case_coordinator_without_mutation() -> None:
    coordinator = RecordingCoordinator()
    adapter = HumanAccessDirectApiExecutor(cast(HumanAccessApplyCoordinator, coordinator))

    receipt = await adapter.execute(_request())

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert receipt.detail == "shadow human access plan verified; no Graph mutation submitted"
    assert coordinator.calls == [
        {
            "case_id": "case-1",
            "expected_revision": 4,
            "actor_ref": "Thor",
            "mode": Mode.SHADOW,
        }
    ]


async def test_enforce_is_refused_until_separate_promotion() -> None:
    adapter = HumanAccessDirectApiExecutor(
        cast(HumanAccessApplyCoordinator, RecordingCoordinator())
    )

    with pytest.raises(DirectApiPromotionError, match="separately reviewed"):
        await adapter.execute(_request(mode=Mode.ENFORCE))


async def test_revoke_is_held_until_replacement_coverage_case_exists() -> None:
    adapter = HumanAccessDirectApiExecutor(
        cast(HumanAccessApplyCoordinator, RecordingCoordinator())
    )

    with pytest.raises(DirectApiPreconditionError, match="replacement-coverage"):
        await adapter.execute(_request(action_type=REVOKE_HUMAN_ACCESS_ACTION))


async def test_resource_ref_must_match_case_id() -> None:
    adapter = HumanAccessDirectApiExecutor(
        cast(HumanAccessApplyCoordinator, RecordingCoordinator())
    )

    with pytest.raises(DirectApiPreconditionError, match="does not match"):
        await adapter.execute(_request(resource_ref="human-assignment:other-case"))
