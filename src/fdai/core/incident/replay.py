"""Fail-closed incident lifecycle audit replay."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from uuid import UUID

from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState

from .state_machine import IncidentStateMachine, IncidentTransition


class IncidentReplayError(RuntimeError):
    """Raised when lifecycle audit rows cannot safely rebuild the registry."""


def rehydrate_incidents(
    entries: Iterable[Mapping[str, object]],
    *,
    state_machine: IncidentStateMachine,
    incident_id_factory: Callable[[Iterable[str]], UUID],
    schema_version: str,
) -> dict[UUID, Incident]:
    """Validate ordered lifecycle rows and return a complete incident index."""
    restored: dict[UUID, Incident] = {}
    try:
        for entry in entries:
            kind = _required_string(entry, "kind")
            if kind == "incident.open":
                opened = _incident_from_open_entry(
                    entry,
                    incident_id_factory=incident_id_factory,
                    schema_version=schema_version,
                )
                existing = restored.get(opened.incident_id)
                restored[opened.incident_id] = (
                    opened if existing is None else _merge_replayed_open(existing, opened)
                )
                continue
            if kind == "incident.members":
                _replay_members(restored, entry)
                continue
            if kind == "incident.assigned":
                _replay_assignment(restored, entry)
                continue
            if kind == "incident.ticket":
                _require_existing_incident(restored, entry, kind="ticket")
                continue
            if kind != "incident.transition":
                raise ValueError(f"unsupported lifecycle kind: {kind}")
            _replay_transition(restored, entry, state_machine=state_machine)
    except (KeyError, TypeError, ValueError) as exc:
        raise IncidentReplayError(f"invalid incident lifecycle audit: {exc}") from exc
    return restored


def apply_incident_transition(
    incident: Incident,
    transition: IncidentTransition,
    *,
    severity: IncidentSeverity | None = None,
) -> Incident:
    """Return an incident copy with one validated transition applied."""
    updates: dict[str, object] = {
        "state": transition.to_state,
        "severity": severity or incident.severity,
    }
    if transition.to_state is IncidentState.MITIGATED:
        updates["mitigated_at"] = transition.at
    elif transition.to_state is IncidentState.RESOLVED:
        updates["resolved_at"] = transition.at
    elif transition.to_state is IncidentState.CLOSED:
        updates["closed_at"] = transition.at
    if transition.reason and transition.to_state is IncidentState.MITIGATED:
        updates["mitigation_summary"] = transition.reason
    return incident.model_copy(update=updates)


def _replay_members(
    restored: dict[UUID, Incident],
    entry: Mapping[str, object],
) -> None:
    incident_id = UUID(_required_string(entry, "incident_id"))
    current = restored.get(incident_id)
    if current is None:
        raise ValueError(f"members precede incident.open: {incident_id}")
    added = tuple(UUID(value) for value in _required_string_list(entry, "member_event_ids"))
    restored[incident_id] = current.model_copy(
        update={"member_event_ids": tuple(dict.fromkeys((*current.member_event_ids, *added)))}
    )


def _replay_assignment(
    restored: dict[UUID, Incident],
    entry: Mapping[str, object],
) -> None:
    current = _require_existing_incident(restored, entry, kind="assignment")
    target_assignee = _optional_string(entry, "assignee_oid")
    if current.assignee_oid == target_assignee:
        return
    from_assignee = _optional_string(entry, "from_assignee_oid")
    if current.assignee_oid != from_assignee:
        raise ValueError(f"assignment from_assignee mismatch for {current.incident_id}")
    restored[current.incident_id] = current.model_copy(update={"assignee_oid": target_assignee})


def _require_existing_incident(
    restored: dict[UUID, Incident],
    entry: Mapping[str, object],
    *,
    kind: str,
) -> Incident:
    incident_id = UUID(_required_string(entry, "incident_id"))
    current = restored.get(incident_id)
    if current is None:
        raise ValueError(f"{kind} precedes incident.open: {incident_id}")
    return current


def _replay_transition(
    restored: dict[UUID, Incident],
    entry: Mapping[str, object],
    *,
    state_machine: IncidentStateMachine,
) -> None:
    incident_id = UUID(_required_string(entry, "incident_id"))
    current = restored.get(incident_id)
    if current is None:
        raise ValueError(f"transition precedes incident.open: {incident_id}")
    from_state = IncidentState(_required_string(entry, "from_state"))
    if current.state is not from_state:
        raise ValueError(
            f"transition from_state mismatch for {incident_id}: "
            f"audit={from_state.value}, current={current.state.value}"
        )
    transition = IncidentTransition(
        incident_id=incident_id,
        from_state=from_state,
        to_state=IncidentState(_required_string(entry, "to_state")),
        actor_oid=_required_string(entry, "actor_oid"),
        at=_aware_datetime(entry, "at"),
        reason=_optional_string(entry, "reason"),
    )
    state_machine.validate(current=current.state, target=transition.to_state)
    from_severity_value = _optional_string(entry, "from_severity")
    from_severity = (
        IncidentSeverity(from_severity_value)
        if from_severity_value is not None
        else current.severity
    )
    if current.severity is not from_severity:
        raise ValueError(
            f"transition from_severity mismatch for {incident_id}: "
            f"audit={from_severity.value}, current={current.severity.value}"
        )
    severity_value = _optional_string(entry, "severity")
    target_severity = (
        IncidentSeverity(severity_value) if severity_value is not None else current.severity
    )
    if target_severity is not current.severity and not (
        current.state is IncidentState.RESOLVED and transition.to_state is IncidentState.TRIAGING
    ):
        raise ValueError("severity changed outside resolved -> triaging reopen")
    restored[incident_id] = apply_incident_transition(
        current,
        transition,
        severity=target_severity,
    )


def _incident_from_open_entry(
    entry: Mapping[str, object],
    *,
    incident_id_factory: Callable[[Iterable[str]], UUID],
    schema_version: str,
) -> Incident:
    correlation_keys = _required_string_list(entry, "correlation_keys")
    incident_id = UUID(_required_string(entry, "incident_id"))
    expected_id = incident_id_factory(correlation_keys)
    if incident_id != expected_id:
        raise ValueError(f"incident_id does not match correlation keys: {incident_id}")
    member_event_ids = tuple(
        UUID(value) for value in _required_string_list(entry, "member_event_ids")
    )
    return Incident(
        schema_version=schema_version,
        incident_id=incident_id,
        state=IncidentState(_required_string(entry, "state")),
        severity=IncidentSeverity(_required_string(entry, "severity")),
        opened_at=_aware_datetime(entry, "opened_at"),
        correlation_keys=tuple(correlation_keys),
        member_event_ids=member_event_ids,
        assignee_oid=_optional_string(entry, "assignee_oid"),
    )


def _merge_replayed_open(existing: Incident, replayed: Incident) -> Incident:
    if (
        existing.correlation_keys != replayed.correlation_keys
        or existing.severity is not replayed.severity
        or existing.state is not IncidentState.OPEN
        or replayed.state is not IncidentState.OPEN
    ):
        raise ValueError(f"conflicting duplicate incident.open: {existing.incident_id}")
    return existing.model_copy(
        update={
            "opened_at": min(existing.opened_at, replayed.opened_at),
            "member_event_ids": tuple(
                dict.fromkeys((*existing.member_event_ids, *replayed.member_event_ids))
            ),
            "assignee_oid": existing.assignee_oid or replayed.assignee_oid,
        }
    )


def _required_string(entry: Mapping[str, object], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} MUST be a non-empty string")
    return value


def _optional_string(entry: Mapping[str, object], key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} MUST be a string or null")
    return value or None


def _required_string_list(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = entry[key]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"{key} MUST be a non-empty string list")
    return tuple(value)


def _aware_datetime(entry: Mapping[str, object], key: str) -> datetime:
    value = datetime.fromisoformat(_required_string(entry, key))
    if value.tzinfo is None:
        raise ValueError(f"{key} MUST be timezone-aware")
    return value


__all__ = ["IncidentReplayError", "apply_incident_transition", "rehydrate_incidents"]
