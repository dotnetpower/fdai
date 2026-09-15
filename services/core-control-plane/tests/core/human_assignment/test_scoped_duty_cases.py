"""Scoped duty review mechanics; all identity, scope, and time evidence is synthetic."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.human_assignment.scoped_duties import (
    DutyResolution,
    ScopeCatalogEntry,
    ScopedDutyPolicy,
)
from fdai.core.human_assignment.scoped_duty_case_model import ScopedDutyCase, ScopedDutyCommand
from fdai.core.human_assignment.scoped_duty_case_service import ScopedDutyCaseService
from fdai.core.human_assignment.scoped_duty_planning import ScopedDutyPlanner
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.scoped_duty import ScopedDutyRequest

AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
AGE = timedelta(minutes=5)
REQUESTER = "human:requester"
FIRST = "human:reviewer-one"
SECOND = "human:reviewer-two"


def request():
    return ScopedDutyRequest.model_validate(
        {
            "source_revision": "revision:example",
            "bindings": [
                {
                    "subject": {"kind": "user", "ref": person},
                    "agent_name": "Odin",
                    "scope_ref": "scope:example",
                    "duty": duty,
                    "fallback": None,
                    "effective_from": (AT - AGE).isoformat(),
                    "effective_until": (AT + timedelta(hours=1)).isoformat(),
                }
                for person, duty in (("human:primary", "primary"), ("human:backup", "backup"))
            ],
        }
    )


def command(number):
    digest = f"{number:064x}"
    return ScopedDutyCommand(proposal_id="operator-" + digest[:32], request_digest=digest)


@pytest.fixture
def runtime():
    time = {"now": AT}

    async def resolve(subject, *, at):
        return DutyResolution(
            subject, at, (subject,), at, at + AGE, "directory:example", "a" * 64, True
        )

    owners = SimpleNamespace(is_current_owner=AsyncMock(return_value=True))
    scopes = SimpleNamespace(
        read_scope=AsyncMock(
            side_effect=lambda ref, *, source_revision: ScopeCatalogEntry(ref, source_revision)
        )
    )
    planner = ScopedDutyPlanner(
        SimpleNamespace(resolve=resolve),
        scopes,
        lambda: time["now"],
        ScopedDutyPolicy(AGE, 1.0, 5.0),
    )
    store = InMemoryStateStore()
    return ScopedDutyCaseService(store, planner, owners, lambda: time["now"]), time, owners


async def pending(runtime):
    service = runtime[0]
    case = await service.create(
        actor=REQUESTER,
        idempotency_key="example-request",
        request=request(),
        justification="Review explicit operational duty coverage.",
        command=command(1 << 240),
        accepted_at=AT,
    )
    return await service.submit(
        case_id=case.case_id,
        actor=REQUESTER,
        expected_revision=case.revision,
        command=command(2 << 240),
        accepted_at=AT,
    )


async def review(service, case, *, actor=FIRST, decision="approve", number=3):
    return await service.review(
        case_id=case.case_id,
        actor=actor,
        expected_revision=case.revision,
        decision=decision,
        plan_digest=case.plan()["digest"],
        command=command(number << 240),
        accepted_at=AT,
    )


async def test_two_distinct_reviews_produce_no_iam_or_merged_ownership(runtime):
    service = runtime[0]
    case = await pending(runtime)
    one = await review(service, case)
    assert one.state == "pending_review" and len(one.reviews) == 1
    two = await review(service, one, actor=SECOND, number=4)
    assert two.state == "approved" and two.pr_ref is None and two.merge_commit_sha is None
    assert two.execution_authority is False and len(two.commands) == 4
    assert (await service.store.read_state_page("human_assignment:case:", limit=5))[1] == 0


@pytest.mark.parametrize("actor", [REQUESTER, "human:primary", "human:backup"])
async def test_requester_and_current_targets_cannot_review(runtime, actor):
    case = await pending(runtime)
    with pytest.raises(PermissionError):
        await review(runtime[0], case, actor=actor)
    assert (await runtime[0].get(case.case_id)).revision == case.revision


async def test_prior_reviewer_losing_owner_blocks_final_review(runtime):
    service, _, owners = runtime
    case = await review(service, await pending(runtime))
    owners.is_current_owner.side_effect = lambda actor, *, at: actor != FIRST
    with pytest.raises(PermissionError):
        await review(service, case, actor=SECOND, number=4)
    assert (await service.get(case.case_id)).state == "pending_review"


async def test_lost_scope_or_current_person_holds_without_recording_review(runtime):
    service = runtime[0]
    case = await pending(runtime)
    service.planner.scopes.read_scope.side_effect = None
    service.planner.scopes.read_scope.return_value = None
    with pytest.raises(ValueError, match="coverage"):
        await review(service, case)
    assert not (await service.get(case.case_id)).reviews


async def test_review_digest_and_stale_revision_are_fenced(runtime):
    service = runtime[0]
    case = await pending(runtime)
    for digest, revision in (("b" * 64, case.revision), (case.plan()["digest"], 1)):
        with pytest.raises(ValueError):
            await service.review(
                case_id=case.case_id,
                actor=FIRST,
                expected_revision=revision,
                decision="approve",
                plan_digest=digest,
                command=command(3 << 240),
                accepted_at=AT,
            )
    assert (await service.get(case.case_id)).revision == case.revision


async def test_exact_replay_and_restart_do_not_duplicate_review(runtime):
    service, _, owners = runtime
    case = await pending(runtime)
    first = await review(service, case)
    restarted = ScopedDutyCaseService(service.store, service.planner, owners, service.clock)
    assert await review(restarted, case) == first
    assert len((await restarted.get(case.case_id)).reviews) == 1


async def test_rejection_is_terminal_and_never_asks_a_second_owner(runtime):
    service = runtime[0]
    case = await review(service, await pending(runtime), decision="reject")
    with pytest.raises(ValueError, match="pending"):
        await review(service, case, actor=SECOND, number=4)
    assert (await service.get(case.case_id)).state == "rejected"


async def test_concurrent_different_reviews_have_one_cas_winner(runtime):
    service = runtime[0]
    case = await pending(runtime)
    results = await asyncio.gather(
        review(service, case), review(service, case, actor=SECOND, number=4), return_exceptions=True
    )
    assert sum(isinstance(result, ScopedDutyCase) for result in results) == 1
    assert len((await service.get(case.case_id)).reviews) == 1


async def test_failed_atomic_audit_leaves_review_unwritten(runtime, monkeypatch):
    service = runtime[0]
    case = await pending(runtime)
    monkeypatch.setattr(
        service.store,
        "compare_and_set_state_with_audit",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit"):
        await review(service, case)
    assert not (await service.get(case.case_id)).reviews


async def test_review_cannot_outlive_plan_during_owner_lookup(runtime):
    service, time, owners = runtime
    case = await pending(runtime)

    def expire(actor, *, at):
        time["now"] = AT + AGE
        return True

    owners.is_current_owner.side_effect = expire
    with pytest.raises(ValueError, match="expired"):
        await review(service, case)
    assert not (await service.get(case.case_id)).reviews


async def test_case_rejects_coerced_authority_and_plan_tampering(runtime):
    case = await pending(runtime)
    for changes in (
        {"execution_authority": 0},
        {"plan_json": case.plan_json.replace("scope:example", "scope:other")},
        {"state": "active"},
        {"state": "ownership_merged", "merge_commit_sha": "a" * 40},
    ):
        with pytest.raises(ValueError):
            ScopedDutyCase.model_validate({**case.model_dump(), **changes})
