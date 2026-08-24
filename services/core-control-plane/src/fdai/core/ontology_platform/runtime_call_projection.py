"""Project exact telemetry endpoint identities into authority-free runtime-call links."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyRelease
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

RUNTIME_CALL_LINK_TYPE = "runtime_calls"
RUNTIME_CALL_LINK_TYPE_VERSION = "1.0.0"
RUNTIME_CALL_LINK_TYPE_DECLARATION_DIGEST = (
    "sha256:5d27e75ecb92cdcdfc8e9a5fb9f0e60c0d17ff028299387376b7563f08f51c08"
)
RUNTIME_CALL_MAPPING_ID = "runtime-call-endpoint-identity"
RUNTIME_CALL_MAPPING_REVISION = "1.1.0"
RUNTIME_CALL_SOURCE_SCHEMA_VERSION = "fdai.runtime-call-observation@1.1.0"
_RUNTIME_CALL_SOURCE_SCHEMA = (
    "observation_id:string;caller_resource_ids:ordered_unique_string_tuple;"
    "target_resource_ids:ordered_unique_string_tuple;scope_ref:string;"
    "observed_at:aware_datetime;evidence_cutoff:aware_datetime;"
    "recorded_at:aware_datetime;freshness_ceiling_seconds:bounded_positive_integer;"
    "source_identity:string;source_revision:string;evidence_ref:string;authentication_ref:string;"
    "execution_authority:false;mutation_authority:false"
)
RUNTIME_CALL_SOURCE_SCHEMA_DIGEST = (
    "sha256:" + hashlib.sha256(_RUNTIME_CALL_SOURCE_SCHEMA.encode("ascii")).hexdigest()
)


def _identity_set_digest(values: Collection[str]) -> str:
    encoded = json.dumps(sorted(set(values)), separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _scope_allows_observation(
    observation: RuntimeCallObservation,
    *,
    principal_scope_ref: str,
    readable_resource_ids: frozenset[str],
) -> bool:
    endpoint_ids = (*observation.caller_resource_ids, *observation.target_resource_ids)
    return observation.scope_ref == principal_scope_ref and all(
        endpoint_id in readable_resource_ids for endpoint_id in endpoint_ids
    )


_MAX_ENDPOINT_CANDIDATES = 8
_MAX_FRESHNESS_CEILING_SECONDS = 31_536_000


class RuntimeCallProjectionReason(StrEnum):
    """Stable terminal reason for one runtime-call projection attempt."""

    PROJECTED = "projected"
    MISSING_CALLER = "missing_caller"
    MISSING_TARGET = "missing_target"
    AMBIGUOUS_CALLER = "ambiguous_caller"
    AMBIGUOUS_TARGET = "ambiguous_target"
    WRONG_SCOPE = "wrong_scope"
    STALE = "stale"
    LINK_TYPE_UNAVAILABLE = "link_type_unavailable"
    LINK_TYPE_MISMATCH = "link_type_mismatch"
    CALLER_NOT_OBSERVED = "caller_not_observed"
    TARGET_NOT_OBSERVED = "target_not_observed"


@dataclass(frozen=True, slots=True)
class RuntimeCallObservation:
    """One telemetry observation carrying exact candidate endpoint identities."""

    observation_id: str
    caller_resource_ids: tuple[str, ...]
    target_resource_ids: tuple[str, ...]
    scope_ref: str
    observed_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int
    source_identity: str
    source_revision: str
    evidence_ref: str
    authentication_ref: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for text_field_name, text_value in (
            ("observation_id", self.observation_id),
            ("scope_ref", self.scope_ref),
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
            ("evidence_ref", self.evidence_ref),
            ("authentication_ref", self.authentication_ref),
        ):
            if not text_value.strip() or len(text_value) > 512:
                raise ValueError(
                    f"RuntimeCallObservation.{text_field_name} MUST be bounded non-empty text"
                )
        if not _is_digest(self.authentication_ref):
            raise ValueError("RuntimeCallObservation.authentication_ref MUST be canonical SHA-256")
        for field_name, values in (
            ("caller_resource_ids", self.caller_resource_ids),
            ("target_resource_ids", self.target_resource_ids),
        ):
            if len(values) > _MAX_ENDPOINT_CANDIDATES:
                raise ValueError(
                    f"RuntimeCallObservation.{field_name} MUST contain at most "
                    f"{_MAX_ENDPOINT_CANDIDATES} candidates"
                )
            if values != tuple(sorted(set(values))):
                raise ValueError(f"RuntimeCallObservation.{field_name} MUST be ordered and unique")
            if any(not value.strip() or len(value) > 512 for value in values):
                raise ValueError(
                    f"RuntimeCallObservation.{field_name} MUST contain bounded identities"
                )
        for timestamp_field_name, timestamp in (
            ("observed_at", self.observed_at),
            ("evidence_cutoff", self.evidence_cutoff),
            ("recorded_at", self.recorded_at),
        ):
            if timestamp.tzinfo is None:
                raise ValueError(
                    f"RuntimeCallObservation.{timestamp_field_name} MUST be timezone-aware"
                )
        if self.observed_at > self.evidence_cutoff:
            raise ValueError("runtime call observed_at MUST NOT exceed evidence_cutoff")
        if self.evidence_cutoff > self.recorded_at:
            raise ValueError("runtime call evidence_cutoff MUST NOT exceed recorded_at")
        if isinstance(self.freshness_ceiling_seconds, bool) or not isinstance(
            self.freshness_ceiling_seconds, int
        ):
            raise ValueError("runtime call freshness ceiling MUST be an integer")
        if not 1 <= self.freshness_ceiling_seconds <= _MAX_FRESHNESS_CEILING_SECONDS:
            raise ValueError(
                "runtime call freshness ceiling MUST be between 1 and "
                f"{_MAX_FRESHNESS_CEILING_SECONDS} seconds"
            )
        if self.execution_authority or self.mutation_authority:
            raise ValueError("runtime call observation MUST NOT carry action authority")


@dataclass(frozen=True, slots=True)
class RuntimeCallProjection:
    """One deterministic edge candidate or fail-closed reason without action authority."""

    reason: RuntimeCallProjectionReason
    edge: LinkRecord | None
    digest: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        projected = self.reason is RuntimeCallProjectionReason.PROJECTED
        if projected != (self.edge is not None):
            raise ValueError("runtime call projected reason MUST match edge presence")
        if self.execution_authority or self.mutation_authority:
            raise ValueError("runtime call projection MUST NOT carry action authority")


def project_runtime_call(
    observation: RuntimeCallObservation,
    *,
    active_resources: Sequence[ResourceRecord],
    readable_resource_ids: Collection[str],
    principal_scope_ref: str,
    ontology_release: OntologyRelease,
    inventory_generation: str,
    evaluation_time: datetime,
    verifier_identity: str,
    verifier_revision: str,
) -> RuntimeCallProjection:
    """Return one verified candidate only for fresh, exact, in-scope endpoints."""

    for field_name, value in (
        ("principal_scope_ref", principal_scope_ref),
        ("inventory_generation", inventory_generation),
        ("verifier_identity", verifier_identity),
        ("verifier_revision", verifier_revision),
    ):
        if not value.strip() or len(value) > 512:
            raise ValueError(f"runtime call {field_name} MUST be bounded non-empty text")
    if evaluation_time.tzinfo is None:
        raise ValueError("runtime call evaluation_time MUST be timezone-aware")
    if evaluation_time < observation.recorded_at:
        raise ValueError("runtime call evaluation_time MUST NOT precede recorded_at")
    if observation.source_identity.strip().casefold() == verifier_identity.strip().casefold():
        raise ValueError("runtime call projection requires an independent verifier")

    readable = frozenset(readable_resource_ids)
    decision_context = {
        "evaluation_time": _timestamp(evaluation_time),
        "inventory_generation": inventory_generation,
        "ontology_release_digest": ontology_release.digest,
        "principal_scope_ref": principal_scope_ref,
        "readable_resource_ids_digest": _identity_set_digest(readable),
        "verifier_identity": verifier_identity,
        "verifier_revision": verifier_revision,
    }
    if not _scope_allows_observation(
        observation,
        principal_scope_ref=principal_scope_ref,
        readable_resource_ids=readable,
    ):
        return _projection(
            observation,
            reason=RuntimeCallProjectionReason.WRONG_SCOPE,
            decision_context=decision_context,
        )

    caller_reason = _endpoint_cardinality_reason(
        observation.caller_resource_ids,
        missing=RuntimeCallProjectionReason.MISSING_CALLER,
        ambiguous=RuntimeCallProjectionReason.AMBIGUOUS_CALLER,
    )
    if caller_reason is not None:
        return _projection(observation, reason=caller_reason, decision_context=decision_context)
    target_reason = _endpoint_cardinality_reason(
        observation.target_resource_ids,
        missing=RuntimeCallProjectionReason.MISSING_TARGET,
        ambiguous=RuntimeCallProjectionReason.AMBIGUOUS_TARGET,
    )
    if target_reason is not None:
        return _projection(observation, reason=target_reason, decision_context=decision_context)

    caller_id = observation.caller_resource_ids[0]
    target_id = observation.target_resource_ids[0]
    age_seconds = (evaluation_time - observation.evidence_cutoff).total_seconds()
    if age_seconds > observation.freshness_ceiling_seconds:
        return _projection(
            observation,
            reason=RuntimeCallProjectionReason.STALE,
            decision_context=decision_context,
        )
    declaration = next(
        (
            item
            for item in ontology_release.declarations
            if item.kind is OntologyDeclarationKind.LINK and item.name == RUNTIME_CALL_LINK_TYPE
        ),
        None,
    )
    if declaration is None:
        return _projection(
            observation,
            reason=RuntimeCallProjectionReason.LINK_TYPE_UNAVAILABLE,
            decision_context=decision_context,
        )
    if (
        str(declaration.version) != RUNTIME_CALL_LINK_TYPE_VERSION
        or declaration.declaration_digest != RUNTIME_CALL_LINK_TYPE_DECLARATION_DIGEST
    ):
        return _projection(
            observation,
            reason=RuntimeCallProjectionReason.LINK_TYPE_MISMATCH,
            decision_context=decision_context,
        )

    resources_by_id: dict[str, ResourceRecord] = {}
    for resource in active_resources:
        if resource.resource_id in resources_by_id:
            raise ValueError("active runtime call resources MUST have unique identities")
        resources_by_id[resource.resource_id] = resource
    caller = resources_by_id.get(caller_id)
    if caller is None:
        return _projection(
            observation,
            reason=RuntimeCallProjectionReason.CALLER_NOT_OBSERVED,
            decision_context=decision_context,
        )
    target = resources_by_id.get(target_id)
    if target is None:
        return _projection(
            observation,
            reason=RuntimeCallProjectionReason.TARGET_NOT_OBSERVED,
            decision_context=decision_context,
        )

    verification_receipt = _verification_receipt(
        observation,
        caller_id=caller_id,
        target_id=target_id,
        inventory_generation=inventory_generation,
        verifier_identity=verifier_identity,
        verifier_revision=verifier_revision,
        ontology_release_digest=ontology_release.digest,
    )
    metadata = LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.TELEMETRY,
            source_identity=observation.source_identity,
            source_revision=observation.source_revision,
            effective_at=observation.observed_at,
            recorded_at=observation.recorded_at,
            evidence_cutoff=observation.evidence_cutoff,
            freshness_ceiling_seconds=observation.freshness_ceiling_seconds,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(observation.evidence_ref, observation.authentication_ref),
        ),
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity=verifier_identity,
        verifier_revision=verifier_revision,
        verification_receipt_ref=verification_receipt,
        inventory_generation=inventory_generation,
        mapping_id=RUNTIME_CALL_MAPPING_ID,
        mapping_revision=RUNTIME_CALL_MAPPING_REVISION,
        source_schema_version=RUNTIME_CALL_SOURCE_SCHEMA_VERSION,
        source_schema_digest=RUNTIME_CALL_SOURCE_SCHEMA_DIGEST,
    )
    edge = LinkRecord(
        from_id=caller.resource_id,
        from_type=caller.type,
        link_type=RUNTIME_CALL_LINK_TYPE,
        to_id=target.resource_id,
        to_type=target.type,
        observation_metadata=metadata,
    )
    return _projection(
        observation,
        reason=RuntimeCallProjectionReason.PROJECTED,
        edge=edge,
        verification_receipt=verification_receipt,
        decision_context=decision_context,
    )


def _endpoint_cardinality_reason(
    values: tuple[str, ...],
    *,
    missing: RuntimeCallProjectionReason,
    ambiguous: RuntimeCallProjectionReason,
) -> RuntimeCallProjectionReason | None:
    if not values:
        return missing
    if len(values) > 1:
        return ambiguous
    return None


def _verification_receipt(
    observation: RuntimeCallObservation,
    *,
    caller_id: str,
    target_id: str,
    inventory_generation: str,
    verifier_identity: str,
    verifier_revision: str,
    ontology_release_digest: str,
) -> str:
    body = {
        **_observation_body(observation),
        "caller_resource_id": caller_id,
        "inventory_generation": inventory_generation,
        "mapping_id": RUNTIME_CALL_MAPPING_ID,
        "mapping_revision": RUNTIME_CALL_MAPPING_REVISION,
        "ontology_release_digest": ontology_release_digest,
        "source_schema_digest": RUNTIME_CALL_SOURCE_SCHEMA_DIGEST,
        "source_schema_version": RUNTIME_CALL_SOURCE_SCHEMA_VERSION,
        "target_resource_id": target_id,
        "verifier_identity": verifier_identity,
        "verifier_revision": verifier_revision,
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
    )


def _projection(
    observation: RuntimeCallObservation,
    *,
    reason: RuntimeCallProjectionReason,
    decision_context: dict[str, str],
    edge: LinkRecord | None = None,
    verification_receipt: str | None = None,
) -> RuntimeCallProjection:
    body = {
        "decision_context": decision_context,
        "observation": _observation_body(observation),
        "reason": reason.value,
        "verification_receipt": verification_receipt,
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
    )
    return RuntimeCallProjection(reason=reason, edge=edge, digest=digest)


def _observation_body(observation: RuntimeCallObservation) -> dict[str, object]:
    return {
        "caller_resource_ids": observation.caller_resource_ids,
        "evidence_cutoff": _timestamp(observation.evidence_cutoff),
        "evidence_ref": observation.evidence_ref,
        "authentication_ref": observation.authentication_ref,
        "freshness_ceiling_seconds": observation.freshness_ceiling_seconds,
        "observation_id": observation.observation_id,
        "observed_at": _timestamp(observation.observed_at),
        "recorded_at": _timestamp(observation.recorded_at),
        "scope_ref": observation.scope_ref,
        "source_identity": observation.source_identity,
        "source_revision": observation.source_revision,
        "target_resource_ids": observation.target_resource_ids,
    }


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "RUNTIME_CALL_LINK_TYPE",
    "RUNTIME_CALL_LINK_TYPE_DECLARATION_DIGEST",
    "RUNTIME_CALL_LINK_TYPE_VERSION",
    "RuntimeCallObservation",
    "RuntimeCallProjection",
    "RuntimeCallProjectionReason",
    "project_runtime_call",
]
