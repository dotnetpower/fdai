"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE
from fdai_service_contracts.test_context import TestContextApplication

from fdai.agents._framework.adapters import (
    AuditEntry,
    canonical_json_digest,
)
from fdai.agents._framework.assignment_workflow import seal_assignment
from fdai.agents._framework.human_access_workflow import seal_human_access
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.topics import stable_idempotency_key

_FINGERPRINT_BUCKET = "issue_fingerprint_index"
_AUDIT_OUTBOX_PREFIX = "pantheon/saga/audit-outbox/"
_FINGERPRINT_PREFIX = "pantheon/saga/issue-fingerprint/"
_ISSUE_CLOSE_ELIGIBILITY_PREFIX = "pantheon/saga/issue-close-eligibility/"
_AUDIT_OUTBOX_PENDING_SCAN_LIMIT = 5_000
_AUDIT_OUTBOX_MAINTENANCE_PAGE = 16
# Published outbox tombstones retain only digests long enough to suppress
# duplicate redelivery across restarts while keeping prefix scans bounded.
_AUDIT_OUTBOX_TOMBSTONE_RETENTION = 1_024
_AUDIT_OUTBOX_CLAIM_LEASE = timedelta(minutes=5)
_FORECAST_AUDIT_FENCE_SIZE = 10_000
_MAX_FINGERPRINT_INDEX = 50_000
_FINGERPRINT_RETENTION = 10_000
_ISSUE_CLOSE_CLEAN_WINDOW = timedelta(hours=24)
_ISSUE_CLOSE_ELIGIBILITY_BUCKET = "issue_close_eligibility"
_MAX_HANDOFF_CONTEXT_ITEMS = 8
_MAX_HANDOFF_CONTEXT_VALUE_CHARS = 256
_HANDOFF_CONTEXT_KEYS = frozenset(
    {
        "context_ref",
        "evidence_ref",
        "handoff_ref",
        "payload_digest",
        "source_ref",
        "trace_ref",
    }
)
_NON_LEARNABLE_TERMINAL_STATES = frozenset(
    {"deny_dropped", "rejected", "expired", "approval_expired"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SagaAuditChain(Protocol):
    durable: bool
    entries: list[AuditEntry]

    def append(
        self: Any,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry | Awaitable[AuditEntry]: ...

    def entries_for_correlation(self: Any, correlation_id: str) -> list[AuditEntry]: ...


@dataclass
class _RefCountedLock:
    lock: asyncio.Lock
    ref_count: int = 0


class SagaMessageRuntimeMixin:
    """Behavior-preserving extracted runtime methods."""

    async def record_rate_limit_overflow(
        self: Any,
        agent_name: str,
        topic: str,
        payload: dict[str, Any],
    ) -> None:
        """Append one rate-limit overflow record to Saga's chain.

        Bound through the runtime as a callback. Saga does not import or call
        the overflowing member directly, and the record grants no authority.
        """
        correlation_id = str(payload.get("correlation_id") or "")
        try:
            payload_digest: str | None = canonical_json_digest(payload)
            payload_digest_state = "measured"
            payload_digest_error = None
        except (TypeError, ValueError) as exc:
            self.record_behavior("rate_limit_overflow:payload_digest_unavailable")
            payload_digest = None
            payload_digest_state = "non_json_rejected"
            payload_digest_error = type(exc).__name__
        if not correlation_id:
            correlation_id = stable_idempotency_key(
                "rate-limit-exceeded:correlation",
                agent_name,
                topic,
                payload_digest,
                payload_digest_state,
            )
        idempotency_key = stable_idempotency_key(
            "rate-limit-exceeded",
            agent_name,
            topic,
            correlation_id,
            payload_digest,
            payload_digest_state,
        )
        audit_payload = {
            "producer_principal": "Saga",
            "kind": "rate_limit_exceeded",
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "overflowing_agent": agent_name,
            "overflowed_topic": topic,
            "payload_digest": payload_digest,
            "payload_digest_evidence_state": payload_digest_state,
            "payload_digest_error": payload_digest_error,
            "dropped_count": 1,
            "non_learnable": True,
            "execution_authority": False,
        }
        await self._append_audit(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id=correlation_id,
            payload=audit_payload,
        )
        await self._publish_audit_entry_with_outbox(audit_payload)
        self.record_behavior("rate_limit_exceeded:audit_published")

    async def on_typed_message(self: Any, topic: str, payload: dict[str, Any]) -> None:
        """Authenticate every audited topic before appending it.

        Rejected records are not appended: the append-only chain remains a
        truthful record of authenticated owner-produced facts, while the
        rejection is counted as behavior telemetry instead of being made to
        look like a valid audit fact.
        """

        if topic.startswith("object.") and require_topic_owner(
            self,
            topic,
            payload,
            behavior="typed_message:rejected_owner",
        ):
            return
        principal = str(payload.get("producer_principal", "unknown"))
        correlation_id = str(payload.get("correlation_id") or "")
        self.record_behavior("typed_message:accepted")
        if (
            topic == "object.event"
            and payload.get("event_type") != INCIDENT_INTERVENTION_EVENT_TYPE
        ):
            await self._append_ingress_retention_audit(payload, correlation_id)
            return
        await self._append_audit(
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload=payload,
        )
        if payload.get("kind") == "ontology_context_index":
            return
        if await self._handover_message(topic, payload):
            return
        if payload.get("kind") == "human_access_execution":
            await seal_human_access(self, topic, payload)
            return
        if payload.get("kind") == "human_assignment":
            await seal_assignment(self, topic, payload)
            return
        if topic == "object.verdict" and payload.get("kind") == "document_ingestion":
            await self._republish_document_decision(payload, correlation_id)
        if topic == "object.approval" and payload.get("kind") == "document_ingestion":
            await self._republish_document_approval(payload, correlation_id)
        if topic == "object.approval" and payload.get("kind") == "shadow_outcome_review":
            await self._republish_shadow_review(payload, correlation_id)
        if topic == "object.action-run":
            await self._republish_outcome(payload, correlation_id)
        if topic == "object.forecast-outcome":
            await self._republish_forecast_outcome(payload, correlation_id)
        if topic == "object.rule" and payload.get("kind") == "catalog_review_outcome":
            await self._record_issue_close_eligibility(payload)
            await self._republish_catalog_review_outcome(payload, correlation_id)
        if topic == "object.policy" and payload.get("kind") == "test_context_revision":
            if principal != "Mimir" or self.bus is None:
                raise ValueError(
                    "context application requires Mimir policy and Saga audit transport"
                )
            application = TestContextApplication.model_validate(payload.get("application"))
            if application.request_key != correlation_id:
                raise ValueError("context application correlation mismatch")
            await self.bus.publish(
                "Saga",
                "object.audit-entry",
                {
                    "kind": "test_context_application",
                    "audited_topic": "object.policy",
                    "correlation_id": correlation_id,
                    "idempotency_key": "test-context-application:" + application.command_digest,
                    "application": application.model_dump(mode="json"),
                    "execution_authority": False,
                },
            )
        if topic == "object.handoff-escalation":
            if payload.get("kind") == "operator_proposal_denied":
                self.record_behavior("handoff:operator_proposal_denied_audited")
                return
            await self._materialize_handoff(payload, correlation_id)
        if topic == "object.prospective-lineage":
            await self._republish_prospective_lineage(payload, correlation_id)

    async def _republish_prospective_lineage(
        self: Any,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if self.bus is None:
            raise RuntimeError("Saga prospective-lineage audit bus is unavailable")
        lineage_id = str(payload.get("id") or "")
        subgraph_digest = str(payload.get("subgraph_digest") or "")
        if (
            payload.get("producer_principal") != "Forseti"
            or not correlation_id
            or not lineage_id
            or not subgraph_digest
        ):
            raise ValueError("prospective-lineage audit payload is invalid")
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": f"prospective-lineage-seal:{lineage_id}",
                "audited_topic": "object.prospective-lineage",
                "action_kind": "prospective_lineage.sealed",
                "lineage_id": lineage_id,
                "proposal_id": str(payload.get("proposal_id") or ""),
                "subgraph_digest": subgraph_digest,
                "execution_authority": False,
            },
        )

    async def _republish_catalog_review_outcome(
        self: Any,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if self.bus is None:
            self.record_behavior("catalog_review_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("catalog_review_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("catalog_review_audit:missing_idempotency_key")
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "audited_topic": "object.rule",
                "action_kind": "catalog_review.outcome",
                "candidate_digest": payload.get("candidate_digest"),
                "package_digest": payload.get("package_digest"),
                "outcome": str(payload.get("outcome") or ""),
                "reason": str(payload.get("reason") or ""),
                "review_ref": payload.get("review_ref"),
                "mode": "shadow",
            },
        )

    async def _record_issue_close_eligibility(self: Any, payload: Mapping[str, Any]) -> None:
        fingerprint = str(payload.get("problem_fingerprint") or payload.get("fingerprint") or "")
        promotion_pr = str(payload.get("promotion_pr") or payload.get("promotion_pr_url") or "")
        clean_started = str(
            payload.get("clean_regression_started_at")
            or payload.get("clean_regression_tests_started_at")
            or ""
        )
        outcome = str(payload.get("outcome") or "").strip().lower()
        correlation_id = str(payload.get("correlation_id") or "")
        if (
            payload.get("producer_principal") != "Mimir"
            or outcome not in {"promoted", "promotion_succeeded"}
            or not fingerprint
            or not promotion_pr
            or not clean_started
            or not correlation_id
        ):
            return
        evidence = {
            "fingerprint": fingerprint,
            "promotion_pr": promotion_pr,
            "clean_regression_started_at": clean_started,
            "promotion_recorded_at": self._clock().isoformat(),
            "correlation_id": correlation_id,
        }
        self._issue_close_eligibility.set(fingerprint, evidence)
        self.state_store.data[_ISSUE_CLOSE_ELIGIBILITY_BUCKET] = dict(
            self._issue_close_eligibility.items()
        )
        if self._durable_state_store is not None:
            await self._durable_state_store.write_state(
                _issue_close_eligibility_key(fingerprint),
                evidence,
            )
            await self._durable_state_store.delete_states_beyond(
                _ISSUE_CLOSE_ELIGIBILITY_PREFIX,
                retain_newest=_MAX_FINGERPRINT_INDEX,
            )
        self.record_behavior("issue_close:evidence_recorded")

    async def rehydrate_issue_close_eligibility(self: Any) -> int:
        if self._durable_state_store is None:
            self._issue_close_eligibility_rehydrated = True
            self._last_issue_close_eligibility_recovered = 0
            return 0
        rows = await self._durable_state_store.read_states(
            _ISSUE_CLOSE_ELIGIBILITY_PREFIX,
            limit=_MAX_FINGERPRINT_INDEX,
        )
        recovered = 0
        for row in reversed(rows):
            fingerprint = str(row.get("fingerprint") or "")
            if not fingerprint:
                continue
            self._issue_close_eligibility.set(fingerprint, dict(row))
            recovered += 1
        self.state_store.data[_ISSUE_CLOSE_ELIGIBILITY_BUCKET] = dict(
            self._issue_close_eligibility.items()
        )
        self._issue_close_eligibility_rehydrated = True
        self._last_issue_close_eligibility_recovered = recovered
        if recovered:
            self.record_behavior("issue_close:evidence_rehydrated", recovered)
        return recovered

    async def _republish_shadow_review(
        self: Any,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if self.bus is None or not correlation_id:
            return
        if (
            payload.get("producer_principal") != "Var"
            or payload.get("operator_reviewed") is not True
            or not isinstance(payload.get("operator_agreed"), bool)
            or not isinstance(payload.get("policy_escape"), bool)
            or not str(payload.get("action_type") or "")
            or not str(payload.get("shadow_observation_id") or "")
            or not str(payload.get("observed_at") or "")
        ):
            raise ValueError("shadow outcome review approval is malformed")
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": str(payload.get("idempotency_key") or ""),
                "audited_topic": "object.approval",
                "action_type": str(payload["action_type"]),
                "shadow_mode": True,
                "shadow_observation_id": str(payload["shadow_observation_id"]),
                "shadow_review_update": True,
                "observed_at": str(payload["observed_at"]),
                "operator_reviewed": True,
                "operator_agreed": bool(payload["operator_agreed"]),
                "policy_escape": bool(payload["policy_escape"]),
            },
        )


def _issue_close_eligibility_key(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{_ISSUE_CLOSE_ELIGIBILITY_PREFIX}{digest}"


__all__ = ["SagaMessageRuntimeMixin"]
