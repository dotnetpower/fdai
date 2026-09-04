"""Focused tests for the server-owned current ownership projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.iam.assignments import enrich_assignment_identities
from fdai_operator_service.families.iam.contracts import (
    DirectoryIdentity,
    DirectoryStatus,
)
from fdai_operator_service.families.operations.contracts import (
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.ownership_projection import OwnershipProjectionReader
from fdai_service_contracts import OperatorRole


def _payload(*, version: int = 2, subject_id: str = "subject-1") -> dict[str, object]:
    return {
        "_revision": "sha256:source",
        "map": {
            "version": version,
            "maintainers": ["maintainer-1", "maintainer-2"],
            "agents": [
                {
                    "name": "Odin",
                    "autonomous": False,
                    "accept_autonomous_reason": None,
                    "stewards": [
                        {
                            "kind": "user",
                            "id": subject_id,
                            "responsibility": "accountable",
                            **({"duty": "primary"} if version == 2 else {"duty": None}),
                        },
                        {
                            "kind": "user",
                            "id": "subject-2",
                            "responsibility": "accountable",
                            **({"duty": "backup"} if version == 2 else {"duty": None}),
                        },
                    ],
                }
            ],
        },
        "coverage": {
            "is_clean": True,
            "total_agents": 1,
            "autonomous_agents": 0,
            "maintainer_count": 2,
            "findings": [],
        },
        "identity_health": {"status": "not_configured", "checked_at": None},
    }


class _Fallback:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        del query
        return self.payload


class _Directory:
    def __init__(self) -> None:
        self.lookups: list[str] = []

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        self.lookups.append(subject_id)
        return DirectoryIdentity(
            provider="entra",
            subject_id=subject_id,
            username=f"{subject_id}@example.com",
            display_name=f"Person {subject_id}",
            active=True,
            roles=("Owner",) if subject_id.startswith("maintainer") else (),
        )

    async def directory_status(self) -> DirectoryStatus:
        return DirectoryStatus(
            source="microsoft-graph",
            availability="available",
            observed_at=datetime(2026, 9, 4, tzinfo=UTC),
        )

    async def get_steward_subject_by_id(
        self,
        subject_id: str,
        *,
        kind: str,
    ) -> DirectoryIdentity | None:
        if kind == "user":
            return await self.get_by_subject_id(subject_id)
        self.lookups.append(subject_id)
        return DirectoryIdentity(
            provider="entra",
            subject_id=subject_id,
            username=f"Group {subject_id}",
            display_name=f"Group {subject_id}",
            active=True,
            user_type="group",
            principal_type="group",
        )


class _Assignments:
    def __init__(self) -> None:
        self.calls = 0

    async def assignment_projection(self, query: object) -> Mapping[str, object]:
        del query
        self.calls += 1
        return {
            "items": [
                {
                    "case": {
                        "case_id": "case-1",
                        "state": "pending_review",
                        "revision": 2,
                        "intent": {
                            "subject": {"provider": "entra", "subject_id": "candidate-1"},
                            "requested_role": "Reader",
                            "duty_bindings": [
                                {
                                    "agent_name": "Odin",
                                    "duty": "backup",
                                    "scope_ref": "scope:platform",
                                }
                            ],
                            "goal_refs": ["goal:odin:v1"],
                        },
                        "effect_receipts": [],
                    }
                }
            ],
            "total": 1,
            "case_projection_truncated": False,
        }


class _UnavailableAssignments(_Assignments):
    async def assignment_projection(self, query: object) -> Mapping[str, object]:
        del query
        raise RuntimeError("private database detail")


class _MismatchedDirectory(_Directory):
    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        self.lookups.append(subject_id)
        return DirectoryIdentity(
            provider="entra",
            subject_id=f"different-{subject_id}",
            username="wrong@example.com",
            display_name="Wrong Identity",
            active=True,
        )


def _query(*, owner: bool = True, operation: str = "stewardship.coverage") -> ProjectionQuery:
    return ProjectionQuery(
        operation=operation,
        principal_id="operator-1",
        path={},
        params={},
        limit=100,
        cursor=None,
        roles=frozenset({OperatorRole.OWNER} if owner else {OperatorRole.READER}),
    )


async def test_enriches_exact_identities_coverage_and_owner_proposals() -> None:
    directory = _Directory()
    assignments = _Assignments()
    reader = OwnershipProjectionReader(_Fallback(_payload()), directory, assignments)

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    assert isinstance(ownership, Mapping)
    assert ownership["deployment_readiness"] == "ready"
    assert ownership["source_revision"] == "sha256:source"
    summary = ownership["summary"]
    assert isinstance(summary, Mapping)
    assert summary == {
        "agent_count": 1,
        "ready_agents": 1,
        "coverage_gap_agents": 0,
        "autonomous_agents": 0,
        "pending_proposals": 1,
    }
    agents = ownership["agents"]
    assert isinstance(agents, list)
    odin = agents[0]
    assert odin["subjects"][0]["display_name"] == "Person subject-1"
    assert odin["coverage"]["backup_or_escalation_count"] == 1
    assert odin["proposals"][0]["scope_ref"] == "scope:platform"
    assert odin["proposals"][0]["subject"]["display_name"] == "Person candidate-1"
    assert assignments.calls == 1
    assert set(directory.lookups) == {
        "maintainer-1",
        "maintainer-2",
        "subject-1",
        "subject-2",
        "candidate-1",
    }


async def test_reader_does_not_expose_owner_assignment_cases_to_readers() -> None:
    assignments = _Assignments()
    reader = OwnershipProjectionReader(_Fallback(_payload()), _Directory(), assignments)

    result = await reader.read(_query(owner=False))

    ownership = result["current_ownership"]
    assert ownership["assignment_projection"] == {
        "availability": "restricted_or_not_configured",
        "total": None,
    }
    assert ownership["summary"]["pending_proposals"] == 0
    assert assignments.calls == 0


async def test_assignment_failure_does_not_hide_current_ownership() -> None:
    reader = OwnershipProjectionReader(
        _Fallback(_payload()),
        _Directory(),
        _UnavailableAssignments(),
    )

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    assert ownership["deployment_readiness"] == "ready"
    assert ownership["assignment_projection"] == {
        "availability": "unavailable",
        "total": None,
        "truncated": False,
    }


async def test_terminal_assignment_cases_are_not_reported_as_pending_changes() -> None:
    assignments = _Assignments()
    original = await assignments.assignment_projection(object())
    item = original["items"][0]

    class TerminalAssignments(_Assignments):
        async def assignment_projection(self, query: object) -> Mapping[str, object]:
            del query
            rejected = {**item, "case": {**item["case"], "case_id": "case-2", "state": "rejected"}}
            active = {**item, "case": {**item["case"], "case_id": "case-3", "state": "active"}}
            return {**original, "items": [item, rejected, active], "total": 3}

    reader = OwnershipProjectionReader(_Fallback(_payload()), _Directory(), TerminalAssignments())

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    assert ownership["summary"]["pending_proposals"] == 1
    assert ownership["agents"][0]["proposals"][0]["case_id"] == "case-1"


async def test_bounded_assignment_page_reports_incomplete_change_evidence() -> None:
    class TruncatedAssignments(_Assignments):
        async def assignment_projection(self, query: object) -> Mapping[str, object]:
            payload = await super().assignment_projection(query)
            return {**payload, "total": 101, "next_cursor": 100}

    reader = OwnershipProjectionReader(
        _Fallback(_payload()),
        _Directory(),
        TruncatedAssignments(),
    )

    result = await reader.read(_query())

    assert result["current_ownership"]["assignment_projection"] == {
        "availability": "available",
        "total": 101,
        "truncated": True,
    }


async def test_terminal_history_does_not_consume_identity_lookup_budget() -> None:
    assignments = _Assignments()
    original = await assignments.assignment_projection(object())
    item = original["items"][0]

    class TerminalHistory(_Assignments):
        async def assignment_projection(self, query: object) -> Mapping[str, object]:
            del query
            items = [
                {
                    **item,
                    "case": {
                        **item["case"],
                        "case_id": f"case-{index}",
                        "state": "rejected",
                        "intent": {
                            **item["case"]["intent"],
                            "subject": {
                                "provider": "entra",
                                "subject_id": f"terminal-{index}",
                            },
                        },
                    },
                }
                for index in range(70)
            ]
            return {**original, "items": items, "total": len(items)}

    directory = _Directory()
    reader = OwnershipProjectionReader(_Fallback(_payload()), directory, TerminalHistory())

    result = await reader.read(_query())

    assert result["current_ownership"]["summary"]["pending_proposals"] == 0
    assert all(not subject.startswith("terminal-") for subject in directory.lookups)


async def test_unique_subject_limit_degrades_enrichment_without_hiding_map() -> None:
    assignments = _Assignments()
    original = await assignments.assignment_projection(object())
    item = original["items"][0]

    class LargePendingPage(_Assignments):
        async def assignment_projection(self, query: object) -> Mapping[str, object]:
            del query
            items = [
                {
                    **item,
                    "case": {
                        **item["case"],
                        "case_id": f"case-{index}",
                        "intent": {
                            **item["case"]["intent"],
                            "subject": {
                                "provider": "entra",
                                "subject_id": f"candidate-{index}",
                            },
                        },
                    },
                }
                for index in range(70)
            ]
            return {**original, "items": items, "total": len(items)}

    reader = OwnershipProjectionReader(_Fallback(_payload()), _Directory(), LargePendingPage())

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    assert ownership["agents"][0]["name"] == "Odin"
    assert ownership["directory"]["availability"] == "unavailable"
    assert "64-subject lookup limit" in ownership["directory"]["detail"]


async def test_placeholders_block_readiness_without_directory_lookup() -> None:
    directory = _Directory()
    reader = OwnershipProjectionReader(
        _Fallback(_payload(subject_id="00000000-0000-0000-0000-000000000000")),
        directory,
        None,
    )

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    assert ownership["deployment_readiness"] == "bindings_required"
    assert ownership["agents"][0]["coverage"]["status"] == "bindings_required"
    assert "00000000-0000-0000-0000-000000000000" not in directory.lookups


async def test_mismatched_directory_subject_is_never_presented_as_resolved() -> None:
    reader = OwnershipProjectionReader(_Fallback(_payload()), _MismatchedDirectory(), None)

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    subject = ownership["agents"][0]["subjects"][0]
    assert subject["display_name"] is None
    assert subject["resolution"] == "kind_mismatch"
    assert ownership["deployment_readiness"] == "review_required"


async def test_group_stewards_use_the_separate_ownership_lookup() -> None:
    payload = _payload()
    payload["map"]["agents"][0]["stewards"][1].update(  # type: ignore[index]
        {"kind": "group", "id": "group-1"},
    )
    reader = OwnershipProjectionReader(_Fallback(payload), _Directory(), None)

    result = await reader.read(_query())

    backup = result["current_ownership"]["agents"][0]["subjects"][1]
    assert backup["display_name"] == "Group group-1"
    assert backup["principal_type"] == "group"


async def test_schema_v1_is_readable_but_requires_migration() -> None:
    reader = OwnershipProjectionReader(_Fallback(_payload(version=1)), _Directory(), None)

    result = await reader.read(_query())

    ownership = result["current_ownership"]
    assert ownership["deployment_readiness"] == "migration_required"
    assert ownership["agents"][0]["coverage"]["status"] == "migration_required"
    assert [item["duty"] for item in ownership["agents"][0]["subjects"]] == [
        "primary",
        "backup",
    ]


async def test_schema_v1_derives_duties_from_accountable_order_only() -> None:
    payload = _payload(version=1)
    payload["map"]["agents"][0]["stewards"].insert(  # type: ignore[index]
        0,
        {
            "kind": "user",
            "id": "informed-1",
            "responsibility": "informed",
            "duty": None,
        },
    )
    reader = OwnershipProjectionReader(_Fallback(payload), _Directory(), None)

    result = await reader.read(_query())

    subjects = result["current_ownership"]["agents"][0]["subjects"]
    assert [item["duty"] for item in subjects] == [None, "primary", "backup"]


async def test_same_subject_cannot_satisfy_primary_and_backup_coverage() -> None:
    payload = _payload()
    payload["map"]["agents"][0]["stewards"][1]["id"] = "subject-1"  # type: ignore[index]
    reader = OwnershipProjectionReader(_Fallback(payload), _Directory(), None)

    result = await reader.read(_query())

    agent = result["current_ownership"]["agents"][0]
    assert agent["coverage"] == {
        "primary_count": 1,
        "backup_or_escalation_count": 0,
        "status": "coverage_gap",
    }
    assert result["current_ownership"]["deployment_readiness"] == "review_required"


async def test_non_stewardship_reads_are_delegated_unchanged() -> None:
    payload = {"value": "unchanged"}
    reader = OwnershipProjectionReader(_Fallback(payload), _Directory(), _Assignments())

    assert await reader.read(_query(operation="dashboard")) is payload


async def test_malformed_stewardship_payload_fails_closed() -> None:
    reader = OwnershipProjectionReader(_Fallback({"map": {"version": 2}}), None, None)

    with pytest.raises(ProjectionUnavailableError, match="stewardship agents is malformed"):
        await reader.read(_query())


async def test_assignment_identity_enrichment_replaces_null_display_hints() -> None:
    result = await enrich_assignment_identities(
        {
            "items": [
                {
                    "subject": {
                        "provider": "entra",
                        "subject_id": "subject-1",
                        "display_name": None,
                        "username": None,
                        "active": None,
                    },
                    "roles": None,
                }
            ],
            "total": 1,
        },
        directory=_Directory(),
    )

    assert result["directory_availability"] == "available"
    assert result["items"][0]["subject"]["display_name"] == "Person subject-1"
    assert result["items"][0]["subject"]["resolution"] == "resolved"


async def test_assignment_identity_enrichment_marks_missing_directory_explicitly() -> None:
    result = await enrich_assignment_identities(
        {"items": [{"subject": {"subject_id": "subject-1"}}], "total": 1},
        directory=None,
    )

    assert result["directory_availability"] == "not_configured"
