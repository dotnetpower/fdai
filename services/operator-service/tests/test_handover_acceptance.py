"""Six-slot and independent-review regressions over the real goal command runtime."""

from __future__ import annotations

import runpy
from dataclasses import replace
from pathlib import Path

import pytest
from fdai_operator_service.families.iam.contracts import HandoverGoalCommand, IamPrincipal
from fdai_operator_service.families.iam.errors import IamConflictError, IamPermissionError
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.handover_checklist import HANDOVER_SLOTS, acceptance_complete

_support = runpy.run_path(str(Path(__file__).with_name("test_handover_runtime.py")))
_EVIDENCE_REF = _support["_EVIDENCE_REF"]
_OTHER_SUBJECT = _support["_OTHER_SUBJECT"]
_SUBJECT = _support["_SUBJECT"]
EvidenceVerifier = _support["EvidenceVerifier"]
_runtime = _support["_runtime"]

BACKUP = "00000000-0000-0000-0000-000000000033"


async def _setup():
    verifier = EvidenceVerifier()
    runtime, store, reader = _runtime(evidence_verifier=verifier)
    original = reader.read

    async def read(query):
        result = dict(await original(query))
        result["current_ownership"]["agents"][0]["subjects"].append(
            {
                "kind": "user",
                "subject_id": BACKUP,
                "active": True,
                "responsibility": "accountable",
                "duty": "backup",
            }
        )
        return result

    reader.read = read

    async def roster(_groups, *, limit):
        from fdai_operator_service.families.iam.contracts import DirectoryIdentity

        return tuple(
            DirectoryIdentity("entra", actor, "user@example.com", None, True, roles=("Owner",))
            for actor in (_OTHER_SUBJECT, BACKUP)
        )

    runtime.directory.list_role_roster = roster
    invitation = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login",
    )
    assert invitation is not None
    return runtime, store, reader, verifier, str(invitation["goal_id"])


def _command(goal_id, operation="evidence", revision=1, slot=None, actor=_SUBJECT):
    return HandoverGoalCommand(
        principal=IamPrincipal(
            actor,
            frozenset(
                {
                    OperatorRole.OWNER
                    if operation == "accept"
                    else (
                        OperatorRole.CONTRIBUTOR
                        if operation == "acknowledge"
                        else OperatorRole.READER
                    )
                }
            ),
        ),
        goal_id=goal_id,
        operation=operation,
        expected_revision=revision,
        evidence_ref=_EVIDENCE_REF if operation == "evidence" else None,
        digest="a" * 64 if operation == "evidence" else None,
        kind="document" if operation == "evidence" else None,
        reason_ref="reason:outside-reviewed-scope" if operation == "not-applicable" else None,
        slot=slot,
    )


async def _complete(runtime, goal_id, *, exemption=False):
    result = None
    for revision, slot in enumerate(HANDOVER_SLOTS, start=1):
        result = await runtime.submit(
            _command(goal_id, "not-applicable" if exemption else "evidence", revision, slot)
        )
        assert result["state"] == ("ready_for_review" if revision == 6 else "in_progress")
    return result


async def test_one_document_does_not_complete_six_required_slots():
    runtime, _, _, _, goal_id = await _setup()
    result = await runtime.submit(_command(goal_id, slot=HANDOVER_SLOTS[0]))
    assert result["state"] == "in_progress"
    with pytest.raises(IamConflictError, match="six"):
        await runtime.submit(_command(goal_id, "accept", 2, actor=_OTHER_SUBJECT))


async def test_unassigned_legacy_evidence_is_readable_but_not_reviewable():
    runtime, _, _, _, goal_id = await _setup()
    result = await runtime.submit(_command(goal_id))
    assert result["state"] == "in_progress"
    assert result["evidence"][0]["evidence_ref"] == _EVIDENCE_REF
    with pytest.raises(IamConflictError):
        await runtime.submit(_command(goal_id, "accept", 2, actor=_OTHER_SUBJECT))


async def test_legacy_accepted_goal_is_projected_as_blocked_without_erasing_its_evidence():
    runtime, store, _, _, goal_id = await _setup()
    await runtime.submit(_command(goal_id))
    recorded = store.states[f"operator-handover-goal:{goal_id}"]
    recorded.pop("checklist_version")
    recorded["state"] = "accepted"
    projected = await runtime.get_goal(goal_id)
    assert projected["state"] == "blocked"
    assert projected["legacy_state"] == "accepted"
    assert projected["evidence"] == recorded["evidence"]
    assert recorded["state"] == "accepted"
    changed = await runtime.submit(_command(goal_id, revision=2, slot=HANDOVER_SLOTS[0]))
    assert changed["state"] == "in_progress"
    assert changed["revision"] == 3


@pytest.mark.parametrize("operation", ["evidence", "not-applicable"])
async def test_each_slot_requires_an_explicit_valid_assignment(operation):
    runtime, _, _, _, goal_id = await _setup()
    with pytest.raises(IamConflictError):
        await runtime.submit(_command(goal_id, operation, slot="unknown_slot"))
    result = await runtime.submit(_command(goal_id, operation, slot=HANDOVER_SLOTS[0]))
    assert result["state"] == "in_progress"
    with pytest.raises(IamConflictError):
        await runtime.submit(_command(goal_id, operation, 2, HANDOVER_SLOTS[0]))


