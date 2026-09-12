"""Decode bounded canonical audit evidence for descriptive dashboard reads."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai_service_contracts.control_loop_measurement import (
    CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
    ControlLoopMeasurement,
)

from fdai_operator_service.dashboard_aggregation import (
    ActionObservation,
    ClassifiedEvent,
    HumanTouchpoint,
    MetricObservation,
)

MEASUREMENT_ROW_LIMIT = 20_000
MEASUREMENT_KINDS = (
    CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
    "measurement.action_outcome.v1",
    "measurement.metric.v1",
    "hil.requested",
    "measurement.control_loop.rejected.v1",
)
MEASUREMENT_SNAPSHOT_SQL = """
WITH boundary AS (
    SELECT COALESCE(MAX(seq), 0) AS cutoff_seq, CURRENT_TIMESTAMP AS window_end
      FROM audit_log
), selected AS (
    SELECT audit.seq, audit.action_kind, audit.entry, audit.created_at,
           parked.value->'action'->>'event_id' AS approval_event_id
      FROM audit_log AS audit
      CROSS JOIN boundary
      LEFT JOIN state_kv AS parked
        ON audit.action_kind = 'hil.requested'
       AND parked.key = 'hil_park:' || (audit.entry->>'approval_id')
     WHERE audit.seq <= boundary.cutoff_seq
       AND audit.created_at >= boundary.window_end - interval '30 days'
       AND audit.created_at <= boundary.window_end
       AND audit.action_kind = ANY(%s)
     ORDER BY audit.seq DESC
     LIMIT %s
)
SELECT boundary.cutoff_seq, boundary.window_end,
       COALESCE(jsonb_agg(to_jsonb(selected) ORDER BY selected.seq)
                FILTER (WHERE selected.seq IS NOT NULL), '[]'::jsonb) AS records
  FROM boundary LEFT JOIN selected ON TRUE
 GROUP BY boundary.cutoff_seq, boundary.window_end
