"""Canonical evidence extraction for resource-state shadow comparison."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_profiles import QueryProfile
from fdai.core.ontology_platform.semantic_plans import (
    SemanticOperationClass,
    VerifiedSemanticPlan,
)
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

ResourceIdentityCanonicalizer = Callable[[str], str]

_RESOURCE_STATE_MAX_AGE_SECONDS = 300
_MAX_BOUNDED_INPUT_BYTES = 65_536
_MAX_PROPERTY_BYTES = 32_768
_MAX_EVIDENCE_REFS = 64
_MAX_REF_BYTES = 512
_NORMALIZED_STATES = frozenset(
    {
        "running",
        "starting",
        "stopping",
        "stopped",
        "deallocating",
        "deallocated",
        "restarting",
        "unknown",
    }
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


def extract_existing_state(
    result: ReadInvestigationResult,
    *,
    trusted_cutoff: datetime,
    identity_canonicalizer: ResourceIdentityCanonicalizer | None = None,
) -> ResourceStateExtraction:
    """Extract one exact state fact from the authoritative existing result."""

    try:
        return _extract_existing_state(
            result,
            trusted_cutoff=trusted_cutoff,
            identity_canonicalizer=identity_canonicalizer,
        )
    except Exception:  # noqa: BLE001 - untrusted evidence must close as a receipt
        return _malformed_existing()


def _extract_existing_state(
    result: ReadInvestigationResult,
    *,
    trusted_cutoff: datetime,
    identity_canonicalizer: ResourceIdentityCanonicalizer | None,
) -> ResourceStateExtraction:
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
    if envelope.limitations:
        return ResourceStateExtraction(
            None, (ShadowComparisonReason.EXISTING_EVIDENCE_UNAVAILABLE,)
        )
    if envelope.freshness is EvidenceFreshness.STALE:
        return ResourceStateExtraction(None, (ShadowComparisonReason.EXISTING_OBSERVATION_STALE,))
    state = record.state
    if state is None:  # pragma: no cover - filtered by state_records
        return _malformed_existing()
    cutoff = _utc(trusted_cutoff)
    observed_at = _utc(record.occurred_at)
    envelope_observed_at = _utc(envelope.observed_at)
    if (
        observed_at > cutoff
        or envelope_observed_at > cutoff
        or observed_at > envelope_observed_at
        or (cutoff - observed_at).total_seconds() > _RESOURCE_STATE_MAX_AGE_SECONDS
        or (cutoff - envelope_observed_at).total_seconds() > _RESOURCE_STATE_MAX_AGE_SECONDS
    ):
        return ResourceStateExtraction(None, (ShadowComparisonReason.EXISTING_OBSERVATION_STALE,))
    resolved_identity = _canonical_identity(
        result.resolution.resource.resource_ref,
        identity_canonicalizer,
    )
    evidence_identity = _canonical_identity(envelope.resource_ref, identity_canonicalizer)
    if resolved_identity != evidence_identity:
        return _malformed_existing()
    evidence_refs = _bounded_evidence_refs(envelope.evidence_refs)
    return ResourceStateExtraction(
        NormalizedResourceStateObservation(
            resource_identity=resolved_identity,
            state=_normalize_state(state),
            observed_at=observed_at,
            evidence_refs=evidence_refs,
        ),
        (),
    )


def extract_semantic_state(
    result: SecuredObjectSetQueryResult,
    *,
    trusted_cutoff: datetime,
    identity_canonicalizer: ResourceIdentityCanonicalizer | None = None,
) -> ResourceStateExtraction:
    """Extract one fresh complete observed state fact from a secured ObjectSet."""

    try:
        return _extract_semantic_state(
            result,
            trusted_cutoff=trusted_cutoff,
            identity_canonicalizer=identity_canonicalizer,
        )
    except Exception:  # noqa: BLE001 - untrusted evidence must close as a receipt
        return _malformed_semantic()


def _extract_semantic_state(
    result: SecuredObjectSetQueryResult,
    *,
    trusted_cutoff: datetime,
    identity_canonicalizer: ResourceIdentityCanonicalizer | None,
) -> ResourceStateExtraction:
    graph = result.materialization.graph
    if graph.truncated or result.receipt.truncated or result.materialization.truncated:
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_RESULT_TRUNCATED,))
    if (
        not result.receipt.complete
        or len(graph.objects) != 1
        or graph.links
        or any(value != 0 for value in result.receipt.redactions.model_dump().values())
    ):
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_RESULT_UNAVAILABLE,))
    item = graph.objects[0]
    _bounded_json(item.properties, max_bytes=_MAX_PROPERTY_BYTES)
    if item.object_type != "Resource":
        return _malformed_semantic()
    raw_identity = item.properties.get("id")
    raw_provider_properties = item.properties.get("properties")
    if not isinstance(raw_identity, str) or not isinstance(raw_provider_properties, Mapping):
        return _malformed_semantic()
    identity = _canonical_identity(item.id, identity_canonicalizer)
    if identity != _canonical_identity(raw_identity, identity_canonicalizer):
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
    cutoff = _utc(trusted_cutoff)
    if cutoff != _utc(result.receipt.observation_cutoff):
        return _malformed_semantic()
    observed_at = _utc(metadata.effective_at)
    evidence_cutoff = _utc(metadata.evidence_cutoff)
    recorded_at = _utc(metadata.recorded_at)
    freshness_ceiling = min(
        _RESOURCE_STATE_MAX_AGE_SECONDS,
        metadata.freshness_ceiling_seconds,
    )
    if (
        observed_at > cutoff
        or evidence_cutoff > cutoff
        or recorded_at > cutoff
        or (cutoff - observed_at).total_seconds() > freshness_ceiling
        or (cutoff - evidence_cutoff).total_seconds() > _RESOURCE_STATE_MAX_AGE_SECONDS
    ):
        return ResourceStateExtraction(None, (ShadowComparisonReason.SEMANTIC_OBSERVATION_STALE,))
    return ResourceStateExtraction(
        NormalizedResourceStateObservation(
            resource_identity=identity,
            state=_normalize_state(raw_state),
            observed_at=observed_at,
            evidence_refs=_bounded_evidence_refs(metadata.evidence_refs),
        ),
        (),
    )


def semantic_lineage_matches(
    result: SecuredObjectSetQueryResult,
    receipt: SemanticQueryReceipt,
    *,
    profile: QueryProfile,
    plan: VerifiedSemanticPlan,
) -> bool:
    """Reverify exact reviewed profile, plan, invocation, and result lineage."""

    try:
        _bounded_json(profile.model_dump(mode="json"), max_bytes=_MAX_BOUNDED_INPUT_BYTES)
        _bounded_json(plan.model_dump(mode="json"), max_bytes=_MAX_BOUNDED_INPUT_BYTES)
        _bounded_json(receipt.model_dump(mode="json"), max_bytes=_MAX_BOUNDED_INPUT_BYTES)
        _bounded_evidence_refs(receipt.function_invocation.evidence_refs)
        QueryProfile.model_validate(profile.model_dump(mode="json"))
        VerifiedSemanticPlan.model_validate(plan.model_dump(mode="json"))
    except (TypeError, ValueError):
        return False
    if not _semantic_input_is_bounded(result):
        return False
    expected_arguments = {"object_set": profile.object_set_template.model_dump(mode="json")}
    expected_output = ontology_function_digest(result.model_dump(mode="json"))
    invocation = receipt.function_invocation
    return (
        plan.operation_class is SemanticOperationClass.QUERY
        and profile.function_ref == plan.target_ref == invocation.function_ref
        and profile.function_type.name == profile.function_ref.name
        and profile.function_type.version == profile.function_ref.version
        and profile.purpose == result.receipt.purpose
        and profile.object_set_template == result.materialization.definition
        and profile.profile_ref == receipt.profile_ref
        and profile.profile_digest == receipt.profile_digest
        and plan.arguments == expected_arguments
        and plan.plan_digest == receipt.plan_digest
        and plan.ontology_release_digest == receipt.ontology_release.digest
        and receipt.ontology_release == result.receipt.ontology_release
        and invocation.purposes == (profile.purpose,)
        and invocation.input_digest == ontology_function_digest(expected_arguments)
        and receipt.request_id == canonical_semantic_request_id(receipt, profile, plan)
        and receipt.truncated == result.receipt.truncated
        and receipt.truncation_reason == result.receipt.truncation_reason
        and invocation.output_digest == expected_output
        and receipt.receipt_digest == _semantic_receipt_digest(receipt)
    )


def canonical_semantic_request_id(
    receipt: SemanticQueryReceipt,
    profile: QueryProfile,
    plan: VerifiedSemanticPlan,
) -> str:
    """Return the request identity sealed by semantic query execution."""

    identity = ontology_function_digest(
        {
            "ontology_release": receipt.ontology_release.model_dump(mode="json"),
            "profile_ref": profile.profile_ref,
            "profile_digest": profile.profile_digest,
            "plan_digest": plan.plan_digest,
            "function_request_id": receipt.function_invocation.request_id,
        }
    ).removeprefix("sha256:")
    return f"semantic-query-request:{identity}"


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

    payload = {
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
    _bounded_json(payload, max_bytes=_MAX_BOUNDED_INPUT_BYTES)
    return ontology_function_digest(payload)


def rejected_input_digest(*, source: str) -> str:
    """Return a bounded marker when malformed input cannot be content-hashed safely."""

    return ontology_function_digest({"source": source, "status": "rejected_before_content_hash"})


def invocation_digest(receipt: SemanticQueryReceipt) -> str:
    """Digest stable invocation lineage while excluding attempt timing."""

    invocation = receipt.function_invocation
    payload = {
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
    _bounded_evidence_refs(invocation.evidence_refs)
    _bounded_json(payload, max_bytes=_MAX_BOUNDED_INPUT_BYTES)
    return ontology_function_digest(payload)


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


def _semantic_input_is_bounded(result: SecuredObjectSetQueryResult) -> bool:
    graph = result.materialization.graph
    if len(graph.objects) > 1 or len(graph.links) > 16:
        return False
    try:
        for object_record in graph.objects:
            _bounded_json(object_record.properties, max_bytes=_MAX_PROPERTY_BYTES)
        for link_record in graph.links:
            _bounded_json(link_record.properties, max_bytes=_MAX_PROPERTY_BYTES)
        _bounded_json(result.model_dump(mode="json"), max_bytes=_MAX_BOUNDED_INPUT_BYTES)
    except (TypeError, ValueError):
        return False
    return True


def _bounded_json(value: Any, *, max_bytes: int) -> None:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    if len(encoded) > max_bytes:
        raise ValueError("resource-state shadow input exceeds its encoded byte limit")


def _bounded_evidence_refs(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > _MAX_EVIDENCE_REFS:
        raise ValueError("resource-state shadow evidence refs exceed their count limit")
    normalized = tuple(sorted(values))
    if any(
        not value
        or len(value.encode("utf-8")) > _MAX_REF_BYTES
        or any(ord(char) < 32 for char in value)
        for value in normalized
    ):
        raise ValueError("resource-state shadow evidence ref is malformed")
    return normalized


def _canonical_identity(
    value: str,
    canonicalizer: ResourceIdentityCanonicalizer | None,
) -> str:
    canonical = canonicalizer(value) if canonicalizer is not None else value
    if (
        not isinstance(canonical, str)
        or not canonical
        or len(canonical.encode("utf-8")) > _MAX_REF_BYTES
        or any(ord(char) < 32 for char in canonical)
    ):
        raise ValueError("resource-state comparison identity MUST be a bounded opaque ref")
    return canonical


def _normalize_state(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in _NORMALIZED_STATES:
        raise ValueError("resource-state comparison state is outside the closed vocabulary")
    return normalized


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("resource-state comparison time MUST be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "NormalizedResourceStateObservation",
    "ResourceIdentityCanonicalizer",
    "ResourceStateExtraction",
    "canonical_semantic_request_id",
    "existing_input_digest",
    "extract_existing_state",
    "extract_semantic_state",
    "invocation_digest",
    "observation_mismatches",
    "rejected_input_digest",
    "semantic_lineage_matches",
]