@pytest.mark.parametrize("exemption", [False, True])
async def test_high_impact_acceptance_needs_distinct_owner_and_current_backup(exemption):
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id, exemption=exemption)
    reviewed = await runtime.submit(_command(goal_id, "accept", 7, actor=_OTHER_SUBJECT))
    assert reviewed["state"] == "ready_for_review"
    assert not acceptance_complete(reviewed)
    accepted = await runtime.submit(_command(goal_id, "acknowledge", 8, actor=BACKUP))
    assert accepted["state"] == "accepted"
    assert acceptance_complete(accepted)
    assert accepted["owner_review"]["reviewer_ref"] != accepted["backup_review"]["reviewer_ref"]


async def test_exact_slot_replay_is_idempotent_but_changing_slot_conflicts():
    runtime, _, _, _, goal_id = await _setup()
    command = _command(goal_id, slot=HANDOVER_SLOTS[0])
    first = await runtime.submit(command)
    assert await runtime.submit(command) == first
    with pytest.raises(IamConflictError, match="payload"):
        await runtime.submit(replace(command, slot=HANDOVER_SLOTS[1]))


async def test_second_slot_replay_keeps_the_new_command_identity():
    runtime, _, _, _, goal_id = await _setup()
    await runtime.submit(_command(goal_id, slot=HANDOVER_SLOTS[0]))
    second = _command(goal_id, revision=2, slot=HANDOVER_SLOTS[1])
    result = await runtime.submit(second)
    assert await runtime.submit(second) == result


async def test_backup_ack_cannot_be_borrowed_from_owner_or_primary():
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id)
    with pytest.raises(IamConflictError, match="backup"):
        await runtime.submit(_command(goal_id, "acknowledge", 7, actor=_OTHER_SUBJECT))
    with pytest.raises(IamPermissionError):
        await runtime.submit(_command(goal_id, "acknowledge", 7))


async def test_same_owner_backup_cannot_supply_two_independent_reviews():
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id)
    await runtime.submit(_command(goal_id, "accept", 7, actor=BACKUP))
    with pytest.raises(IamConflictError, match="distinct"):
        await runtime.submit(_command(goal_id, "acknowledge", 8, actor=BACKUP))


async def test_document_withdrawal_invalidates_ready_goal_and_prevents_acceptance():
    runtime, _, _, verifier, goal_id = await _setup()
    await _complete(runtime, goal_id)
    verifier.admitted = False
    stale = await runtime.get_goal(goal_id)
    assert stale["state"] == "stale"
    with pytest.raises(IamConflictError):
        await runtime.submit(_command(goal_id, "accept", 7, actor=_OTHER_SUBJECT))


async def test_reader_backup_does_not_inherit_document_acl_from_ownership():
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id)
    command = _command(goal_id, "acknowledge", 7, actor=BACKUP)
    with pytest.raises(IamConflictError):
        await runtime.submit(
            replace(command, principal=IamPrincipal(BACKUP, frozenset({OperatorRole.READER})))
        )


async def test_prior_owner_role_loss_blocks_final_backup_acceptance():
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id)
    await runtime.submit(_command(goal_id, "accept", 7, actor=_OTHER_SUBJECT))

    async def empty(_groups, *, limit):
        return ()

    runtime.directory.list_role_roster = empty
    with pytest.raises(IamConflictError, match="current identity"):
        await runtime.submit(_command(goal_id, "acknowledge", 8, actor=BACKUP))


async def test_new_owner_review_requires_a_current_directory_role_not_only_a_token():
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id)

    async def empty(_groups, *, limit):
        return ()

    runtime.directory.list_role_roster = empty
    with pytest.raises(IamConflictError, match="current identity"):
        await runtime.submit(_command(goal_id, "accept", 7, actor=_OTHER_SUBJECT))


async def test_cross_agent_reuse_copies_only_current_evidence_not_review_authority():
    runtime, store, reader, _, goal_id = await _setup()
    await _complete(runtime, goal_id)
    await runtime.submit(_command(goal_id, "accept", 7, actor=_OTHER_SUBJECT))
    await runtime.submit(_command(goal_id, "acknowledge", 8, actor=BACKUP))
    target = "b" * 64
    source = dict(store.states[f"operator-handover-goal:{goal_id}"])
    store.states[f"operator-handover-goal:{target}"] = {
        **source,
        "goal_id": target,
        "agent_name": "Thor",
        "revision": 1,
        "state": "not_started",
        "evidence": [],
        "slot_exemptions": {},
        "owner_review": None,
        "backup_review": None,
    }
    read = reader.read

    async def with_thor(query):
        payload = dict(await read(query))
        payload["current_ownership"]["agents"].append(
            {
                **payload["current_ownership"]["agents"][0],
                "name": "Thor",
            }
        )
        return payload

    reader.read = with_thor
    command = replace(_command(target, "reuse"), source_goal_id=goal_id)
    reused = await runtime.submit(command)
    assert reused["evidence"] == source["evidence"]
    assert reused["state"] == "ready_for_review"
    assert reused["owner_review"] is reused["backup_review"] is None
    assert await runtime.submit(command) == reused
    reader.source_revision = "different-revision"
    with pytest.raises(IamConflictError):
        await runtime.submit(command)


@pytest.mark.parametrize("operation", ["evidence", "snooze", "decline", "not-applicable"])
async def test_accepted_goal_never_reopens_through_another_command(operation):
    runtime, _, _, _, goal_id = await _setup()
    await _complete(runtime, goal_id)
    await runtime.submit(_command(goal_id, "accept", 7, actor=_OTHER_SUBJECT))
    await runtime.submit(_command(goal_id, "acknowledge", 8, actor=BACKUP))
    with pytest.raises(IamConflictError, match="closed"):
        await runtime.submit(_command(goal_id, operation, 9, HANDOVER_SLOTS[0]))
