"""Fail-closed projection of Core observations onto the Agent SSE contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from fdai_service_contracts import AgentOperationalActivity
from pydantic import ValidationError

from .live_stream import LiveStreamEvent
from .stage_frames import parse_stage_frame

_PANTHEON: Final = frozenset(
    {
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Vidar",
        "Var",
        "Bragi",
        "Saga",
        "Mimir",
        "Muninn",
        "Norns",
        "Njord",
        "Freyr",
        "Loki",
    }
)
_AGENT_STATES: Final = frozenset(
    {
        "idle",
        "watching",
        "collecting",
        "analyzing",
        "deciding",
        "executing",
        "approving",
        "auditing",
    }
)
_SOURCES: Final = frozenset({"unknown", "synthetic-dev", "replay", "runtime-observed"})
_STAGE_AGENT: Final = {
    "ingest": "Huginn",
    "route": "Heimdall",
    "verify": "Forseti",
    "gate": "Forseti",
    "execute": "Thor",
    "audit": "Saga",
}
_ACTIVE_STATE: Final = {
    "ingest": "collecting",
    "route": "analyzing",
    "verify": "analyzing",
    "gate": "deciding",
    "execute": "executing",
    "audit": "auditing",
}
_HANDOFF: Final = {
    "route": "routing the event",
    "verify": "verifying the candidate action",
    "gate": "risk-gating the action",
    "execute": "executing the approved action",
    "audit": "recording the audit entry",
}
_SENSING_AGENTS: Final = frozenset({"Huginn", "Heimdall"})
_MAX_IDENTIFIER_CHARS: Final = 1_024
_MAX_DETAIL_CHARS: Final = 512
_MAX_INCIDENTS: Final = 256
_MAX_FUTURE_SKEW: Final = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class _IncidentState:
    correlation_id: str
    ticket_id: str
    incident_id: str | None
    title: str
    severity: str
    status: str
    involved: tuple[str, ...]
    last_agent: str | None


class AgentActivityProjector:
    """Project observed runtime and stage records into bounded Agent stream events."""

    def __init__(self) -> None:
        self._incidents: dict[str, _IncidentState] = {}

    def project(self, payload: Mapping[str, object]) -> tuple[LiveStreamEvent, ...]:
        """Return only events grounded in a valid runtime or stage observation."""
        operational = _operational_activity_event(payload)
        if operational is not None:
            return (operational,)
        runtime = _runtime_state_event(payload)
        if runtime is not None:
            return (runtime,)
        stage_event = parse_stage_frame(payload)
        if stage_event is None:
            return ()
        return self._project_stage(stage_event.payload)

    def _project_stage(self, payload: Mapping[str, object]) -> tuple[LiveStreamEvent, ...]:
        event_id = str(payload["event_id"])
        correlation_id = str(payload["correlation_id"])
        stage = str(payload["stage"])
        phase = str(payload["phase"])
        source = str(payload["source"])
        timestamp = str(payload["ts"])
        detail_raw = payload.get("detail")
        detail = dict(detail_raw) if isinstance(detail_raw, Mapping) else {}
        agent = (
            "Var"
            if stage == "gate" and detail.get("gate_decision") == "hil"
            else _STAGE_AGENT[stage]
        )
        prior = self._incidents.get(correlation_id)
        involved = prior.involved if prior is not None else ()
        if agent not in involved:
            involved = (*involved, agent)
        incident_id = _nonempty(detail.get("incident_id")) or (
            prior.incident_id if prior is not None else None
        )
        ticket_id = incident_id or (
            prior.ticket_id if prior is not None else f"INC-{correlation_id}"
        )
        status = _next_status(prior.status if prior is not None else "open", stage, phase, detail)
        incident = _IncidentState(
            correlation_id=correlation_id,
            ticket_id=ticket_id,
            incident_id=incident_id,
            title=(
                prior.title
                if prior is not None
                else f"Rule {detail['rule']}"
                if _nonempty(detail.get("rule"))
                else f"Event {event_id}"
            ),
            severity=(
                _nonempty(detail.get("severity"))
                or (prior.severity if prior is not None else "info")
            ),
            status=status,
            involved=involved,
            last_agent=agent,
        )
        self._incidents[correlation_id] = incident
        if len(self._incidents) > _MAX_INCIDENTS:
            self._incidents.pop(next(iter(self._incidents)))

        events: list[LiveStreamEvent] = []
        if incident_id is not None and incident != prior:
            events.append(
                _event(
                    event_id,
                    {
                        "type": "incident.ticket",
                        "ticket_id": ticket_id,
                        "correlation_id": correlation_id,
                        "status": status,
                        "title": incident.title,
                        "severity": incident.severity,
                        "involved_agents": list(involved),
                        "rca": None,
                        "ts": timestamp,
                        "source": source,
                    },
                )
            )
        if prior is not None and prior.last_agent is not None and prior.last_agent != agent:
            events.append(
                _event(
                    event_id,
                    {
                        "type": "conversation.turn",
                        "correlation_id": correlation_id,
                        "from_agent": prior.last_agent,
                        "to_agent": agent,
                        "kind": "handoff",
                        "text": _HANDOFF.get(stage, f"handling {stage}"),
                        "ts": timestamp,
                        "source": source,
                    },
                )
            )
        state = (
            "idle"
            if phase == "failed"
            else ("approving" if agent == "Var" else _ACTIVE_STATE[stage])
        )
        events.append(
            _agent_state(
                event_id=event_id,
                agent=agent,
                state=state,
                timestamp=timestamp,
                correlation_id=correlation_id,
                detail=f"{stage} {phase}",
                source=source,
            )
        )
        if stage == "audit" and phase == "done":
            waiting = (
                str(detail.get("decision") or detail.get("gate_decision") or "").lower() == "hil"
            )
            for involved_agent in involved:
                events.append(
                    _agent_state(
                        event_id=event_id,
                        agent=involved_agent,
                        state=(
                            "approving"
                            if waiting and involved_agent == "Var"
                            else "watching"
                            if involved_agent in _SENSING_AGENTS
                            else "idle"
                        ),
                        timestamp=timestamp,
                        correlation_id=(
                            correlation_id if waiting and involved_agent == "Var" else None
                        ),
                        detail=(
                            "awaiting human approval"
                            if waiting and involved_agent == "Var"
                            else "pipeline stage complete"
                        ),
                        source=source,
                    )
                )
        return tuple(events)


def _runtime_state_event(payload: Mapping[str, object]) -> LiveStreamEvent | None:
    if payload.get("type") != "agent.runtime-state":
        return None
    agent = payload.get("agent")
    state = payload.get("state")
    timestamp = payload.get("ts")
    correlation_id = payload.get("correlation_id")
    detail = payload.get("detail")
    source = payload.get("source", "unknown")
    if (
        agent not in _PANTHEON
        or state not in _AGENT_STATES
        or source not in _SOURCES
        or not isinstance(timestamp, str)
        or (correlation_id is not None and _identifier(correlation_id) is None)
        or (detail is not None and (not isinstance(detail, str) or len(detail) > _MAX_DETAIL_CHARS))
    ):
        return None
    try:
        observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed_at.tzinfo is None or observed_at > datetime.now(UTC) + _MAX_FUTURE_SKEW:
        return None
    return _agent_state(
        event_id=f"{agent}:{timestamp}",
        agent=str(agent),
        state=str(state),
        timestamp=timestamp,
        correlation_id=str(correlation_id) if correlation_id is not None else None,
        detail=detail if isinstance(detail, str) else None,
        source=str(source),
    )


def _operational_activity_event(payload: Mapping[str, object]) -> LiveStreamEvent | None:
    if payload.get("type") != "agent.operational-activity":
        return None
    try:
        activity = AgentOperationalActivity.model_validate(payload)
    except ValidationError:
        return None
    if activity.observed_at > datetime.now(UTC) + _MAX_FUTURE_SKEW:
        return None
    return _event(activity.activity_id, activity.model_dump(mode="json"))


def _agent_state(
    *,
    event_id: str,
    agent: str,
    state: str,
    timestamp: str,
    correlation_id: str | None,
    detail: str | None,
    source: str,
) -> LiveStreamEvent:
    return _event(
        event_id,
        {
            "type": "agent.state",
            "agent": agent,
            "state": state,
            "ts": timestamp,
            "correlation_id": correlation_id,
            "detail": detail,
            "source": source,
        },
    )


def _event(event_id: str, payload: Mapping[str, object]) -> LiveStreamEvent:
    return LiveStreamEvent(event_id=event_id, payload=payload, event_type="message")


def _next_status(current: str, stage: str, phase: str, detail: Mapping[str, object]) -> str:
    if current == "resolved":
        return current
    if stage == "audit" and phase == "done":
        decision = str(detail.get("decision") or detail.get("gate_decision") or "").lower()
        outcome = str(detail.get("outcome") or "").lower()
        if decision == "hil":
            return "investigating"
        if outcome in {
            "executed",
            "resolved",
            "remediated",
            "mitigated",
            "rollback_succeeded",
            "rollback_completed",
        }:
            return "resolved"
    if stage in {"verify", "gate", "execute"}:
        return "investigating"
    return current


def _identifier(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_CHARS:
        return None
    return value


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["AgentActivityProjector"]
