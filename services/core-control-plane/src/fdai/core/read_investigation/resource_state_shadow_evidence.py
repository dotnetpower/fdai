"""Canonical evidence extraction for resource-state shadow comparison."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.semantic_query import SemanticQueryReceipt
from fdai.core.read_investigation.intent_spec import read_investigation_intent_spec
from fdai.core.read_investigation.models import (
    ReadInvestigationOutcome,
    ReadInvestigationResult,
)
from fdai.core.read_investigation.resource_state_shadow_models import ShadowComparisonReason
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
    ResourceResolutionStatus,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactLane,
    StateFactMetadata,
)


@dataclass(frozen=True, slots=True)
class NormalizedResourceStateObservation:
    """Exact normalized identity, state, time, and evidence pointers."""

    resource_identity: str
    state: str
    observed_at: datetime
    evidence_refs: tuple[str, ...]

    @property
    def evidence_digest(self) -> str:
        return ontology_function_digest(
            {
                "resource_identity": self.resource_identity,
                "state": self.state,
                "observed_at": _timestamp(self.observed_at),
                "evidence_refs": list(self.evidence_refs),
            }
        )


@dataclass(frozen=True, slots=True)
class ResourceStateExtraction:
    """One normalized observation or stable fail-closed reasons."""

    observation: NormalizedResourceStateObservation | None
    reasons: tuple[ShadowComparisonReason, ...]


def extract_existing_state(result: ReadInvestigationResult) -> ResourceStateExtraction:
    """Extract one exact state fact from the authoritative existing result."""

    if result.request.intent is not ReadInvestigationIntent.RESOURCE_STATE:
        return _malformed_existing()
    expected_plan = read_investigation_intent_spec(result.request.intent).plan_id
    if expected_plan != "read.resource-state.v1":  # pragma: no cover - fixed intent registry
        return _malformed_existing()
    if result.outcome is not ReadInvestigationOutcome.MATCHED:
        return ResourceStateExtraction(
            None, (ShadowComparisonReason.EXISTING_EVIDENCE_UNAVAILABLE,)
        )
    if (
        result.resolution.status is not ResourceResolutionStatus.MATCHED
        or result.resolution.resource is None
    ):
        return _malformed_existing()

    state_records = tuple(
        (envelope, record)
        for envelope in result.evidence
        for record in envelope.records
        if record.state is not None
    )
    if len(state_records) != 1:
        return _malformed_existing()
    envelope, record = state_records[0]
    if envelope.status is not EvidenceStatus.MATCHED or not envelope.evidence_refs:
        return ResourceStateExtraction(
            None, (ShadowComparisonReason.EXISTING_EVIDENCE_UNAVAILABLE,)
        )
    if envelope.truncated:
        return ResourceStateExtraction(None, (ShadowComparisonReason.EXISTING_EVIDENCE_TRUNCATED,))
    if envelope.freshness is EvidenceFreshness.STALE:
        return ResourceStateExtraction(None, (ShadowComparisonReason.EXISTING_OBSERVATION_STALE,))
    state = record.state
    if state is None:  # pragma: no cover - filtered by state_records
        return _malformed_existing()
    resolved_identity = _normalize_token(result.resolution.resource.resource_ref)
    evidence_identity = _normalize_token(envelope.resource_ref)
    if resolved_identity != evidence_identity or record.occurred_at > envelope.observed_at:
        return _malformed_existing()
    return ResourceStateExtraction(
        NormalizedResourceStateObservation(
            resource_identity=resolved_identity,
            state=_normalize_token(state),
            observed_at=record.occurred_at.astimezone(UTC),
            evidence_refs=tuple(sorted(envelope.evidence_refs)),
        ),
        (),
    )


def extract_semantic_state(result: SecuredObjectSetQueryResult) -> ResourceStateExtraction:
    """Extract one fresh complete observed state fact from a secured ObjectSet."""

    if result.receipt.truncated or result.materialization.truncated:
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_RESULT_TRUNCATED,))
    if not result.receipt.complete or len(result.materialization.graph.objects) != 1:
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_RESULT_UNAVAILABLE,))
    item = result.materialization.graph.objects[0]
    if item.object_type != "Resource":
        return _malformed_semantic()
    raw_identity = item.properties.get("id")
    raw_provider_properties = item.properties.get("properties")
    if not isinstance(raw_identity, str) or not isinstance(raw_provider_properties, Mapping):
        return _malformed_semantic()
    identity = _normalize_token(item.id)
    if identity != _normalize_token(raw_identity):
        return _malformed_semantic()
    raw_state = raw_provider_properties.get("state")
    raw_metadata = raw_provider_properties.get(STATE_FACT_METADATA_PROPERTY)
    if not isinstance(raw_state, str) or not isinstance(raw_metadata, Mapping):
        return _malformed_semantic()
    try:
        metadata = StateFactMetadata.from_mapping(raw_metadata)
    except (TypeError, ValueError):
        return _malformed_semantic()
    if (
        metadata.lane is not StateFactLane.OBSERVED
        or metadata.synthetic
        or metadata.completeness < 1.0
        or metadata.conflicts
    ):
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_RESULT_UNAVAILABLE,))
    cutoff = result.receipt.observation_cutoff.astimezone(UTC)
    observed_at = metadata.effective_at.astimezone(UTC)
    if (
        observed_at > cutoff
        or metadata.evidence_cutoff.astimezone(UTC) > cutoff
        or metadata.recorded_at.astimezone(UTC) > cutoff
        or (cutoff - observed_at).total_seconds() > metadata.freshness_ceiling_seconds
    ):
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_OBSERVATION_STALE,))
    return ResourceStateExtraction(
        NormalizedResourceStateObservation(
            resource_identity=identity,
            state=_normalize_token(raw_state),
            observed_at=observed_at,
            evidence_refs=metadata.evidence_refs,
        ),
        (),
    )


def semantic_lineage_matches(
    result: SecuredObjectSetQueryResult,
    receipt: SemanticQueryReceipt,
) -> bool:
    """Reverify that the semantic receipt was issued for this secured result."""

    expected_output = ontology_function_digest(result.model_dump(mode="json"))
    return (
        receipt.ontology_release == result.receipt.ontology_release
        and receipt.truncated == result.receipt.truncated
        and receipt.truncation_reason == result.receipt.truncation_reason
        and receipt.function_invocation.output_digest == expected_output
        and receipt.receipt_digest == _semantic_receipt_digest(receipt)
    )


def observation_mismatches(
    baseline: NormalizedResourceStateObservation,
    candidate: NormalizedResourceStateObservation,
) -> set[ShadowComparisonReason]:
    """Return exact normalized dimensions that diverge."""

    reasons: set[ShadowComparisonReason] = set()
    if baseline.resource_identity != candidate.resource_identity:
        reasons.add(ShadowComparisonReason.RESOURCE_IDENTITY_MISMATCH)
    if baseline.state != candidate.state:
        reasons.add(ShadowComparisonReason.STATE_MISMATCH)
    if baseline.observed_at != candidate.observed_at:
        reasons.add(ShadowComparisonReason.OBSERVED_AT_MISMATCH)
    return reasons


def existing_input_digest(result: ReadInvestigationResult) -> str:
    """Digest stable existing evidence while excluding attempt timing."""

    return ontology_function_digest(
        {
            "intent": result.request.intent.value,
            "outcome": result.outcome.value,
            "resolution_status": result.resolution.status.value,
            "resource_ref": (
                result.resolution.resource.resource_ref
                if result.resolution.resource is not None
                else None
            ),
            "evidence": [_stable_envelope(item) for item in result.evidence],
        }
    )


def invocation_digest(receipt: SemanticQueryReceipt) -> str:
    """Digest stable invocation lineage while excluding attempt timing."""

    invocation = receipt.function_invocation
    return ontology_function_digest(
        {
            "request_id": invocation.request_id,
            "invocation_id": invocation.invocation_id,
            "function_ref": invocation.function_ref.model_dump(mode="json"),
            "caller_agent": invocation.caller_agent,
            "caller_role": invocation.caller_role.value,
            "purposes": list(invocation.purposes),
            "input_digest": invocation.input_digest,
            "output_digest": invocation.output_digest,
            "seed": invocation.seed,
            "evidence_refs": list(invocation.evidence_refs),
        }
    )


def _semantic_receipt_digest(receipt: SemanticQueryReceipt) -> str:
    return ontology_function_digest(
        {
            "ontology_release": receipt.ontology_release.model_dump(mode="json"),
            "profile_ref": receipt.profile_ref,
            "profile_digest": receipt.profile_digest,
            "request_id": receipt.request_id,
            "plan_digest": receipt.plan_digest,
            "function_invocation": receipt.function_invocation.model_dump(mode="json"),
            "truncated": receipt.truncated,
            "truncation_reason": (
                receipt.truncation_reason.value if receipt.truncation_reason is not None else None
            ),
            "execution_authority": False,
        }
    )


def _stable_envelope(envelope: ReadEvidenceEnvelope) -> dict[str, object]:
    return {
        "status": envelope.status.value,
        "authority": envelope.authority,
        "resource_ref": envelope.resource_ref,
        "observed_at": _timestamp(envelope.observed_at),
        "freshness": envelope.freshness.value,
        "truncated": envelope.truncated,
        "records": [_stable_record(item) for item in envelope.records],
        "evidence_refs": sorted(envelope.evidence_refs),
        "limitations": sorted(item.value for item in envelope.limitations),
        "truncation_reason": (
            envelope.truncation_reason.value if envelope.truncation_reason is not None else None
        ),
    }


def _stable_record(record: ReadEvidenceRecord) -> dict[str, object]:
    return {
        "occurred_at": _timestamp(record.occurred_at),
        "status": record.status,
        "state": record.state,
        "details": [list(item) for item in record.details],
    }


def _malformed_existing() -> ResourceStateExtraction:
    return ResourceStateExtraction(None, (ShadowComparisonReason.EXISTING_EVIDENCE_MALFORMED,))


def _malformed_semantic() -> ResourceStateExtraction:
    return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_EVIDENCE_MALFORMED,))


def _normalize_token(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError("resource-state comparison token MUST be non-empty")
    return normalized


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "NormalizedResourceStateObservation",
    "ResourceStateExtraction",
    "existing_input_digest",
    "extract_existing_state",
    "extract_semantic_state",
    "invocation_digest",
    "observation_mismatches",
    "semantic_lineage_matches",
]
