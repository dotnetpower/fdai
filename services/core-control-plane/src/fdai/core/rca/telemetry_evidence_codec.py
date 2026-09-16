"""JSON-safe codecs for typed adaptive telemetry evidence contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from .telemetry_evidence import (
    TELEMETRY_EVIDENCE_SCHEMA_VERSION,
    TelemetryEvidenceNeed,
    TelemetryEvidenceReceipt,
    TelemetryLookbackProfile,
)


def telemetry_evidence_need_to_mapping(need: TelemetryEvidenceNeed) -> dict[str, object]:
    """Serialize one need as bounded JSON-safe query-node arguments."""

    return {
        "schema_version": need.schema_version,
        "need_id": need.need_id,
        "incident_id": need.incident_id,
        "resource_ref": need.resource_ref,
        "evidence_cutoff": _timestamp(need.evidence_cutoff),
        "recipe_id": need.recipe_id,
        "recipe_version": need.recipe_version,
        "lookback": need.lookback.value,
        "expected_output_schema_digest": need.expected_output_schema_digest,
        "max_query_count": need.max_query_count,
        "max_cost_units": need.max_cost_units,
        "idempotency_key": need.idempotency_key,
    }


def telemetry_evidence_need_from_mapping(value: object) -> TelemetryEvidenceNeed:
    """Parse an exact need mapping and recheck its content identity."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "need_id",
        "incident_id",
        "resource_ref",
        "evidence_cutoff",
        "recipe_id",
        "recipe_version",
        "lookback",
        "expected_output_schema_digest",
        "max_query_count",
        "max_cost_units",
        "idempotency_key",
    }:
        raise ValueError("telemetry evidence need mapping has an invalid shape")
    if value["schema_version"] != TELEMETRY_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported telemetry evidence need schema version")
    cutoff = value["evidence_cutoff"]
    if not isinstance(cutoff, str):
        raise ValueError("telemetry evidence cutoff MUST be an RFC 3339 string")
    try:
        parsed_cutoff = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        lookback = TelemetryLookbackProfile(value["lookback"])
    except (TypeError, ValueError) as exc:
        raise ValueError("telemetry evidence need contains an invalid typed value") from exc
    return TelemetryEvidenceNeed(
        need_id=value["need_id"],
        incident_id=value["incident_id"],
        resource_ref=value["resource_ref"],
        evidence_cutoff=parsed_cutoff,
        recipe_id=value["recipe_id"],
        recipe_version=value["recipe_version"],
        lookback=lookback,
        expected_output_schema_digest=value["expected_output_schema_digest"],
        max_query_count=value["max_query_count"],
        max_cost_units=value["max_cost_units"],
        idempotency_key=value["idempotency_key"],
    )


def telemetry_evidence_receipt_to_mapping(
    receipt: TelemetryEvidenceReceipt,
) -> dict[str, object]:
    """Serialize a receipt without raw rows, routes, endpoints, or query text."""

    return {
        "schema_version": receipt.schema_version,
        "receipt_digest": receipt.receipt_digest,
        "need_id": receipt.need_id,
        "recipe_id": receipt.recipe_id,
        "recipe_version": receipt.recipe_version,
        "resource_ref": receipt.resource_ref,
        "evidence_cutoff": _timestamp(receipt.evidence_cutoff),
        "observed_until": (
            _timestamp(receipt.observed_until) if receipt.observed_until is not None else None
        ),
        "disposition": receipt.disposition.value,
        "route_count": receipt.route_count,
        "queried_route_count": receipt.queried_route_count,
        "row_count": receipt.row_count,
        "latency_ms": receipt.latency_ms,
        "estimated_cost_units": receipt.estimated_cost_units,
        "actual_cost_units": receipt.actual_cost_units,
        "fact_tokens": list(receipt.fact_tokens),
        "complete": receipt.complete,
        "truncated": receipt.truncated,
        "execution_authority": False,
        "mutation_authority": False,
        "query_execution_authority": False,
    }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("telemetry evidence datetime MUST be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "telemetry_evidence_need_from_mapping",
    "telemetry_evidence_need_to_mapping",
    "telemetry_evidence_receipt_to_mapping",
]
