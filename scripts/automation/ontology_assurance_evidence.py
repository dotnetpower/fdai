"""Evidence binding and acceptance for ontology assurance."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

DIGEST_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
STRICT_OPERATION_COUNTS: Final = {
    "aggregation": 2,
    "causal_analysis": 2,
    "evidence_validation": 2,
    "inventory_listing": 2,
    "property_filter": 2,
    "relationship_traversal": 2,
    "temporal_comparison": 2,
    "declaration_detail": 2,
    "release_evidence_health": 2,
    "inventory_impact": 2,
    "rule_state_distinction": 2,
}


class AssuranceRunError(RuntimeError):
    """Raised when a governed precondition or release gate fails."""


def _find_artifact(output_path: Path) -> Path:
    candidates = sorted(output_path.glob("**/ontology-query-randomized-assurance.json"))
    if not candidates:
        raise AssuranceRunError(f"assurance artifact is missing under {output_path}")
    return candidates[0]


def _read_artifact(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssuranceRunError(f"assurance artifact is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise AssuranceRunError("assurance artifact root MUST be an object")
    return payload


def _digest_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _bind_transport_evidence(
    path: Path,
    *,
    phase: str,
    request_topic: str,
    projection_topic: str,
    request_count: int,
    projection_count: int,
) -> None:
    payload = _read_artifact(path)
    payload["transport_evidence"] = {
        "schema_version": "1.0.0",
        "phase": phase,
        "request_topic_digest": _digest_text(request_topic),
        "projection_topic_digest": _digest_text(projection_topic),
        "request_count": request_count,
        "projection_count": projection_count,
    }
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _transport_evidence_accepted(
    payload: Mapping[str, Any],
    *,
    phase: str,
    expected_count: int,
) -> bool:
    evidence = payload.get("transport_evidence")
    if not isinstance(evidence, Mapping):
        return False
    request_digest = evidence.get("request_topic_digest")
    projection_digest = evidence.get("projection_topic_digest")
    return (
        evidence.get("schema_version") == "1.0.0"
        and evidence.get("phase") == phase
        and evidence.get("request_count") == expected_count
        and evidence.get("projection_count") == expected_count
        and isinstance(request_digest, str)
        and DIGEST_PATTERN.fullmatch(request_digest) is not None
        and isinstance(projection_digest, str)
        and DIGEST_PATTERN.fullmatch(projection_digest) is not None
        and request_digest != projection_digest
    )


def strict_artifact_accepted(payload: Mapping[str, Any], source_revision: str) -> bool:
    """Return whether the fresh bilingual 22-cell artifact clears strict v2."""
    summary = payload.get("summary")
    configuration = payload.get("run_configuration")
    answered_count = summary.get("answered_count") if isinstance(summary, Mapping) else None
    return (
        isinstance(summary, Mapping)
        and isinstance(configuration, Mapping)
        and _transport_evidence_accepted(payload, phase="strict_v2", expected_count=22)
        and all(
            (
                payload.get("schema_version") == "1.3.0",
                configuration.get("schema_version") == "1.4.0",
                payload.get("source_revision") == source_revision,
                payload.get("passed") is True,
                payload.get("run_mode") == "live",
                payload.get("receipt_source") == "live_assurance",
                summary.get("question_count") == 22,
                summary.get("live_question_count") == 22,
                summary.get("resumed_question_count") == 0,
                summary.get("passed_count") == 22,
                isinstance(answered_count, int) and answered_count >= 16,
                answered_count == summary.get("answered_with_complete_evidence_count"),
                summary.get("evidence_generation_consistent") is True,
                summary.get("answered_locale_coverage_complete") is True,
                summary.get("locale_counts") == {"en": 11, "ko": 11},
                summary.get("operation_counts") == STRICT_OPERATION_COUNTS,
                summary.get("transport_retry_count") == 0,
                summary.get("exhausted_transport_retry_count") == 0,
                summary.get("unsupported_operational_claim_count") == 0,
                summary.get("unauthorized_execution_count") == 0,
                summary.get("ambient_request_count") == 0,
                summary.get("bound_request_count") == 0,
                summary.get("plan_capability_mismatch_count") == 0,
            )
        )
    )


def full_artifact_accepted(payload: Mapping[str, Any], source_revision: str) -> bool:
    """Return whether the seeded 100-case artifact clears every release criterion."""
    summary = payload.get("summary")
    configuration = payload.get("run_configuration")
    return (
        isinstance(summary, Mapping)
        and isinstance(configuration, Mapping)
        and _transport_evidence_accepted(payload, phase="seeded_100", expected_count=100)
        and all(
            (
                payload.get("schema_version") == "1.3.0",
                configuration.get("schema_version") == "1.4.0",
                payload.get("source_revision") == source_revision,
                payload.get("passed") is True,
                payload.get("production_ready") is True,
                payload.get("run_mode") == "live",
                payload.get("receipt_source") == "live_assurance",
                summary.get("question_count") == 100,
                summary.get("live_question_count") == 100,
                summary.get("resumed_question_count") == 0,
                summary.get("passed_count") == 100,
                summary.get("locale_coverage_complete") is True,
                summary.get("operation_coverage_complete") is True,
                summary.get("answered_locale_coverage_complete") is True,
                summary.get("required_answer_coverage_complete") is True,
                summary.get("answered_count")
                == summary.get("answered_with_complete_evidence_count"),
                summary.get("unsupported_operational_claim_count") == 0,
                summary.get("unauthorized_execution_count") == 0,
                summary.get("ambient_request_count") == 0,
                summary.get("bound_request_count") == 0,
                summary.get("plan_capability_mismatch_count") == 0,
                summary.get("exhausted_transport_retry_count") == 0,
            )
        )
    )


def transport_delta_accepted(
    *,
    request_before: int,
    request_after: int,
    projection_before: int,
    projection_after: int,
    expected_count: int,
) -> bool:
    """Require one exact request and projection record per measured live turn."""
    return (
        expected_count > 0
        and request_after - request_before == expected_count
        and projection_after - projection_before == expected_count
    )
