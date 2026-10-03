"""Bounded raw-ingress validation and projection helpers for Huginn."""

from __future__ import annotations

import hashlib
import re
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

_DEDUP_CAPACITY = 100_000
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


__all__ = [
    "DiscoveryProjector",
    "HuginnIngressRejected",
    "HuginnIngressRejectedError",
    "_AUTHORITY_FIELDS",
    "_DEDUP_CAPACITY",
    "_DISCOVERY_PROJECTOR_TIMEOUT_SECONDS",
    "_MAX_ATTR_KEYS",
    "_MAX_FIELD_CHARS",
    "_MAX_KPI_SAMPLES",
    "_MAX_OPERATIONAL_CASE_ERRORS",
    "_MIN_P99_SAMPLES",
    "_TRACE_CONTINUITY_EVENT",
    "_bound",
    "_bound_attributes",
    "_bound_json",
    "_change_projection",
    "_copy_validated_json",
    "_event_occurred_at",
    "_kpi_measured",
    "_kpi_unavailable",
    "_p99_kpi",
    "_ratio_kpi",
    "_raw_payload_digest",
    "_safe_identity",
    "_safe_string",
    "_validate_raw_ingress",
    "_validated_operator_request_fields",
]
