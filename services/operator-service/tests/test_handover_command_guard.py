from __future__ import annotations

from dataclasses import replace

import pytest
from fdai_operator_service.families.iam.contracts import HandoverGoalCommand, IamPrincipal
from fdai_operator_service.families.iam.errors import IamConflictError, IamPermissionError
from fdai_operator_service.families.iam.handover_command_guard import (
    authorize_goal_command,
    goal_command_digest,
)
from fdai_service_contracts import OperatorRole


def _command(operation: str = "accept", *, actor: str = "reviewer") -> HandoverGoalCommand:
    return HandoverGoalCommand(
        principal=IamPrincipal(oid=actor, roles=frozenset({OperatorRole.OWNER})),
        goal_id="goal-1",
        operation=operation,
        expected_revision=2,
    )


@pytest.mark.parametrize("actor", ["subject", "SUBJECT"])
def test_goal_subject_cannot_accept_own_evidence(actor: str) -> None:
    with pytest.raises(IamPermissionError, match="independent Owner"):
        authorize_goal_command({"subject_ref": "subject"}, _command(actor=actor))


@pytest.mark.parametrize(
    "role", [OperatorRole.READER, OperatorRole.APPROVER, OperatorRole.BREAK_GLASS]
)
def test_acceptance_requires_owner_not_an_approval_or_emergency_role(role: OperatorRole) -> None:
    command = replace(_command(), principal=IamPrincipal(oid="reviewer", roles=frozenset({role})))
    with pytest.raises(IamPermissionError, match="independent Owner"):
        authorize_goal_command({"subject_ref": "subject"}, command)


@pytest.mark.parametrize("operation", ["snooze", "decline", "not-applicable", "evidence"])
def test_an_owner_cannot_answer_another_subjects_goal(operation: str) -> None:
    with pytest.raises(IamPermissionError, match="another subject"):
        authorize_goal_command({"subject_ref": "subject"}, _command(operation))


def test_subject_matching_is_case_insensitive_without_replacing_the_exact_subject() -> None:
    subject = authorize_goal_command(
        {"subject_ref": "SUBJECT"}, _command("snooze", actor="subject")
    )
    assert subject == "SUBJECT"


@pytest.mark.parametrize("subject", [None, "", "  ", 1])
def test_missing_goal_subject_is_not_authority(subject: object) -> None:
    with pytest.raises(IamConflictError, match="ownership"):
        authorize_goal_command({"subject_ref": subject}, _command())


def test_replay_digest_normalizes_identity_but_binds_changed_reason() -> None:
    command = replace(_command("not-applicable", actor="subject"), reason_ref="reason:one")
    upper = replace(command, principal=IamPrincipal(oid="SUBJECT", roles=command.principal.roles))
    assert goal_command_digest(command) == goal_command_digest(upper)
    changed = replace(command, reason_ref="reason:two")
    assert goal_command_digest(command) != goal_command_digest(changed)


def test_unknown_operations_are_not_accepted_as_subject_commands() -> None:
    with pytest.raises(IamConflictError, match="unknown"):
        authorize_goal_command({"subject_ref": "subject"}, _command("promote", actor="subject"))
