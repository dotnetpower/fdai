"""Huginn - Event Collector (Wave 3 behavior).

Huginn normalizes incoming raw signals into `Event` payloads, dedups
by stable key, and publishes to `object.event`. Wave 3 implements the
in-process ingestion; adapter integration for Azure Activity Log lives
behind a provider protocol added in a later wave.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.alert_noise_wire import ALERT_NOISE_EVENT_TYPES, SignedAlertCommand

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.huginn_dedup import (
    HuginnDedupJournal,
    request_digest,
)
from fdai.agents._framework.huginn_operator_receipt import (
    OperatorRequestReceiptGate,
    ReservedOperatorRequestReceipt,
    VerifiedOperatorRequestReceipt,
)
from fdai.agents._framework.huginn_schema_learning import HuginnSchemaLearningLedger
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.pantheon import _HUGINN
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.case_history import OperationalCaseInput
from fdai.shared.providers.state_store import StateStore

# Bound the dedup memory so a long-lived process cannot leak: the most
# recent N idempotency keys are retained; older keys age out (a re-arrival
# after eviction is re-published, which the downstream idempotency key
# still makes safe - at-least-once is the bus contract).
_DEDUP_CAPACITY = 100_000

#: Bound each ingress string field so a single pathological signal cannot bloat
#: the pipeline / audit or become a huge bus partition key. Applies to every
#: ingested event, not just operator proposals.
_MAX_FIELD_CHARS = 512
_MAX_RAW_DEPTH = 6
_MAX_RAW_LIST_ITEMS = 128
_MAX_SOURCE_PAST_AGE = timedelta(days=366)
_MAX_SOURCE_FUTURE_SKEW = timedelta(minutes=5)
_SAFE_IDENTITY_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_AUTHORITY_FIELDS = frozenset(
    {
        "operator_initiated",
        "initiator_principal",
        "action_type",
        "human_approval_required",
        "risk",
        "risk_hint",
        "risk_hints",
        "params",
    }
)
_UNOWNED_AUTHORITY_FIELDS = frozenset(
    {
        "resolved_autonomy_ceiling",
        "risk_verdict",
        "quorum_required",
        "risk",
        "risk_hint",
        "risk_hints",
    }
)

#: Bound the free-form ``attributes`` map at ingress: cap the key count and
#: truncate string values, so a pathological or forged signal cannot smuggle a
#: giant nested payload past the top-level field caps (same bloat / audit /
#: partition-key concern, one level down). Shallow by design - the common
#: bloat vectors are too many keys and oversized string values.
_MAX_ATTR_KEYS = 64
_TRACE_CONTINUITY_EVENT = "trace-continuity.discontinuity"
_TRACE_CONTINUITY_FIELDS = (
    "detector_id",
    "reason_code",
    "topology_ref",
    "expected_hops",
    "observed_hops",
    "missing_hops",
    "trace_ids",
    "disconnected_boundaries",
    "evidence_refs",
    "window_bucket",
)
_MAX_OPERATIONAL_CASE_ERRORS = 32
_DISCOVERY_PROJECTOR_TIMEOUT_SECONDS = 5.0
_MAX_KPI_SAMPLES = 512
_MIN_P99_SAMPLES = 2

DiscoveryProjector = Callable[[Mapping[str, Any]], Awaitable[object]]
"""Injected durable inventory projector; cloud and database I/O stay outside Huginn."""


def _bound(value: Any) -> Any:
    """Truncate a string value to the ingress field cap; pass non-strings."""
    return value[:_MAX_FIELD_CHARS] if isinstance(value, str) else value


def _has_control_characters(value: str) -> bool:
    return any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in value)


def _safe_string(value: Any, *, field: str, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise HuginnIngressRejected("invalid_string", field=field)
        return None
    if not isinstance(value, str):
        raise HuginnIngressRejected("invalid_string", field=field)
    if len(value) > _MAX_FIELD_CHARS or _has_control_characters(value):
        raise HuginnIngressRejected("invalid_string", field=field)
    return value


def _safe_identity(value: Any, *, field: str, default: str | None = None) -> str:
    candidate = _safe_string(value, field=field) if value is not None else default
    if candidate is None:
        candidate = ""
    if not candidate or not _SAFE_IDENTITY_RE.fullmatch(candidate):
        raise HuginnIngressRejected("invalid_identity", field=field)
    return candidate


def _raw_payload_digest(value: Any) -> str:
    hasher = hashlib.sha256()

    def feed(item: Any, depth: int) -> None:
        if depth > _MAX_RAW_DEPTH:
            hasher.update(b"<depth>")
            return
        if isinstance(item, Mapping):
            hasher.update(f"dict:{len(item)}".encode())
            for key, nested in list(item.items())[:_MAX_ATTR_KEYS]:
                key_text = key if isinstance(key, str) else type(key).__name__
                hasher.update(
                    hashlib.sha256(key_text.encode(errors="replace")).hexdigest().encode()
                )
                feed(nested, depth + 1)
            return
        if isinstance(item, list | tuple):
            hasher.update(f"list:{len(item)}".encode())
            for nested in item[:_MAX_RAW_LIST_ITEMS]:
                feed(nested, depth + 1)
            return
        if isinstance(item, str):
            hasher.update(f"str:{len(item)}:".encode())
            hasher.update(hashlib.sha256(item.encode(errors="replace")).hexdigest().encode())
            return
        if isinstance(item, datetime):
            hasher.update(b"datetime")
            return
        hasher.update(type(item).__name__.encode())

    feed(value, 0)
    return hasher.hexdigest()


def _validate_raw_value(value: Any, *, path: str, depth: int = 0) -> None:
    if depth > _MAX_RAW_DEPTH:
        raise HuginnIngressRejected("raw_depth_exceeded", field=path)
    if value is None or isinstance(value, bool | int | float | datetime):
        return
    if isinstance(value, str):
        if len(value) > _MAX_FIELD_CHARS or _has_control_characters(value):
            raise HuginnIngressRejected("invalid_string", field=path)
        return
    if isinstance(value, Mapping):
        if len(value) > _MAX_ATTR_KEYS:
            raise HuginnIngressRejected("raw_object_too_large", field=path)
        for key, nested in value.items():
            if not isinstance(key, str):
                raise HuginnIngressRejected("invalid_field_name", field=path)
            if len(key) > _MAX_FIELD_CHARS or _has_control_characters(key):
                raise HuginnIngressRejected("invalid_field_name", field=path)
            _validate_raw_value(nested, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, list | tuple):
        if len(value) > _MAX_RAW_LIST_ITEMS:
            raise HuginnIngressRejected("raw_list_too_large", field=path)
        for index, nested in enumerate(value):
            _validate_raw_value(nested, path=f"{path}[{index}]", depth=depth + 1)
        return
    raise HuginnIngressRejected("invalid_type", field=path)


def _validate_raw_ingress(raw: Mapping[str, Any]) -> None:
    for field in ("idempotency_key", "id", "event_id"):
        value = raw.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise HuginnIngressRejected("invalid_idempotency_key", field=field)
        if len(value.strip()) > _MAX_FIELD_CHARS or _has_control_characters(value):
            raise HuginnIngressRejected("invalid_idempotency_key", field=field)
    _validate_raw_value(raw, path="raw")
    for field in ("event_type", "source", "resource_type"):
        if field in raw and raw[field] not in (None, ""):
            _safe_identity(raw[field], field=field)
    for field in ("correlation_id",):
        if field in raw and raw[field] not in (None, ""):
            _safe_string(raw[field], field=field)


def _validated_operator_request_fields(
    raw: Mapping[str, Any],
    *,
    channel: str,
) -> dict[str, Any]:
    initiator = _safe_string(raw.get("initiator_principal"), field="initiator_principal")
    action_type = _safe_identity(raw.get("action_type"), field="action_type")
    if initiator is None:
        raise HuginnIngressRejected(
            "operator_request_initiator_missing", field="initiator_principal"
        )
    params = raw.get("params")
    if params is not None and not isinstance(params, Mapping):
        raise HuginnIngressRejected("operator_request_params_invalid", field="params")
    operator_initiated = raw.get("operator_initiated")
    payload: dict[str, Any] = {
        "initiator_principal": initiator,
        "action_type": action_type,
        "operator_request_channel": channel,
    }
    if isinstance(params, Mapping):
        payload["params"] = _copy_validated_json(params)
    if isinstance(operator_initiated, bool):
        payload["operator_initiated"] = operator_initiated
    elif operator_initiated is not None:
        payload["operator_initiated"] = False
    human_approval_required = raw.get("human_approval_required")
    if isinstance(human_approval_required, bool):
        payload["human_approval_required"] = human_approval_required
    return payload


def _copy_validated_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_validated_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_copy_validated_json(item) for item in value]
    return value


def _bound_attributes(attrs: Any) -> dict[str, Any]:
    """Cap the attribute key count and truncate string values at ingress."""
    if not isinstance(attrs, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if len(out) >= _MAX_ATTR_KEYS:
            break
        out[str(key)[:_MAX_FIELD_CHARS]] = _bound_json(value, depth=1)
    return out


def _bound_json(value: Any, *, depth: int = 0) -> Any:
    """Bound a canonical inventory change without changing its typed shape."""
    if isinstance(value, str):
        return value[:_MAX_FIELD_CHARS]
    if value is None or isinstance(value, int | float | bool):
        return value
    if depth >= 4:
        return str(value)[:_MAX_FIELD_CHARS]
    if isinstance(value, Mapping):
        return {
            str(key)[:_MAX_FIELD_CHARS]: _bound_json(item, depth=depth + 1)
            for key, item in list(value.items())[:_MAX_ATTR_KEYS]
        }
    if isinstance(value, list | tuple):
        return [_bound_json(item, depth=depth + 1) for item in value[:_MAX_ATTR_KEYS]]
    return str(value)[:_MAX_FIELD_CHARS]


def _event_occurred_at(
    raw: Mapping[str, Any],
    *,
    ingested_at: datetime,
) -> str | None:
    """Return one validated source-event timestamp when the producer supplied it."""

    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise ValueError("Huginn clock MUST return a timezone-aware datetime")
    observed_at: datetime | None = None
    observed_field = ""
    for field in ("occurred_at", "detected_at", "created_at"):
        value = raw.get(field)
        if value is None or value == "":
            continue
        if isinstance(value, datetime):
            observed_at = value
        elif isinstance(value, str):
            try:
                observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HuginnIngressRejected("timestamp_not_rfc3339", field=field) from exc
        else:
            raise HuginnIngressRejected("timestamp_not_rfc3339", field=field)
        observed_field = field
        break
    if observed_at is None:
        return None
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise HuginnIngressRejected("timestamp_naive", field=observed_field)

    observed_at = observed_at.astimezone(UTC)
    trusted_ingested_at = ingested_at.astimezone(UTC)
    if observed_at > trusted_ingested_at + _MAX_SOURCE_FUTURE_SKEW:
        raise HuginnIngressRejected(
            "timestamp_future",
            field=observed_field,
        )
    if observed_at < trusted_ingested_at - _MAX_SOURCE_PAST_AGE:
        raise HuginnIngressRejected("timestamp_too_old", field=observed_field)
    return observed_at.isoformat()


def _kpi_measured(
    value: float,
    *,
    numerator: int | float,
    denominator: int | float,
    unit: str = "ratio",
    sample_count: int | None = None,
) -> dict[str, Any]:
    evidence = {
        "value": float(value),
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }
    if sample_count is not None:
        evidence["sample_count"] = sample_count
    return evidence


def _kpi_unavailable(evidence_state: str, reason: str, *, unit: str = "ratio") -> dict[str, Any]:
    return {
        "value": None,
        "evidence_state": evidence_state,
        "reason": reason,
        "numerator": 0,
        "denominator": 0,
        "unit": unit,
    }


def _p99_kpi(samples: deque[float], *, unit: str, reason: str) -> dict[str, Any]:
    if len(samples) < _MIN_P99_SAMPLES:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.99) - 1))
    return _kpi_measured(
        ordered[index],
        numerator=len(ordered),
        denominator=len(ordered),
        unit=unit,
        sample_count=len(ordered),
    )


def _ratio_kpi(numerator: object, denominator: object, *, reason: str) -> dict[str, Any]:
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int | float)
        or not isinstance(denominator, int | float)
        or denominator <= 0
    ):
        return _kpi_unavailable("insufficient_sample", reason)
    return _kpi_measured(
        float(numerator) / float(denominator),
        numerator=numerator,
        denominator=denominator,
    )


class HuginnIngressRejectedError(ValueError):
    """Ingress input was rejected before a normalized Event could be published."""

    def __init__(
        self,
        reason_code: str,
        *,
        field: str = "",
        payload_digest: str = "",
    ) -> None:
        super().__init__(f"Huginn raw ingress rejected: {reason_code}")
        self.reason_code = reason_code
        self.field = field[:_MAX_FIELD_CHARS]
        self.payload_digest = payload_digest

    def rejection_record(self) -> dict[str, str]:
        return {
            "schema_version": "1.0.0",
            "kind": "huginn.raw_ingress_rejection",
            "reason_code": self.reason_code,
            "payload_digest": self.payload_digest,
        }


HuginnIngressRejected = HuginnIngressRejectedError


def _change_projection(
    *,
    raw: Mapping[str, Any],
    canonical_payload: Mapping[str, Any],
    event_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    declared = raw.get("change") or canonical_payload.get("change")
    change = declared if isinstance(declared, Mapping) else None
    signal_kind = canonical_payload.get("signal_kind")
    event_type = str(event_payload["event_type"])
    inferred_activity = signal_kind == "azure.activity_log"
    inferred_planned = event_type in {
        "change.requested",
        "change.planned",
        "deployment.requested",
        "iac.plan",
        "iac.pull_request",
        "release.ready",
    }
    if change is None and not inferred_activity and not inferred_planned:
        return None

    def value(name: str, *fallbacks: object) -> object | None:
        candidate: object | None = change.get(name) if change is not None else None
        if candidate is not None:
            return candidate
        return next((item for item in fallbacks if item is not None), None)

    occurred_at = str(
        value(
            "occurred_at",
            raw.get("occurred_at"),
            raw.get("detected_at"),
            raw.get("created_at"),
            event_payload.get("ingested_at"),
        )
        or ""
    )
    try:
        parsed_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HuginnIngressRejected("change_timestamp_not_rfc3339", field="occurred_at") from exc
    if parsed_at.tzinfo is None:
        raise HuginnIngressRejected("change_timestamp_naive", field="occurred_at")

    target_ref = str(value("target_ref", event_payload.get("resource_id")) or "").strip()
    if not target_ref:
        raise HuginnIngressRejected("change_target_missing", field="target_ref")
    actor = canonical_payload.get("actor")
    actor_ref = value(
        "actor_ref",
        actor.get("principal_id") if isinstance(actor, Mapping) else actor,
        raw.get("source"),
    )
    actor_ref = str(actor_ref or "").strip()
    if not actor_ref:
        raise HuginnIngressRejected("change_actor_missing", field="actor_ref")

    change_id = str(value("id", event_payload.get("event_id")) or "").strip()
    if not change_id:
        raise HuginnIngressRejected("change_id_missing", field="id")
    default_status = "observed" if inferred_activity else "planned"
    default_intent = "detected" if inferred_activity else "planned"
    projection: dict[str, Any] = {
        "producer_principal": "Huginn",
        "correlation_id": event_payload["correlation_id"],
        "idempotency_key": f"change:{event_payload['idempotency_key']}",
        "id": change_id[:_MAX_FIELD_CHARS],
        "change_kind": str(value("change_kind", event_type) or "")[:_MAX_FIELD_CHARS],
        "source_kind": str(value("source_kind", event_payload.get("source")) or "")[
            :_MAX_FIELD_CHARS
        ],
        "intent_kind": str(value("intent_kind", default_intent) or "")[:_MAX_FIELD_CHARS],
        "target_ref": target_ref[:_MAX_FIELD_CHARS],
        "actor_ref": actor_ref[:_MAX_FIELD_CHARS],
        "status": str(value("status", default_status) or "")[:_MAX_FIELD_CHARS],
        "occurred_at": parsed_at.isoformat(),
        "evidence_ref": str(value("evidence_ref", f"event:{event_payload['event_id']}") or "")[
            :_MAX_FIELD_CHARS
        ],
    }
    for field in (
        "desired_state_digest",
        "ontology_release_digest",
        "plan_receipt_ref",
        "window_ref",
        "incident_ref",
        "process_ref",
    ):
        optional = value(field)
        if optional is not None and str(optional).strip():
            projection[field] = str(optional)[:_MAX_FIELD_CHARS]
    return projection


class Huginn(Agent):
    """Wave-3 Huginn: normalize + dedup + publish."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        dedup_capacity: int = _DEDUP_CAPACITY,
        discovery_projector: DiscoveryProjector | None = None,
        clock: Callable[[], datetime] | None = None,
        state_store: StateStore | None = None,
        dedup_clock: Callable[[], datetime] | None = None,
        dedup_claim_lease: timedelta = timedelta(seconds=60),
        operator_request_receipt_gate: OperatorRequestReceiptGate | None = None,
        schema_learning_enabled: bool = False,
        schema_learning_capacity: int = 128,
    ) -> None:
        super().__init__(spec=_HUGINN)
        self.bus = bus
        if dedup_capacity < 1:
            raise ValueError("dedup_capacity MUST be >= 1")
        self._dedup_capacity = dedup_capacity
        self._discovery_projector = discovery_projector
        self._alert_noise_verifier: Callable[[Mapping[str, Any]], object] | None = None
        self._operator_request_receipt_gate = operator_request_receipt_gate
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._dedup_journal = (
            HuginnDedupJournal(
                state_store,
                capacity=dedup_capacity,
                clock=dedup_clock,
                claim_lease=dedup_claim_lease,
            )
            if state_store is not None
            else None
        )
        # OrderedDict as an LRU set: key -> None, oldest first.
        self._seen_keys: OrderedDict[str, None] = OrderedDict()
        self._ingress_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._ingress_lock_refs: dict[str, int] = {}
        self._operational_case_errors: deque[str] = deque(maxlen=_MAX_OPERATIONAL_CASE_ERRORS)
        self._event_latency_seconds: deque[float] = deque(maxlen=_MAX_KPI_SAMPLES)
        self._discovery_latency_seconds: deque[float] = deque(maxlen=_MAX_KPI_SAMPLES)
        self._dedup_correct_decisions = 0
        self._dedup_collision_decisions = 0
        self._last_checkpoint_read_at: datetime | None = None
        self._schema_learning = (
            HuginnSchemaLearningLedger(
                state_store=state_store,
                capacity=schema_learning_capacity,
            )
            if schema_learning_enabled
            else None
        )

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_alert_noise_verifier(self, verifier: Callable[[Mapping[str, Any]], object]) -> None:
        """Bind deterministic authentication before alert requests can reserve a dedup key."""
        if self._alert_noise_verifier is not None:
            raise RuntimeError("alert ingress verifier is already bound")
        self._alert_noise_verifier = verifier

    async def rehydrate(self) -> int:
        """Restore completed dedup keys before the ingress consumer starts."""
        if self._dedup_journal is None:
            return 0
        self._seen_keys = OrderedDict(
            (key, None) for key in await self._dedup_journal.published_keys()
        )
        self._last_checkpoint_read_at = self._clock()
        return len(self._seen_keys)

    def health(self) -> dict[str, Any]:
        """Expose ingress / dedup state for Heimdall's probe."""
        checkpoint_durability = "durable" if self._dedup_journal is not None else "process_local"
        status = "ok" if self._dedup_journal is not None else "degraded"
        checkpoint_age_seconds: dict[str, Any]
        if self._last_checkpoint_read_at is None:
            checkpoint_age_seconds = _kpi_unavailable(
                "not_observed" if self._dedup_journal is not None else "not_connected",
                "checkpoint_resume_not_read",
                unit="seconds",
            )
        else:
            now = self._clock()
            checkpoint_age_seconds = _kpi_measured(
                max(0.0, (now - self._last_checkpoint_read_at).total_seconds()),
                numerator=1,
                denominator=1,
                unit="seconds",
            )
        return {
            "agent": "Huginn",
            "status": status,
            "discovery": {
                "projection": "bound" if self._discovery_projector is not None else "not_bound",
                "cursor": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_cursor_not_bound",
                    unit="seconds",
                ),
                "backpressure": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_backpressure_not_bound",
                ),
                "source_health": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_source_health_not_bound",
                ),
            },
            "checkpoint": {
                "durability": checkpoint_durability,
                "retained_cursor_source": "state_store"
                if self._dedup_journal is not None
                else None,
                "last_checkpoint_age_seconds": checkpoint_age_seconds,
            },
            "operator_request_receipts": {
                "verification": "bound"
                if self._operator_request_receipt_gate is not None
                else "fail_closed_unbound",
            },
            "schema_learning": {
                "status": "bound" if self._schema_learning is not None else "not_bound",
                "pending_fingerprints": self._schema_learning.pending_count()
                if self._schema_learning is not None
                else 0,
            },
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
            "operational_case_errors": list(self._operational_case_errors),
            "kpis": {
                "event_processing_latency_p99_seconds": _p99_kpi(
                    self._event_latency_seconds,
                    unit="seconds",
                    reason="no_ingest_latency_samples",
                ),
                "discovery_delivery_latency_p99_seconds": _p99_kpi(
                    self._discovery_latency_seconds,
                    unit="seconds",
                    reason="no_discovery_projection_samples",
                ),
                "dedup_accuracy": self._dedup_accuracy_kpi(),
                "schema_match_failure_rate": _ratio_kpi(
                    self.behavior_snapshot().get("raw_ingress_rejected:invalid_type", 0)
                    + self.behavior_snapshot().get("raw_ingress_rejected:invalid_string", 0),
                    self.behavior_snapshot().get("ingested", 0)
                    + self.behavior_snapshot().get("raw_ingress_rejected:invalid_type", 0)
                    + self.behavior_snapshot().get("raw_ingress_rejected:invalid_string", 0),
                    reason="no_schema_validation_denominator",
                ),
                "discovery_cursor_lag_seconds": _kpi_unavailable(
                    "not_observed" if self._discovery_projector is not None else "not_connected",
                    "delivery_cursor_not_bound",
                    unit="seconds",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    async def ingest(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a raw source signal into an Event payload.

        Returns the normalized payload (also publishes it on the bus if
        one is bound). Duplicates by ``idempotency_key`` are dropped
        and return ``None``.
        """
        try:
            verified_operator_receipt: VerifiedOperatorRequestReceipt | None = None
            _validate_raw_ingress(raw)
            if (
                raw.get("event_type") in ALERT_NOISE_EVENT_TYPES
                or raw.get("source") == "operator-alert-noise"
            ):
                if self._alert_noise_verifier is None:
                    raise HuginnIngressRejected("alert_verifier_unavailable")
                self._alert_noise_verifier(raw)
            if raw.get("event_type") == "operator_request":
                if self._operator_request_receipt_gate is None:
                    raise HuginnIngressRejected("operator_request_receipt_unbound")
                try:
                    verified_operator_receipt = await self._operator_request_receipt_gate.verify(
                        raw
                    )
                except ValueError as exc:
                    reason = str(exc) or "invalid"
                    safe_reason = (
                        reason
                        if reason
                        in {
                            "missing",
                            "mismatch",
                            "expired",
                            "unverifiable",
                            "replayed",
                            "unknown_producer",
                            "unsigned_workflow_action",
                        }
                        else "invalid"
                    )
                    raise HuginnIngressRejected(
                        f"operator_request_receipt_{safe_reason}",
                        field="operator_request_receipt",
                    ) from exc
            if self._schema_learning is not None:
                self._schema_learning.record_accepted(raw)
            key = self._ingress_key(raw)
            async with self._key_lock(key):
                return await self._ingest_locked(
                    raw,
                    key=key,
                    verified_operator_receipt=verified_operator_receipt,
                )
        except HuginnIngressRejectedError as exc:
            if not exc.payload_digest:
                exc.payload_digest = _raw_payload_digest(raw)
            self.record_behavior(f"raw_ingress_rejected:{exc.reason_code}")
            raise

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        if self._schema_learning is None:
            self.record_behavior("maintenance:schema_learning_unbound")
            return
        if self.bus is None:
            self.record_behavior("maintenance:schema_learning_no_bus")
            return
        evidence = await self._schema_learning.next_evidence()
        if evidence is None:
            self.record_behavior("maintenance:schema_learning_idle")
            return
        await self.bus.publish("Huginn", "object.event", evidence.payload)
        self.record_behavior("maintenance:schema_cluster_evidence_published")

    async def ingest_operator_proposal(self, proposal: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize Bragi's authenticated in-process operator proposal."""

        try:
            _validate_raw_ingress(proposal)
            if proposal.get("event_type") != "operator_request":
                raise HuginnIngressRejected("operator_proposal_event_type", field="event_type")
            if proposal.get("operator_initiated") is not True:
                raise HuginnIngressRejected(
                    "operator_proposal_initiator", field="operator_initiated"
                )
            for field in ("initiator_principal", "action_type"):
                _safe_string(proposal.get(field), field=field, required=True)
            key = self._ingress_key(proposal)
            async with self._key_lock(key):
                return await self._ingest_locked(
                    proposal,
                    key=key,
                    trusted_operator_proposal=True,
                )
        except HuginnIngressRejectedError as exc:
            if not exc.payload_digest:
                exc.payload_digest = _raw_payload_digest(proposal)
            self.record_behavior(f"operator_proposal_rejected:{exc.reason_code}")
            raise

    async def _ingest_locked(
        self,
        raw: dict[str, Any],
        *,
        key: str,
        trusted_operator_proposal: bool = False,
        verified_operator_receipt: VerifiedOperatorRequestReceipt | None = None,
    ) -> dict[str, Any] | None:
        raw_request_digest = request_digest(raw) if self._dedup_journal is not None else ""
        if key in self._seen_keys:
            self._seen_keys.move_to_end(key)
            self.record_behavior("deduped")
            return None
        reserved_operator_receipt: ReservedOperatorRequestReceipt | None = None
        processing_started_at = self._clock()
        ingested_at = processing_started_at
        if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
            raise ValueError("Huginn clock MUST return a timezone-aware datetime")
        event_payload = raw.get("payload")
        canonical_payload = event_payload if isinstance(event_payload, Mapping) else {}
        inventory_change = canonical_payload.get("inventory_change")
        detection_readiness = canonical_payload.get("detection_readiness")
        resource_value = (
            inventory_change.get("resource") if isinstance(inventory_change, Mapping) else None
        )
        resource: Mapping[str, Any] = resource_value if isinstance(resource_value, Mapping) else {}

        event_type = _safe_identity(raw.get("event_type") or "generic", field="event_type")
        attributes = _bound_attributes(raw.get("attributes", {}))
        correlation_id = _safe_string(raw.get("correlation_id"), field="correlation_id") or key
        if event_type == "case_history.operational_case.v1":
            raw_attributes = raw.get("attributes")
            if isinstance(raw_attributes, Mapping):
                try:
                    operational_case = OperationalCaseInput.from_mapping(raw_attributes)
                    attributes = operational_case.to_mapping()
                    correlation_id = operational_case.failure_fingerprint.digest
                except (TypeError, ValueError) as exc:
                    reason = type(exc).__name__
                    self.record_behavior("operational_case:invalid")
                    self._operational_case_errors.append(reason)
        payload: dict[str, Any] = {
            "producer_principal": "Huginn",
            "correlation_id": correlation_id,
            "incident_correlation": (
                "none"
                if str(raw.get("event_type", "")).startswith("inventory.")
                else _safe_string(raw.get("incident_correlation"), field="incident_correlation")
                or "correlate"
            ),
            "idempotency_key": key,
            "event_id": _safe_string(raw.get("event_id"), field="event_id") or key,
            "source": _safe_identity(raw.get("source") or "unknown", field="source"),
            "resource_id": _bound(
                raw.get("resource_id") or raw.get("resource_ref") or resource.get("resource_id")
            ),
            "resource_type": (
                _safe_identity(
                    raw.get("resource_type") or resource.get("type"), field="resource_type"
                )
                if raw.get("resource_type") or resource.get("type")
                else None
            ),
            "event_type": event_type,
            "attributes": attributes,
            "ingested_at": ingested_at.isoformat(),
        }
        occurred_at = _event_occurred_at(raw, ingested_at=ingested_at)
        if occurred_at is not None:
            payload["occurred_at"] = occurred_at
        severity = raw.get("severity") or canonical_payload.get("severity")
        if event_type in ALERT_NOISE_EVENT_TYPES:
            signed = SignedAlertCommand.model_validate(canonical_payload.get("alert_noise"))
            if signed.command.operation != event_type or raw.get("mode") != "shadow":
                raise HuginnIngressRejected(
                    "alert_authority_mismatch",
                    field="alert_noise",
                )
            payload["alert_noise"] = signed.model_dump(mode="json")
            payload["incident_correlation"] = "none"
        if isinstance(severity, str) and severity.strip():
            payload["severity"] = _bound(severity)
        if isinstance(inventory_change, Mapping):
            payload["inventory_change"] = _bound_json(inventory_change)
            signal_kind = canonical_payload.get("signal_kind")
            if isinstance(signal_kind, str):
                payload["attributes"]["signal_kind"] = _bound(signal_kind)
        if isinstance(detection_readiness, Mapping):
            for field in (
                "dimension",
                "status",
                "observed_at",
                "expires_at",
                "source",
                "evidence_digest",
                "detail_code",
                "pass_id",
            ):
                value = detection_readiness.get(field)
                if value is not None:
                    payload["attributes"][field] = _bound(value)
        if event_type == _TRACE_CONTINUITY_EVENT and canonical_payload.get("kind") == (
            "trace_continuity"
        ):
            payload["attributes"]["trace_continuity"] = {
                field: _bound_json(canonical_payload[field], depth=1)
                for field in _TRACE_CONTINUITY_FIELDS
                if field in canonical_payload
            }
        if payload["event_type"] == "operator_request":
            payload.update(
                _validated_operator_request_fields(
                    raw,
                    channel="conversation" if trusted_operator_proposal else "ingress",
                )
            )
            stripped = _UNOWNED_AUTHORITY_FIELDS.intersection(raw)
            if stripped:
                self.record_behavior("operator_request:unowned_authority_fields_stripped")
            workflow_action = raw.get("workflow_action")
            if isinstance(workflow_action, Mapping):
                payload["workflow_action"] = _copy_validated_json(workflow_action)
        if payload["event_type"] == "human.assignment.iam_apply_requested":
            payload["attributes"]["iam_request"] = {
                field: _bound_json(canonical_payload[field])
                for field in ("case_id", "expected_revision", "ownership_digest", "ownership_ref")
                if field in canonical_payload
            }
            payload["incident_correlation"] = "none"
        if payload["event_type"] == "knowledge.handover.source_observed.v1":
            from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice

            notice = HandoverKnowledgeNotice.model_validate(canonical_payload.get("notice"))
            payload["attributes"] = {"knowledge_notice": notice.model_dump(mode="json")}
            payload["correlation_id"] = notice.source_id
            payload["incident_correlation"] = "none"
        if payload["event_type"] == "human.assignment.execution.v1":
            from fdai_service_contracts.human_access_workflow import HumanAccessWorkNotice

            access_notice = HumanAccessWorkNotice.model_validate(canonical_payload.get("notice"))
            payload["attributes"] = {"human_access_notice": access_notice.model_dump(mode="json")}
            payload["correlation_id"] = str(access_notice.request_id)
            payload["incident_correlation"] = "none"
        change_projection = _change_projection(
            raw=raw,
            canonical_payload=canonical_payload,
            event_payload=payload,
        )
        if change_projection is not None:
            payload["normalized_change"] = dict(change_projection)
        if self._dedup_journal is not None:
            try:
                claim = await self._dedup_journal.claim(
                    idempotency_key=key,
                    request_digest=raw_request_digest,
                    payload=payload,
                    change_projection=change_projection,
                )
            except ValueError:
                self._dedup_collision_decisions += 1
                self.record_behavior("dedup:key_collision")
                raise
            if claim.duplicate:
                self._remember_key(key)
                self._dedup_correct_decisions += 1
                self.record_behavior("deduped")
                return None
            payload = claim.payload
            change_projection = claim.change_projection
            published_topics = claim.published_topics
        else:
            published_topics = frozenset()
        if verified_operator_receipt is not None:
            if self._operator_request_receipt_gate is None:
                raise HuginnIngressRejected("operator_request_receipt_unbound")
            try:
                reserved_operator_receipt = await self._operator_request_receipt_gate.reserve(
                    verified_operator_receipt
                )
            except ValueError as exc:
                reason = str(exc) or "invalid"
                safe_reason = reason if reason in {"expired", "replayed"} else "invalid"
                raise HuginnIngressRejected(
                    f"operator_request_receipt_{safe_reason}",
                    field="operator_request_receipt",
                ) from exc
        # Measurable behaviour: the sensing layer's ingest / dedup rates, so a
        # scenario can see an ingress flood (the flooding concern one layer up
        # from the judge). Recorded on the decision to emit, before publish.
        self.record_behavior("ingested")
        if self._dedup_journal is not None:
            self._dedup_correct_decisions += 1
        if "inventory_change" in payload and self._discovery_projector is not None:
            try:
                discovery_started_at = self._clock()
                async with asyncio.timeout(_DISCOVERY_PROJECTOR_TIMEOUT_SECONDS):
                    await self._discovery_projector(payload)
                self._record_latency(self._discovery_latency_seconds, discovery_started_at)
                self.record_behavior("discovery_projected")
            except TimeoutError:
                self.record_behavior("discovery_projection:timeout")
                raise
            except asyncio.CancelledError:
                self.record_behavior("discovery_projection:cancelled")
                raise
            except Exception:
                self.record_behavior("discovery_projection_failed")
                raise
        publish_cancelled = False
        try:
            if self.bus is not None:
                publish_cancelled = await self._publish_event_change(
                    payload,
                    change_projection,
                    idempotency_key=key,
                    request_digest=raw_request_digest,
                    published_topics=published_topics,
                )
            elif self._dedup_journal is not None:
                await self._dedup_journal.mark_published(
                    idempotency_key=key,
                    request_digest=raw_request_digest,
                    topic="object.event",
                )
                if change_projection is not None:
                    await self._dedup_journal.mark_published(
                        idempotency_key=key,
                        request_digest=raw_request_digest,
                        topic="object.change",
                    )
            if self._dedup_journal is not None:
                complete_task = asyncio.create_task(
                    self._dedup_journal.complete(
                        idempotency_key=key,
                        request_digest=raw_request_digest,
                        require_published_topics=self.bus is not None,
                    )
                )
                try:
                    await asyncio.shield(complete_task)
                except asyncio.CancelledError:
                    await complete_task
                    self.record_behavior("dedup_completion:cancelled")
                    publish_cancelled = True
        except Exception:
            if (
                reserved_operator_receipt is not None
                and self._operator_request_receipt_gate is not None
            ):
                await self._operator_request_receipt_gate.release(reserved_operator_receipt)
            raise
        if reserved_operator_receipt is not None:
            if self._operator_request_receipt_gate is None:
                raise HuginnIngressRejected("operator_request_receipt_unbound")
            try:
                await self._operator_request_receipt_gate.finalize(reserved_operator_receipt)
            except ValueError as exc:
                reason = str(exc) or "invalid"
                safe_reason = reason if reason in {"expired", "replayed"} else "invalid"
                raise HuginnIngressRejected(
                    f"operator_request_receipt_{safe_reason}",
                    field="operator_request_receipt",
                ) from exc
        self._remember_key(key)
        self._record_latency(self._event_latency_seconds, processing_started_at)
        if publish_cancelled:
            raise asyncio.CancelledError
        return payload

    def _record_latency(self, target: deque[float], started_at: datetime) -> None:
        ended_at = self._clock()
        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("Huginn clock MUST return a timezone-aware datetime")
        target.append(max(0.0, (ended_at - started_at).total_seconds()))

    def _dedup_accuracy_kpi(self) -> dict[str, Any]:
        total = self._dedup_correct_decisions + self._dedup_collision_decisions
        if total == 0:
            return _kpi_unavailable("not_measured", "no_authoritative_dedup_decisions")
        return _kpi_measured(
            self._dedup_correct_decisions / total,
            numerator=self._dedup_correct_decisions,
            denominator=total,
            unit="ratio",
        )

    async def _publish_event_change(
        self,
        payload: Mapping[str, Any],
        change_projection: Mapping[str, Any] | None,
        *,
        idempotency_key: str,
        request_digest: str,
        published_topics: frozenset[str],
    ) -> bool:
        if self.bus is None:
            return False
        cancelled = False
        if "object.event" not in published_topics:
            event_task = asyncio.create_task(
                self.bus.publish("Huginn", "object.event", dict(payload))
            )
            try:
                await asyncio.shield(event_task)
            except asyncio.CancelledError:
                await event_task
                self.record_behavior("event_publication:cancelled")
                cancelled = True
            if self._dedup_journal is not None:
                await self._dedup_journal.mark_published(
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    topic="object.event",
                )
        if change_projection is not None:
            if "object.change" not in published_topics:
                change_task = asyncio.create_task(
                    self.bus.publish("Huginn", "object.change", dict(change_projection))
                )
                try:
                    await asyncio.shield(change_task)
                except asyncio.CancelledError:
                    await change_task
                    self.record_behavior("change_publication:cancelled")
                    cancelled = True
                if self._dedup_journal is not None:
                    await self._dedup_journal.mark_published(
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        topic="object.change",
                    )
        return cancelled

    @asynccontextmanager
    async def _key_lock(self, key: str) -> AsyncIterator[None]:
        lock = self._lock_for_key(key)
        self._ingress_lock_refs[key] = self._ingress_lock_refs.get(key, 0) + 1
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._ingress_lock_refs.get(key, 1) - 1
            if remaining > 0:
                self._ingress_lock_refs[key] = remaining
            else:
                self._ingress_lock_refs.pop(key, None)
                self._ingress_locks.pop(key, None)

    def _lock_for_key(self, key: str) -> asyncio.Lock:
        lock = self._ingress_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._ingress_locks[key] = lock
        self._ingress_locks.move_to_end(key)
        retained_count = sum(self._ingress_lock_refs.values())
        while len(self._ingress_locks) > self._dedup_capacity + retained_count:
            for old_key, old_lock in tuple(self._ingress_locks.items()):
                if not old_lock.locked() and old_key not in self._ingress_lock_refs:
                    self._ingress_locks.pop(old_key, None)
                    break
            else:
                break
        return lock

    def _ingress_key(self, raw: Mapping[str, Any]) -> str:
        for field in ("idempotency_key", "id", "event_id"):
            provided = raw.get(field)
            if provided in (None, ""):
                continue
            if not isinstance(provided, str):
                raise HuginnIngressRejected("invalid_idempotency_key", field=field)
            normalized = provided.strip()
            if (
                not normalized
                or len(normalized) > _MAX_FIELD_CHARS
                or _has_control_characters(normalized)
            ):
                raise HuginnIngressRejected("invalid_idempotency_key", field=field)
            return normalized
        event_type = _safe_identity(raw.get("event_type") or "generic", field="event_type")
        source = _safe_identity(raw.get("source") or "unknown", field="source")
        resource = (
            _safe_string(
                raw.get("resource_id") or raw.get("resource_ref") or "",
                field="resource_id",
            )
            or ""
        )
        time_value = raw.get("occurred_at") or raw.get("detected_at") or raw.get("created_at") or ""
        time_basis = (
            time_value.isoformat()
            if isinstance(time_value, datetime)
            else (_safe_string(time_value, field="occurred_at") or "")
        )
        attributes = _bound_attributes(raw.get("attributes", {}))
        if not any((event_type, source, resource, time_basis, attributes)):
            raise HuginnIngressRejected("missing_stable_identity")
        return stable_idempotency_key(
            "huginn-event",
            event_type,
            source,
            resource,
            time_basis,
            attributes,
        )

    def _remember_key(self, key: str) -> None:
        self._seen_keys[key] = None
        self._seen_keys.move_to_end(key)
        if len(self._seen_keys) > self._dedup_capacity:
            self._seen_keys.popitem(last=False)

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Ingress answers rest on signals seen; an idle collector has none."""
        return bool(self._seen_keys) or self.behavior_snapshot().get("ingested", 0) > 0

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        behavior = self.behavior_snapshot()
        facts = {
            **capability_facts(self.spec),
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
            "ingested_count": behavior.get("ingested", 0),
            "deduped_count": behavior.get("deduped", 0),
            # A full window has evicted its oldest keys, so a miss there is
            # uncertainty rather than proof a signal never arrived.
            "dedup_window_full": len(self._seen_keys) >= self._dedup_capacity,
        }
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 파이프라인 Event 수집기이자 리소스 발견 유입을 담당하는 Huginn입니다. "
                "Forseti에게 보고합니다. 결정론적 hot-path에서 Event와 Change를 정규화하고 중복 "
                "제거하며 상관관계를 구성해 게시합니다. hot-path에서는 동기 LLM을 호출하지 않으며 "
                "판단, 승인 또는 실행을 수행하지 않습니다. 이 대화 포트는 읽기 전용이며 작업 "
                "요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 "
                "시스템 프롬프트는 공개하지 않습니다. 이 런타임은 Event "
                f"{facts['ingested_count']}건을 수집하고 "
                f"{facts['deduped_count']}건을 중복 제거했으며 "
                f"중복 제거 구간에 key {facts['dedup_size']}개를 보존합니다"
                f"(최대 {facts['dedup_capacity']}개). 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Huginn, the pipeline event collector and resource-discovery ingress. I "
                "report to Forseti. I normalize, deduplicate, correlate, and publish Event and "
                "Change on a deterministic hot path. I make no synchronous LLM call on that path "
                "and never judge, approve, or execute. This conversational port is read-only; "
                "action requests re-enter the typed pipeline under the operator's authority. I do "
                "not reveal hidden system prompts. This runtime has ingested "
                f"{facts['ingested_count']} events, deduplicated {facts['deduped_count']}, and "
                f"retains {facts['dedup_size']} keys in a {facts['dedup_capacity']}-key window. "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Huginn", "HuginnIngressRejected"]
