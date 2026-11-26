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
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.muninn_constants import (
    _CONVERSATION_PROJECTION_RECOVERY_PAGE as _CONVERSATION_PROJECTION_RECOVERY_PAGE,
)
from fdai.agents._framework.muninn_constants import (
    _DEFAULT_PROVIDER_TIMEOUT_SECONDS as _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
)
from fdai.agents._framework.muninn_constants import (
    _MAX_CONTEXT_FETCH_SAMPLES as _MAX_CONTEXT_FETCH_SAMPLES,
)
from fdai.agents._framework.muninn_constants import (
    _MAX_CONTEXT_UNAVAILABLE_FACTS as _MAX_CONTEXT_UNAVAILABLE_FACTS,
)
from fdai.agents._framework.muninn_constants import (
    _MAX_CONVERSATION_PROJECTIONS as _MAX_CONVERSATION_PROJECTIONS,
)
from fdai.agents._framework.muninn_constants import (
    _MAX_OPERATING_PATTERN_CASES as _MAX_OPERATING_PATTERN_CASES,
)
from fdai.agents._framework.muninn_constants import (
    _OPERATIONAL_OUTBOX_PREFIX as _OPERATIONAL_OUTBOX_PREFIX,
)
from fdai.agents._framework.muninn_constants import (
    _PROJECTION_PREFIX as _PROJECTION_PREFIX,
)
from fdai.agents._framework.muninn_constants import (
    _PROTECTED_CONVERSATION_BUCKETS as _PROTECTED_CONVERSATION_BUCKETS,
)
from fdai.agents._framework.muninn_constants import (
    _PUBLICATION_CAS_ATTEMPTS as _PUBLICATION_CAS_ATTEMPTS,
)
from fdai.agents._framework.muninn_constants import (
    _PUBLICATION_CLAIM_LEASE as _PUBLICATION_CLAIM_LEASE,
)
from fdai.agents._framework.muninn_constants import (
    _PUBLICATION_COMPACTION_INTERVAL as _PUBLICATION_COMPACTION_INTERVAL,
)
from fdai.agents._framework.muninn_constants import (
    _PUBLICATION_MAINTENANCE_PAGE as _PUBLICATION_MAINTENANCE_PAGE,
)
from fdai.agents._framework.muninn_constants import (
    _PUBLICATION_OUTBOX_RETAIN as _PUBLICATION_OUTBOX_RETAIN,
)
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

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object


def _readiness_generated_at(record: Mapping[str, Any]) -> datetime | None:
    raw = record.get("generated_at")
    if not isinstance(raw, str):
        return None
    try:
        generated_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return generated_at if generated_at.tzinfo is not None else None


class MuninnContextMaterializationMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _apply_case_history_retention: Any
        _assignment_clock: Any
        _assignment_materializer: Any
        _case_deletion_days: Any
        _case_history: Any
        _case_history_clock: Any
        _case_history_retention: Any
        _case_projection_store: Any
        _case_retention_days: Any
        _conversation_sessions: Any
        _conversation_turns: Any
        _durable_state_store: Any
        _evidence_conflict_sink: Any
        _handover_message: Any
        _materialize_detection_readiness: Any
        _materialize_forecast_outcome: Any
        _materialize_operating_pattern: Any
        _outbox_key_for_recovery: Any
        _prospective_lineage_materializer: Any
        _provider_timeout_seconds: Any
        _publication_outbox_claimed_at: Any
        _publish_with_outbox: Any
        _request_document_index: Any
        _user_preferences: Any
        state_store: Any

    async def _materialize_evidence_conflict(self, payload: dict[str, Any]) -> None:
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

    async def _materialize_prospective_lineage(self, payload: dict[str, Any]) -> None:
        materializer = self._prospective_lineage_materializer
        if materializer is None:
            raise RuntimeError("Muninn prospective-lineage materializer is unavailable")
        envelope = ProspectiveLineage.model_validate(
            {field: payload[field] for field in ProspectiveLineage.model_fields if field in payload}
        )
        created = await materializer.materialize(envelope)
        self.record_behavior("prospective_lineage:" + ("materialized" if created else "duplicate"))

    async def _seal_prospective_lineage(self, payload: dict[str, Any]) -> None:
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

    async def _materialize_retrieval_validation(self, payload: dict[str, Any]) -> None:
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

    def _materialize_change(self, payload: dict[str, Any]) -> None:
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

    def _hold_response_outcome(self, payload: dict[str, Any]) -> None:
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

    async def _materialize_operational_case(self, payload: dict[str, Any]) -> None:
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
