"""Server-owned current operational ownership projection.

Responsibility:
    Enrich the reviewed stewardship declaration with read-only identity and assignment evidence.
Boundary:
    This module never changes stewardship, IAM membership, assignment cases, or runtime authority.
Authority and state:
    The wrapped projection remains authoritative. Enrichment reports unavailable evidence
    explicitly.
Dependencies:
    Operations projection, IAM directory, and assignment observation ports.
Deployment:
    Runs inside the independently deployed Operator service.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fdai_service_contracts import OperatorRole

from fdai_operator_service.families.iam.contracts import (
    AssignmentCaseQuery,
    AssignmentRequestOutbox,
    DirectoryIdentity,
    HumanIdentityDirectory,
    HumanIdentityDirectoryStatus,
    IamPrincipal,
)
from fdai_operator_service.families.operations.contracts import (
    ProjectionQuery,
    ProjectionReader,
    ProjectionUnavailableError,
)

_STEWARDSHIP_OPERATION: Final = "stewardship.coverage"
_PLACEHOLDER_SUBJECT: Final = "00000000-0000-0000-0000-000000000000"
_MAX_SUBJECTS: Final = 64
_ASSIGNMENT_LIMIT: Final = 100


@dataclass(frozen=True, slots=True)
class OwnershipProjectionReader:
    """Decorate only the stewardship read with bounded ownership evidence."""

    fallback: ProjectionReader
    directory: HumanIdentityDirectory | None
    assignments: AssignmentRequestOutbox | None

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Return an additive ownership projection without changing other reads."""
        payload = await self.fallback.read(query)
        if query.operation != _STEWARDSHIP_OPERATION:
            return payload
        assignment_projection = await self._assignment_projection(query)
        return await build_current_ownership_projection(
            payload,
            directory=self.directory,
            assignment_projection=assignment_projection,
        )

    async def _assignment_projection(
        self,
        query: ProjectionQuery,
    ) -> Mapping[str, object] | None:
        if self.assignments is None or OperatorRole.OWNER not in query.roles:
            return None
        try:
            return await self.assignments.assignment_projection(
                AssignmentCaseQuery(
                    principal=IamPrincipal(oid=query.principal_id, roles=query.roles),
                    limit=_ASSIGNMENT_LIMIT,
                    offset=0,
                )
            )
        except Exception:  # noqa: BLE001 - durable source details are not caller-safe.
            return {
                "_availability": "unavailable",
                "items": [],
                "total": 0,
                "case_projection_truncated": False,
            }


async def build_current_ownership_projection(
    payload: Mapping[str, object],
    *,
    directory: HumanIdentityDirectory | None,
    assignment_projection: Mapping[str, object] | None,
) -> Mapping[str, object]:
    """Build the browser-safe joined projection from bounded server-owned inputs."""
    map_value = _mapping(payload.get("map"), "stewardship map")
    agents = _mapping_sequence(map_value.get("agents"), "stewardship agents")
    maintainers = _string_sequence(map_value.get("maintainers"), "stewardship maintainers")
    version = _integer(map_value.get("version"), "stewardship version")
    subject_refs = (
        *_subject_refs(maintainers, agents),
        *_assignment_subject_refs(assignment_projection),
    )
    if len(subject_refs) > _MAX_SUBJECTS:
        raise ProjectionUnavailableError(
            f"stewardship projection exceeds the {_MAX_SUBJECTS}-subject enrichment limit"
        )

    resolved, directory_state = await _resolve_subjects(directory, subject_refs)
    proposals, proposal_state = _assignment_proposals(assignment_projection, resolved=resolved)
    projected_agents = [
        _project_agent(agent, version=version, resolved=resolved, proposals=proposals)
        for agent in agents
    ]
    projected_maintainers = [
        _project_subject(
            kind="user",
            subject_id=subject_id,
            responsibility="accountable",
            duty="escalation",
            resolved=resolved,
        )
        for subject_id in maintainers
    ]
    readiness = _overall_readiness(version, projected_maintainers, projected_agents)
    ownership = {
        "schema_version": "1.0.0",
        "authority": "read_only",
        "source_revision": _optional_string(payload.get("_revision")),
        "deployment_readiness": readiness,
        "directory": directory_state,
        "assignment_projection": proposal_state,
        "maintainers": projected_maintainers,
        "agents": projected_agents,
        "summary": _summary(projected_agents, proposals),
    }
    return {**payload, "current_ownership": ownership}


