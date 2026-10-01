"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.readiness import DetectionReadinessSnapshot, detection_readiness_state_key
from fdai.shared.contracts.models import ForecastOutcome


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


class MuninnReadinessRuntimeMixin:
    """Behavior-preserving extracted runtime methods."""

    async def _materialize_detection_readiness(self: Any, payload: dict[str, Any]) -> None:
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

    async def _apply_case_history_retention(self: Any, payload: dict[str, Any]) -> None:
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

    async def _materialize_forecast_outcome(self: Any, payload: dict[str, Any]) -> None:
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

    async def _request_document_index(self: Any, audited: dict[str, Any]) -> None:
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
