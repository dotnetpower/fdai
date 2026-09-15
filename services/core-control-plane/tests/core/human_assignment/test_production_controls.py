from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime

import pytest
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

    reconciler = AssignmentReconciler(store=store)
    items = await reconciler.plan(at=datetime(2026, 8, 3, tzinfo=UTC))
    replayed = await reconciler.plan(at=datetime(2026, 8, 3, 1, tzinfo=UTC))

    assert {item.next_step for item in items} == {
        "request_iam_apply",
        "verify_iam_membership",
        "operator_repair",
    }
    assert replayed == items
    assert len(tuple(store.audit_entries)) == 3
    assert all(entry["entry"]["mode"] == "shadow" for entry in store.audit_entries)


async def test_reconciler_reports_bounded_scan_truncation(caplog) -> None:
    store = InMemoryStateStore()
    for case in (
        _case(AssignmentState.OWNERSHIP_MERGED),
        _case(AssignmentState.IAM_APPLYING),
    ):
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())

    with caplog.at_level(logging.WARNING, logger="fdai.human_assignment.reconciliation"):
        items = await AssignmentReconciler(store=store, scan_limit=1).plan()

    assert len(items) == 1
    record = next(
        item
        for item in caplog.records
        if item.message == "assignment_reconciliation_scan_truncated"
    )
    assert record.limit == 1
    assert record.observed == 1
    assert record.total == 2


async def test_reconciler_isolates_malformed_case_and_continues(caplog) -> None:
    store = InMemoryStateStore()
    first = _case(AssignmentState.OWNERSHIP_MERGED)
    second = _case(AssignmentState.DEGRADED, reason="iam_provider_failed")
    await store.write_state(f"human_assignment:case:{first.case_id}", first.to_dict())
    await store.write_state(
        "human_assignment:case:malformed",
        {"case_id": "malformed", "state": AssignmentState.IAM_APPLYING.value},
    )
    await store.write_state(f"human_assignment:case:{second.case_id}", second.to_dict())

    with caplog.at_level(logging.ERROR, logger="fdai.human_assignment.reconciliation"):
        items = await AssignmentReconciler(store=store).plan()

    assert {item.case_id for item in items} == {first.case_id, second.case_id}
    malformed = next(
        record
        for record in caplog.records
        if record.message == "assignment_reconciliation_case_malformed"
    )
    assert malformed.exception_type == "AssignmentModelError"


async def test_reconciler_isolates_plain_value_error_from_decoder(caplog) -> None:
    store = InMemoryStateStore()
    valid = _case(AssignmentState.DEGRADED, reason="iam_provider_failed")
    malformed = _case(AssignmentState.IAM_APPLYING).to_dict()
    malformed["case_id"] = "invalid-state"
    malformed["state"] = "not-an-assignment-state"
    await store.write_state("human_assignment:case:invalid-state", malformed)
    await store.write_state(f"human_assignment:case:{valid.case_id}", valid.to_dict())

    with caplog.at_level(logging.ERROR, logger="fdai.human_assignment.reconciliation"):
        items = await AssignmentReconciler(store=store).plan()

    assert {item.case_id for item in items} == {valid.case_id}
    malformed_record = next(
        record
        for record in caplog.records
        if record.message == "assignment_reconciliation_case_malformed"
    )
    assert malformed_record.exception_type == "ValueError"


async def test_reconciler_visits_every_bounded_page_and_wraps_without_duplicate_audit() -> None:
    store = InMemoryStateStore()
    cases = tuple(
        replace(_case(AssignmentState.DEGRADED), case_id=f"case-{index}") for index in range(5)
    )
    for case in cases:
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    reconciler = AssignmentReconciler(store=store, scan_limit=2)
    pages = [await reconciler.plan() for _ in range(6)]
    assert [[item.case_id for item in page] for page in pages] == [
        ["case-4", "case-3"],
        ["case-2", "case-1"],
        ["case-0"],
        ["case-4", "case-3"],
        ["case-2", "case-1"],
        ["case-0"],
    ]
    assert len(tuple(store.audit_entries)) == 5


async def test_reconciliation_page_failure_does_not_advance_cursor(monkeypatch) -> None:
    store = InMemoryStateStore()
    for index in range(2):
        case = replace(_case(AssignmentState.DEGRADED), case_id=f"case-{index}")
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    reconciler = AssignmentReconciler(store=store, scan_limit=1)
    write = store.write_state_with_audit_if_absent

    async def fail(*args, **kwargs):
        raise OSError("test store unavailable")

    monkeypatch.setattr(store, "write_state_with_audit_if_absent", fail)
    with pytest.raises(OSError):
        await reconciler.plan()
    monkeypatch.setattr(store, "write_state_with_audit_if_absent", write)
    first = await reconciler.plan()
    second = await reconciler.plan()
    assert [item.case_id for item in first] == ["case-1"]
    assert [item.case_id for item in second] == ["case-0"]


async def test_reconciliation_concurrent_ticks_serialize_page_progress() -> None:
    store = InMemoryStateStore()
    for index in range(3):
        case = replace(_case(AssignmentState.DEGRADED), case_id=f"case-{index}")
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    reconciler = AssignmentReconciler(store=store, scan_limit=1)
    pages = await asyncio.gather(*(reconciler.plan() for _ in range(3)))
    assert {item.case_id for page in pages for item in page} == {"case-0", "case-1", "case-2"}
    assert len(tuple(store.audit_entries)) == 3


async def test_reconciliation_restart_reuses_audit_and_visits_later_pages() -> None:
    store = InMemoryStateStore()
    for index in range(3):
        case = replace(_case(AssignmentState.DEGRADED), case_id=f"case-{index}")
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    await AssignmentReconciler(store=store, scan_limit=1).plan()
    restarted = AssignmentReconciler(store=store, scan_limit=1)
    pages = [await restarted.plan() for _ in range(3)]
    assert {item.case_id for page in pages for item in page} == {"case-0", "case-1", "case-2"}
    assert len(tuple(store.audit_entries)) == 3


async def test_reconciliation_wraps_when_retention_shrinks_the_page_set() -> None:
    store = InMemoryStateStore()
    for index in range(3):
        case = replace(_case(AssignmentState.DEGRADED), case_id=f"case-{index}")
        await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    reconciler = AssignmentReconciler(store=store, scan_limit=2)
    await reconciler.plan()
    await store.delete_states_beyond("human_assignment:case:", retain_newest=1)
    assert [item.case_id for item in await reconciler.plan()] == ["case-2"]
