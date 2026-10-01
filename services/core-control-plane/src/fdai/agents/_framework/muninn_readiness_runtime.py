"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import asyncio
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
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.readiness import DetectionReadinessSnapshot, detection_readiness_state_key
from fdai.shared.contracts.models import ForecastOutcome

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


class MuninnReadinessRuntimeMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
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
        _hold_response_outcome: Any
        _materialize_change: Any
        _materialize_evidence_conflict: Any
        _materialize_operating_pattern: Any
        _materialize_operational_case: Any
        _materialize_prospective_lineage: Any
        _materialize_retrieval_validation: Any
        _outbox_key_for_recovery: Any
        _prospective_lineage_materializer: Any
        _provider_timeout_seconds: Any
        _publication_outbox_claimed_at: Any
        _publish_with_outbox: Any
        _seal_prospective_lineage: Any
        _user_preferences: Any
        state_store: Any

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
            "pass_id": str(payload.get("pass_id") or ""),
            "content_digest": str(payload.get("content_digest") or ""),
            "readiness_status": str(payload.get("readiness_status") or snapshot.decision.value),
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
        snapshot_payload = {
            **record,
            "snapshot_type": "detection_readiness",
            "idempotency_key": f"state-snapshot:{idempotency_key}",
        }
        outbox_key = f"{_OPERATIONAL_OUTBOX_PREFIX}/detection-readiness/{idempotency_key}"
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
                await self._publish_with_outbox(
                    outbox_key, "object.state-snapshot", snapshot_payload
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
        await self._publish_with_outbox(outbox_key, "object.state-snapshot", snapshot_payload)

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
        try:
            async with asyncio.timeout(self._provider_timeout_seconds):
                deleted = await self._case_history_retention.delete_due(now=as_of)
        except TimeoutError:
            self.record_behavior("case_history:retention_timeout")
            raise
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
        indexed = {
            "producer_principal": "Muninn",
            "kind": "forecast_case_history",
            "correlation_id": outcome.correlation_id,
            "idempotency_key": f"case-history-index:{record.case_id}:{record.source_set_digest}",
            "case_id": record.case_id,
            "revision": record.revision,
            "manifest_digest": record.manifest_digest,
            "access_scope_digest": record.access_scope_digest,
            "purpose": record.purpose,
            "outcome_label": record.outcome_label,
            "detector_id": record.detector_id,
            "detector_version": record.detector_version,
            "metric": outcome.metric,
            "case_ref": f"case-history:{record.case_id}:{record.revision}:{record.manifest_digest}",
        }
        outbox_key = (
            f"{_OPERATIONAL_OUTBOX_PREFIX}/forecast-case/"
            f"{record.case_id}/{record.revision}/{record.manifest_digest}"
        )
        await self._publish_with_outbox(outbox_key, "object.context-index", indexed)

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
            "idempotency_key": str(
                audited.get("idempotency_key")
                or stable_idempotency_key("document-index", correlation_id, document_id, upload_id)
            ),
            "resource_id": document_id,
            "document_id": document_id,
            "upload_id": upload_id,
        }
        self.record_behavior("document_index:requested")
        if self.bus is not None:
            await self.bus.publish("Muninn", "object.context-index", command)


__all__ = ["MuninnReadinessRuntimeMixin"]
