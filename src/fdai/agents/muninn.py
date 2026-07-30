"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.adapters import InMemoryStateStore
from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _MUNINN
from fdai.core.case_history import CaseHistoryMaterializer, CaseHistoryRetentionService
from fdai.core.operational_learning import PatternCase, pattern_case_from_response_outcome
from fdai.core.readiness import DetectionReadinessSnapshot, detection_readiness_state_key
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


class Muninn(Agent):
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
    ) -> None:
        if case_retention_days < 1 or case_deletion_days < case_retention_days:
            raise ValueError("Muninn case retention days MUST be positive and ordered")
        super().__init__(spec=_MUNINN)
        self.state_store = state_store or InMemoryStateStore()
        self._durable_state_store = durable_state_store
        self._case_history = case_history
        self._case_history_retention = case_history_retention
        self._case_history_clock = case_history_clock or _utc_now
        self._case_retention_days = case_retention_days
        self._case_deletion_days = case_deletion_days

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.turn":
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
            topic == "object.event" and payload.get("event_type") == "measurement.action_outcome.v1"
        ):
            await self._materialize_response_outcome(payload)
        elif topic == "object.event" and payload.get("event_type") == (
            "case_history.retention_due"
        ):
            await self._apply_case_history_retention(payload)

    async def _materialize_response_outcome(self, payload: dict[str, Any]) -> None:
        attributes = payload.get("attributes")
        if payload.get("producer_principal") != "Huginn" or not isinstance(attributes, dict):
            self.record_behavior("operating_pattern:invalid")
            return
        try:
            outcome = ResponseOutcome.model_validate(
                {
                    name: attributes[name]
                    for name in ResponseOutcome.model_fields
                    if name in attributes
                }
            )
        except ValueError:
            self.record_behavior("operating_pattern:invalid")
            return
        case = pattern_case_from_response_outcome(outcome)
        if case is None:
            self.record_behavior("operating_pattern:held")
            return
        state_key = _operating_pattern_state_key(case.action_type)
        state = self.state_store.get("operating_pattern_cohorts", case.action_type)
        if state is None and self._durable_state_store is not None:
            state = await self._durable_state_store.read_state(state_key)
        cohort = _append_pattern_case(state, case, recorded_at=outcome.recorded_at)
        self.state_store.put("operating_pattern_cohorts", case.action_type, cohort)
        if self._durable_state_store is not None:
            await self._durable_state_store.write_state(state_key, cohort)
        cases = cohort["cases"]
        digest = _cohort_digest(cases) if len(cases) >= 2 else None
        if digest is None or digest == cohort.get("last_emitted_digest") or self.bus is None:
            self.record_behavior("operating_pattern:stored")
            return
        await self.bus.publish(
            "Muninn",
            "object.context-index",
            {
                "producer_principal": "Muninn",
                "kind": "operating_pattern_cohort",
                "correlation_id": str(outcome.action_id),
                "idempotency_key": f"operating-pattern-cohort:{digest}",
                "action_type": case.action_type,
                "cases": [record["case"] for record in cases],
            },
        )
        cohort["last_emitted_digest"] = digest
        self.state_store.put("operating_pattern_cohorts", case.action_type, cohort)
        if self._durable_state_store is not None:
            await self._durable_state_store.write_state(state_key, cohort)
        self.record_behavior("operating_pattern:published")

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
            answer = f"Bucket {bucket!r} holds {len(data[bucket])} key(s)."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Holding {len(data)} state bucket(s) with "
            f"{sum(len(v) for v in data.values())} key(s) total."
        )
        return IntrospectionResult(answer=answer, facts=facts)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _operating_pattern_state_key(action_type: str) -> str:
    digest = hashlib.sha256(action_type.encode()).hexdigest()
    return f"operating-pattern-cohort:{digest}"


def _append_pattern_case(
    state: object,
    case: PatternCase,
    *,
    recorded_at: datetime,
) -> dict[str, Any]:
    current = dict(state) if isinstance(state, Mapping) else {}
    raw_cases = current.get("cases")
    records = (
        [dict(item) for item in raw_cases if isinstance(item, Mapping)]
        if isinstance(raw_cases, list)
        else []
    )
    mapping = {
        "case_id": case.case_id,
        "action_type": case.action_type,
        "outcome_id": case.outcome_id,
        "reusable": case.reusable,
        "evidence_refs": list(case.evidence_refs),
    }
    records = [
        record for record in records if record.get("case", {}).get("case_id") != case.case_id
    ]
    records.append({"recorded_at": recorded_at.isoformat(), "case": mapping})
    records.sort(
        key=lambda record: (
            str(record.get("recorded_at", "")),
            str(record.get("case", {}).get("case_id", "")),
        )
    )
    return {
        "schema_version": "1.0.0",
        "action_type": case.action_type,
        "cases": records[-_MAX_OPERATING_PATTERN_CASES:],
        "last_emitted_digest": current.get("last_emitted_digest"),
    }


def _cohort_digest(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(cases, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = ["Muninn"]
