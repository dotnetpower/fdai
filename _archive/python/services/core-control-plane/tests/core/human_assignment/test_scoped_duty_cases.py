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


async def test_scoped_duty_case_model_and_service_branches(runtime, monkeypatch):
    import json

    from fdai.core.human_assignment.repository import assignment_case_id
    from fdai.core.human_assignment.scoped_duty_case_model import (
        SCOPED_CASE_PREFIX,
        ScopedDutyReview,
        plan_expiry,
        require_current_plan,
    )

    service, _time, _owners = runtime

    # ScopedDutyCommand and ScopedDutyReview validation
    with pytest.raises(ValueError, match="does not match its digest"):
        ScopedDutyCommand(proposal_id="operator-" + "b" * 32, request_digest="a" * 64)
    with pytest.raises(ValueError, match="MUST be retained together"):
        ScopedDutyCommand(
            proposal_id="operator-" + "a" * 32,
            request_digest="a" * 64,
            result_state="draft",
        )
    cmd = command(10 << 240)
    mat_cmd = cmd.materialized("draft", 1)
    with pytest.raises(ValueError, match="result is immutable"):
        mat_cmd.materialized("draft", 1)
    with pytest.raises(ValueError, match="MUST already be normalized"):
        ScopedDutyReview(
            reviewer_ref="Human:Upper",
            decision="approve",
            plan_digest="a" * 64,
            reviewed_at=AT,
        )

    # ScopedDutyCase model invariants
    draft = await service.create(
        actor=REQUESTER,
        idempotency_key="model-invariants",
        request=request(),
        justification="Review explicit operational duty coverage.",
        command=command(11 << 240),
        accepted_at=AT,
    )
    base_dump = draft.model_dump()
    rev_ok = ScopedDutyReview(
        reviewer_ref=FIRST,
        decision="approve",
        plan_digest=draft.plan()["digest"],
        reviewed_at=AT,
    )
    rev_ok2 = ScopedDutyReview(
        reviewer_ref=SECOND,
        decision="approve",
        plan_digest=draft.plan()["digest"],
        reviewed_at=AT,
    )
    rev_bad_digest = ScopedDutyReview(
        reviewer_ref=FIRST,
        decision="approve",
        plan_digest="f" * 64,
        reviewed_at=AT,
    )
    for bad_patch, match in [
        ({"requester_ref": "Human:Upper"}, "canonical identity"),
        ({"justification": " " * 25}, "canonical identity"),
        ({"updated_at": AT - timedelta(seconds=10)}, "cannot move backwards"),
        ({"state": "pending_review", "reviews": (rev_ok, rev_ok)}, "distinct and independent"),
        ({"state": "pending_review", "reviews": (rev_bad_digest,)}, "does not bind"),
        ({"reviews": (rev_ok,)}, "draft cannot carry a human review"),
        ({"state": "rejected", "reviews": (rev_ok,)}, "rejection MUST remain terminal"),
        (
            {"state": "ownership_pr_open", "reviews": (rev_ok, rev_ok2)},
            "exact review artifact",
        ),
        (
            {
                "state": "ownership_pr_open",
                "reviews": (rev_ok, rev_ok2),
                "pr_ref": "pr:1",
                "candidate_digest": "a" * 64,
                "merge_commit_sha": "b" * 40,
            },
            "separately verified merge",
        ),
        ({"commands": (mat_cmd, mat_cmd)}, "command receipts MUST be unique"),
        ({"commands": (cmd,)}, "original materialized command result"),
        ({"plan_json": '{"not": "canonical"}'}, "canonical object"),
    ]:
        with pytest.raises(ValueError, match=match):
            ScopedDutyCase.model_validate({**base_dump, **bad_patch})

    # command_receipt conflict when same proposal_id has different suffix digest
    conflict_cmd = ScopedDutyCommand(
        proposal_id=draft.commands[0].proposal_id,
        request_digest=draft.commands[0].request_digest[:32] + "f" * 32,
    )
    with pytest.raises(ValueError, match="differs from its retained receipt"):
        draft.command_receipt(conflict_cmd)

    # require_current_plan and plan_expiry branches
    plan_dict = draft.plan()
    with pytest.raises(ValueError, match="clock moved backwards"):
        require_current_plan(plan_dict, at=AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match="across a duty transition"):
        require_current_plan(plan_dict, at=AT + timedelta(hours=2))
    held_plan = json.loads(draft.plan_json)
    held_plan["bindings"][0]["held_reason"] = "scope_missing"
    require_current_plan(held_plan, at=AT)
    assert plan_expiry(held_plan) <= AT + AGE

    # ScopedDutyCaseService branches: get, require_current_command, create replay/conflicts/race
    with pytest.raises(ValueError, match="expired during processing"):
        service.require_current_command(AT - timedelta(minutes=6))
    with pytest.raises(ValueError, match="MUST be non-empty"):
        await service.get("   ")
    with pytest.raises(ValueError, match="not found"):
        await service.get("00000000-0000-0000-0000-000000000000")
    await service.store.write_state(
        SCOPED_CASE_PREFIX + "00000000-0000-0000-0000-000000000001",
        draft.model_dump(mode="json"),
    )
    with pytest.raises(ValueError, match="does not match its source key"):
        await service.get("00000000-0000-0000-0000-000000000001")

    # create replay and conflict
    assert (
        await service.create(
            actor=REQUESTER,
            idempotency_key="model-invariants",
            request=request(),
            justification="Review explicit operational duty coverage.",
            command=command(11 << 240),
            accepted_at=AT,
        )
        == draft
    )
    with pytest.raises(ValueError, match="conflicts with retained intent"):
        await service.create(
            actor=REQUESTER,
            idempotency_key="model-invariants",
            request=request(),
            justification="Different justification text here.",
            command=command(11 << 240),
            accepted_at=AT,
        )

    # Self-supersession and predecessor checks
    self_id = assignment_case_id(REQUESTER, "scoped-duty:self-super")
    self_req = ScopedDutyRequest.model_validate(
        {**request().model_dump(mode="json"), "supersedes_case_id": self_id}
    )
    await service.store.write_state(
        SCOPED_CASE_PREFIX + self_id,
        {
            **draft.model_dump(mode="json"),
            "case_id": self_id,
            "state": "ownership_pr_open",
            "reviews": [rev_ok.model_dump(mode="json"), rev_ok2.model_dump(mode="json")],
            "pr_ref": "pr:1",
            "candidate_digest": "a" * 64,
        },
    )
    with pytest.raises(ValueError, match="cannot supersede itself"):
        await service.create(
            actor=REQUESTER,
            idempotency_key="self-super",
            request=self_req,
            justification="Review explicit operational duty coverage.",
            command=command(12 << 240),
            accepted_at=AT,
        )

    bad_pred_req = ScopedDutyRequest.model_validate(
        {**request().model_dump(mode="json"), "supersedes_case_id": draft.case_id}
    )
    with pytest.raises(ValueError, match="requires a reviewed predecessor"):
        await service.predecessor(bad_pred_req)

    # Valid predecessor in check_review
    pred_req_with_fb = ScopedDutyRequest.model_validate(
        {
            **request().model_dump(mode="json"),
            "supersedes_case_id": self_id,
        }
    )
    succ_draft = await service.create(
        actor=REQUESTER,
        idempotency_key="succ-case",
        request=pred_req_with_fb,
        justification="Review explicit operational duty coverage.",
        command=command(13 << 240),
        accepted_at=AT,
    )
    succ_pending = await service.submit(
        case_id=succ_draft.case_id,
        actor=REQUESTER,
        expected_revision=succ_draft.revision,
        command=command(14 << 240),
        accepted_at=AT,
    )
    # Submit replay returns current
    assert (
        await service.submit(
            case_id=succ_draft.case_id,
            actor=REQUESTER,
            expected_revision=succ_draft.revision,
            command=command(14 << 240),
            accepted_at=AT,
        )
        == succ_pending
    )
    with pytest.raises(PermissionError, match="only the scoped duty requester"):
        await service.submit(
            case_id=succ_draft.case_id,
            actor=FIRST,
            expected_revision=succ_draft.revision,
            command=command(15 << 240),
            accepted_at=AT,
        )
    with pytest.raises(ValueError, match="exact draft revision"):
        await service.submit(
            case_id=succ_draft.case_id,
            actor=REQUESTER,
            expected_revision=99,
            command=command(15 << 240),
            accepted_at=AT,
        )
    await service.check_review(succ_pending, actor=FIRST, plan_digest=succ_pending.plan()["digest"])
    r1_case = await review(service, succ_pending, actor=FIRST, number=16)
    with pytest.raises(ValueError, match="already has a decision"):
        await review(service, r1_case, actor=FIRST, number=17)

    # Create race when write_state_with_audit_if_absent returns False
    race_id = assignment_case_id(REQUESTER, "scoped-duty:race-case")
    await service.store.write_state(
        SCOPED_CASE_PREFIX + race_id,
        {
            **draft.model_dump(mode="json"),
            "case_id": race_id,
            "idempotency_key": "race-case",
            "justification": "Different raced justification.",
        },
    )
    orig_read = service.store.read_state
    read_count = 0

    async def hide_first_read(k: str):
        nonlocal read_count
        if k == SCOPED_CASE_PREFIX + race_id:
            read_count += 1
            if read_count == 1:
                return None
        return await orig_read(k)

    monkeypatch.setattr(service.store, "read_state", hide_first_read)
    with pytest.raises(ValueError, match="conflicts after a concurrent request"):
        await service.create(
            actor=REQUESTER,
            idempotency_key="race-case",
            request=request(),
            justification="Review explicit operational duty coverage.",
            command=command(18 << 240),
            accepted_at=AT,
        )
    monkeypatch.setattr(service.store, "read_state", orig_read)

    # persist CAS race returning matching winner
    orig_cas = service.store.compare_and_set_state_with_audit
    monkeypatch.setattr(
        service.store, "compare_and_set_state_with_audit", AsyncMock(return_value=False)
    )
    assert (
        await service.persist(
            succ_pending,
            r1_case,
            "reviewed",
            FIRST,
            observation=r1_case.plan(),
            accepted_at=None,
        )
        == r1_case
    )
    monkeypatch.setattr(service.store, "compare_and_set_state_with_audit", orig_cas)

    # Incomplete coverage on submit
    inc_draft = await service.create(
        actor=REQUESTER,
        idempotency_key="inc-cov",
        request=request(),
        justification="Review explicit operational duty coverage.",
        command=command(19 << 240),
        accepted_at=AT,
    )
    service.planner.scopes.read_scope.side_effect = None
    service.planner.scopes.read_scope.return_value = None
    with pytest.raises(ValueError, match="coverage is incomplete"):
        await service.submit(
            case_id=inc_draft.case_id,
            actor=REQUESTER,
            expected_revision=inc_draft.revision,
            command=command(20 << 240),
            accepted_at=AT,
        )
