"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.adapters import InMemoryStateStore
from fdai.agents._framework.assignment_workflow import (
    AssignmentClock,
    AssignmentMaterializer,
    assignment_clock,
    materialize_assignment,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _MUNINN
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
    OperationalCaseInput,
)
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictRevision,
    EvidenceConflictSink,
)
from fdai.core.operational_learning import (
    OperatingPatternCompiler,
    PatternCase,
    pattern_case_from_operational_case,
)
from fdai.core.operational_learning.cohort_retention import retain_cohort_case
from fdai.core.operational_learning.patterns import valid_pattern_publication_envelope
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineage,
    ProspectiveLineageMaterializer,
)
from fdai.core.readiness import DetectionReadinessSnapshot, detection_readiness_state_key
from fdai.rule_catalog.schema.rule_semantic_feedback import (
    build_feedback_candidate,
    query_failure_evidence_from_mapping,
    query_failure_evidence_to_mapping,
)
from fdai.shared.contracts.models import ForecastOutcome, ResponseOutcome
from fdai.shared.providers.state_store import StateStore


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


class Muninn(Agent, HandoverKnowledgeMixin):
    """Wave-2 Muninn: state / context store proxy."""

    def __init__(
        self,
        *,
        state_store: InMemoryStateStore | None = None,
        durable_state_store: StateStore | None = None,
        case_history: CaseHistoryMaterializer | None = None,
        case_history_retention: CaseHistoryRetentionService | None = None,
        case_history_clock: Callable[[], datetime] | None = None,
        case_retention_days: int = 30,
        case_deletion_days: int = 60,
        evidence_conflict_sink: EvidenceConflictSink | None = None,
        prospective_lineage_materializer: ProspectiveLineageMaterializer | None = None,
    ) -> None:
        if case_retention_days < 1 or case_deletion_days < case_retention_days:
            raise ValueError("Muninn case retention days MUST be positive and ordered")
        super().__init__(spec=_MUNINN)
        self.state_store = state_store or InMemoryStateStore()
        self._durable_state_store = durable_state_store
        self._case_history = case_history
        self._case_history_retention = case_history_retention
        self._case_history_clock = case_history_clock or _utc_now
        self._case_retention_days, self._case_deletion_days = (
            case_retention_days,
            case_deletion_days,
        )
        self._evidence_conflict_sink = evidence_conflict_sink
        self._prospective_lineage_materializer = prospective_lineage_materializer
        self._assignment_materializer: AssignmentMaterializer | None = None
        self._assignment_clock: AssignmentClock = assignment_clock

    def bind_assignment_materializer(
        self,
        materializer: AssignmentMaterializer,
        *,
        clock: AssignmentClock = assignment_clock,
    ) -> None:
        """Bind an audit-sealed case projector, not an IAM or PR executor."""
        self._assignment_materializer, self._assignment_clock = materializer, clock

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._handover_message(topic, payload):
            return
        if topic == "object.audit-entry" and payload.get("kind") == "human_assignment":
            await materialize_assignment(
                self, payload, self._assignment_materializer, clock=self._assignment_clock
            )
            return
        if topic == "object.pattern":
            async with asyncio.timeout(5):
                await self._materialize_operating_pattern(payload)
        elif topic == "object.turn":
            turn_id = str(payload.get("turn_id") or payload.get("id", ""))
            if turn_id:
                self.state_store.put("conversation_turns", turn_id, payload)
        elif topic == "object.drift" and payload.get("kind") == "detection_readiness":
            await self._materialize_detection_readiness(payload)
        elif (
            topic == "object.audit-entry"
            and payload.get("kind") == "document_ingestion"
            and payload.get("stage") == "protection_check"
            and (
                (
                    payload.get("audited_topic") == "object.verdict"
                    and payload.get("decision") == "admit"
                )
                or (
                    payload.get("audited_topic") == "object.approval"
                    and payload.get("decision") == "approved"
                )
            )
        ):
            await self._request_document_index(payload)
        elif topic == "object.forecast-outcome":
            await self._materialize_forecast_outcome(payload)
        elif (
            topic == "object.retrieval-validation"
            and payload.get("event_type") == "rule.semantic_generation.validation.completed.v1"
        ):
            self.record_behavior("rule_generation_validation:observed")
        elif topic == "object.retrieval-validation":
            await self._materialize_retrieval_validation(payload)
        elif (
            topic == "object.event" and payload.get("event_type") == "measurement.action_outcome.v1"
        ):
            self._hold_response_outcome(payload)
        elif topic == "object.event" and payload.get("event_type") == (
            "case_history.operational_case.v1"
        ):
            await self._materialize_operational_case(payload)
        elif topic == "object.event" and payload.get("event_type") == (
            "case_history.retention_due"
        ):
            await self._apply_case_history_retention(payload)
        elif topic == "object.change":
            self._materialize_change(payload)
        elif topic == "object.evidence-conflict":
            await self._materialize_evidence_conflict(payload)
        elif topic == "object.prospective-lineage":
            await self._materialize_prospective_lineage(payload)
        elif (
            topic == "object.audit-entry"
            and payload.get("action_kind") == "prospective_lineage.sealed"
        ):
            await self._seal_prospective_lineage(payload)

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
        await self.bus.publish(
            "Muninn",
            "object.context-index",
            {
                "producer_principal": "Muninn",
                "kind": "semantic_retrieval_failure",
                "correlation_id": str(payload.get("correlation_id") or evidence.attempt_id),
                "idempotency_key": f"semantic-feedback:{candidate.candidate_id}",
                "candidate_id": candidate.candidate_id,
                "failure": query_failure_evidence_to_mapping(evidence),
            },
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
        if await projections.read_state(emission_key) is not None:
            self.record_behavior("operational_case:stored")
            return
        snapshot_key = f"{state_key}:snapshot:{digest}"
        await projections.write_state_if_absent(snapshot_key, cohort)
        if await projections.read_state(snapshot_key) != cohort:
            raise ValueError("operational cohort snapshot conflict")
        await self.bus.publish(
            "Muninn",
            "object.context-index",
            {
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
            },
        )
        await projections.write_state_if_absent(
            emission_key, {"digest": digest, "revision": cohort["revision"]}
        )
        self.record_behavior("operational_case:published")

    async def _materialize_operating_pattern(self, payload: dict[str, Any]) -> None:
        if not valid_pattern_publication_envelope(payload):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        if (
            payload.get("producer_principal") != "Norns"
            or payload.get("kind") != "operational_pattern"
        ):
            self.record_behavior("operating_pattern:invalid_producer")
            return
        if self._durable_state_store is None:
            raise RuntimeError("operating pattern durable store is unavailable")
        pattern_id = payload.get("pattern_id")
        cohort_key = payload.get("cohort_key")
        scope = payload.get("access_scope_digest")
        purpose = payload.get("purpose")
        snapshot_key = payload.get("cohort_snapshot_ref")
        if (
            not isinstance(pattern_id, str)
            or len(pattern_id) != 64
            or any(character not in "0123456789abcdef" for character in pattern_id)
            or not isinstance(cohort_key, str)
            or not cohort_key.startswith("operational-case-fingerprint-cohort:v2:")
            or len(cohort_key) != len("operational-case-fingerprint-cohort:v2:") + 64
            or payload.get("correlation_id") != cohort_key
            or payload.get("idempotency_key") != f"operating-pattern:{pattern_id}"
            or not isinstance(snapshot_key, str)
            or not snapshot_key.startswith(f"{cohort_key}:snapshot:")
            or len(snapshot_key) != len(cohort_key) + len(":snapshot:") + 64
        ):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        projections = self._case_projection_store(str(scope))
        cohort = await projections.read_state(snapshot_key)
        if (
            not isinstance(cohort, Mapping)
            or cohort.get("access_scope_digest") != scope
            or cohort.get("purpose") != purpose
        ):
            self.record_behavior("operating_pattern:scope_mismatch")
            return
        raw_cases = cohort.get("cases")
        if (
            not isinstance(raw_cases, list)
            or not 2 <= len(raw_cases) <= _MAX_OPERATING_PATTERN_CASES
        ):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        try:
            if snapshot_key != f"{cohort_key}:snapshot:{_cohort_digest(raw_cases)}":
                self.record_behavior("operating_pattern:invalid_snapshot")
                return
            cases = tuple(PatternCase.from_mapping(record["case"]) for record in raw_cases)
            compiled = OperatingPatternCompiler().compile(
                cases, reviewed_at=self._case_history_clock()
            )
        except (KeyError, TypeError, ValueError):
            self.record_behavior("operating_pattern:invalid_payload")
            return
        if compiled is None or compiled.pattern_id != pattern_id:
            self.record_behavior("operating_pattern:cohort_changed")
            return
        if self._case_history is None:
            raise RuntimeError("operating pattern case evidence is unavailable")
        for case_ref in compiled.immutable_case_refs:
            if not await self._case_history.current_revision_available(
                case_ref=case_ref,
                access_scope_digest=str(scope),
                purpose=str(purpose),
                now=self._case_history_clock(),
            ):
                self.record_behavior("operating_pattern:case_unavailable")
                return
        record = {
            "schema_version": "1.0.0",
            "pattern_id": pattern_id,
            "access_scope_digest": scope,
            "purpose": purpose,
            "cohort_key": cohort_key,
            "candidate": compiled.to_rule_candidate_mapping(),
            "cases": [case.to_mapping() for case in cases],
            "execution_authority": False,
            "promotion_authority": False,
        }
        key = f"{cohort_key}:pattern:{pattern_id}"
        existing = await projections.read_state(key)
        if existing is not None and existing != record:
            raise ValueError("operating pattern immutable identity conflict")
        if existing is None:
            await projections.write_state_if_absent(key, record)
            if await projections.read_state(key) != record:
                raise ValueError("operating pattern immutable identity conflict")
        if self.bus is not None:
            await self.bus.publish(
                "Muninn",
                "object.state-snapshot",
                {
                    "producer_principal": "Muninn",
                    "kind": "operating_pattern_retained",
                    "correlation_id": cohort_key,
                    "idempotency_key": f"operating-pattern-retained:{pattern_id}",
                    "pattern_id": pattern_id,
                    "access_scope_digest": scope,
                    "purpose": purpose,
                    "execution_authority": False,
                    "promotion_authority": False,
                },
            )
        self.record_behavior("operating_pattern:retained")

    async def read_operating_pattern(
        self, *, cohort_key: str, pattern_id: str, access_scope_digest: str, purpose: str
    ) -> dict[str, Any] | None:
        """Read an inert retained pattern only while its exact scoped cases remain current."""
        try:
            async with asyncio.timeout(5):
                return await self._read_operating_pattern(
                    cohort_key=cohort_key,
                    pattern_id=pattern_id,
                    access_scope_digest=access_scope_digest,
                    purpose=purpose,
                )
        except (TimeoutError, ValueError, TypeError):
            return None

    async def _read_operating_pattern(
        self, *, cohort_key: str, pattern_id: str, access_scope_digest: str, purpose: str
    ) -> dict[str, Any] | None:
        if self._durable_state_store is None or self._case_history is None:
            return None
        prefix = "operational-case-fingerprint-cohort:v2:"
        if not cohort_key.startswith(prefix) or len(cohort_key) != len(prefix) + 64:
            return None
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in (cohort_key[len(prefix) :], pattern_id, access_scope_digest)
        ):
            return None
        if not purpose.strip() or len(purpose) > 512:
            return None
        key = f"{cohort_key}:pattern:{pattern_id}"
        record = await self._case_projection_store(access_scope_digest).read_state(key)
        if not isinstance(record, dict) or (
            record.get("schema_version") != "1.0.0"
            or set(record)
            != {
                "schema_version",
                "pattern_id",
                "access_scope_digest",
                "purpose",
                "cohort_key",
                "candidate",
                "cases",
                "execution_authority",
                "promotion_authority",
            }
            or record.get("access_scope_digest") != access_scope_digest
            or record.get("purpose") != purpose
            or record.get("pattern_id") != pattern_id
            or record.get("cohort_key") != cohort_key
            or record.get("execution_authority") is not False
            or record.get("promotion_authority") is not False
        ):
            return None
        try:
            raw_cases = record["cases"]
            if not isinstance(raw_cases, list) or not 2 <= len(raw_cases) <= 100:
                return None
            compiled = OperatingPatternCompiler().compile(
                tuple(PatternCase.from_mapping(item) for item in raw_cases),
                reviewed_at=self._case_history_clock(),
            )
            if (
                compiled is None
                or compiled.pattern_id != pattern_id
                or compiled.to_rule_candidate_mapping() != record["candidate"]
            ):
                return None
            for case_ref in compiled.immutable_case_refs:
                if not isinstance(
                    case_ref, str
                ) or not await self._case_history.current_revision_available(
                    case_ref=case_ref,
                    access_scope_digest=access_scope_digest,
                    purpose=purpose,
                    now=self._case_history_clock(),
                ):
                    return None
        except (KeyError, TypeError, ValueError):
            return None
        return record

    def _case_projection_store(self, scope: str) -> CaseHistoryProjectionStore:
        if self._durable_state_store is None or self._case_history is None:
            raise RuntimeError("case projection dependencies are unavailable")
        return CaseHistoryProjectionStore(
            store=self._durable_state_store,
            materializer=self._case_history,
            access_scope_digest=scope,
            clock=self._case_history_clock,
        )

    async def _materialize_detection_readiness(self, payload: dict[str, Any]) -> None:
        """Persist and publish one validated Heimdall readiness snapshot."""
        try:
            snapshot = DetectionReadinessSnapshot.model_validate(
                {
                    "resource_ref": payload.get("resource_id"),
                    "generated_at": payload.get("generated_at"),
                    "decision": payload.get("decision"),
                    "observations": payload.get("observations"),
                    "missing_dimensions": payload.get("missing_dimensions", []),
                    "stale_dimensions": payload.get("stale_dimensions", []),
                    "authority_ceiling": payload.get("authority_ceiling"),
                }
            )
        except ValueError:
            self.record_behavior("detection_readiness:invalid")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        correlation_id = str(payload.get("correlation_id") or "")
        if not idempotency_key or not correlation_id:
            self.record_behavior("detection_readiness:invalid")
            return

        record = {
            "kind": "detection_readiness",
            "producer_principal": "Muninn",
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            **snapshot.model_dump(mode="json"),
        }
        prior = self.state_store.get("detection_readiness", snapshot.resource_ref)
        if isinstance(prior, dict) and prior.get("idempotency_key") == idempotency_key:
            self.record_behavior("detection_readiness:duplicate")
            return
        if (
            isinstance(prior, dict)
            and (prior_generated_at := _readiness_generated_at(prior)) is not None
            and prior_generated_at >= snapshot.generated_at
        ):
            self.record_behavior("detection_readiness:stale")
            return
        key = detection_readiness_state_key(snapshot.resource_ref)
        if self._durable_state_store is not None:
            durable_prior = await self._durable_state_store.read_state(key)
            if (
                durable_prior is not None
                and durable_prior.get("idempotency_key") == idempotency_key
            ):
                self.state_store.put(
                    "detection_readiness",
                    snapshot.resource_ref,
                    dict(durable_prior),
                )
                self.record_behavior("detection_readiness:duplicate")
                return
            if (
                durable_prior is not None
                and (durable_generated_at := _readiness_generated_at(durable_prior)) is not None
                and durable_generated_at >= snapshot.generated_at
            ):
                self.state_store.put(
                    "detection_readiness",
                    snapshot.resource_ref,
                    dict(durable_prior),
                )
                self.record_behavior("detection_readiness:stale")
                return
            await self._durable_state_store.write_state(key, record)
        self.state_store.put("detection_readiness", snapshot.resource_ref, record)
        self.record_behavior(f"detection_readiness:{snapshot.decision.value}")
        if self.bus is not None:
            await self.bus.publish(
                "Muninn",
                "object.state-snapshot",
                {
                    **record,
                    "snapshot_type": "detection_readiness",
                    "idempotency_key": f"state-snapshot:{idempotency_key}",
                },
            )

    async def _apply_case_history_retention(self, payload: dict[str, Any]) -> None:
        identity_fields = (
            payload.get("event_id"),
            payload.get("idempotency_key"),
            payload.get("correlation_id"),
        )
        if payload.get("source") != "case-history-retention-scheduler" or any(
            not isinstance(value, str) or not value.startswith("case-history-retention:")
            for value in identity_fields
        ):
            self.record_behavior("case_history:retention_invalid")
            return
        if self._case_history_retention is None:
            self.record_behavior("case_history:retention_unavailable")
            return
        as_of = self._case_history_clock()
        if as_of.tzinfo is None:
            raise ValueError("Muninn case history clock MUST be timezone-aware")
        deleted = await self._case_history_retention.delete_due(now=as_of)
        self.record_behavior("case_history:retention_tick")
        for _case_id in deleted:
            self.record_behavior("case_history:deleted")

    async def _materialize_forecast_outcome(self, payload: dict[str, Any]) -> None:
        if self._case_history is None:
            self.record_behavior("case_history:unavailable")
            return
        contract_payload = {
            name: payload[name] for name in ForecastOutcome.model_fields if name in payload
        }
        outcome = ForecastOutcome.model_validate(contract_payload)
        record = await self._case_history.seal_forecast_outcome(
            outcome,
            purpose="forecast-error-analysis",
            redaction_policy_version="1.0.0",
            retention_until=outcome.closed_at + timedelta(days=self._case_retention_days),
            deletion_due_at=outcome.closed_at + timedelta(days=self._case_deletion_days),
        )
        self.record_behavior(f"case_history:{outcome.label.value}")
        if self.bus is None:
            return
        await self.bus.publish(
            "Muninn",
            "object.context-index",
            {
                "producer_principal": "Muninn",
                "kind": "forecast_case_history",
                "correlation_id": outcome.correlation_id,
                "idempotency_key": (
                    f"case-history-index:{record.case_id}:{record.source_set_digest}"
                ),
                "case_id": record.case_id,
                "revision": record.revision,
                "manifest_digest": record.manifest_digest,
                "access_scope_digest": record.access_scope_digest,
                "purpose": record.purpose,
                "outcome_label": record.outcome_label,
                "detector_id": record.detector_id,
                "detector_version": record.detector_version,
                "metric": outcome.metric,
                "case_ref": (
                    f"case-history:{record.case_id}:{record.revision}:{record.manifest_digest}"
                ),
            },
        )

    async def _request_document_index(self, audited: dict[str, Any]) -> None:
        """Publish the content-free command that unlocks document indexing."""
        upload_id = str(audited.get("upload_id") or "")
        document_id = str(audited.get("document_id") or "")
        correlation_id = str(audited.get("correlation_id") or "")
        if not upload_id or not document_id or not correlation_id:
            self.record_behavior("document_index:invalid")
            return
        command = {
            "schema_version": "1.0.0",
            "producer_principal": "Muninn",
            "kind": "document_ingestion",
            "stage": "indexing",
            "command": "index",
            "correlation_id": correlation_id,
            "idempotency_key": str(audited.get("idempotency_key") or ""),
            "resource_id": document_id,
            "document_id": document_id,
            "upload_id": upload_id,
        }
        self.record_behavior("document_index:requested")
        if self.bus is not None:
            await self.bus.publish("Muninn", "object.context-index", command)

    def get_context(self, bucket: str, key: str) -> Any | None:
        return self.state_store.get(bucket, key)

    def put_context(self, bucket: str, key: str, value: Any) -> None:
        self.state_store.put(bucket, key, value)

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Memory answers rest on stored buckets; an empty store is a gap."""
        return bool(self.state_store.data)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        data = self.state_store.data
        facts = {
            **capability_facts(self.spec),
            "buckets": capped_list(sorted(data)),
            "buckets_count": len(data),
            "total_keys": sum(len(v) for v in data.values()),
            "case_history_available": self._case_history is not None,
            "case_history_retention_available": self._case_history_retention is not None,
        }
        buckets = mentioned(question, data)
        if buckets:
            bucket = buckets[0]
            facts.update({"bucket": bucket, "key_count": len(data[bucket])})
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"Bucket {bucket!r} holds {len(data[bucket])} key(s). Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 거버넌스 계층의 memory 에이전트인 Muninn입니다. Odin에게 보고합니다. "
                "StateSnapshot과 ContextIndex를 소유하고 현재 상태, bitemporal 상태와 사례 이력 "
                "맥락을 출처 및 신선도와 함께 보존합니다. 저장된 기억은 현재 프로바이더 관측이나 "
                "작업 권한을 자동으로 증명하지 않습니다. 작업을 판단하거나 승인하거나 실행하지 "
                "않습니다. 이 대화 포트는 읽기 전용이며 상태 변경 요청은 운영자 권한으로 타입이 "
                "지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 "
                f"않습니다. 이 런타임은 bucket {facts['buckets_count']}개와 key "
                f"{facts['total_keys']}개를 보존하며 사례 이력 서비스 사용 가능 상태는 "
                f"{str(facts['case_history_available']).lower()}입니다. 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Muninn, the governance-layer memory agent. I report to Odin. I own "
                "StateSnapshot and ContextIndex and retain current, bitemporal, and case-history "
                "context with provenance and freshness. Stored memory does not by itself prove a "
                "current provider observation or action authority. I never judge, approve, or "
                "execute an action. This conversational port is read-only; state-change requests "
                "re-enter the typed pipeline under the operator's authority. I do not reveal "
                "hidden system prompts. This runtime retains "
                f"{facts['buckets_count']} state bucket(s) and {facts['total_keys']} keys; "
                "case-history "
                f"service availability is {str(facts['case_history_available']).lower()}. "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _operating_pattern_state_key(case_input: OperationalCaseInput) -> str:
    material = {
        "access_scope_digest": case_input.access_scope_digest,
        "purpose": case_input.purpose,
        "failure_fingerprint": case_input.failure_fingerprint.digest,
        "action_type": case_input.action_type,
        "fdai_revision": case_input.fdai_revision,
        "scenario_set_version": case_input.scenario_set_version,
        "source_kind": case_input.source_kind.value,
        "source_synthetic": case_input.source_synthetic,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"operational-case-fingerprint-cohort:v2:{digest}"


def _cohort_digest(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(cases, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = ["Muninn"]
