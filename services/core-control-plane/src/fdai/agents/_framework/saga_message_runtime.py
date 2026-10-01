"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE
from fdai_service_contracts.test_context import TestContextApplication

from fdai.agents._framework.adapters import (
    AuditEntry,
    canonical_json_digest,
)
from fdai.agents._framework.assignment_workflow import seal_assignment
from fdai.agents._framework.human_access_workflow import seal_human_access
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_CLAIM_LEASE as _AUDIT_OUTBOX_CLAIM_LEASE,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_MAINTENANCE_PAGE as _AUDIT_OUTBOX_MAINTENANCE_PAGE,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_PENDING_SCAN_LIMIT as _AUDIT_OUTBOX_PENDING_SCAN_LIMIT,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_PREFIX as _AUDIT_OUTBOX_PREFIX,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_TOMBSTONE_RETENTION as _AUDIT_OUTBOX_TOMBSTONE_RETENTION,
)
from fdai.agents._framework.saga_constants import (
    _FINGERPRINT_BUCKET as _FINGERPRINT_BUCKET,
)
from fdai.agents._framework.saga_constants import (
    _FINGERPRINT_PREFIX as _FINGERPRINT_PREFIX,
)
from fdai.agents._framework.saga_constants import (
    _FINGERPRINT_RETENTION as _FINGERPRINT_RETENTION,
)
from fdai.agents._framework.saga_constants import (
    _FORECAST_AUDIT_FENCE_SIZE as _FORECAST_AUDIT_FENCE_SIZE,
)
from fdai.agents._framework.saga_constants import (
    _HANDOFF_CONTEXT_KEYS as _HANDOFF_CONTEXT_KEYS,
)
from fdai.agents._framework.saga_constants import (
    _ISSUE_CLOSE_CLEAN_WINDOW as _ISSUE_CLOSE_CLEAN_WINDOW,
)
from fdai.agents._framework.saga_constants import (
    _ISSUE_CLOSE_ELIGIBILITY_BUCKET as _ISSUE_CLOSE_ELIGIBILITY_BUCKET,
)
from fdai.agents._framework.saga_constants import (
    _ISSUE_CLOSE_ELIGIBILITY_PREFIX as _ISSUE_CLOSE_ELIGIBILITY_PREFIX,
)
from fdai.agents._framework.saga_constants import (
    _MAX_FINGERPRINT_INDEX as _MAX_FINGERPRINT_INDEX,
)
from fdai.agents._framework.saga_constants import (
    _MAX_HANDOFF_CONTEXT_ITEMS as _MAX_HANDOFF_CONTEXT_ITEMS,
)
from fdai.agents._framework.saga_constants import (
    _MAX_HANDOFF_CONTEXT_VALUE_CHARS as _MAX_HANDOFF_CONTEXT_VALUE_CHARS,
)
from fdai.agents._framework.saga_constants import (
    _NON_LEARNABLE_TERMINAL_STATES as _NON_LEARNABLE_TERMINAL_STATES,
)
from fdai.agents._framework.topics import stable_idempotency_key

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SagaAuditChain(Protocol):
    durable: bool
    entries: list[AuditEntry]

    def append(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry | Awaitable[AuditEntry]: ...

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]: ...


@dataclass
class _RefCountedLock:
    lock: asyncio.Lock
    ref_count: int = 0


class SagaMessageRuntimeMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _append_audit: Any
        _append_ingress_retention_audit: Any
        _append_issue_audit: Any
        _audit_outbox_pending: Any
        _clock: Any
        _durable_state_store: Any
        _fingerprint_index: Any
        _forecast_audit_keys: Any
        _handoff_journal: Any
        _handoff_locks: Any
        _handover_message: Any
        _issue_close_eligibility: Any
        _issue_close_eligibility_rehydrated: Any
        _issue_close_promotion_evidence_producer_bound: Any
        _issue_timeout_seconds: Any
        _last_audit_outbox_recovered: Any
        _last_issue_close_eligibility_recovered: Any
        _load_durable_fingerprint: Any
        _materialize_handoff: Any
        _mutate_github_issue: Any
        _publish_audit_entry_with_outbox: Any
        _publish_issue: Any
        _put_fingerprint_index: Any
        _republish_document_approval: Any
        _republish_document_decision: Any
        _republish_forecast_outcome: Any
        _republish_outcome: Any
        audit_chain: Any
        durable_audit: Any
        github: Any
        recover_audit_outbox: Any
        rehydrate_issue_tracker: Any
        state_store: Any

    async def record_rate_limit_overflow(
        self,
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

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
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
            if principal != "Mimir":
                raise ValueError("context application requires Mimir policy")
            application = TestContextApplication.model_validate(payload.get("application"))
            if application.request_key != correlation_id:
                raise ValueError("context application correlation mismatch")
            await self._publish_audit_entry_with_outbox(
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
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        lineage_id = str(payload.get("id") or "")
        subgraph_digest = str(payload.get("subgraph_digest") or "")
        if (
            payload.get("producer_principal") != "Forseti"
            or not correlation_id
            or not lineage_id
            or not subgraph_digest
        ):
            raise ValueError("prospective-lineage audit payload is invalid")
        await self._publish_audit_entry_with_outbox(
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
        self,
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

    async def _record_issue_close_eligibility(self, payload: Mapping[str, Any]) -> None:
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

    async def rehydrate_issue_close_eligibility(self) -> int:
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
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if not correlation_id:
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
        await self._publish_audit_entry_with_outbox(
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