async def _resolve_subjects(
    directory: HumanIdentityDirectory | None,
    subject_refs: Sequence[tuple[str, str]],
) -> tuple[dict[tuple[str, str], DirectoryIdentity | str], Mapping[str, object]]:
    unique_refs = tuple(dict.fromkeys(subject_refs))
    if directory is None:
        return (
            {ref: "not_configured" for ref in unique_refs},
            {
                "source": "not_configured",
                "availability": "not_configured",
                "observed_at": None,
                "detail": "No human identity directory is configured.",
            },
        )

    semaphore = asyncio.Semaphore(8)

    async def resolve(ref: tuple[str, str]) -> tuple[tuple[str, str], DirectoryIdentity | str]:
        kind, subject_id = ref
        if subject_id == _PLACEHOLDER_SUBJECT:
            return ref, "placeholder"
        try:
            async with semaphore:
                identity = await directory.get_by_subject_id(subject_id)
        except Exception:  # noqa: BLE001 - provider details must not cross the API boundary.
            return ref, "unavailable"
        if identity is None:
            return ref, "not_found"
        if identity.subject_id != subject_id:
            return ref, "kind_mismatch"
        if kind == "group" and identity.principal_type != "group":
            return ref, "kind_mismatch"
        if kind == "user" and identity.principal_type == "group":
            return ref, "kind_mismatch"
        return ref, identity

    resolved = dict(await asyncio.gather(*(resolve(ref) for ref in unique_refs)))
    status = await _directory_status(directory)
    if any(value == "unavailable" for value in resolved.values()):
        status = {**status, "availability": "unavailable", "detail": "Identity lookup failed."}
    return resolved, status


async def _directory_status(directory: HumanIdentityDirectory) -> Mapping[str, object]:
    if not isinstance(directory, HumanIdentityDirectoryStatus):
        return {
            "source": "configured",
            "availability": "unknown",
            "observed_at": None,
            "detail": "The directory does not expose freshness evidence.",
        }
    try:
        status = await directory.directory_status()
    except Exception:  # noqa: BLE001 - provider details must not cross the API boundary.
        return {
            "source": "configured",
            "availability": "unavailable",
            "observed_at": None,
            "detail": "Directory status is unavailable.",
        }
    return status.to_dict()


