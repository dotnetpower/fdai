"""Read-only Core planning and shared contract compatibility."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.human_assignment import AssignmentCaseService
from fdai.core.human_assignment.access_planning import HumanAccessPlanner
from fdai.core.rbac.roles import Role
from fdai.shared.providers import human_access as legacy
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import human_access as shared
from tests.core.human_assignment.test_access_apply import _ownership_merged


def test_core_and_executor_share_one_membership_contract_identity() -> None:
    for name in shared.__all__:
        assert getattr(legacy, name) is getattr(shared, name)


async def test_planning_retains_case_state_and_does_not_hold_a_provider() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    groups = {Role.READER: "group:reader"}
    planner = HumanAccessPlanner(cases, groups)
    groups[Role.READER] = "group:changed"
    before = await cases.get_case(case.case_id)
    value = await planner.plan(case_id=case.case_id, expected_revision=case.revision)
    assert value.group_id == "group:reader"
    assert await cases.get_case(case.case_id) == before
    assert not hasattr(planner, "execute") and not hasattr(planner, "provisioner")
    inverse = replace(value, operation=shared.HumanAccessOperation.REVOKE)
    assert value.membership_lock_key == inverse.membership_lock_key


@pytest.mark.parametrize("revision", [True, 0, -1, "5", 999])
async def test_planning_refuses_nonexact_or_coerced_revision(revision) -> None:
    cases = AssignmentCaseService(InMemoryStateStore())
    case = await _ownership_merged(cases)
    with pytest.raises(ValueError, match="exact current"):
        await HumanAccessPlanner(cases, {Role.READER: "group:reader"}).plan(
            case_id=case.case_id, expected_revision=revision
        )
