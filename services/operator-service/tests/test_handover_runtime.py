from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest
from fdai_operator_service.families.iam.contracts import (
    DirectoryIdentity,
    HandoverGoalCommand,
    IamPrincipal,
)
from fdai_operator_service.families.iam.errors import IamConflictError
from fdai_operator_service.families.iam.handover_runtime import ProactiveHandoverRuntime
from fdai_operator_service.families.operations.contracts import ProjectionQuery
from fdai_operator_service.postgres_family_store import PostgresProposalConflict
from fdai_service_contracts import OperatorRole

_NOW = datetime(2026, 9, 5, 3, 0, tzinfo=UTC)
_SUBJECT = str(uuid5(NAMESPACE_URL, "fdai-test-handover-subject"))
_OTHER_SUBJECT = str(uuid5(NAMESPACE_URL, "fdai-test-handover-other"))
_DOCUMENT_ID = str(uuid5(NAMESPACE_URL, "fdai-test-handover-document"))
_VERSION_ID = str(uuid5(NAMESPACE_URL, "fdai-test-handover-version"))
_EVIDENCE_REF = f"doc:{_DOCUMENT_ID}:{_VERSION_ID}"


class MemoryStore:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, object]] = {}
        self.proposals: set[str] = set()

    async def read_state(self, key: str) -> dict[str, object] | None:
        value = self.states.get(key)
        return None if value is None else dict(value)

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        if key in self.states:
            return False
        self.states[key] = dict(value)
        return True

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> object:
        del family, operation, principal_id, payload
        if idempotency_key in self.proposals:
            return object()
        current = self.states.get(state_key)
        revision = 0 if current is None else current.get("revision")
        if revision != expected_revision:
            raise PostgresProposalConflict("state revision conflict")
        self.states[state_key] = dict(state_value)
        self.proposals.add(idempotency_key)
        return object()


class OwnershipReader:
    def __init__(self, *, active: bool = True, mapped: bool = True, raw: bool = False) -> None:
        self.active = active
        self.mapped = mapped
        self.raw = raw
        self.queries: list[ProjectionQuery] = []

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        self.queries.append(query)
        subject_id = _SUBJECT if self.mapped else _OTHER_SUBJECT
        if self.raw:
            return {
                "_revision": "revision-7",
                "map": {
                    "agents": [
                        {
                            "name": "Muninn",
                            "stewards": [
                                {
                                    "kind": "user",
                                    "id": subject_id,
                                    "responsibility": "accountable",
                                    "duty": "primary",
                                }
                            ],
                        }
                    ],
                },
            }
        return {
            "current_ownership": {
                "source_revision": "revision-7",
                "agents": [
                    {
                        "name": "Muninn",
                        "subjects": [
                            {
                                "kind": "user",
                                "subject_id": subject_id,
                                "responsibility": "accountable",
                                "duty": "primary",
                                "active": self.active,
                            }
                        ],
                    }
                ],
            }
        }


class IdentityDirectory:
    def __init__(self, *, active: bool) -> None:
        self.active = active

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        return DirectoryIdentity(
            provider="entra",
            subject_id=subject_id,
            username="owner@example.invalid",
            display_name="Owner",
            active=self.active,
            user_type="member",
            roles=(),
            principal_type="person",
        )


def _runtime(
    *,
    store: MemoryStore | None = None,
    active: bool = True,
    mapped: bool = True,
    raw: bool = False,
) -> tuple[ProactiveHandoverRuntime, MemoryStore, OwnershipReader]:
    resolved_store = store or MemoryStore()
    reader = OwnershipReader(active=active, mapped=mapped, raw=raw)
    return (
        ProactiveHandoverRuntime(
            store=resolved_store,
            ownership=reader,
            directory=IdentityDirectory(active=active),
            clock=lambda: _NOW,
        ),
        resolved_store,
        reader,
    )


@pytest.mark.asyncio
async def test_invitation_is_bound_to_active_accountable_owner_and_replays() -> None:
    runtime, store, reader = _runtime()

    first = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )
    replay = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )

    assert first == replay
    assert first is not None
    assert first["agent_name"] == "Muninn"
    assert first["source_revision"] == "revision-7"
    assert first["execution_authority"] is False
    assert len(reader.queries) == 2
    assert len([key for key in store.states if "invitation:" in key]) == 1


@pytest.mark.asyncio
async def test_invitation_accepts_the_raw_operations_projection_shape() -> None:
    runtime, _store, _reader = _runtime(raw=True)

    invitation = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )

    assert invitation is not None
    assert invitation["agent_name"] == "Muninn"


@pytest.mark.asyncio
async def test_cached_invitation_is_hidden_after_identity_deactivation() -> None:
    runtime, store, _reader = _runtime()
    first = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )
    assert first is not None
    inactive = ProactiveHandoverRuntime(
        store=store,
        ownership=OwnershipReader(active=False),
        directory=IdentityDirectory(active=False),
        clock=lambda: _NOW,
    )

    assert (
        await inactive.invitation_for_session(
            subject_ref=_SUBJECT,
            roles=frozenset({OperatorRole.READER}),
            session_id="login-session-1",
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("active", "mapped"), [(False, True), (True, False)])
async def test_invitation_is_not_created_without_live_mapping(active: bool, mapped: bool) -> None:
    runtime, store, _reader = _runtime(active=active, mapped=mapped)

    invitation = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )

    assert invitation is None
    assert not store.states


@pytest.mark.asyncio
async def test_weekly_budget_allows_two_sessions_and_rejects_third() -> None:
    runtime, _store, _reader = _runtime()

    first = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )
    second = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-2",
    )
    third = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-3",
    )

    assert first is not None
    assert second is not None
    assert third is None


@pytest.mark.asyncio
async def test_evidence_transition_is_revision_fenced_and_reviewable() -> None:
    runtime, _store, _reader = _runtime()
    invitation = await runtime.invitation_for_session(
        subject_ref=_SUBJECT,
        roles=frozenset({OperatorRole.READER}),
        session_id="login-session-1",
    )
    assert invitation is not None
    goal_id = str(invitation["goal_id"])
    principal = IamPrincipal(oid=_SUBJECT, roles=frozenset({OperatorRole.READER}))

    updated = await runtime.submit(
        HandoverGoalCommand(
            principal=principal,
            goal_id=goal_id,
            operation="evidence",
            expected_revision=1,
            evidence_ref=_EVIDENCE_REF,
            digest="a" * 64,
            kind="document",
        )
    )

    assert updated["state"] == "ready_for_review"
    assert updated["revision"] == 2
    assert updated["evidence"] == [
        {
            "evidence_ref": _EVIDENCE_REF,
            "digest": "a" * 64,
            "kind": "document",
        }
    ]
    replay = await runtime.submit(
        HandoverGoalCommand(
            principal=principal,
            goal_id=goal_id,
            operation="evidence",
            expected_revision=1,
            evidence_ref=_EVIDENCE_REF,
            digest="a" * 64,
            kind="document",
        )
    )
    assert replay == updated
    with pytest.raises(IamConflictError, match="revision is stale"):
        await runtime.submit(
            HandoverGoalCommand(
                principal=principal,
                goal_id=goal_id,
                operation="decline",
                expected_revision=1,
            )
        )
