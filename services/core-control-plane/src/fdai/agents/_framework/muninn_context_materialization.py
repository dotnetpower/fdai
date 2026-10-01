"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai.core.case_history import (
    OperationalCaseInput,
)
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictRevision,
)
from fdai.core.operational_learning import (
    pattern_case_from_operational_case,
)
from fdai.core.operational_learning.cohort_retention import (
    cohort_state_key,
    retain_cohort_case,
)
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineage,
)
from fdai.rule_catalog.schema.rule_semantic_feedback import (
    build_feedback_candidate,
    query_failure_evidence_from_mapping,
    query_failure_evidence_to_mapping,
)
from fdai.shared.contracts.models import ResponseOutcome


def _readiness_generated_at(record: Mapping[str, Any]) -> datetime | None:
    raw = record.get("generated_at")
    if not isinstance(raw, str):
        return None
    try:
        generated_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return generated_at if generated_at.tzinfo is not None else None


_MAX_OPERATING_PATTERN_CASES = 100
_MAX_CONVERSATION_PROJECTIONS = 50_000
_CONVERSATION_PROJECTION_RECOVERY_PAGE = 128
_PUBLICATION_OUTBOX_RETAIN = 5_000
# Compaction runs every N published rows (and on maintenance) so a publish costs O(1) amortized.
_PUBLICATION_COMPACTION_INTERVAL = 64
_PUBLICATION_CAS_ATTEMPTS = 8
_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)
_PUBLICATION_MAINTENANCE_PAGE = 16
_PROJECTION_PREFIX = "pantheon/muninn/conversation-projections"
_OPERATIONAL_OUTBOX_PREFIX = "pantheon/muninn/operational-outbox"
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0
_MAX_CONTEXT_FETCH_SAMPLES = 512
_MAX_CONTEXT_UNAVAILABLE_FACTS = 128
_PROTECTED_CONVERSATION_BUCKETS = frozenset(
    {"conversation_turns", "conversations", "user_preferences"}
)