def _subject_refs(
    maintainers: Sequence[str],
    agents: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    refs = [("user", subject_id) for subject_id in maintainers]
    for agent in agents:
        for steward in _mapping_sequence(agent.get("stewards"), "agent stewards"):
            refs.append(
                (
                    _required_string(steward.get("kind"), "steward kind"),
                    _required_string(steward.get("id"), "steward id"),
                )
            )
    return tuple(refs)


def _project_agent(
    agent: Mapping[str, object],
    *,
    version: int,
    resolved: Mapping[tuple[str, str], DirectoryIdentity | str],
    proposals: Mapping[str, Sequence[Mapping[str, object]]],
) -> Mapping[str, object]:
    name = _required_string(agent.get("name"), "agent name")
    autonomous = _boolean(agent.get("autonomous"), "agent autonomous")
    subjects: list[Mapping[str, object]] = []
    accountable_index = 0
    for steward in _mapping_sequence(agent.get("stewards"), "agent stewards"):
        responsibility = _required_string(
            steward.get("responsibility"),
            "steward responsibility",
        )
        subjects.append(
            _project_subject(
                kind=_required_string(steward.get("kind"), "steward kind"),
                subject_id=_required_string(steward.get("id"), "steward id"),
                responsibility=responsibility,
                duty=_derived_duty(
                    steward,
                    version=version,
                    accountable_index=accountable_index,
                ),
                resolved=resolved,
            )
        )
        if responsibility == "accountable":
            accountable_index += 1
    primary_subjects = {
        (str(subject["kind"]), str(subject["subject_id"]))
        for subject in subjects
        if subject["responsibility"] == "accountable" and subject["duty"] == "primary"
    }
    backup_subjects = {
        (str(subject["kind"]), str(subject["subject_id"]))
        for subject in subjects
        if subject["responsibility"] == "accountable"
        and subject["duty"] in {"backup", "escalation"}
    }
    primary_count = len(primary_subjects)
    backup_count = len(backup_subjects - primary_subjects)
    status = _agent_readiness(
        version=version,
        autonomous=autonomous,
        subjects=subjects,
        primary_count=primary_count,
        backup_count=backup_count,
    )
    return {
        "name": name,
        "autonomous": autonomous,
        "accept_autonomous_reason": _optional_string(agent.get("accept_autonomous_reason")),
        "scope": {
            "scope_ref": None,
            "status": "unscoped_declaration",
            "effective_from": None,
            "effective_until": None,
        },
        "subjects": subjects,
        "coverage": {
            "primary_count": primary_count,
            "backup_or_escalation_count": backup_count,
            "status": status,
        },
        "proposals": list(proposals.get(name, ())),
    }


def _project_subject(
    *,
    kind: str,
    subject_id: str,
    responsibility: str,
    duty: str | None,
    resolved: Mapping[tuple[str, str], DirectoryIdentity | str],
) -> Mapping[str, object]:
    identity = resolved.get((kind, subject_id), "not_configured")
    if isinstance(identity, DirectoryIdentity):
        resolution = "resolved" if identity.active else "inactive"
        return {
            "kind": kind,
            "subject_id": subject_id,
            "responsibility": responsibility,
            "duty": duty,
            "display_name": identity.display_name,
            "username": identity.username,
            "active": identity.active,
            "principal_type": identity.principal_type,
            "roles": list(identity.roles),
            "resolution": resolution,
        }
    return {
        "kind": kind,
        "subject_id": subject_id,
        "responsibility": responsibility,
        "duty": duty,
        "display_name": None,
        "username": None,
        "active": None,
        "principal_type": "group" if kind == "group" else "person",
        "roles": [],
        "resolution": identity,
    }


def _derived_duty(
    steward: Mapping[str, object],
    *,
    version: int,
    accountable_index: int,
) -> str | None:
    explicit = _optional_string(steward.get("duty"))
    if explicit is not None or version != 1:
        return explicit
    if steward.get("responsibility") != "accountable":
        return None
    return "primary" if accountable_index == 0 else "backup"


def _agent_readiness(
    *,
    version: int,
    autonomous: bool,
    subjects: Sequence[Mapping[str, object]],
    primary_count: int,
    backup_count: int,
) -> str:
    if autonomous:
        return "autonomous"
    resolutions = {str(subject["resolution"]) for subject in subjects}
    if "placeholder" in resolutions:
        return "bindings_required"
    if version < 2:
        return "migration_required"
    if primary_count < 1 or backup_count < 1:
        return "coverage_gap"
    if "unavailable" in resolutions or "not_configured" in resolutions:
        return "identity_unavailable"
    if resolutions & {"inactive", "not_found", "kind_mismatch"}:
        return "identity_review"
    return "ready"


def _overall_readiness(
    version: int,
    maintainers: Sequence[Mapping[str, object]],
    agents: Sequence[Mapping[str, object]],
) -> str:
    subject_resolutions = {
        str(subject["resolution"]) for subject in maintainers if isinstance(subject, Mapping)
    }
    agent_states = {
        str(_mapping(agent.get("coverage"), "agent coverage").get("status")) for agent in agents
    }
    if "placeholder" in subject_resolutions or "bindings_required" in agent_states:
        return "bindings_required"
    if version < 2 or "migration_required" in agent_states:
        return "migration_required"
    if agent_states & {"coverage_gap", "identity_review"}:
        return "review_required"
    if (
        subject_resolutions & {"unavailable", "not_configured"}
        or "identity_unavailable" in agent_states
    ):
        return "identity_unavailable"
    if subject_resolutions & {"inactive", "not_found", "kind_mismatch"}:
        return "review_required"
    return "ready"


def _assignment_proposals(
    payload: Mapping[str, object] | None,
    *,
    resolved: Mapping[tuple[str, str], DirectoryIdentity | str],
) -> tuple[dict[str, list[Mapping[str, object]]], Mapping[str, object]]:
    if payload is None:
        return {}, {"availability": "restricted_or_not_configured", "total": None}
    if payload.get("_availability") == "unavailable":
        return {}, {"availability": "unavailable", "total": None, "truncated": False}
    items = _mapping_sequence(payload.get("items"), "assignment projection items")
    proposals: dict[str, list[Mapping[str, object]]] = {}
    for item in items:
        case = item.get("case")
        if not isinstance(case, Mapping):
            continue
        intent = case.get("intent")
        if not isinstance(intent, Mapping):
            continue
        subject = intent.get("subject")
        if not isinstance(subject, Mapping):
            continue
        subject_id = _required_string(subject.get("subject_id"), "assignment subject id")
        projected_subject = _project_subject(
            kind="user",
            subject_id=subject_id,
            responsibility="accountable",
            duty=None,
            resolved=resolved,
        )
        for duty in _mapping_sequence(intent.get("duty_bindings"), "assignment duties"):
            agent_name = _required_string(duty.get("agent_name"), "assignment agent")
            proposals.setdefault(agent_name, []).append(
                {
                    "case_id": _required_string(case.get("case_id"), "assignment case id"),
                    "state": _required_string(case.get("state"), "assignment case state"),
                    "revision": _integer(case.get("revision"), "assignment case revision"),
                    "subject": projected_subject,
                    "requested_role": _required_string(
                        intent.get("requested_role"),
                        "assignment requested role",
                    ),
                    "duty": _required_string(duty.get("duty"), "assignment duty"),
                    "scope_ref": _required_string(
                        duty.get("scope_ref"),
                        "assignment scope reference",
                    ),
                    "goal_refs": list(
                        _string_sequence(intent.get("goal_refs"), "assignment goal refs")
                    ),
                    "effect_receipt_count": len(
                        _mapping_sequence(case.get("effect_receipts"), "effect receipts")
                    ),
                }
            )
    return proposals, {
        "availability": "available",
        "total": _integer(payload.get("total"), "assignment projection total"),
        "truncated": bool(payload.get("case_projection_truncated", False)),
    }


def _assignment_subject_refs(
    payload: Mapping[str, object] | None,
) -> tuple[tuple[str, str], ...]:
    if payload is None:
        return ()
    refs: list[tuple[str, str]] = []
    for item in _mapping_sequence(payload.get("items"), "assignment projection items"):
        case = item.get("case")
        if not isinstance(case, Mapping):
            continue
        intent = case.get("intent")
        if not isinstance(intent, Mapping):
            continue
        subject = intent.get("subject")
        if not isinstance(subject, Mapping):
            continue
        refs.append(
            (
                "user",
                _required_string(subject.get("subject_id"), "assignment subject id"),
            )
        )
    return tuple(refs)


def _summary(
    agents: Sequence[Mapping[str, object]],
    proposals: Mapping[str, Sequence[Mapping[str, object]]],
) -> Mapping[str, int]:
    states = [
        str(_mapping(agent.get("coverage"), "agent coverage").get("status")) for agent in agents
    ]
    return {
        "agent_count": len(agents),
        "ready_agents": states.count("ready"),
        "coverage_gap_agents": sum(state not in {"ready", "autonomous"} for state in states),
        "autonomous_agents": states.count("autonomous"),
        "pending_proposals": sum(len(items) for items in proposals.values()),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _mapping_sequence(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProjectionUnavailableError(f"{label} is malformed")
    if not all(isinstance(item, Mapping) for item in value):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return tuple(value)


def _string_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProjectionUnavailableError(f"{label} is malformed")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return tuple(value)


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


__all__ = ["OwnershipProjectionReader", "build_current_ownership_projection"]
