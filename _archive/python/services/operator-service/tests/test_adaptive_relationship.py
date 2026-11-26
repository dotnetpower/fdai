"""Read-only relationship proofs require current ownership and directory evidence."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai_operator_service.adaptive_relationship import (
    AdaptiveRelationshipPolicy,
    AdaptiveRelationshipResolver,
)
from fdai_operator_service.families.iam.contracts import (
    DirectoryIdentity,
    DirectoryStatus,
    HumanIdentityDirectory,
)
from fdai_operator_service.families.operations.contracts import ProjectionQuery
from fdai_operator_service.iam_composition import build_adaptive_relationship_resolver
from fdai_operator_service.ownership_projection import OwnershipProjectionReader
from fdai_service_contracts import OperatorRole

_NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
_SUBJECT = "subject-example"
_GROUP = "group-example"
_ROLES = frozenset({OperatorRole.READER})


def _identity(subject_id: str = _SUBJECT, *, group: bool = False) -> DirectoryIdentity:
    return DirectoryIdentity(
        provider="example-directory",
        subject_id=subject_id,
        username="display-only@example.com",
        display_name="Display only",
        active=True,
        principal_type="group" if group else "person",
        roles=("Owner",),
    )


def _subject(*, group: bool = False, informed: bool = False) -> dict[str, object]:
    return {
        "kind": "group" if group else "user",
        "subject_id": _GROUP if group else _SUBJECT,
        "active": True,
        "resolution": "resolved",
        "responsibility": "informed" if informed else "accountable",
        "duty": None if informed else "primary",
    }


def _payload(*subjects: Mapping[str, object]) -> dict[str, object]:
    return {
        "_revision": "sha256:example-revision",
        "current_ownership": {
            "schema_version": "1.0.0",
            "authority": "read_only",
            "source_revision": "sha256:example-revision",
            "directory": {
                "availability": "available",
                "observed_at": _NOW.isoformat(),
            },
            "agents": [{"name": "Odin", "subjects": list(subjects or (_subject(),))}],
        },
    }


class _Reader:
    def __init__(self, payload: Mapping[str, object] | None = None) -> None:
        self.payload = payload if payload is not None else _payload()
        self.queries: list[ProjectionQuery] = []

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        self.queries.append(query)
        return self.payload


def test_iam_composition_binds_relationship_evidence_without_reading_sources() -> None:
    reader = _Reader()
    directory = _Directory()
    resolver = build_adaptive_relationship_resolver(
        projection_reader=reader,
        directory=directory,
        assignments=None,
    )
    assert isinstance(resolver.ownership, OwnershipProjectionReader)
    assert resolver.ownership.fallback is reader
    assert resolver.ownership.directory is directory
    assert resolver.ownership.assignments is None
    assert resolver.directory is directory
    assert reader.queries == []
    assert directory.lookups == []


class _Directory:
    def __init__(self) -> None:
        self.identity: DirectoryIdentity | None = _identity()
        self.status = DirectoryStatus("example-directory", "available", _NOW)
        self.roster_mode = "member"
        self.lookups: list[str] = []
        self.roster_queries: list[Mapping[str, str]] = []

    async def search(self, query: str, *, limit: int) -> Sequence[DirectoryIdentity]:
        raise AssertionError("conversation relationships MUST NOT search names")

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        self.lookups.append(subject_id)
        return self.identity

    async def directory_status(self) -> DirectoryStatus:
        return self.status

    async def list_role_roster(
        self, role_group_ids: Mapping[str, str], *, limit: int
    ) -> Sequence[DirectoryIdentity]:
        self.roster_queries.append(dict(role_group_ids))
        assert len(role_group_ids) == 1
        marker, group_id = next(iter(role_group_ids.items()))
        assert marker.startswith("adaptive_relationship_")
        group = replace(_identity(group_id, group=True), roles=(marker,))
        member = replace(_identity(), roles=(marker,))
        if self.roster_mode == "app_roles":
            return (_identity(group_id, group=True), _identity())
        if self.roster_mode == "no_member":
            return (group,)
        if self.roster_mode == "truncated":
            return (group, *(_identity(f"other-{index}") for index in range(limit - 1)))
        if self.roster_mode == "oversized":
            return (group, *(member for _ in range(limit)))
        if self.roster_mode == "duplicate":
            return (group, member, member)
        if self.roster_mode == "inactive":
            return (group, replace(member, active=False))
        if self.roster_mode == "other_provider":
            return (group, replace(member, provider="different-directory"))
        return (group, member)


def _resolver(
    payload: Mapping[str, object] | None = None,
    directory: _Directory | None = None,
    *,
    policy: AdaptiveRelationshipPolicy | None = None,
) -> AdaptiveRelationshipResolver:
    return AdaptiveRelationshipResolver(
        _Reader(payload),
        directory or _Directory(),
        clock=lambda: _NOW,
        policy=policy or AdaptiveRelationshipPolicy(),
    )


def _current(payload: Mapping[str, object]) -> dict[str, object]:
    return cast(dict[str, object], payload["current_ownership"])


def _agent(payload: Mapping[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], _current(payload)["agents"])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("informed", "duty", "kind"),
    [
        (False, "primary", "steward"),
        (False, "backup", "steward"),
        (False, "escalation", "steward"),
        (True, None, "collaborator"),
    ],
)
async def test_exact_active_subject_gets_bounded_non_authorizing_proof(
    informed: bool, duty: str | None, kind: str
) -> None:
    subject = {**_subject(informed=informed), "duty": duty}
    resolver = _resolver(_payload(subject))
    result = await resolver.resolve(principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin")
    assert result.status == "matched" and result.reason is None and result.proof is not None
    assert result.proof.target_agent == "Odin"
    assert result.proof.principal_id == _SUBJECT
    assert result.proof.kind == kind
    assert result.proof.source_revision == "sha256:example-revision"
    assert result.proof.verified_at == _NOW
    assert result.proof.expires_at == _NOW + timedelta(seconds=60)
    assert result.proof.execution_authority is False
    assert "display-only" not in result.proof.model_dump_json()
    assert "roles" not in result.proof.model_dump()
    assert cast(_Reader, resolver.ownership).queries[0].roles == _ROLES
    assert cast(_Directory, resolver.directory).lookups == [_SUBJECT]
    assert cast(_Directory, resolver.directory).roster_queries == []


@pytest.mark.asyncio
async def test_explicit_target_is_not_replaced_by_another_mapped_agent() -> None:
    result = await _resolver().resolve(principal_id=_SUBJECT, roles=_ROLES, target_agent="Bragi")
    assert result.target_agent == "Bragi"
    assert (
        result.status == "unknown" and result.reason == "mapping_not_found" and result.proof is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, 1, True, "", "unversioned", "UNKNOWN", "a" * 257])
async def test_unversioned_or_non_string_revision_cannot_create_proof(revision: object) -> None:
    payload = _payload()
    _current(payload)["source_revision"] = revision
    result = await _resolver(payload).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.status == "unknown" and result.reason == "ownership_unversioned"


@pytest.mark.asyncio
async def test_revision_disagreement_is_not_silently_reconciled() -> None:
    payload = _payload()
    payload["_revision"] = "sha256:different-revision"
    result = await _resolver(payload).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == "ownership_revision_mismatch" and result.proof is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observed_at",
    [
        None,
        "not-a-date",
        _NOW.replace(tzinfo=None).isoformat(),
        (_NOW - timedelta(seconds=300)).isoformat(),
        (_NOW + timedelta(seconds=1)).isoformat(),
    ],
)
async def test_stale_unknown_naive_or_future_projection_is_unknown(observed_at: object) -> None:
    payload = _payload()
    _current(payload)["directory"] = {"availability": "available", "observed_at": observed_at}
    result = await _resolver(payload).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == "ownership_directory_stale" and result.proof is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        (None, "principal_not_verified"),
        (_identity("another-subject"), "principal_not_verified"),
        (_identity(group=True), "principal_not_verified"),
        (replace(_identity(), active=False), "principal_inactive"),
    ],
)
async def test_directory_must_independently_verify_exact_active_person(
    identity: DirectoryIdentity | None, reason: str
) -> None:
    directory = _Directory()
    directory.identity = identity
    result = await _resolver(directory=directory).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == reason and result.proof is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"active": False}, "mapping_inactive"),
        ({"active": "true"}, "mapping_inactive"),
        ({"resolution": "unresolved"}, "mapping_unavailable"),
        ({"duty": None}, "mapping_invalid"),
        ({"responsibility": "Owner"}, "mapping_invalid"),
    ],
)
async def test_mapping_activity_resolution_and_duty_are_required(
    patch: Mapping[str, object], reason: str
) -> None:
    result = await _resolver(_payload({**_subject(), **patch})).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == reason and result.proof is None


@pytest.mark.asyncio
async def test_usernames_and_roles_never_match_a_different_subject() -> None:
    subject = {
        **_subject(),
        "subject_id": "different-subject",
        "username": "display-only@example.com",
    }
    result = await _resolver(_payload(subject)).resolve(
        principal_id=_SUBJECT, roles=frozenset({OperatorRole.OWNER}), target_agent="Odin"
    )
    assert result.reason == "mapping_not_found" and result.proof is None


@pytest.mark.asyncio
async def test_duplicate_agent_or_subject_mapping_is_ambiguous() -> None:
    duplicate_agent = _payload()
    _current(duplicate_agent)["agents"] = [_agent(duplicate_agent), _agent(duplicate_agent)]
    for payload in (duplicate_agent, _payload(_subject(), _subject())):
        result = await _resolver(payload).resolve(
            principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
        )
        assert result.reason == "mapping_ambiguous" and result.proof is None


@pytest.mark.asyncio
async def test_independent_group_membership_produces_proof_without_role_grants() -> None:
    directory = _Directory()
    resolver = _resolver(_payload(_subject(group=True)), directory)
    result = await resolver.resolve(principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin")
    assert (
        result.status == "matched" and result.proof is not None and result.proof.kind == "steward"
    )
    assert len(directory.roster_queries) == 1
    assert tuple(directory.roster_queries[0].values()) == (_GROUP,)
    assert set(directory.roster_queries[0]).isdisjoint(role.value for role in OperatorRole)
    assert _GROUP not in result.proof.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["app_roles", "truncated", "oversized", "duplicate", "inactive", "other_provider"]
)
async def test_unproved_or_ambiguous_group_membership_is_unknown(mode: str) -> None:
    directory = _Directory()
    directory.roster_mode = mode
    result = await _resolver(_payload(_subject(group=True)), directory).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == "group_membership_unavailable" and result.proof is None


@pytest.mark.asyncio
async def test_group_existence_alone_is_not_membership() -> None:
    directory = _Directory()
    directory.roster_mode = "no_member"
    result = await _resolver(_payload(_subject(group=True)), directory).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.status == "unknown" and result.proof is None


@pytest.mark.asyncio
async def test_conflicting_user_and_group_relationship_kinds_are_ambiguous() -> None:
    result = await _resolver(_payload(_subject(), _subject(group=True, informed=True))).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == "mapping_ambiguous" and result.proof is None


@pytest.mark.asyncio
async def test_group_work_is_bounded_before_directory_queries() -> None:
    directory = _Directory()
    subjects = [{**_subject(group=True), "subject_id": f"group-{index}"} for index in range(5)]
    result = await _resolver(_payload(*subjects), directory).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == "mapping_limit_exceeded" and result.proof is None
    assert directory.lookups == [] and directory.roster_queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["unknown", "unavailable"])
async def test_unavailable_independent_directory_status_is_unknown(availability: str) -> None:
    directory = _Directory()
    directory.status = DirectoryStatus("example-directory", availability, _NOW)
    result = await _resolver(directory=directory).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert result.reason == "directory_stale" and result.proof is None


@pytest.mark.asyncio
async def test_directory_without_freshness_contract_is_unknown() -> None:
    class DirectoryWithoutStatus:
        async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity:
            return _identity(subject_id)

    resolver = replace(
        _resolver(), directory=cast(HumanIdentityDirectory, DirectoryWithoutStatus())
    )
    result = await resolver.resolve(principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin")
    assert result.reason == "directory_freshness_unavailable" and result.proof is None


@pytest.mark.asyncio
async def test_proof_expiry_cannot_outlive_source_freshness_or_scope() -> None:
    payload = _payload()
    _current(payload)["directory"] = {
        "availability": "available",
        "observed_at": (_NOW - timedelta(seconds=290)).isoformat(),
    }
    first = await _resolver(payload).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert first.proof is not None and first.proof.expires_at == _NOW + timedelta(seconds=10)
    _agent(payload)["scope"] = {"effective_until": (_NOW + timedelta(seconds=5)).isoformat()}
    second = await _resolver(payload).resolve(
        principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
    )
    assert second.proof is not None and second.proof.expires_at == _NOW + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_provider_failure_is_content_free_and_never_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingReader(_Reader):
        async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
            self.queries.append(query)
            raise RuntimeError("sensitive-directory-body")

    reader = FailingReader()
    with caplog.at_level(logging.INFO):
        result = await replace(_resolver(), ownership=reader).resolve(
            principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
        )
    assert result.reason == "relationship_source_unavailable" and result.proof is None
    assert len(reader.queries) == 1
    assert "sensitive-directory-body" not in caplog.text and _SUBJECT not in caplog.text


@pytest.mark.asyncio
async def test_deadline_returns_unknown_without_retry() -> None:
    class SlowReader(_Reader):
        async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
            self.queries.append(query)
            await asyncio.sleep(10)
            return self.payload

    reader = SlowReader()
    resolver = replace(
        _resolver(policy=AdaptiveRelationshipPolicy(timeout_seconds=0.01)), ownership=reader
    )
    result = await resolver.resolve(principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin")
    assert result.reason == "relationship_deadline" and result.proof is None
    assert len(reader.queries) == 1


@pytest.mark.asyncio
async def test_external_cancellation_propagates() -> None:
    class CancelledReader(_Reader):
        async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await replace(_resolver(), ownership=CancelledReader()).resolve(
            principal_id=_SUBJECT, roles=_ROLES, target_agent="Odin"
        )


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), 301])
def test_proof_lifetime_is_bounded(value: float) -> None:
    with pytest.raises(ValueError):
        AdaptiveRelationshipPolicy(proof_ttl_seconds=value)
