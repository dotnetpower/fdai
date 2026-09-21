"""Fail-closed evidence decoding for Operator PostgreSQL inventory projections."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.runtime_call import (
    RUNTIME_CALL_MAPPING_ID,
    RUNTIME_CALL_MAPPING_REVISION,
    RUNTIME_CALL_SOURCE_SCHEMA_DIGEST,
    RUNTIME_CALL_SOURCE_SCHEMA_VERSION,
    RUNTIME_CALL_VERIFICATION_METHOD,
)

from fdai_operator_service.families.operations.contracts import (
    AKS_DIAGNOSTIC_STATUSES,
    InventoryAksDiagnosticReceipt,
    InventoryProjectionSourceState,
    InventoryProviderScopeCoverage,
    InventoryProviderTypeCount,
    InventoryRelationshipCoverage,
    InventoryRelationshipDropClassification,
    InventoryRelationshipEvidence,
)
from fdai_operator_service.postgres_family_models import PostgresFamilyStoreUnavailableError

_LOGGER = logging.getLogger(__name__)
_RFC3339_TIMESTAMP: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)
_MAX_PROJECTION_SOURCE_STATES: Final = 40
_AKS_DIAGNOSTIC_RECEIPT_KEYS: Final = frozenset(
    {
        "audit_correlation_id",
        "cause_claim_supported",
        "complete",
        "conflicts",
        "cutoff",
        "evidence_gaps",
        "evidence_refs",
        "execution_authority",
        "method_version",
        "ontology_release",
        "owner_agent",
        "principal_class",
        "producer_version",
        "purpose",
        "schema_version",
        "signals",
        "source_cutoffs",
        "source_revisions",
        "status",
        "synthetic",
        "target_resource_id",
        "target_resource_version",
        "target_uid",
    }
)
PostgresFamilyStoreUnavailable = PostgresFamilyStoreUnavailableError


def instance_relationship_evidence(
    value: object,
    *,
    inventory_generation: str,
) -> InventoryRelationshipEvidence | None:
    """Decode one provider relationship receipt or its observation fallback."""
    if value is None:
        return None
    properties = _json_object(value, label="inventory instance relationship properties")
    raw_evidence = properties.get("provider_relationship_evidence")
    if raw_evidence is None:
        return instance_observation_evidence(
            properties.get("link_observation_metadata"),
            inventory_generation=inventory_generation,
        )
    evidence = _json_object(
        raw_evidence,
        label="inventory instance provider relationship evidence",
    )
    expected_keys = {
        "mapping_id",
        "mapping_revision",
        "mapping_receipt_ref",
        "source_identity",
        "source_property_path",
        "source_schema_version",
        "source_schema_digest",
        "evidence_method",
        "freshness_ceiling_seconds",
        "observation_receipt_ref",
    }
    if set(evidence) != expected_keys:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance provider relationship evidence shape is malformed"
        )

    def required_text(key: str) -> str:
        raw = evidence.get(key)
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 512:
            raise PostgresFamilyStoreUnavailableError(
                f"inventory instance relationship evidence {key} is malformed"
            )
        return raw.strip()

    freshness = evidence.get("freshness_ceiling_seconds")
    if (
        isinstance(freshness, bool)
        or not isinstance(freshness, int)
        or not 1 <= freshness <= 31_536_000
    ):
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance relationship evidence freshness is malformed"
        )
    for key in (
        "mapping_revision",
        "mapping_receipt_ref",
        "source_schema_version",
    ):
        required_text(key)
    for key in ("source_schema_digest", "observation_receipt_ref"):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", required_text(key)) is None:
            raise PostgresFamilyStoreUnavailableError(
                f"inventory instance relationship evidence {key} is malformed"
            )
    evidence_method = required_text("evidence_method")
    if evidence_method != "deterministic-cross-check":
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance relationship evidence method is not trusted"
        )
    try:
        return InventoryRelationshipEvidence(
            source_identity=required_text("source_identity"),
            source_property_path=required_text("source_property_path"),
            mapping_id=required_text("mapping_id"),
            evidence_method=evidence_method,
            freshness_ceiling_seconds=freshness,
        )
    except ValueError as exc:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance relationship evidence is malformed"
        ) from exc


def instance_observation_evidence(
    value: object,
    *,
    inventory_generation: str,
) -> InventoryRelationshipEvidence | None:
    """Decode one independently verified runtime-call observation receipt."""
    if value is None:
        return None
    metadata = _json_object(value, label="inventory instance observation metadata")
    state_fact = _json_object(
        metadata.get("state_fact"),
        label="inventory instance observation state fact",
    )

    def required_text(source: Mapping[str, object], key: str) -> str:
        raw = source.get(key)
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 512:
            raise PostgresFamilyStoreUnavailableError(
                f"inventory instance observation evidence {key} is malformed"
            )
        return raw.strip()

    def required_timestamp(source: Mapping[str, object], key: str) -> datetime:
        raw = required_text(source, key)
        if _RFC3339_TIMESTAMP.fullmatch(raw) is None:
            raise PostgresFamilyStoreUnavailableError(
                f"inventory instance observation evidence {key} is malformed"
            )
        try:
            result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PostgresFamilyStoreUnavailableError(
                f"inventory instance observation evidence {key} is malformed"
            ) from exc
        if result.tzinfo is None or result.utcoffset() is None:
            raise PostgresFamilyStoreUnavailableError(
                f"inventory instance observation evidence {key} is malformed"
            )
        return result

    expected_metadata_keys = {
        "state_fact",
        "verification_method",
        "verified",
        "verifier_identity",
        "verifier_revision",
        "verification_receipt_ref",
        "inventory_generation",
        "mapping_id",
        "mapping_revision",
        "source_schema_version",
        "source_schema_digest",
    }
    expected_state_keys = {
        "authority",
        "completeness",
        "conflicts",
        "effective_at",
        "evidence_cutoff",
        "evidence_refs",
        "freshness_ceiling_seconds",
        "lane",
        "recorded_at",
        "source_identity",
        "source_revision",
        "synthetic",
    }
    if set(metadata) != expected_metadata_keys or set(state_fact) != expected_state_keys:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence shape is malformed"
        )
    if (
        metadata.get("verified") is not True
        or metadata.get("mapping_id") != RUNTIME_CALL_MAPPING_ID
        or metadata.get("mapping_revision") != RUNTIME_CALL_MAPPING_REVISION
        or metadata.get("source_schema_version") != RUNTIME_CALL_SOURCE_SCHEMA_VERSION
        or metadata.get("source_schema_digest") != RUNTIME_CALL_SOURCE_SCHEMA_DIGEST
        or metadata.get("inventory_generation") != inventory_generation
        or state_fact.get("lane") != "observed"
        or state_fact.get("authority") != "telemetry"
        or state_fact.get("synthetic") is not False
        or state_fact.get("conflicts") != []
    ):
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence is not verified"
        )
    freshness = state_fact.get("freshness_ceiling_seconds")
    completeness = state_fact.get("completeness")
    if (
        isinstance(freshness, bool)
        or not isinstance(freshness, int)
        or not 1 <= freshness <= 31_536_000
    ):
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence freshness is malformed"
        )
    if isinstance(completeness, bool) or completeness != 1.0:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence completeness is malformed"
        )
    evidence_refs = state_fact.get("evidence_refs")
    if (
        not isinstance(evidence_refs, list)
        or len(evidence_refs) != 2
        or any(not isinstance(item, str) or not item.strip() for item in evidence_refs)
        or len(set(evidence_refs)) != 2
    ):
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence references are malformed"
        )
    verifier_identity = required_text(metadata, "verifier_identity")
    source_identity = required_text(state_fact, "source_identity")
    required_text(metadata, "verifier_revision")
    required_text(state_fact, "source_revision")
    if verifier_identity.casefold() == source_identity.casefold():
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence verifier is not independent"
        )
    for key in ("verification_receipt_ref", "source_schema_digest"):
        digest = required_text(metadata, key)
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise PostgresFamilyStoreUnavailableError(
                "inventory instance observation evidence digest is malformed"
            )
    verification_method = required_text(metadata, "verification_method")
    if verification_method != RUNTIME_CALL_VERIFICATION_METHOD:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence method is not trusted"
        )
    effective_at = required_timestamp(state_fact, "effective_at")
    cutoff = required_timestamp(state_fact, "evidence_cutoff")
    recorded_at = required_timestamp(state_fact, "recorded_at")
    if not effective_at <= cutoff <= recorded_at:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence timestamps are inconsistent"
        )
    try:
        return InventoryRelationshipEvidence(
            source_identity=source_identity,
            source_property_path="caller_resource_ids,target_resource_ids",
            mapping_id=required_text(metadata, "mapping_id"),
            evidence_method=verification_method,
            freshness_ceiling_seconds=freshness,
            evidence_kind="observation",
            evidence_cutoff=cutoff,
        )
    except ValueError as exc:
        raise PostgresFamilyStoreUnavailableError(
            "inventory instance observation evidence is malformed"
        ) from exc


def aks_diagnostic_receipt(
    row: Mapping[str, object],
    *,
    expected_key_prefix: str,
    expected_resource_id: str,
) -> InventoryAksDiagnosticReceipt:
    """Decode one content-addressed no-authority AKS diagnostic receipt."""
    key = row.get("key")
    if (
        not isinstance(key, str)
        or re.fullmatch(
            re.escape(expected_key_prefix) + r"\d{8}T\d{12}Z:[a-f0-9]{64}",
            key,
        )
        is None
    ):
        raise PostgresFamilyStoreUnavailable("AKS diagnostic receipt key is malformed")
    envelope = _json_object(row.get("value"), label="AKS diagnostic receipt envelope")
    if set(envelope) != {"record_type", "record_digest", "receipt"}:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic receipt envelope is malformed")
    receipt = _json_object(envelope.get("receipt"), label="AKS diagnostic receipt")
    record_digest = envelope.get("record_digest")
    if (
        envelope.get("record_type") != "aks_diagnostic_evidence_receipt"
        or not isinstance(record_digest, str)
        or re.fullmatch(r"sha256:[a-f0-9]{64}", record_digest) is None
        or record_digest != content_digest(receipt)
        or set(receipt) != _AKS_DIAGNOSTIC_RECEIPT_KEYS
        or receipt.get("schema_version") != "1.0.0"
        or receipt.get("owner_agent") != "Forseti"
        or receipt.get("purpose") != "operations-review"
        or receipt.get("synthetic") is not False
        or receipt.get("cause_claim_supported") is not False
        or receipt.get("execution_authority") is not False
        or receipt.get("target_resource_id") != expected_resource_id
    ):
        raise PostgresFamilyStoreUnavailable("AKS diagnostic receipt integrity is malformed")
    source_cutoffs = _aks_diagnostic_source_cutoffs(receipt.get("source_cutoffs"))
    source_revisions = _aks_diagnostic_source_revisions(receipt.get("source_revisions"))
    status = receipt.get("status")
    if not isinstance(status, str) or status not in AKS_DIAGNOSTIC_STATUSES:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic status is malformed")
    cutoff = _receipt_timestamp(receipt.get("cutoff"), label="cutoff")
    target_uid = _receipt_text(receipt, "target_uid")
    target_resource_version = _receipt_text(receipt, "target_resource_version")
    ontology_release = _receipt_text(receipt, "ontology_release")
    identity = {
        "target_resource_id": expected_resource_id,
        "target_uid": target_uid,
        "target_resource_version": target_resource_version,
        "ontology_release": ontology_release,
        "cutoff": receipt.get("cutoff"),
        "source_cutoffs": dict(
            sorted(_json_object(receipt.get("source_cutoffs"), label="cutoffs").items())
        ),
        "source_revisions": dict(sorted(source_revisions.items())),
    }
    expected_key = (
        expected_key_prefix
        + cutoff.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        + ":"
        + content_digest(identity)[7:]
    )
    if key != expected_key:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic receipt key identity is malformed")
    try:
        return InventoryAksDiagnosticReceipt(
            principal_class=_receipt_text(receipt, "principal_class"),
            producer_version=_receipt_text(receipt, "producer_version"),
            method_version=_receipt_text(receipt, "method_version"),
            target_resource_id=expected_resource_id,
            target_uid=target_uid,
            target_resource_version=target_resource_version,
            ontology_release=ontology_release,
            cutoff=cutoff,
            source_cutoffs=source_cutoffs,
            source_revisions=source_revisions,
            status=status,
            signals=_receipt_text_sequence(receipt.get("signals"), label="signals", maximum=16),
            complete=_receipt_boolean(receipt, "complete"),
            evidence_gaps=_receipt_text_sequence(
                receipt.get("evidence_gaps"),
                label="evidence_gaps",
                maximum=32,
            ),
            conflicts=_receipt_text_sequence(
                receipt.get("conflicts"),
                label="conflicts",
                maximum=32,
            ),
            evidence_refs=_receipt_text_sequence(
                receipt.get("evidence_refs"),
                label="evidence_refs",
                maximum=32,
                item_maximum=512,
            ),
            audit_correlation_id=_receipt_text(receipt, "audit_correlation_id"),
            cause_claim_supported=False,
            execution_authority=False,
        )
    except ValueError as exc:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic receipt fields are malformed") from exc


def _aks_diagnostic_source_cutoffs(value: object) -> dict[str, datetime]:
    raw = _json_object(value, label="AKS diagnostic source cutoffs")
    if not raw or len(raw) > 16:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic source cutoffs are malformed")
    return {
        _receipt_mapping_key(key): _receipt_timestamp(item, label=f"source cutoff {key}")
        for key, item in raw.items()
    }


def _aks_diagnostic_source_revisions(value: object) -> dict[str, str]:
    raw = _json_object(value, label="AKS diagnostic source revisions")
    if not raw or len(raw) > 16:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic source revisions are malformed")
    revisions: dict[str, str] = {}
    for key, item in raw.items():
        bounded_key = _receipt_mapping_key(key)
        if not isinstance(item, str) or not item.strip() or len(item) > 256:
            raise PostgresFamilyStoreUnavailable("AKS diagnostic source revision is malformed")
        revisions[bounded_key] = item
    return revisions


def _receipt_mapping_key(value: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", value) is None:
        raise PostgresFamilyStoreUnavailable("AKS diagnostic source identity is malformed")
    return value


def _receipt_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise PostgresFamilyStoreUnavailable(f"AKS diagnostic {label} is malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PostgresFamilyStoreUnavailable(f"AKS diagnostic {label} is malformed") from exc
    if parsed.tzinfo is None:
        raise PostgresFamilyStoreUnavailable(f"AKS diagnostic {label} is timezone-naive")
    return parsed


def _receipt_text(
    receipt: Mapping[str, object],
    field: str,
    *,
    maximum: int = 1_024,
) -> str:
    value = receipt.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PostgresFamilyStoreUnavailable(f"AKS diagnostic {field} is malformed")
    return value


def _receipt_boolean(receipt: Mapping[str, object], field: str) -> bool:
    value = receipt.get(field)
    if not isinstance(value, bool):
        raise PostgresFamilyStoreUnavailable(f"AKS diagnostic {field} is malformed")
    return value


def _receipt_text_sequence(
    value: object,
    *,
    label: str,
    maximum: int,
    item_maximum: int = 128,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > item_maximum
            for item in value
        )
    ):
        raise PostgresFamilyStoreUnavailable(f"AKS diagnostic {label} is malformed")
    return tuple(value)


def relationship_drop_classifications(
    value: object,
) -> tuple[InventoryRelationshipDropClassification, ...]:
    """Decode bounded mapping-specific coverage without provider resource identities."""
    if not isinstance(value, list) or len(value) > 256:
        raise PostgresFamilyStoreUnavailable(
            "active inventory relationship classifications are malformed"
        )
    allowed_unavailable_reasons = {
        "authorization_child_scope_unmodeled",
        "reference_not_observed",
        "source_outside_active_generation",
        "target_outside_active_generation",
        "target_provider_type_unmodeled",
        "unclassified",
    }
    classifications: list[InventoryRelationshipDropClassification] = []
    for raw_item in value:
        item = _json_object(raw_item, label="active inventory relationship classification")
        fields: dict[str, str] = {}
        for name, maximum in (
            ("reason", 128),
            ("mapping_id", 256),
            ("source_property_path", 512),
            ("source_provider_type", 512),
            ("target_provider_type", 512),
            ("unavailable_reason", 128),
        ):
            raw_field = item.get(name)
            if not isinstance(raw_field, str) or not raw_field.strip() or len(raw_field) > maximum:
                raise PostgresFamilyStoreUnavailable(
                    "active inventory relationship classification is malformed"
                )
            fields[name] = raw_field
        raw_count = item.get("count")
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or not 1 <= raw_count <= (2**31) - 1
            or fields["unavailable_reason"] not in allowed_unavailable_reasons
        ):
            raise PostgresFamilyStoreUnavailable(
                "active inventory relationship classification is malformed"
            )
        classifications.append(
            InventoryRelationshipDropClassification(
                reason=fields["reason"],
                mapping_id=fields["mapping_id"],
                source_property_path=fields["source_property_path"],
                source_provider_type=fields["source_provider_type"],
                target_provider_type=fields["target_provider_type"],
                unavailable_reason=fields["unavailable_reason"],
                count=raw_count,
            )
        )
    identities = [
        (
            item.reason,
            item.mapping_id,
            item.source_property_path,
            item.source_provider_type,
            item.target_provider_type,
            item.unavailable_reason,
        )
        for item in classifications
    ]
    if len(set(identities)) != len(identities):
        raise PostgresFamilyStoreUnavailable(
            "active inventory relationship classifications are duplicated"
        )
    return tuple(
        sorted(
            classifications,
            key=lambda item: (
                item.reason,
                item.mapping_id,
                item.source_property_path,
                item.source_provider_type,
                item.target_provider_type,
                item.unavailable_reason,
            ),
        )
    )


def projection_source_states(value: object) -> tuple[InventoryProjectionSourceState, ...]:
    """Decode only reviewed no-authority source availability records."""
    if not isinstance(value, list) or len(value) > _MAX_PROJECTION_SOURCE_STATES:
        raise PostgresFamilyStoreUnavailable("active inventory source states are malformed")
    allowed_sources = {
        "azure_activity_log",
        "azure_model_serving_metrics",
        "azure_resource_health",
        "azure_static_web_app_environment",
        "kubernetes_runtime_inventory",
        "runtime_call_graph",
        "postgres_role_evidence",
    }
    states: list[InventoryProjectionSourceState] = []
    for raw_item in value:
        item = _json_object(raw_item, label="active inventory source state")
        source = item.get("source")
        status = item.get("status")
        observed_at = item.get("observed_at")
        reason = item.get("reason")
        scope_digest = item.get("scope_digest")
        if (
            not isinstance(source, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", source) is None
            or status not in {"available", "unavailable"}
            or (
                scope_digest is not None
                and (
                    not isinstance(scope_digest, str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", scope_digest) is None
                )
            )
        ):
            raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
        if source not in allowed_sources:
            _LOGGER.warning(
                "ignored_unreviewed_inventory_source_state",
                extra={"source": source},
            )
            continue
        if status == "available":
            if reason is not None or observed_at is None:
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            if not isinstance(observed_at, str):
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            try:
                parsed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PostgresFamilyStoreUnavailable(
                    "active inventory source state is malformed"
                ) from exc
            if parsed_at.tzinfo is None:
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            parsed_reason = None
        else:
            if (
                observed_at is not None
                or not isinstance(reason, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason) is None
            ):
                raise PostgresFamilyStoreUnavailable("active inventory source state is malformed")
            parsed_at = None
            parsed_reason = reason
        states.append(
            InventoryProjectionSourceState(
                source=source,
                status=status,
                observed_at=parsed_at,
                reason=parsed_reason,
                scope_digest=scope_digest,
            )
        )
    if len({(state.source, state.scope_digest) for state in states}) != len(states):
        raise PostgresFamilyStoreUnavailable("active inventory source states are duplicated")
    return tuple(sorted(states, key=lambda state: (state.source, state.scope_digest or "")))


def combined_projection_source_state_metadata(
    metadata: Mapping[str, object],
) -> list[object]:
    """Merge baseline and forward-compatible source records for upgraded readers."""
    baseline = metadata.get("derived_source_states", [])
    additive = metadata.get("additive_source_states", [])
    if not isinstance(baseline, list) or not isinstance(additive, list):
        raise PostgresFamilyStoreUnavailable("active inventory source states are malformed")
    return [*baseline, *additive]


def relationship_coverage(value: object) -> InventoryRelationshipCoverage | None:
    """Decode exact candidate-relationship coverage from an active snapshot."""
    if value is None:
        return None
    item = _json_object(value, label="active inventory relationship coverage")
    counts: dict[str, int] = {}
    for name in ("materialized", "reviewed_unavailable", "unclassified", "total_candidates"):
        raw_count = item.get(name)
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
            raise PostgresFamilyStoreUnavailable(
                "active inventory relationship coverage is malformed"
            )
        counts[name] = raw_count
    if counts["total_candidates"] != (
        counts["materialized"] + counts["reviewed_unavailable"] + counts["unclassified"]
    ):
        raise PostgresFamilyStoreUnavailable(
            "active inventory relationship coverage sums are inconsistent"
        )
    complete = item.get("complete")
    if not isinstance(complete, bool) or (complete and counts["unclassified"] != 0):
        raise PostgresFamilyStoreUnavailable(
            "active inventory relationship coverage complete flag is inconsistent"
        )
    return InventoryRelationshipCoverage(
        materialized=counts["materialized"],
        reviewed_unavailable=counts["reviewed_unavailable"],
        unclassified=counts["unclassified"],
        total_candidates=counts["total_candidates"],
        complete=complete,
    )


def provider_scope_coverage(value: object) -> InventoryProviderScopeCoverage | None:
    """Decode bounded provider-native type coverage from an active snapshot."""
    if value is None:
        return None
    item = _json_object(value, label="active inventory provider scope coverage")
    if item.get("schema_version") != "1.1.0":
        raise PostgresFamilyStoreUnavailable(
            "active inventory provider scope coverage schema is unsupported"
        )
    capture_method = item.get("capture_method")
    if (
        not isinstance(capture_method, str)
        or not capture_method.strip()
        or len(capture_method) > 128
    ):
        raise PostgresFamilyStoreUnavailable(
            "active inventory provider scope coverage is malformed"
        )
    counts: dict[str, int] = {}
    for name in (
        "provider_object_count",
        "mapped_provider_object_count",
        "unmapped_provider_object_count",
        "materialized_unmapped_provider_object_count",
        "provider_type_count",
        "unmapped_provider_type_count",
    ):
        raw_count = item.get(name)
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
            raise PostgresFamilyStoreUnavailable(
                "active inventory provider scope coverage is malformed"
            )
        counts[name] = raw_count
    raw_types = item.get("unmapped_provider_types")
    if not isinstance(raw_types, list) or len(raw_types) > 10_000:
        raise PostgresFamilyStoreUnavailable(
            "active inventory provider scope coverage is malformed"
        )
    provider_types: list[InventoryProviderTypeCount] = []
    for raw_type in raw_types:
        type_count = _json_object(raw_type, label="active inventory provider type coverage")
        provider_type = type_count.get("provider_type")
        count = type_count.get("count")
        if (
            not isinstance(provider_type, str)
            or not provider_type.strip()
            or len(provider_type) > 512
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
        ):
            raise PostgresFamilyStoreUnavailable(
                "active inventory provider type coverage is malformed"
            )
        provider_types.append(InventoryProviderTypeCount(provider_type=provider_type, count=count))
    type_names = tuple(entry.provider_type for entry in provider_types)
    identity_complete = item.get("provider_identity_complete")
    unmapped_objects = counts["unmapped_provider_object_count"]
    materialized_objects = counts["materialized_unmapped_provider_object_count"]
    if (
        counts["provider_object_count"] != counts["mapped_provider_object_count"] + unmapped_objects
        or counts["provider_type_count"] > counts["provider_object_count"]
        or (counts["provider_object_count"] == 0) != (counts["provider_type_count"] == 0)
        or counts["unmapped_provider_type_count"] != len(provider_types)
        or len(provider_types) > counts["provider_type_count"]
        or sum(entry.count for entry in provider_types) != unmapped_objects
        or type_names != tuple(sorted(set(type_names)))
        or materialized_objects not in {0, unmapped_objects}
        or not isinstance(identity_complete, bool)
        or identity_complete != (materialized_objects == unmapped_objects)
    ):
        raise PostgresFamilyStoreUnavailable(
            "active inventory provider scope coverage is inconsistent"
        )
    return InventoryProviderScopeCoverage(
        capture_method=capture_method,
        provider_object_count=counts["provider_object_count"],
        mapped_provider_object_count=counts["mapped_provider_object_count"],
        unmapped_provider_object_count=unmapped_objects,
        materialized_unmapped_provider_object_count=materialized_objects,
        provider_identity_complete=identity_complete,
        provider_type_count=counts["provider_type_count"],
        unmapped_provider_types=tuple(provider_types),
    )


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PostgresFamilyStoreUnavailableError(f"{label} is not a JSON object")
    return {str(key): item for key, item in value.items()}