"""


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """One complete database-cutoff read with separate canonical fact streams."""

    events: tuple[ClassifiedEvent, ...]
    outcomes: tuple[ActionObservation, ...]
    metrics: tuple[MetricObservation, ...]
    touchpoints: tuple[HumanTouchpoint, ...]
    window_start: datetime
    window_end: datetime
    cutoff_seq: int
    unattributed_touchpoints: int


def decode_dashboard_snapshot(result: Sequence[Mapping[str, object]]) -> DashboardSnapshot:
    """Reject malformed, future or over-bound sources rather than inventing a value."""

    if len(result) != 1:
        raise ValueError("measurement snapshot boundary is unavailable")
    boundary = result[0]
    cutoff = _integer(boundary.get("cutoff_seq"), "cutoff", minimum=0)
    end = _time(boundary.get("window_end"), "snapshot time")
    records = boundary.get("records")
    if not isinstance(records, list):
        raise ValueError("measurement snapshot records MUST be an array")
    if len(records) > MEASUREMENT_ROW_LIMIT:
        raise ValueError("measurement snapshot exceeds the complete read bound")
    events: list[ClassifiedEvent] = []
    outcomes: list[ActionObservation] = []
    metrics: list[MetricObservation] = []
    touchpoints: list[HumanTouchpoint] = []
    orphaned_human_times: list[datetime] = []
    rejected: dict[str, tuple[str, datetime]] = {}
    retained: dict[str, tuple[str, datetime]] = {}
    for raw in records:
        row = _mapping(raw, "audit row")
        seq = _integer(row.get("seq"), "audit sequence", minimum=1)
        if seq > cutoff:
            raise ValueError("measurement audit sequence exceeds its cutoff")
        recorded = _time(row.get("created_at"), "audit time")
        if recorded > end:
            raise ValueError("measurement audit time exceeds its cutoff")
        kind = row.get("action_kind")
        entry = _mapping(row.get("entry"), "audit payload")
        if entry.get("action_kind") != kind:
            raise ValueError("measurement row and payload kinds disagree")
        if kind == CONTROL_LOOP_MEASUREMENT_ACTION_KIND:
            fact = ControlLoopMeasurement.from_audit_entry(entry)
            if fact.recorded_at > end or fact.occurred_at > fact.recorded_at:
                raise ValueError("terminal measurement time is inconsistent")
            if fact.synthetic is not True:
                retained[str(fact.measurement_id)] = (str(fact.event_id), fact.occurred_at)
            events.append(
                ClassifiedEvent(
                    event_id=str(fact.event_id),
                    identity=fact.idempotency_key,
                    tier=fact.tier,
                    decision=fact.gate_route,
                    mode=fact.mode,
                    occurred_at=fact.occurred_at,
                    seq=seq,
                    action_ids=tuple(str(value) for value in fact.action_ids),
                    synthetic=fact.synthetic is True,
                )
            )
        elif kind == "measurement.action_outcome.v1":
            outcomes.append(_outcome(entry, seq=seq, end=end))
        elif kind == "measurement.metric.v1":
            metric = _metric_observation(entry, seq=seq, end=end)
            if metric is not None:
                metrics.append(metric)
        elif kind == "hil.requested":
            event_id = entry.get("event_id") or row.get("approval_event_id")
            if event_id is None:
                orphaned_human_times.append(recorded)
            else:
                touchpoints.append(
                    HumanTouchpoint(
                        event_id=_uuid(event_id, "human input event"),
                        identity=_text(entry.get("approval_id"), "approval identity"),
                    )
                )
        elif kind == "measurement.control_loop.rejected.v1":
            if entry.get("actor") != "fdai.measurement":
                raise ValueError("rejected measurement producer is not canonical")
            occurred = _time(entry.get("occurred_at"), "rejected event time")
            if entry.get("synthetic") is not True and (end - timedelta(days=30) <= occurred <= end):
                rejected[_uuid(entry.get("measurement_id"), "rejected measurement")] = (
                    _uuid(entry.get("event_id"), "rejected event"),
                    occurred,
                )
        else:
            raise ValueError("unsupported measurement source kind")
    if any(retained.get(identity) != source for identity, source in rejected.items()):
        raise ValueError("terminal classification evidence is incomplete after rejection")
    earliest = min((event.occurred_at for event in events), default=end)
    return DashboardSnapshot(
        events=tuple(events),
        outcomes=tuple(outcomes),
        metrics=tuple(metrics),
        touchpoints=tuple(touchpoints),
        window_start=end - timedelta(days=30),
        window_end=end,
        cutoff_seq=cutoff,
        unattributed_touchpoints=sum(value >= earliest for value in orphaned_human_times),
    )


def _outcome(entry: Mapping[str, object], *, seq: int, end: datetime) -> ActionObservation:
    if entry.get("actor") != "fdai.measurement" or entry.get("schema_version") != "1.0.0":
        raise ValueError("action outcome producer or version is not canonical")
    event_id = _uuid(entry.get("event_id"), "outcome event")
    action_id = _uuid(entry.get("action_id"), "outcome action")
    observation_id = _uuid(entry.get("outcome_id"), "outcome identity")
    label = _text(entry.get("label"), "outcome label")
    if label not in {"verified", "mismatch", "unscorable"}:
        raise ValueError("action outcome label is invalid")
    verified = _boolean(entry.get("verification_passed"), "outcome verification")
    scorable = _boolean(entry.get("scorable"), "outcome scorability")
    if verified != (label == "verified") or scorable != (label != "unscorable"):
        raise ValueError("action outcome flags contradict its label")
    expected_status = {"verified": "verified", "mismatch": "mismatch", "unscorable": "hold"}
    if entry.get("verification_status") != expected_status[label]:
        raise ValueError("action outcome verification status contradicts its label")
    mode = _text(entry.get("execution_mode"), "outcome mode")
    if mode not in {"shadow", "enforce"} or entry.get("mode") != mode:
        raise ValueError("action outcome modes disagree")
    decision = _text(entry.get("decision"), "outcome decision")
    if decision not in {"auto", "hil", "deny", "abstain"}:
        raise ValueError("action outcome decision is invalid")
    recorded = _time(entry.get("recorded_at"), "outcome recorded time")
    if recorded > end:
        raise ValueError("action outcome is future-dated")
    observed = None
    if scorable:
        observed = _time(entry.get("observed_at"), "outcome observation time")
        predicted = _time(entry.get("predicted_at"), "outcome prediction time")
        deadline = _time(entry.get("observation_deadline"), "outcome deadline")
        if not predicted <= observed <= min(deadline, recorded):
            raise ValueError("action outcome observation is outside its effect window")
        lower = _number(entry.get("expected_min"), "expected minimum")
        upper = _number(entry.get("expected_max"), "expected maximum")
        value = _number(entry.get("observed_value"), "observed value")
        if lower > upper or (verified and not lower <= value <= upper):
            raise ValueError("action outcome numeric evidence contradicts verification")
        refs = entry.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
        ):
            raise ValueError("action outcome requires evidence references")
    rollback = entry.get("rollback_succeeded")
    if rollback is not None and not isinstance(rollback, bool):
        raise ValueError("rollback evidence MUST be boolean or absent")
    return ActionObservation(
        event_id=event_id,
        action_id=action_id,
        observation_id=observation_id,
        mode=mode,
        decision=decision,
        scorable=scorable,
        verified=verified,
        rollback=rollback is not None,
        observed_at=observed,
        seq=seq,
    )


def _metric_observation(
    entry: Mapping[str, object],
    *,
    seq: int,
    end: datetime,
) -> MetricObservation | None:
    from fdai_service_contracts.metric_observation import MetricObservationV1

    fact = MetricObservationV1.from_audit_entry(entry)
    if fact.recorded_at > end or fact.observed_at > fact.recorded_at:
        raise ValueError("metric observation time is inconsistent")
    return MetricObservation(
        event_id=str(fact.event_id),
        metric_id=fact.metric_id,
        value=fact.value if fact.complete and not fact.synthetic else None,
        observed_at=fact.observed_at,
        seq=seq,
        source_context=(
            fact.measurement_protocol_digest,
            fact.source_revision,
            fact.source_id,
            fact.mode,
        ),
        sample_identity=(fact.source_id, fact.source_record_id)
        if fact.metric_id != "attributed_cost_usd"
        else None,
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be an object")
    return value


def _integer(value: object, label: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label} MUST be an integer in range")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{label} MUST be a bounded nonempty string")
    return value


def _uuid(value: object, label: str) -> str:
    return str(UUID(_text(value, label)))


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} MUST be finite numeric evidence")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} exceeds the numeric reporting range") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} MUST be finite numeric evidence")
    return number


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} MUST be boolean")
    return value


def _time(value: object, label: str) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError(f"{label} MUST be timezone-aware")
    return parsed.astimezone(UTC)
