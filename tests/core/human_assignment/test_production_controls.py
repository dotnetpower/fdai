from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.human_assignment import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentReconciler,
    AssignmentState,
    DutyBinding,
    ProviderSubject,
    assignment_capability_status,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _case(state: AssignmentState, *, reason: str | None = None) -> AssignmentCase:
    return AssignmentCase(
        case_id=f"case-{state.value}",
        intent=AssignmentIntent(
            idempotency_key=f"assignment-{state.value}",
            subject=ProviderSubject("entra", "subject-1"),
            requested_role=Role.READER,
            duty_bindings=(DutyBinding("Muninn", Duty.PRIMARY, "scope:platform"),),
            goal_refs=(),
            requester_ref="requester-1",
            justification="Exercise held assignment recovery planning.",
        ),
        state=state,
        revision=4,
        degraded_reason=reason,
    )


def test_capability_axes_are_independent_and_kill_switch_never_enables() -> None:
    configured = {
        "FDAI_HUMAN_ACCESS_MI_CLIENT_ID": "identity-client",
        "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": "{}",
        "FDAI_STATE_STORE_DSN": "configured",
    }
    available = assignment_capability_status(configured, mode=Mode.ENFORCE)
    killed = assignment_capability_status(
        configured,
        mode=Mode.ENFORCE,
        kill_switch_engaged=True,
    )
    unavailable = assignment_capability_status({}, mode=Mode.ENFORCE)

    assert available.can_mutate is True
    assert killed.can_mutate is False
    assert unavailable.available is False
    assert unavailable.mode is Mode.ENFORCE


async def test_reconciler_only_plans_held_cases_and_writes_shadow_audit() -> None:
    store = InMemoryStateStore()
    for case in (
        _case(AssignmentState.OWNERSHIP_MERGED),
        _case(AssignmentState.IAM_APPLYING),
        _case(AssignmentState.DEGRADED, reason="iam_provider_failed"),
        _case(AssignmentState.REJECTED),
    ):
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())

    items = await AssignmentReconciler(store=store).plan(at=datetime(2026, 8, 3, tzinfo=UTC))

    assert {item.next_step for item in items} == {
        "request_iam_apply",
        "verify_iam_membership",
        "operator_repair",
    }
    assert all(entry["entry"]["mode"] == "shadow" for entry in store.audit_entries)
