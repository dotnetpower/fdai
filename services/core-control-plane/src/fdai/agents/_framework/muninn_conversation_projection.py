"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.adapters import canonical_json_digest
from fdai.agents._framework.assignment_workflow import (
    materialize_assignment,
)
from fdai.agents._framework.bounded import BoundedLruDict
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
from fdai.agents._framework.producer_auth import require_topic_owner

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


class MuninnConversationProjectionMixin(_AgentMixinBase):
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
        _hold_response_outcome: Any
        _materialize_change: Any
        _materialize_detection_readiness: Any
        _materialize_evidence_conflict: Any
        _materialize_forecast_outcome: Any
        _materialize_operating_pattern: Any
        _materialize_operational_case: Any
        _materialize_prospective_lineage: Any
        _materialize_retrieval_validation: Any
        _outbox_key_for_recovery: Any
        _prospective_lineage_materializer: Any
        _provider_timeout_seconds: Any
        _publication_outbox_claimed_at: Any
        _publish_with_outbox: Any
        _request_document_index: Any
        _seal_prospective_lineage: Any
        _user_preferences: Any
        state_store: Any

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._handover_message(topic, payload):
            return
        if topic == "object.audit-entry" and payload.get("kind") == "human_assignment":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="assignment:invalid_producer",
            ):
                raise ValueError("human assignment audit MUST be published by Saga")
            await materialize_assignment(
                self, payload, self._assignment_materializer, clock=self._assignment_clock
            )
            return
        if topic == "object.pattern":
            if require_topic_owner(
                self, topic, payload, behavior="operating_pattern:invalid_producer"
            ):
                return
            async with asyncio.timeout(5):
                await self._materialize_operating_pattern(payload)
        elif topic == "object.turn":
            if require_topic_owner(self, topic, payload, behavior="turn:invalid_producer"):
                return
            await self._materialize_turn_projection(payload)
        elif topic == "object.conversation":
            if require_topic_owner(self, topic, payload, behavior="conversation:invalid_producer"):
                return
            await self._materialize_conversation_projection(payload)
        elif topic == "object.user-preference":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="user_preference:invalid_producer",
            ):
                return
            await self._materialize_user_preference_projection(payload)
        elif topic == "object.drift" and payload.get("kind") == "detection_readiness":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="detection_readiness:invalid_producer",
            ):
                return
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
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="document_index:invalid_producer",
            ):
                return
            await self._request_document_index(payload)
        elif topic == "object.forecast-outcome":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="forecast_outcome:invalid_producer",
            ):
                return
            await self._materialize_forecast_outcome(payload)
        elif (
            topic == "object.retrieval-validation"
            and payload.get("event_type") == "rule.semantic_generation.validation.completed.v1"
        ):
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="retrieval_validation:invalid_producer",
            ):
                return
            self.record_behavior("rule_generation_validation:observed")
        elif topic == "object.retrieval-validation":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="retrieval_validation:invalid_producer",
            ):
                return
            await self._materialize_retrieval_validation(payload)
        elif (
            topic == "object.event" and payload.get("event_type") == "measurement.action_outcome.v1"
        ):
            if require_topic_owner(self, topic, payload, behavior="event:invalid_producer"):
                return
            self._hold_response_outcome(payload)
        elif topic == "object.event" and payload.get("event_type") == (
            "case_history.operational_case.v1"
        ):
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="operational_case:invalid_producer",
            ):
                return
            await self._materialize_operational_case(payload)
        elif topic == "object.event" and payload.get("event_type") == (
            "case_history.retention_due"
        ):
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="case_history:retention_invalid_producer",
            ):
                return
            await self._apply_case_history_retention(payload)
        elif topic == "object.change":
            if require_topic_owner(self, topic, payload, behavior="change:invalid_producer"):
                return
            self._materialize_change(payload)
        elif topic == "object.evidence-conflict":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="evidence_conflict:invalid_producer",
            ):
                return
            await self._materialize_evidence_conflict(payload)
        elif topic == "object.prospective-lineage":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="prospective_lineage:invalid_producer",
            ):
                return
            await self._materialize_prospective_lineage(payload)
        elif (
            topic == "object.audit-entry"
            and payload.get("action_kind") == "prospective_lineage.sealed"
        ):
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="prospective_lineage:invalid_seal_producer",
            ):
                return
            await self._seal_prospective_lineage(payload)
        else:
            self.record_behavior("typed_message:ignored")

    async def recover_conversation_projections(self) -> int:
        """Restore digest-only Bragi conversation projections from the durable store."""
        store = self._durable_state_store
        if store is None:
            return 0
        restored = 0
        for bucket, projection in (
            ("conversation_turns", self._conversation_turns),
            ("conversations", self._conversation_sessions),
            ("user_preferences", self._user_preferences),
        ):
            offset = 0
            bucket_restored = 0
            while bucket_restored < _MAX_CONVERSATION_PROJECTIONS:
                rows, _total = await store.read_state_page(
                    f"{_PROJECTION_PREFIX}/{bucket}/",
                    limit=min(
                        _CONVERSATION_PROJECTION_RECOVERY_PAGE,
                        _MAX_CONVERSATION_PROJECTIONS - bucket_restored,
                    ),
                    offset=offset,
                )
                if not rows:
                    break
                for row in rows:
                    key = row.get("projection_key")
                    record = row.get("record")
                    if not isinstance(key, str) or not isinstance(record, dict):
                        raise ValueError("Muninn durable conversation projection is invalid")
                    projection.set(key, dict(record))
                    self.state_store.put(bucket, key, dict(record))
                    restored += 1
                    bucket_restored += 1
                offset += len(rows)
        return restored

    async def _materialize_turn_projection(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Bragi":
            self.record_behavior("conversation_turn:rejected")
            raise ValueError("Muninn conversation turns MUST be published by Bragi")
        turn_id = str(payload.get("turn_id") or payload.get("id", "")).strip()
        correlation_id = str(payload.get("correlation_id") or "").strip()
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not turn_id or not correlation_id or not idempotency_key:
            self.record_behavior("conversation_turn:rejected")
            return
        record = {
            "schema_version": "1.0.0",
            "turn_id": turn_id,
            "conversation_id": str(payload.get("conversation_id") or ""),
            "session_ref": str(payload.get("session_ref") or payload.get("session_id") or ""),
            "principal_scope": str(payload.get("principal_scope") or ""),
            "turn_index": payload.get("turn_index"),
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "payload_digest": _payload_digest(payload),
            "question_ref": str(payload.get("question_ref") or ""),
            "question_sha256": str(payload.get("question_sha256") or ""),
            "answer_ref": str(payload.get("answer_ref") or ""),
            "answer_sha256": str(payload.get("answer_sha256") or ""),
        }
        self._conversation_turns.set(turn_id, record)
        await self._sync_projection_record("conversation_turns", turn_id, record)
        self.record_behavior("conversation_turn:accepted")

    async def _materialize_conversation_projection(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Bragi":
            self.record_behavior("conversation:rejected")
            raise ValueError("Muninn conversations MUST be published by Bragi")
        conversation_id = str(payload.get("conversation_id") or payload.get("id") or "").strip()
        correlation_id = str(payload.get("correlation_id") or "").strip()
        if not conversation_id or not correlation_id:
            self.record_behavior("conversation:rejected")
            return
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            self.record_behavior("conversation:missing_idempotency_key")
            return
        record = {
            "schema_version": "1.0.0",
            "conversation_id": conversation_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "principal_scope": str(payload.get("principal_scope") or ""),
            "status": str(payload.get("status") or ""),
            "payload_digest": _payload_digest(payload),
        }
        self._conversation_sessions.set(conversation_id, record)
        await self._sync_projection_record("conversations", conversation_id, record)
        self.record_behavior("conversation:accepted")

    async def _materialize_user_preference_projection(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Bragi":
            self.record_behavior("user_preference:rejected")
            raise ValueError("Muninn user preferences MUST be published by Bragi")
        preference_id = str(payload.get("id") or payload.get("principal_scope") or "").strip()
        correlation_id = str(payload.get("correlation_id") or "").strip()
        preference_digest = str(payload.get("preference_digest") or "").strip()
        if not preference_id or not correlation_id or not preference_digest:
            self.record_behavior("user_preference:rejected")
            return
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            self.record_behavior("user_preference:missing_idempotency_key")
            return
        record = {
            "schema_version": "1.0.0",
            "id": preference_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "principal_scope": str(payload.get("principal_scope") or ""),
            "preference_digest": preference_digest,
            "revision": payload.get("revision"),
            "payload_digest": _payload_digest(payload),
        }
        self._user_preferences.set(preference_id, record)
        await self._sync_projection_record("user_preferences", preference_id, record)
        self.record_behavior("user_preference:accepted")

    def _sync_projection_bucket(
        self,
        bucket: str,
        projection: BoundedLruDict[str, dict[str, Any]],
    ) -> None:
        for key, record in projection.items():
            self.state_store.put(bucket, key, record)

    async def _sync_projection_record(
        self,
        bucket: str,
        key: str,
        record: dict[str, Any],
    ) -> None:
        self.state_store.put(bucket, key, record)
        store = self._durable_state_store
        if store is None:
            return
        state_key = f"{_PROJECTION_PREFIX}/{bucket}/{key}"
        for _attempt in range(3):
            prior = await store.read_state(state_key)
            revision = int(prior.get("revision", 0)) if prior is not None else 0
            value = {
                "kind": "muninn_conversation_projection",
                "revision": revision + 1,
                "bucket": bucket,
                "projection_key": key,
                "idempotency_key": record["idempotency_key"],
                "correlation_id": record["correlation_id"],
                "record": dict(record),
            }
            audit = {
                "kind": "muninn_conversation_projection_recorded",
                "principal": "Muninn",
                "bucket": bucket,
                "projection_key": key,
                "idempotency_key": record["idempotency_key"],
                "revision": revision + 1,
                "grants_authority": False,
            }
            if prior is None:
                if await store.write_state_with_audit_if_absent(state_key, value, audit):
                    return
                self.record_behavior("conversation_projection:cas_retry")
                continue
            if await store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=revision,
                audit_entry=audit,
            ):
                return
            self.record_behavior("conversation_projection:cas_retry")
        self.record_behavior("conversation_projection:cas_conflict")
        raise RuntimeError("Muninn conversation projection CAS did not converge")


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return canonical_json_digest(payload)


__all__ = ["MuninnConversationProjectionMixin"]