class MuninnContextMaterializationMixin:
    """Behavior-preserving extracted runtime methods."""

    async def _materialize_evidence_conflict(self: Any, payload: dict[str, Any]) -> None:
        if self._evidence_conflict_sink is None:
            raise RuntimeError("Muninn evidence-conflict sink is unavailable")
        try:
            revision = EvidenceConflictRevision.model_validate(
                {
                    field: payload[field]
                    for field in EvidenceConflictRevision.model_fields
                    if field in payload
                }
            )
        except (KeyError, ValueError) as exc:
            raise ValueError("Muninn received invalid evidence-conflict revision") from exc
        created = await self._evidence_conflict_sink.append(revision)
        self.record_behavior("evidence_conflict:" + ("stored" if created else "duplicate"))

    async def _materialize_prospective_lineage(self: Any, payload: dict[str, Any]) -> None:
        materializer = self._prospective_lineage_materializer
        if materializer is None:
            raise RuntimeError("Muninn prospective-lineage materializer is unavailable")
        envelope = ProspectiveLineage.model_validate(
            {field: payload[field] for field in ProspectiveLineage.model_fields if field in payload}
        )
        created = await materializer.materialize(envelope)
        self.record_behavior("prospective_lineage:" + ("materialized" if created else "duplicate"))

    async def _seal_prospective_lineage(self: Any, payload: dict[str, Any]) -> None:
        materializer = self._prospective_lineage_materializer
        if materializer is None:
            raise RuntimeError("Muninn prospective-lineage materializer is unavailable")
        lineage_id = str(payload.get("lineage_id") or "")
        subgraph_digest = str(payload.get("subgraph_digest") or "")
        if not lineage_id or not subgraph_digest:
            raise ValueError("prospective-lineage Saga seal is incomplete")
        created = await materializer.seal_saga(
            lineage_id=lineage_id,
            subgraph_digest=subgraph_digest,
        )
        self.record_behavior(
            "prospective_lineage:" + ("saga_sealed" if created else "saga_duplicate")
        )

    async def _materialize_retrieval_validation(self: Any, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Heimdall":
            raise ValueError("retrieval validation MUST be published by Heimdall")
        raw_failure = payload.get("failure")
        if not isinstance(raw_failure, Mapping):
            raise ValueError("retrieval validation MUST contain failure evidence")
        evidence = query_failure_evidence_from_mapping(raw_failure)
        candidate = build_feedback_candidate(evidence)
        if payload.get("candidate_id") != candidate.candidate_id:
            raise ValueError("retrieval validation candidate identity mismatch")
        if self.bus is None:
            raise RuntimeError("Muninn context-index bus is unavailable")
        indexed = {
            "producer_principal": "Muninn",
            "kind": "semantic_retrieval_failure",
            "correlation_id": str(payload.get("correlation_id") or evidence.attempt_id),
            "idempotency_key": f"semantic-feedback:{candidate.candidate_id}",
            "candidate_id": candidate.candidate_id,
            "failure": query_failure_evidence_to_mapping(evidence),
        }
        await self._publish_with_outbox(
            f"{_OPERATIONAL_OUTBOX_PREFIX}/semantic-feedback/{candidate.candidate_id}",
            "object.context-index",
            indexed,
        )
        self.record_behavior("semantic_retrieval_failure:published")

    def _materialize_change(self: Any, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Huginn":
            self.record_behavior("change:invalid_producer")
            return
        change_id = str(payload.get("id") or "").strip()
        if not change_id:
            self.record_behavior("change:invalid_payload")
            return
        correlation_id = str(payload.get("correlation_id") or "").strip()
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not correlation_id or not idempotency_key:
            self.record_behavior("change:missing_identity")
            return
        canonical = {
            key: value
            for key, value in payload.items()
            if key not in {"envelope_schema_version", "schema_version"}
        }
        digest = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        revision_key = f"{change_id}:{digest}"
        if self.state_store.get("change_revisions", revision_key) is not None:
            self.record_behavior("change:duplicate")
            return
        self.state_store.put("change_revisions", revision_key, canonical)
        self.state_store.put(
            "changes",
            change_id,
            {"revision_key": revision_key, "digest": digest, "change": canonical},
        )
        self.record_behavior("change:stored")

    def _hold_response_outcome(self: Any, payload: dict[str, Any]) -> None:
        attributes = payload.get("attributes")
        if payload.get("producer_principal") != "Huginn" or not isinstance(attributes, dict):
            self.record_behavior("operating_pattern:invalid")
            return
        try:
            ResponseOutcome.model_validate(
                {
                    name: attributes[name]
                    for name in ResponseOutcome.model_fields
                    if name in attributes
                }
            )
        except ValueError:
            self.record_behavior("operating_pattern:invalid")
            return
        self.record_behavior("operating_pattern:mechanism_evidence_insufficient")

    async def _materialize_operational_case(self: Any, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Huginn":
            self.record_behavior("operational_case:invalid_producer")
            return
        attributes = payload.get("attributes")
        if not isinstance(attributes, Mapping):
            self.record_behavior("operational_case:invalid_payload")
            return
        if self._case_history is None or self._durable_state_store is None:
            self.record_behavior(
                "operational_case:materializer_unavailable"
                if self._case_history is None
                else "operational_case:durable_store_unavailable"
            )
            return
        try:
            case_input = OperationalCaseInput.from_mapping(attributes)
        except (TypeError, ValueError):
            self.record_behavior("operational_case:invalid_payload")
            return
        sealed = await self._case_history.seal_operational_case(
            case_input,
            retention_until=case_input.event_time_cutoff
            + timedelta(days=self._case_retention_days),
            deletion_due_at=case_input.event_time_cutoff + timedelta(days=self._case_deletion_days),
        )
        case = pattern_case_from_operational_case(case_input, sealed.projection)
        if case is None:
            self.record_behavior("operational_case:held")
            return
        fingerprint = case.failure_fingerprint
        state_key = _operating_pattern_state_key(case_input)
        projections = self._case_projection_store(case_input.access_scope_digest)
        cohort = await retain_cohort_case(
            projections,
            key=state_key,
            case=case,
            access_scope_digest=case_input.access_scope_digest,
            purpose=case_input.purpose,
            recorded_at=sealed.record.sealed_at,
        )
        cases = cohort["cases"]
        digest = _cohort_digest(cases) if len(cases) >= 2 else None
        if digest is None or self.bus is None:
            self.record_behavior("operational_case:stored")
            return
        emission_key = f"{state_key}:emitted:{digest}"
        outbox_key = f"{_OPERATIONAL_OUTBOX_PREFIX}/cohort/{digest}"
        if await projections.read_state(emission_key) is not None:
            self.record_behavior("operational_case:stored")
            return
        snapshot_key = f"{state_key}:snapshot:{digest}"
        await projections.write_state_if_absent(snapshot_key, cohort)
        if await projections.read_state(snapshot_key) != cohort:
            raise ValueError("operational cohort snapshot conflict")
        payload = {
            "producer_principal": "Muninn",
            "kind": "operational_case_fingerprint_cohort",
            "correlation_id": state_key,
            "idempotency_key": f"operational-case-fingerprint-cohort:{digest}",
            "access_scope_digest": case_input.access_scope_digest,
            "purpose": case_input.purpose,
            "cohort_snapshot_ref": snapshot_key,
            "case_id": case.case_id,
            "revision": case.revision,
            "manifest_digest": case.manifest_digest,
            "failure_fingerprint": fingerprint,
            "resource_type": case.resource_type,
            "action_type": case.action_type,
            "outcome_class": case.outcome_class.value,
            "reusable": case.reusable,
            "negative": case.negative,
            "digest_evidence": list(case.digest_evidence),
            "cases": [record["case"] for record in cases],
        }
        await self._publish_with_outbox(outbox_key, "object.context-index", payload)
        await projections.write_state_if_absent(
            emission_key, {"digest": digest, "revision": cohort["revision"]}
        )
        self.record_behavior("operational_case:published")


def _operating_pattern_state_key(case_input: OperationalCaseInput) -> str:
    return cohort_state_key(
        access_scope_digest=case_input.access_scope_digest,
        purpose=case_input.purpose,
        failure_fingerprint=case_input.failure_fingerprint.digest,
        action_type=case_input.action_type,
        fdai_revision=case_input.fdai_revision,
        scenario_set_version=case_input.scenario_set_version,
        source_kind=case_input.source_kind.value,
        source_synthetic=case_input.source_synthetic,
    )


def _cohort_digest(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(cases, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = ["MuninnContextMaterializationMixin"]
