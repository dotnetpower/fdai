#!/usr/bin/env python3
"""Validate the exact receipt bundle used to complete the OHL scale-out contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_SCHEMA = json.loads(
    (_ROOT / "config/ohl-scale-out-evidence.schema.json").read_text(encoding="utf-8")
)
_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "correlation_id",
    "target_revision",
    "started_at",
    "recurrence_observed_at",
    "receipts",
    "condition_receipts",
    "samples",
}
_RECEIPT_FIELDS = {
    "kind",
    "evidence_level",
    "authority_class",
    "source_identity_digest",
    "scope_digest",
    "purpose",
    "query_version",
    "event_time",
    "recorded_at",
    "freshness_seconds",
    "completeness",
    "provenance_digest",
    "synthetic",
    "correlation_id",
    "target_revision",
    "verified",
}
_SAMPLE_FIELDS = {
    "sample_id",
    "prediction_digest",
    "outcome_digest",
    "event_time",
    "horizon_end",
    "observed_at",
    "observation_window_seconds",
    "evidence_level",
    "synthetic",
    "complete",
    "truncated",
    "censored",
    "predicted_success",
    "observed_success",
    "policy_escape",
    "active_model_mutated",
    "promotion_applied",
    "observer_identity_digest",
    "executor_identity_digest",
}
_INDEPENDENT_RECEIPTS = {
    "cleanup",
    "graph_shadow_outcome",
    "independent_recovery",
}


def _mapping(value: object, field: str, errors: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{field} MUST be an object")
        return None
    return value


def _sequence(value: object, field: str, errors: list[str]) -> Sequence[object] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        errors.append(f"{field} MUST be an array")
        return None
    return value


def _text(value: object, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        errors.append(f"{field} MUST be bounded non-empty text")
        return None
    return value


def _digest(value: object, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        errors.append(f"{field} MUST be a lowercase SHA-256 digest")
        return None
    return value


def _timestamp(value: object, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{field} MUST be an RFC 3339 UTC timestamp ending in Z")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} MUST be a valid RFC 3339 UTC timestamp")
        return None
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        errors.append(f"{field} MUST use UTC")
        return None
    return parsed


def _exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    field: str,
    errors: list[str],
) -> None:
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    for name in missing:
        errors.append(f"{field} missing {name}")
    for name in unexpected:
        errors.append(f"{field} contains unexpected field: {name}")


def _validate_receipts(
    value: object,
    *,
    required_kinds: set[str],
    graph_prediction_fields: set[str],
    graph_outcome_fields: set[str],
    correlation_id: str | None,
    target_revision: str | None,
    errors: list[str],
) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    items = _sequence(value, "receipts", errors)
    receipts: dict[str, Mapping[str, Any]] = {}
    digests: set[str] = set()
    if items is None:
        return receipts, digests
    for index, item in enumerate(items):
        field = f"receipts[{index}]"
        receipt = _mapping(item, field, errors)
        if receipt is None:
            continue
        kind = _text(receipt.get("kind"), f"{field}.kind", errors)
        expected_fields = set(_RECEIPT_FIELDS)
        if kind == "graph_shadow_prediction":
            expected_fields.update(graph_prediction_fields)
        elif kind == "graph_shadow_outcome":
            expected_fields.update(graph_outcome_fields)
        _exact_fields(receipt, expected_fields, field, errors)
        if kind is not None:
            if kind in receipts:
                errors.append(f"receipts contains duplicate kind: {kind}")
            receipts[kind] = receipt
        for name in ("authority_class", "purpose", "query_version"):
            _text(receipt.get(name), f"{field}.{name}", errors)
        source_identity = _digest(
            receipt.get("source_identity_digest"),
            f"{field}.source_identity_digest",
            errors,
        )
        _digest(receipt.get("scope_digest"), f"{field}.scope_digest", errors)
        provenance = _digest(
            receipt.get("provenance_digest"),
            f"{field}.provenance_digest",
            errors,
        )
        if provenance is not None:
            if provenance in digests:
                errors.append(f"receipts contains duplicate provenance digest: {provenance}")
            digests.add(provenance)
        event_time = _timestamp(receipt.get("event_time"), f"{field}.event_time", errors)
        recorded_at = _timestamp(receipt.get("recorded_at"), f"{field}.recorded_at", errors)
        if event_time is not None and recorded_at is not None and recorded_at < event_time:
            errors.append(f"{field}.recorded_at MUST not precede event_time")
        freshness = receipt.get("freshness_seconds")
        if not isinstance(freshness, int) or isinstance(freshness, bool) or freshness < 0:
            errors.append(f"{field}.freshness_seconds MUST be a non-negative integer")
        elif event_time is not None and recorded_at is not None:
            observed_freshness = (recorded_at - event_time).total_seconds()
            if freshness != observed_freshness:
                errors.append(f"{field}.freshness_seconds MUST match its timestamps")
        if receipt.get("evidence_level") != "live_execution":
            errors.append(f"{field}.evidence_level MUST equal live_execution")
        if receipt.get("completeness") is not True:
            errors.append(f"{field}.completeness MUST be true")
        if receipt.get("synthetic") is not False:
            errors.append(f"{field}.synthetic MUST be false")
        if receipt.get("verified") is not True:
            errors.append(f"{field}.verified MUST be true")
        if correlation_id is not None and receipt.get("correlation_id") != correlation_id:
            errors.append(f"{field}.correlation_id MUST match the campaign")
        if target_revision is not None and receipt.get("target_revision") != target_revision:
            errors.append(f"{field}.target_revision MUST match the campaign")
        if kind in _INDEPENDENT_RECEIPTS and source_identity is None:
            errors.append(f"{field} MUST identify its independent observer")
    for kind in sorted(required_kinds - set(receipts)):
        errors.append(f"receipts missing required kind: {kind}")
    executor = receipts.get("provider_scale_out", {}).get("source_identity_digest")
    if isinstance(executor, str):
        for kind in sorted(_INDEPENDENT_RECEIPTS):
            observer = receipts.get(kind, {}).get("source_identity_digest")
            if observer == executor:
                errors.append(
                    f"receipts.{kind} MUST use an identity distinct from provider_scale_out"
                )
    return receipts, digests


def _validate_graph_receipts(
    receipts: Mapping[str, Mapping[str, Any]],
    *,
    errors: list[str],
) -> None:
    prediction = receipts.get("graph_shadow_prediction")
    outcome = receipts.get("graph_shadow_outcome")
    if prediction is not None:
        for name in (
            "prediction_digest",
            "ontology_release_digest",
            "base_snapshot_digest",
        ):
            _digest(prediction.get(name), f"graph_shadow_prediction.{name}", errors)
        for name in ("graph_revision", "inventory_generation"):
            _text(prediction.get(name), f"graph_shadow_prediction.{name}", errors)
        evidence_cutoff = _timestamp(
            prediction.get("evidence_cutoff"),
            "graph_shadow_prediction.evidence_cutoff",
            errors,
        )
        horizon_end = _timestamp(
            prediction.get("horizon_end"),
            "graph_shadow_prediction.horizon_end",
            errors,
        )
        if evidence_cutoff is not None and horizon_end is not None:
            if horizon_end <= evidence_cutoff:
                errors.append("graph_shadow_prediction.horizon_end MUST follow evidence_cutoff")
        for name in ("active_model_refs", "challenger_model_refs"):
            refs = _sequence(
                prediction.get(name),
                f"graph_shadow_prediction.{name}",
                errors,
            )
            if refs is not None:
                if not refs:
                    errors.append(f"graph_shadow_prediction.{name} MUST not be empty")
                for index, ref in enumerate(refs):
                    _text(ref, f"graph_shadow_prediction.{name}[{index}]", errors)
        invariant_digests = _sequence(
            prediction.get("invariant_evidence_digests"),
            "graph_shadow_prediction.invariant_evidence_digests",
            errors,
        )
        if invariant_digests is not None:
            if not invariant_digests:
                errors.append(
                    "graph_shadow_prediction.invariant_evidence_digests MUST not be empty"
                )
            for index, digest in enumerate(invariant_digests):
                _digest(
                    digest,
                    f"graph_shadow_prediction.invariant_evidence_digests[{index}]",
                    errors,
                )
        expected_values = {
            "mode": "shadow",
            "execution_authority": False,
            "complete": True,
            "truncated": False,
        }
        for name, expected in expected_values.items():
            if prediction.get(name) != expected:
                errors.append(f"graph_shadow_prediction.{name} MUST equal {str(expected).lower()}")
    if outcome is not None:
        prediction_digest = _digest(
            outcome.get("prediction_digest"),
            "graph_shadow_outcome.prediction_digest",
            errors,
        )
        _digest(
            outcome.get("observation_digest"),
            "graph_shadow_outcome.observation_digest",
            errors,
        )
        observer = _digest(
            outcome.get("observer_identity_digest"),
            "graph_shadow_outcome.observer_identity_digest",
            errors,
        )
        executor = _digest(
            outcome.get("executor_identity_digest"),
            "graph_shadow_outcome.executor_identity_digest",
            errors,
        )
        _timestamp(
            outcome.get("observed_at"),
            "graph_shadow_outcome.observed_at",
            errors,
        )
        if prediction is not None and prediction_digest != prediction.get("prediction_digest"):
            errors.append("graph_shadow_outcome MUST close the graph prediction digest")
        if observer is not None and observer != outcome.get("source_identity_digest"):
            errors.append("graph_shadow_outcome observer MUST match the receipt source")
        provider_identity = receipts.get("provider_scale_out", {}).get("source_identity_digest")
        if executor is not None and executor != provider_identity:
            errors.append("graph_shadow_outcome executor MUST match provider_scale_out")
        if outcome.get("observer_executor_distinct") is not True or observer == executor:
            errors.append("graph_shadow_outcome observer and executor MUST be distinct")
        expected_values = {
            "status": "closed",
            "completeness": True,
            "active_model_mutated": False,
            "promotion_applied": False,
        }
        for name, expected in expected_values.items():
            if outcome.get(name) != expected:
                errors.append(f"graph_shadow_outcome.{name} MUST equal {str(expected).lower()}")
        censoring_refs = _sequence(
            outcome.get("censoring_refs"),
            "graph_shadow_outcome.censoring_refs",
            errors,
        )
        if censoring_refs is not None and censoring_refs:
            errors.append("graph_shadow_outcome.censoring_refs MUST be empty")
        evidence_refs = _sequence(
            outcome.get("evidence_refs"),
            "graph_shadow_outcome.evidence_refs",
            errors,
        )
        if evidence_refs is not None:
            if not evidence_refs:
                errors.append("graph_shadow_outcome.evidence_refs MUST not be empty")
            for index, digest in enumerate(evidence_refs):
                _digest(
                    digest,
                    f"graph_shadow_outcome.evidence_refs[{index}]",
                    errors,
                )


def _validate_samples(
    value: object,
    *,
    minimum_samples: int,
    minimum_accuracy: float,
    minimum_days: int,
    recurrence_seconds: int,
    horizon_seconds: int,
    grace_seconds: int,
    observation_window_seconds: int,
    campaign_started_at: datetime | None,
    recurrence_observed_at: datetime | None,
    provider_executor_identity: str | None,
    errors: list[str],
) -> list[datetime]:
    items = _sequence(value, "samples", errors)
    if items is None:
        return []
    if len(items) < minimum_samples:
        errors.append(f"samples MUST contain at least {minimum_samples} live observations")
    event_times: list[datetime] = []
    sample_ids: set[str] = set()
    correct = 0
    scored = 0
    for index, item in enumerate(items):
        field = f"samples[{index}]"
        sample = _mapping(item, field, errors)
        if sample is None:
            continue
        _exact_fields(sample, _SAMPLE_FIELDS, field, errors)
        sample_id = _text(sample.get("sample_id"), f"{field}.sample_id", errors)
        if sample_id is not None:
            if sample_id in sample_ids:
                errors.append(f"samples contains duplicate sample_id: {sample_id}")
            sample_ids.add(sample_id)
        _digest(sample.get("prediction_digest"), f"{field}.prediction_digest", errors)
        _digest(sample.get("outcome_digest"), f"{field}.outcome_digest", errors)
        event_time = _timestamp(sample.get("event_time"), f"{field}.event_time", errors)
        horizon_end = _timestamp(sample.get("horizon_end"), f"{field}.horizon_end", errors)
        observed_at = _timestamp(sample.get("observed_at"), f"{field}.observed_at", errors)
        if event_time is not None:
            event_times.append(event_time)
            if campaign_started_at is not None and event_time < campaign_started_at:
                errors.append(f"{field}.event_time MUST not precede the campaign")
        if event_time is not None and horizon_end is not None:
            if (horizon_end - event_time).total_seconds() != horizon_seconds:
                errors.append(f"{field}.horizon_end MUST preserve the configured horizon")
        if horizon_end is not None and observed_at is not None:
            if (observed_at - horizon_end).total_seconds() < grace_seconds:
                errors.append(f"{field}.observed_at MUST follow the telemetry grace period")
            if recurrence_observed_at is not None and observed_at > recurrence_observed_at:
                errors.append(f"{field}.observed_at MUST not follow recurrence closure")
        if sample.get("observation_window_seconds") != observation_window_seconds:
            errors.append(f"{field}.observation_window_seconds MUST match the contract")
        expected_values = {
            "evidence_level": "live_execution",
            "synthetic": False,
            "complete": True,
            "truncated": False,
            "censored": False,
            "policy_escape": False,
            "active_model_mutated": False,
            "promotion_applied": False,
        }
        for name, expected in expected_values.items():
            if sample.get(name) != expected:
                errors.append(f"{field}.{name} MUST equal {str(expected).lower()}")
        predicted = sample.get("predicted_success")
        observed = sample.get("observed_success")
        if not isinstance(predicted, bool) or not isinstance(observed, bool):
            errors.append(f"{field} predicted_success and observed_success MUST be booleans")
        else:
            scored += 1
            correct += int(predicted == observed)
        observer = _digest(
            sample.get("observer_identity_digest"),
            f"{field}.observer_identity_digest",
            errors,
        )
        executor = _digest(
            sample.get("executor_identity_digest"),
            f"{field}.executor_identity_digest",
            errors,
        )
        if observer is not None and observer == executor:
            errors.append(f"{field} observer identity MUST differ from executor identity")
        if executor is not None and executor != provider_executor_identity:
            errors.append(f"{field}.executor_identity_digest MUST match provider_scale_out")
    if scored and correct / scored < minimum_accuracy:
        errors.append(f"sample accuracy MUST be at least {minimum_accuracy:.2f}")
    if event_times:
        elapsed = (max(event_times) - min(event_times)).total_seconds()
        if elapsed < recurrence_seconds:
            errors.append(f"samples MUST span at least {recurrence_seconds} seconds")
        distinct_days = {value.date() for value in event_times}
        if len(distinct_days) < minimum_days:
            errors.append(f"samples MUST cover at least {minimum_days} distinct UTC days")
    return event_times


def validate_completion(
    manifest_value: object,
    bundle_value: object,
    *,
    source_receipt_sha256: str,
) -> list[str]:
    """Return deterministic violations that prevent an OHL completion transition."""
    errors: list[str] = []
    manifest = _mapping(manifest_value, "manifest", errors)
    bundle = _mapping(bundle_value, "bundle", errors)
    if manifest is None or bundle is None:
        return errors
    schema_errors = sorted(
        Draft202012Validator(_MANIFEST_SCHEMA).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        return [
            f"manifest schema violation at {error.json_path}: {error.message}"
            for error in schema_errors
        ]
    _exact_fields(bundle, _ROOT_FIELDS, "bundle", errors)
    if bundle.get("schema_version") != 1:
        errors.append("bundle.schema_version MUST equal 1")
    campaign_id = _text(bundle.get("campaign_id"), "bundle.campaign_id", errors)
    correlation_id = _text(bundle.get("correlation_id"), "bundle.correlation_id", errors)
    target_revision = _text(bundle.get("target_revision"), "bundle.target_revision", errors)
    started_at = _timestamp(bundle.get("started_at"), "bundle.started_at", errors)
    recurrence_observed_at = _timestamp(
        bundle.get("recurrence_observed_at"),
        "bundle.recurrence_observed_at",
        errors,
    )
    if campaign_id is None:
        errors.append("bundle MUST identify the protected-runner campaign")

    evidence = _mapping(manifest.get("evidence"), "manifest.evidence", errors)
    acceptance = _mapping(manifest.get("acceptance"), "manifest.acceptance", errors)
    observation = _mapping(manifest.get("observation"), "manifest.observation", errors)
    result = _mapping(manifest.get("result"), "manifest.result", errors)
    if evidence is None or acceptance is None or observation is None or result is None:
        return errors
    if manifest.get("status") != "complete":
        errors.append("manifest.status MUST equal complete")
    if manifest.get("evidence_level") != "live_execution":
        errors.append("manifest.evidence_level MUST equal live_execution")
    if result.get("status") != "verified":
        errors.append("manifest.result.status MUST equal verified")
    if manifest.get("residuals") != []:
        errors.append("manifest.residuals MUST be empty")
    if result.get("source_receipt_digest") != source_receipt_sha256:
        errors.append("manifest.result.source_receipt_digest MUST match the exact bundle bytes")

    required = evidence.get("required_receipts")
    required_kinds = set(required) if isinstance(required, list) else set()
    graph_prediction_fields = evidence.get("graph_prediction_fields")
    graph_outcome_fields = evidence.get("graph_outcome_fields")
    condition_receipt_kinds = _mapping(
        evidence.get("condition_receipt_kinds"),
        "manifest.evidence.condition_receipt_kinds",
        errors,
    )
    receipts, receipt_digests = _validate_receipts(
        bundle.get("receipts"),
        required_kinds=required_kinds,
        graph_prediction_fields=(
            set(graph_prediction_fields) if isinstance(graph_prediction_fields, list) else set()
        ),
        graph_outcome_fields=(
            set(graph_outcome_fields) if isinstance(graph_outcome_fields, list) else set()
        ),
        correlation_id=correlation_id,
        target_revision=target_revision,
        errors=errors,
    )
    _validate_graph_receipts(receipts, errors=errors)
    conditions = _mapping(bundle.get("condition_receipts"), "condition_receipts", errors)
    required_conditions = acceptance.get("manifest_complete_requires")
    if conditions is not None and isinstance(required_conditions, list):
        expected_conditions = set(required_conditions)
        _exact_fields(conditions, expected_conditions, "condition_receipts", errors)
        if condition_receipt_kinds is None or expected_conditions != set(condition_receipt_kinds):
            errors.append(
                "manifest.acceptance.manifest_complete_requires MUST match the verifier mapping"
            )
        for condition in sorted(expected_conditions):
            digest = _digest(
                conditions.get(condition),
                f"condition_receipts.{condition}",
                errors,
            )
            if digest is not None and digest not in receipt_digests:
                errors.append(f"condition_receipts.{condition} MUST reference a bundle receipt")
            expected_kind = (
                condition_receipt_kinds.get(condition)
                if condition_receipt_kinds is not None
                else None
            )
            expected_digest = receipts.get(expected_kind or "", {}).get("provenance_digest")
            if digest is not None and digest != expected_digest:
                errors.append(f"condition_receipts.{condition} MUST reference {expected_kind}")

    recurrence_seconds = int(observation.get("recurrence_window_seconds", -1))
    provider_executor_identity = receipts.get("provider_scale_out", {}).get(
        "source_identity_digest"
    )
    event_times = _validate_samples(
        bundle.get("samples"),
        minimum_samples=int(acceptance.get("minimum_live_shadow_samples", -1)),
        minimum_accuracy=float(acceptance.get("minimum_accuracy", 2.0)),
        minimum_days=int(observation.get("minimum_live_shadow_days", -1)),
        recurrence_seconds=recurrence_seconds,
        horizon_seconds=int(observation.get("prediction_horizon_seconds", -1)),
        grace_seconds=int(observation.get("telemetry_grace_seconds", -1)),
        observation_window_seconds=int(observation.get("metric_observation_window_seconds", -1)),
        campaign_started_at=started_at,
        recurrence_observed_at=recurrence_observed_at,
        provider_executor_identity=(
            provider_executor_identity if isinstance(provider_executor_identity, str) else None
        ),
        errors=errors,
    )
    if started_at is not None and recurrence_observed_at is not None:
        if recurrence_observed_at < started_at:
            errors.append("bundle.recurrence_observed_at MUST not precede campaign start")
        if (recurrence_observed_at - started_at).total_seconds() < recurrence_seconds:
            errors.append("bundle.recurrence_observed_at MUST close the full recurrence window")
    completed_at = _timestamp(result.get("completed_at"), "manifest.result.completed_at", errors)
    latest_evidence = [
        value for value in (*event_times, recurrence_observed_at) if value is not None
    ]
    if completed_at is not None and latest_evidence and completed_at < max(latest_evidence):
        errors.append("manifest.result.completed_at MUST not precede verified evidence")
    return errors


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _load_json_bytes(value: bytes) -> object:
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("receipt_bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = _load_json_bytes(args.manifest.read_bytes())
        receipt_bytes = args.receipt_bundle.read_bytes()
        bundle = _load_json_bytes(receipt_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ohl-evidence: ERROR: cannot read evidence: {exc}", file=sys.stderr)
        return 1
    errors = validate_completion(
        manifest,
        bundle,
        source_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
    )
    if errors:
        for error in errors:
            print(f"ohl-evidence: ERROR: {error}", file=sys.stderr)
        return 1
    print("ohl-evidence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
