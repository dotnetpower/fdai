"""Build sanitized evidence for process-local T2 startup-proof reuse."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fdai.core.readiness import ProbeStatus, ReadinessDecision, StartupReadinessReport

SCHEMA_VERSION = "fdai.t2-startup-proof-evidence.v1"
QUERY_VERSION = "t2-startup-proof-evidence@1.0.0"
WORKFLOW_REF = ".github/workflows/t2-startup-proof-evidence.yml@refs/heads/main"
CORRELATION_PREFIX = "startup-readiness:"
_PROBE_PREFIX = "model.cross-check."
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROOF_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class T2StartupProofEvidenceError(ValueError):
    """Raised when live inputs cannot support the startup-proof claim."""


class T2StartupProofEvidencePendingError(T2StartupProofEvidenceError):
    """Raised while the current process has not completed enough proof reuses."""


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    """Validated T2 proof state extracted from one readiness result."""

    probe_id: str
    proof_id: str
    proof_started_at: datetime
    proof_sampled_at: datetime
    first_reused_at: datetime
    first_reused_expires_at: datetime
    latest_reused_at: datetime
    latest_reused_expires_at: datetime
    current_observed_at: datetime
    current_expires_at: datetime
    sample_count: int
    reuse_count: int


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise T2StartupProofEvidenceError(f"{field} must be an RFC 3339 timestamp") from exc
    else:
        raise T2StartupProofEvidenceError(f"{field} must be an RFC 3339 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise T2StartupProofEvidenceError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise T2StartupProofEvidenceError(f"{field} must be an integer >= {minimum}")
    return value


def _unix_ms(value: object, field: str) -> datetime:
    milliseconds = _integer(value, field)
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise T2StartupProofEvidenceError(
            f"{field} is outside the supported timestamp range"
        ) from exc


def _candidate_observations(
    report_payload: Mapping[str, Any],
    *,
    captured_at: datetime,
    minimum_reuse_count: int,
    maximum_proof_age_seconds: int,
) -> tuple[StartupReadinessReport, tuple[CandidateObservation, ...]]:
    if minimum_reuse_count < 2:
        raise T2StartupProofEvidenceError("minimum_reuse_count must be >= 2")
    if maximum_proof_age_seconds < 1:
        raise T2StartupProofEvidenceError("maximum_proof_age_seconds must be >= 1")
    try:
        report = StartupReadinessReport.model_validate(report_payload)
    except Exception as exc:
        raise T2StartupProofEvidenceError("startup readiness report is invalid") from exc
    if report.decision is ReadinessDecision.BLOCKED:
        raise T2StartupProofEvidencePendingError("startup readiness remains blocked")
    if report.missing_probe_ids or report.stale_probe_ids:
        raise T2StartupProofEvidencePendingError(
            "startup readiness evidence is incomplete or stale"
        )
    if report.generated_at > captured_at:
        raise T2StartupProofEvidenceError("startup readiness report is future-dated")

    observations: list[CandidateObservation] = []
    for result in report.results:
        if not result.probe_id.startswith(_PROBE_PREFIX):
            continue
        if result.status is not ProbeStatus.PASSED or result.model_evidence is None:
            raise T2StartupProofEvidencePendingError(
                f"{result.probe_id} has not produced successful model evidence"
            )
        evidence = result.evidence
        if evidence.get("sampled") is not False or evidence.get("previously_proven") is not True:
            raise T2StartupProofEvidencePendingError(
                f"{result.probe_id} has not reached a reused proof"
            )
        proof_id = evidence.get("proof_id")
        if not isinstance(proof_id, str) or _PROOF_ID_PATTERN.fullmatch(proof_id) is None:
            raise T2StartupProofEvidenceError(f"{result.probe_id} proof_id is invalid")
        reuse_count = _integer(
            evidence.get("reuse_count"),
            f"{result.probe_id}.reuse_count",
        )
        if reuse_count < minimum_reuse_count:
            raise T2StartupProofEvidencePendingError(
                f"{result.probe_id} has only {reuse_count} proof reuses"
            )
        proof_started_at = _unix_ms(
            evidence.get("proof_started_at_unix_ms"),
            f"{result.probe_id}.proof_started_at_unix_ms",
        )
        proof_sampled_at = _unix_ms(
            evidence.get("proof_sampled_at_unix_ms"),
            f"{result.probe_id}.proof_sampled_at_unix_ms",
        )
        first_reused_at = _unix_ms(
            evidence.get("first_reused_at_unix_ms"),
            f"{result.probe_id}.first_reused_at_unix_ms",
        )
        first_reused_expires_at = _unix_ms(
            evidence.get("first_reused_expires_at_unix_ms"),
            f"{result.probe_id}.first_reused_expires_at_unix_ms",
        )
        latest_reused_at = _unix_ms(
            evidence.get("latest_reused_at_unix_ms"),
            f"{result.probe_id}.latest_reused_at_unix_ms",
        )
        latest_reused_expires_at = _unix_ms(
            evidence.get("latest_reused_expires_at_unix_ms"),
            f"{result.probe_id}.latest_reused_expires_at_unix_ms",
        )
        observed_at_ms = int(result.observed_at.timestamp() * 1000)
        if not proof_started_at <= proof_sampled_at < first_reused_at < latest_reused_at:
            raise T2StartupProofEvidenceError(
                f"{result.probe_id} proof and reuse timestamps are not ordered"
            )
        if int(latest_reused_at.timestamp() * 1000) != observed_at_ms:
            raise T2StartupProofEvidenceError(
                f"{result.probe_id} latest reuse does not match observed_at"
            )
        if not (
            first_reused_at < first_reused_expires_at < latest_reused_expires_at
            and latest_reused_at < latest_reused_expires_at
        ):
            raise T2StartupProofEvidenceError(
                f"{result.probe_id} reuse expiry timestamps are not fresh and ordered"
            )
        if int(latest_reused_expires_at.timestamp() * 1000) != int(
            result.expires_at.timestamp() * 1000
        ):
            raise T2StartupProofEvidenceError(
                f"{result.probe_id} latest reuse expiry does not match expires_at"
            )
        if result.expires_at <= captured_at:
            raise T2StartupProofEvidencePendingError(f"{result.probe_id} evidence has expired")
        if (captured_at - proof_started_at).total_seconds() > maximum_proof_age_seconds:
            raise T2StartupProofEvidenceError(f"{result.probe_id} proof is not fresh")
        observations.append(
            CandidateObservation(
                probe_id=result.probe_id,
                proof_id=proof_id,
                proof_started_at=proof_started_at,
                proof_sampled_at=proof_sampled_at,
                first_reused_at=first_reused_at,
                first_reused_expires_at=first_reused_expires_at,
                latest_reused_at=latest_reused_at,
                latest_reused_expires_at=latest_reused_expires_at,
                current_observed_at=result.observed_at.astimezone(UTC),
                current_expires_at=result.expires_at.astimezone(UTC),
                sample_count=result.model_evidence.sample_count,
                reuse_count=reuse_count,
            )
        )
    if not observations:
        raise T2StartupProofEvidencePendingError(
            "no configured T2 cross-check candidates were observed"
        )
    return report, tuple(sorted(observations, key=lambda item: item.probe_id))


def metering_query_window(
    report_payload: Mapping[str, Any],
    *,
    captured_at: datetime,
    minimum_reuse_count: int = 2,
    maximum_proof_age_seconds: int = 1_800,
) -> tuple[datetime, datetime]:
    """Return the bounded metering interval for a capture-ready report."""

    _report, observations = _candidate_observations(
        report_payload,
        captured_at=captured_at,
        minimum_reuse_count=minimum_reuse_count,
        maximum_proof_age_seconds=maximum_proof_age_seconds,
    )
    return min(item.proof_started_at for item in observations), captured_at


def _metering_receipt(
    observation: CandidateObservation,
    invocations: Sequence[Mapping[str, Any]],
    *,
    captured_at: datetime,
) -> dict[str, object]:
    correlation_id = f"{CORRELATION_PREFIX}{observation.probe_id}"
    matched: list[dict[str, object]] = []
    prompt_token_total = 0
    completion_token_total = 0
    cost_total = Decimal("0")
    for row in invocations:
        if row.get("correlation_id") != correlation_id:
            continue
        occurred_at = _datetime(row.get("occurred_at"), "llm_invocation.occurred_at")
        if not observation.proof_started_at <= occurred_at <= captured_at:
            continue
        prompt_tokens = _integer(row.get("prompt_tokens"), "llm_invocation.prompt_tokens")
        completion_tokens = _integer(
            row.get("completion_tokens"),
            "llm_invocation.completion_tokens",
        )
        if prompt_tokens + completion_tokens < 1:
            raise T2StartupProofEvidenceError("startup metering token usage is unavailable")
        capability_id = row.get("capability_id")
        model_key = row.get("model_key")
        currency = row.get("currency")
        if not isinstance(capability_id, str) or not capability_id:
            raise T2StartupProofEvidenceError("metering capability_id is unavailable")
        if not isinstance(model_key, str) or not model_key:
            raise T2StartupProofEvidenceError("metering model_key is unavailable")
        if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise T2StartupProofEvidenceError("startup metering cost is incomplete")
        raw_cost = row.get("cost")
        if raw_cost is None:
            raise T2StartupProofEvidenceError("startup metering cost is incomplete")
        try:
            cost = Decimal(str(raw_cost))
        except InvalidOperation as exc:
            raise T2StartupProofEvidenceError("startup metering cost is invalid") from exc
        if not cost.is_finite() or cost < 0:
            raise T2StartupProofEvidenceError("startup metering cost is invalid")
        prompt_token_total += prompt_tokens
        completion_token_total += completion_tokens
        cost_total += cost
        matched.append(
            {
                "occurred_at": _timestamp(occurred_at),
                "capability_id": capability_id,
                "model_ref_digest": f"sha256:{hashlib.sha256(model_key.encode()).hexdigest()}",
                "mode": str(row.get("mode")),
                "usage_scope": str(row.get("usage_scope")),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": format(cost, "f"),
                "currency": currency,
            }
        )
    if len(matched) != observation.sample_count:
        raise T2StartupProofEvidenceError(
            f"{observation.probe_id} metered invocation count does not match sample_count"
        )
    sampled_deadline = observation.proof_sampled_at + timedelta(milliseconds=1)
    if any(_datetime(row["occurred_at"], "occurred_at") > sampled_deadline for row in matched):
        raise T2StartupProofEvidenceError(
            f"{observation.probe_id} emitted an additional invocation after proof sampling"
        )
    capability_ids = {str(row["capability_id"]) for row in matched}
    model_ref_digests = {str(row["model_ref_digest"]) for row in matched}
    currencies = {str(row["currency"]) for row in matched}
    modes = {str(row["mode"]) for row in matched}
    usage_scopes = {str(row["usage_scope"]) for row in matched}
    if any(len(values) != 1 for values in (capability_ids, model_ref_digests, currencies)):
        raise T2StartupProofEvidenceError(
            f"{observation.probe_id} metering identity or currency changed during sampling"
        )
    return {
        "probe_id": observation.probe_id,
        "capability_id": next(iter(capability_ids)),
        "model_ref_digest": next(iter(model_ref_digests)),
        "proof_id": observation.proof_id,
        "proof_started_at": _timestamp(observation.proof_started_at),
        "proof_sampled_at": _timestamp(observation.proof_sampled_at),
        "first_reused_at": _timestamp(observation.first_reused_at),
        "first_reused_expires_at": _timestamp(observation.first_reused_expires_at),
        "latest_reused_at": _timestamp(observation.latest_reused_at),
        "latest_reused_expires_at": _timestamp(observation.latest_reused_expires_at),
        "current_observed_at": _timestamp(observation.current_observed_at),
        "current_expires_at": _timestamp(observation.current_expires_at),
        "sample_count": observation.sample_count,
        "reuse_count": observation.reuse_count,
        "initial_sampled": True,
        "current_sampled": False,
        "previously_proven": True,
        "metered_invocation_count": len(matched),
        "additional_invocation_count": 0,
        "prompt_tokens": prompt_token_total,
        "completion_tokens": completion_token_total,
        "total_tokens": prompt_token_total + completion_token_total,
        "total_cost": format(cost_total, "f"),
        "currency": next(iter(currencies)),
        "modes": sorted(modes),
        "usage_scopes": sorted(usage_scopes),
        "metering_digest": _canonical_digest(matched),
    }


def build_t2_startup_proof_evidence(
    report_payload: Mapping[str, Any],
    invocations: Sequence[Mapping[str, Any]],
    *,
    source_revision: str,
    image_digest: str,
    revision_ref_digest: str,
    replica_ref_digest: str,
    source_identity_digest: str,
    environment: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    captured_at: datetime,
    revision_created_at: datetime,
    minimum_reuse_count: int = 2,
    maximum_proof_age_seconds: int = 1_800,
) -> dict[str, object]:
    """Build one customer-agnostic receipt from authoritative deployed records."""

    if _SHA_PATTERN.fullmatch(source_revision) is None:
        raise T2StartupProofEvidenceError("source_revision must be a full lowercase Git SHA-1")
    for field, value in {
        "image_digest": image_digest,
        "revision_ref_digest": revision_ref_digest,
        "replica_ref_digest": replica_ref_digest,
        "source_identity_digest": source_identity_digest,
    }.items():
        if _DIGEST_PATTERN.fullmatch(value) is None:
            raise T2StartupProofEvidenceError(f"{field} must be a sha256 digest")
    if environment not in {"dev", "staging", "prod"}:
        raise T2StartupProofEvidenceError("environment is invalid")
    if workflow_run_id < 1 or workflow_run_attempt < 1:
        raise T2StartupProofEvidenceError("workflow identity must be positive")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise T2StartupProofEvidenceError("captured_at must be timezone-aware")
    captured_at = captured_at.astimezone(UTC)
    if revision_created_at.tzinfo is None or revision_created_at.utcoffset() is None:
        raise T2StartupProofEvidenceError("revision_created_at must be timezone-aware")
    revision_created_at = revision_created_at.astimezone(UTC)
    report, observations = _candidate_observations(
        report_payload,
        captured_at=captured_at,
        minimum_reuse_count=minimum_reuse_count,
        maximum_proof_age_seconds=maximum_proof_age_seconds,
    )
    if any(item.proof_started_at < revision_created_at for item in observations):
        raise T2StartupProofEvidenceError("startup proof predates the deployed revision")
    candidates = [
        _metering_receipt(observation, invocations, captured_at=captured_at)
        for observation in observations
    ]
    scope_digest = _canonical_digest(
        {
            "environment": environment,
            "image_digest": image_digest,
            "replica_ref_digest": replica_ref_digest,
            "revision_ref_digest": revision_ref_digest,
            "source_revision": source_revision,
        }
    )
    evidence: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": "t2_startup_proof_reuse",
        "authority_class": "protected-runner-observation",
        "source_identity_digest": source_identity_digest,
        "scope_digest": scope_digest,
        "purpose": "issue-90-t2-startup-proof-reuse",
        "query_version": QUERY_VERSION,
        "event_time": _timestamp(report.generated_at),
        "recorded_at": _timestamp(captured_at),
        "freshness_seconds": (captured_at - report.generated_at.astimezone(UTC)).total_seconds(),
        "completeness": True,
        "synthetic": False,
        "execution_authority": False,
        "source_revision": source_revision,
        "image_digest": image_digest,
        "environment": environment,
        "revision_created_at": _timestamp(revision_created_at),
        "revision_ref_digest": revision_ref_digest,
        "replica_ref_digest": replica_ref_digest,
        "active_revision_count": 1,
        "replica_count": 1,
        "readiness_decision": report.decision.value,
        "minimum_reuse_count": minimum_reuse_count,
        "maximum_proof_age_seconds": maximum_proof_age_seconds,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "workflow": {
            "ref": WORKFLOW_REF,
            "run_id": workflow_run_id,
            "run_attempt": workflow_run_attempt,
        },
    }
    evidence["provenance_digest"] = _canonical_digest(
        {
            "source_revision": source_revision,
            "image_digest": image_digest,
            "scope_digest": scope_digest,
            "workflow": evidence["workflow"],
            "metering_digests": [candidate["metering_digest"] for candidate in candidates],
        }
    )
    evidence["evidence_digest"] = _canonical_digest(evidence)
    return evidence


__all__ = [
    "CORRELATION_PREFIX",
    "QUERY_VERSION",
    "SCHEMA_VERSION",
    "T2StartupProofEvidenceError",
    "T2StartupProofEvidencePendingError",
    "build_t2_startup_proof_evidence",
    "metering_query_window",
]
