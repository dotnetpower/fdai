"""Current role-group evidence, not duty or token claims, admits Reader backups."""

from __future__ import annotations

import json
import runpy
from dataclasses import replace
from pathlib import Path

import pytest
from fdai_operator_service.families.iam.contracts import DirectoryIdentity, IamPrincipal
from fdai_operator_service.families.iam.errors import IamConflictError, IamUnavailableError
from fdai_operator_service.families.iam.handover_review_eligibility import reader_evidence_current
from fdai_service_contracts import OperatorRole

_support = runpy.run_path(str(Path(__file__).with_name("test_handover_acceptance.py")))
_setup, _complete, _command = (_support[name] for name in ("_setup", "_complete", "_command"))
BACKUP, OWNER = _support["BACKUP"], _support["_OTHER_SUBJECT"]


class GroupVerifier:
    def __init__(self):
        self.calls = []

    async def verify(self, **_kwargs):
        return True

    async def verify_review(self, **kwargs):
        self.calls.append(kwargs)
        return "group:readers" in kwargs["reviewer_group_ids"]


async def _ready():
    runtime, store, _reader, _verifier, goal_id = await _setup()
    groups = {"current": ("group:readers",)}
    verifier = GroupVerifier()
    runtime = replace(runtime, evidence_verifier=verifier)

    async def roster(_groups, *, limit):
        return (
            DirectoryIdentity("entra", OWNER, "owner@example.com", None, True, roles=("Owner",)),
            DirectoryIdentity(
                "entra",
                BACKUP,
                "backup@example.com",
                None,
                True,
                roles=("Reader",),
                group_ids=groups["current"],
            ),
        )

    runtime.directory.list_role_roster = roster
    await _complete(runtime, goal_id)
    return runtime, store, verifier, goal_id, groups


def _ack(goal_id, revision):
    return replace(
        _command(goal_id, "acknowledge", revision, actor=BACKUP),
        principal=IamPrincipal(BACKUP, frozenset({OperatorRole.READER})),
    )


async def test_reader_backup_with_current_matching_group_can_acknowledge():
    runtime, _store, verifier, goal_id, _groups = await _ready()
    await runtime.submit(_command(goal_id, "accept", 7, actor=OWNER))
    accepted = await runtime.submit(_ack(goal_id, 8))
    assert accepted["state"] == "accepted"
    assert verifier.calls
    assert all(call["reviewer_roles"] == ("Reader",) for call in verifier.calls)
    assert "group:readers" not in json.dumps(accepted)


@pytest.mark.parametrize("groups", [(), ("group:other",)])
async def test_role_or_goal_metadata_never_substitutes_for_observed_membership(groups):
    runtime, store, _verifier, goal_id, current = await _ready()
    current["current"] = groups
    store.states[f"operator-handover-goal:{goal_id}"]["group_ids"] = ["group:readers"]
    with pytest.raises(IamConflictError, match="backup"):
        await runtime.submit(_ack(goal_id, 7))
    assert store.states[f"operator-handover-goal:{goal_id}"]["backup_review"] is None


async def test_prior_reader_membership_loss_blocks_final_owner_acceptance():
    runtime, _store, _verifier, goal_id, groups = await _ready()
    reviewed = await runtime.submit(_ack(goal_id, 7))
    assert reviewed["state"] == "ready_for_review"
    groups["current"] = ()
    with pytest.raises(IamConflictError, match="backup"):
        await runtime.submit(_command(goal_id, "accept", 8, actor=OWNER))


async def test_multiple_slots_recheck_each_distinct_document_only_once():
    runtime, _store, verifier, goal_id, _groups = await _ready()
    assert await reader_evidence_current(
        await runtime.get_goal(goal_id),
        _ack(goal_id, 7).principal,
        directory=runtime.directory,
        verifier=verifier,
    )
    assert len(verifier.calls) == 1


async def test_unmapped_backup_does_not_probe_document_acl():
    runtime, _store, verifier, goal_id, _groups = await _ready()
    goal = {**await runtime.get_goal(goal_id), "agent_name": "Thor"}
    assert not await runtime.may_review_goal(goal, _ack(goal_id, 7).principal)
    assert verifier.calls == []


@pytest.mark.parametrize("groups", [(" padded ",), (None,), tuple("group" for _ in range(501))])
async def test_malformed_or_unbounded_membership_is_unavailable(groups):
    runtime, _store, _verifier, goal_id, current = await _ready()
    current["current"] = groups
    with pytest.raises(IamUnavailableError, match="group evidence"):
        await runtime.submit(_ack(goal_id, 7))
