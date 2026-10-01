"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE
from fdai_service_contracts.test_context import TestContextApplication

from fdai.agents._framework.action_semantics import RESULT_VALUES, outcome_result
from fdai.agents._framework.adapters import (
    AuditEntry,
    GitHubIssue,
    IdempotentIssueTrackerAdapter,
    InMemoryAuditChain,
    InMemoryGithubIssueAdapter,
    InMemoryStateStore,
    IssueTrackerAdapter,
    canonical_json_digest,
)
from fdai.agents._framework.assignment_workflow import seal_assignment
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.human_access_workflow import seal_human_access
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _SAGA
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.saga_handoff import (
    HandoffIssueCheckpoint,
    SagaHandoffJournal,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.providers.state_store import StateStore

_FINGERPRINT_BUCKET = "issue_fingerprint_index"
_AUDIT_OUTBOX_PREFIX = "pantheon/saga/audit-outbox/"
_FINGERPRINT_PREFIX = "pantheon/saga/issue-fingerprint/"
_AUDIT_OUTBOX_PENDING_SCAN_LIMIT = 5_000
# Published outbox tombstones retain only digests long enough to suppress
# duplicate redelivery across restarts while keeping prefix scans bounded.
_AUDIT_OUTBOX_TOMBSTONE_RETENTION = 1_024
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


class Saga(Agent, HandoverKnowledgeMixin):
    """Wave-2 Saga: audit chain + GitHub Issue dedup."""

    def __init__(
        self,
        *,
        audit_chain: SagaAuditChain | None = None,
        state_store: InMemoryStateStore | None = None,
        durable_state_store: StateStore | None = None,
        github: IssueTrackerAdapter | None = None,
        clock: Callable[[], datetime] = _utc_now,
        issue_timeout_seconds: float = 5.0,
    ) -> None:
        if issue_timeout_seconds <= 0:
            raise ValueError("issue timeout MUST be positive")
        super().__init__(spec=_SAGA)
        self.audit_chain: SagaAuditChain = audit_chain or InMemoryAuditChain()
        self.state_store = state_store or InMemoryStateStore()
        self._durable_state_store = durable_state_store
        self._handoff_journal = SagaHandoffJournal(
            local_store=self.state_store,
            durable_store=durable_state_store,
        )
        self._fingerprint_index: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_FINGERPRINT_INDEX
        )
        self._issue_close_eligibility: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_FINGERPRINT_INDEX
        )
        self._issue_close_promotion_evidence_producer_bound = False
        self._handoff_locks: dict[str, _RefCountedLock] = {}
        self.github = github or InMemoryGithubIssueAdapter()
        self._clock = clock
        self._issue_timeout_seconds = issue_timeout_seconds
        self._audit_outbox_pending = 0
        self._last_audit_outbox_recovered = 0
        self._last_chain_verified_entries = 0
        self._forecast_audit_keys: BoundedLruSet[str] = BoundedLruSet(_FORECAST_AUDIT_FENCE_SIZE)

    @property
    def durable_audit(self) -> bool:
        """Return whether the configured audit chain survives restart."""
        return bool(getattr(self.audit_chain, "durable", False))

    def bind_issue_close_promotion_evidence_producer(self) -> None:
        """Record that Mimir's producer seam is bound; Saga still owns closure."""

        self._issue_close_promotion_evidence_producer_bound = True

    async def rehydrate_issue_tracker(self) -> int:
        """Restore a durable issue projection when the adapter supports it."""
        rehydrate = getattr(self.github, "rehydrate", None)
        if not callable(rehydrate):
            return 0
        restored = rehydrate()
        return int(await restored if inspect.isawaitable(restored) else restored)

    async def recover_audit_outbox(self) -> int:
        """Republish durable audit-entry intents left unpublished by a crash."""

        if self._durable_state_store is None or self.bus is None:
            return 0
        rows, _total = await self._durable_state_store.read_state_page(
            _AUDIT_OUTBOX_PREFIX,
            limit=_AUDIT_OUTBOX_PENDING_SCAN_LIMIT,
            field="status",
            value="pending",
        )
        self._audit_outbox_pending = _total
        published = 0
        for row in reversed(rows):
            payload = row.get("payload")
            if not isinstance(payload, Mapping):
                raise RuntimeError("Saga audit outbox row is malformed")
            if await self._claim_audit_outbox_publication(dict(payload)):
                publish_task = asyncio.create_task(
                    self.bus.publish("Saga", "object.audit-entry", dict(payload))
                )
                try:
                    await asyncio.shield(publish_task)
                    await asyncio.shield(self._mark_audit_outbox_published(dict(payload)))
                except asyncio.CancelledError:
                    await asyncio.shield(publish_task)
                    await asyncio.shield(self._mark_audit_outbox_published(dict(payload)))
                    raise
                published += 1
        self._last_audit_outbox_recovered = published
        self._audit_outbox_pending = max(0, self._audit_outbox_pending - published)
        return published

    async def _append_audit(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        result = self.audit_chain.append(
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload=payload,
        )
        if inspect.isawaitable(result):
            await result

    async def _publish_audit_entry_with_outbox(self, payload: dict[str, Any]) -> None:
        if self._durable_state_store is None:
            if self.bus is None:
                self.record_behavior("audit_outbox:transport_unavailable")
                return
            await self.bus.publish("Saga", "object.audit-entry", payload)
            return
        await self._checkpoint_audit_outbox(payload)
        if self.bus is None:
            self.record_behavior("audit_outbox:publication_pending")
            return
        if not await self._claim_audit_outbox_publication(payload):
            return
        publish_task = asyncio.create_task(self.bus.publish("Saga", "object.audit-entry", payload))
        try:
            await asyncio.shield(publish_task)
            await asyncio.shield(self._mark_audit_outbox_published(payload))
        except asyncio.CancelledError:
            await asyncio.shield(publish_task)
            await asyncio.shield(self._mark_audit_outbox_published(payload))
            raise

    async def _checkpoint_audit_outbox(self, payload: Mapping[str, Any]) -> None:
        if self._durable_state_store is None:
            return
        key = _audit_outbox_key(payload)
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "correlation_id": str(payload.get("correlation_id") or ""),
            "idempotency_key": str(payload.get("idempotency_key") or ""),
            "payload": dict(payload),
        }
        created = await self._durable_state_store.write_state_if_absent(key, record)
        if created:
            self._audit_outbox_pending += 1
        if created:
            return
        stored = await self._durable_state_store.read_state(key)
        if not isinstance(stored, Mapping):
            raise RuntimeError("Saga audit outbox row disappeared")
        if stored.get("status") == "published":
            stored_digest = str(stored.get("payload_digest") or "")
            record_payload = record["payload"]
            if not isinstance(record_payload, Mapping):
                raise RuntimeError("Saga audit outbox row is malformed")
            payload_digest = _payload_digest(record_payload)
            if stored_digest and stored_digest != payload_digest:
                raise RuntimeError("Saga audit outbox idempotency collision")
            return
        if stored.get("payload") != record["payload"]:
            raise RuntimeError("Saga audit outbox idempotency collision")

    async def _claim_audit_outbox_publication(self, payload: Mapping[str, Any]) -> bool:
        if self._durable_state_store is None:
            return True
        key = _audit_outbox_key(payload)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None:
                raise RuntimeError("Saga audit outbox row disappeared")
            if stored.get("status") == "published":
                return False
            if stored.get("status") == "publishing":
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {**dict(stored), "status": "publishing", "revision": revision + 1},
                expected_revision=revision,
            )
            if advanced:
                return True
        raise RuntimeError("Saga audit outbox publication claim CAS retry limit exceeded")

    async def _mark_audit_outbox_published(self, payload: Mapping[str, Any]) -> None:
        if self._durable_state_store is None:
            return
        key = _audit_outbox_key(payload)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None or stored.get("status") == "published":
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                _published_audit_outbox_tombstone(stored, revision=revision + 1),
                expected_revision=revision,
            )
            if advanced:
                await self._compact_audit_outbox_tombstones()
                return
        raise RuntimeError("Saga audit outbox publication CAS retry limit exceeded")

    async def _compact_audit_outbox_tombstones(self) -> None:
        if self._durable_state_store is None:
            return
        await self._durable_state_store.delete_states_beyond(
            _AUDIT_OUTBOX_PREFIX,
            retain_newest=_AUDIT_OUTBOX_PENDING_SCAN_LIMIT + _AUDIT_OUTBOX_TOMBSTONE_RETENTION,
        )

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
            self._record_issue_close_eligibility(payload)
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
        self,
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

    def _record_issue_close_eligibility(self, payload: Mapping[str, Any]) -> None:
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
        self.record_behavior("issue_close:evidence_recorded")

    async def _republish_shadow_review(
        self,
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

    async def _materialize_handoff(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        lock_key = str(payload.get("escalation_id") or payload.get("id") or correlation_id)
        lock_entry = self._handoff_locks.get(lock_key)
        if lock_entry is None:
            lock_entry = _RefCountedLock(asyncio.Lock())
            self._handoff_locks[lock_key] = lock_entry
        lock_entry.ref_count += 1
        try:
            async with lock_entry.lock:
                await self._materialize_handoff_locked(payload, correlation_id)
        finally:
            lock_entry.ref_count -= 1
            if lock_entry.ref_count == 0 and self._handoff_locks.get(lock_key) is lock_entry:
                del self._handoff_locks[lock_key]

    async def _materialize_handoff_locked(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        escalation_id = str(payload.get("escalation_id") or payload.get("id") or "")
        emitting_agent = str(payload.get("emitting_agent") or "")
        intent_category = str(payload.get("intent_category") or "")
        resource_type = str(payload.get("resource_type") or "")
        failure_reason = str(payload.get("failure_reason_code") or "")
        normalized_selector = str(payload.get("normalized_selector") or "")
        supplied_fingerprint = str(payload.get("problem_fingerprint") or "")
        if not all(
            (escalation_id, correlation_id, emitting_agent, intent_category, failure_reason)
        ):
            self.record_behavior("handoff:invalid")
            return
        if not resource_type:
            if supplied_fingerprint:
                self.record_behavior("handoff:invalid")
                return
            resource_type = "unknown"
        if not normalized_selector:
            if supplied_fingerprint:
                self.record_behavior("handoff:invalid")
                return
            normalized_selector = stable_idempotency_key(
                "handoff-legacy-selector",
                intent_category,
                resource_type,
                emitting_agent,
                failure_reason,
            )
        if not supplied_fingerprint:
            self.record_behavior("handoff:legacy_fingerprint_computed")
        fingerprint = compute_fingerprint(
            intent_category=intent_category,
            resource_type=resource_type,
            normalized_selector=normalized_selector,
            primary_agent=emitting_agent,
            failure_reason_code=failure_reason,
        )
        if supplied_fingerprint and supplied_fingerprint != fingerprint:
            self.record_behavior("handoff:fingerprint_mismatch")
            return
        operation_id = f"handoff:{escalation_id}"
        await self._handoff_journal.claim(
            escalation_id=escalation_id,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
            operation_id=operation_id,
        )
        if await self._handoff_journal.is_complete(
            escalation_id=escalation_id,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
        ):
            self.record_behavior("handoff:duplicate")
            return
        checkpoint = await self._handoff_journal.read_checkpoint(escalation_id)
        if checkpoint is None:
            issue_number, created, occurrence_count = await self._mutate_github_issue(
                operation_id=operation_id,
                fingerprint=fingerprint,
                emitting_agent=emitting_agent,
                intent_category=intent_category,
                failure_reason_code=failure_reason,
                correlation_id=correlation_id,
                emitted_at=str(payload.get("emitted_at") or ""),
                context=_bounded_handoff_context(payload.get("context")),
                require_idempotent=True,
            )
            checkpoint = HandoffIssueCheckpoint(
                fingerprint=fingerprint,
                correlation_id=correlation_id,
                issue_number=issue_number,
                created=created,
                occurrence_count=occurrence_count,
            )
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
        elif checkpoint.fingerprint != fingerprint or checkpoint.correlation_id != correlation_id:
            raise ValueError("handoff escalation id conflicts with its mutation checkpoint")

        if not checkpoint.audit_recorded:
            await self._append_issue_audit(
                fingerprint=fingerprint,
                issue_number=checkpoint.issue_number,
                created=checkpoint.created,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
            checkpoint = checkpoint.with_audit_recorded()
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
        if not checkpoint.published:
            if self.bus is None:
                self.record_behavior("handoff:publication_pending")
                await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
                raise RuntimeError("Saga issue publication bus is unavailable")
            await self._publish_issue(
                fingerprint=fingerprint,
                issue_number=checkpoint.issue_number,
                created=checkpoint.created,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
            checkpoint = checkpoint.with_published()
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
        await self._handoff_journal.complete(escalation_id, checkpoint)
        self.record_behavior("handoff:materialized")

    async def recover_handoff_issue_publications(self) -> int:
        """Republish Saga-owned issue records whose checkpoint survived a crash."""

        if self.bus is None:
            return 0
        recovered = 0
        for escalation_id, checkpoint in await self._handoff_journal.pending_publications():
            if checkpoint.published:
                continue
            operation_id = f"handoff:{escalation_id}"
            await self._publish_issue(
                fingerprint=checkpoint.fingerprint,
                issue_number=checkpoint.issue_number,
                created=checkpoint.created,
                correlation_id=checkpoint.correlation_id,
                operation_id=operation_id,
            )
            checkpoint = checkpoint.with_published()
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
            await self._handoff_journal.complete(escalation_id, checkpoint)
            recovered += 1
        if recovered:
            self.record_behavior("handoff:publication_recovered", recovered)
        return recovered

    async def _append_ingress_retention_audit(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if not correlation_id:
            correlation_id = stable_idempotency_key(
                "ingress-retention-correlation",
                str(payload.get("idempotency_key") or ""),
                str(payload.get("event_type") or ""),
                str(payload.get("resource_id") or ""),
            )
        receipt = {
            "producer_principal": "Saga",
            "kind": "normalized_ingress_retention",
            "audited_topic": "object.event",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "audit-entry:normalized-ingress-retention",
                correlation_id,
                str(payload.get("idempotency_key") or ""),
                str(payload.get("event_type") or ""),
            ),
            "event_type": str(payload.get("event_type") or "unknown"),
            "resource_id": str(payload.get("resource_id") or ""),
            "source_id": str(payload.get("source_id") or payload.get("id") or ""),
            "judgment_state": "retained_for_replay",
            "execution_authority": False,
        }
        await self._append_audit(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id=correlation_id,
            payload=receipt,
        )
        self.record_behavior("ingress_retention:audit_recorded")

    async def _republish_forecast_outcome(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Seal a bounded forecast result onto Saga's public audit stream."""
        if self.bus is None and self._durable_state_store is None:
            self.record_behavior("forecast_outcome_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("forecast_outcome_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("forecast_outcome_audit:missing_idempotency_key")
            return
        outcome_id = str(payload.get("outcome_id") or "")
        if not outcome_id:
            self.record_behavior("forecast_outcome_audit:missing_outcome_id")
            return
        audit_idempotency_key = stable_idempotency_key(
            "audit-entry:forecast-outcome",
            outcome_id,
            idempotency_key,
        )
        if audit_idempotency_key in self._forecast_audit_keys:
            self.record_behavior("forecast_outcome_audit:duplicate")
            return
        await self._publish_audit_entry_with_outbox(
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": audit_idempotency_key,
                "audited_topic": "object.forecast-outcome",
                "action_kind": "forecast.outcome.closed",
                "outcome_id": outcome_id,
                "prediction_id": payload.get("prediction_id"),
                "detector_id": str(payload.get("detector_id") or ""),
                "detector_version": str(payload.get("detector_version") or ""),
                "access_scope_digest": str(payload.get("access_scope_digest") or ""),
                "target_digest": str(payload.get("target_digest") or ""),
                "metric": str(payload.get("metric") or ""),
                "label": str(payload.get("label") or ""),
                "evidence_refs": list(payload.get("evidence_refs") or []),
                "telemetry_completeness": str(payload.get("telemetry_completeness") or ""),
                "closed_at": str(payload.get("closed_at") or ""),
                "mode": str(payload.get("mode") or "shadow"),
            },
        )
        self._forecast_audit_keys.add(audit_idempotency_key)

    async def _republish_document_decision(
        self, payload: dict[str, Any], correlation_id: str
    ) -> None:
        """Seal a document decision before the ingestion worker may act."""
        if self.bus is None:
            self.record_behavior("document_decision_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("document_decision_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("document_decision_audit:missing_idempotency_key")
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "schema_version": "1.0.0",
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "stage": str(payload.get("stage") or ""),
                "decision": str(payload.get("decision") or "hold"),
                "reason": str(payload.get("reason") or ""),
                "document_id": str(payload.get("document_id") or ""),
                "upload_id": str(payload.get("upload_id") or ""),
                "initiator_principal": str(payload.get("initiator_principal") or ""),
            },
        )

    async def _republish_document_approval(
        self, payload: dict[str, Any], correlation_id: str
    ) -> None:
        """Seal a document approval before promotion or hold."""
        if self.bus is None:
            self.record_behavior("document_approval_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("document_approval_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("document_approval_audit:missing_idempotency_key")
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "schema_version": "1.0.0",
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.approval",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "stage": str(payload.get("stage") or "protection_check"),
                "decision": str(payload.get("state") or "rejected"),
                "reason": "human_approval",
                "document_id": str(payload.get("document_id") or ""),
                "upload_id": str(payload.get("upload_id") or ""),
                "approvers": list(payload.get("approvers") or []),
            },
        )

    async def _republish_outcome(self, payload: dict[str, Any], correlation_id: str) -> None:
        """Republish a terminal action outcome as an ``object.audit-entry``.

        Saga owns AuditEntry, so it is the writer that closes the discovery
        loop: Norns (the learner) subscribes ``object.audit-entry`` and scores
        rollback rates from these records. Only outcome-defining terminal
        states (succeeded / failed / rolled_back) are republished - one
        record per definitive outcome; intermediate lifecycle states carry no
        learnable result and are written to the append-only chain only. Saga
        does not subscribe ``object.audit-entry``, so this never loops. A
        bus-less Saga (unit scenarios) simply records to the chain.
        """
        if self.bus is None and self._durable_state_store is None:
            self.record_behavior("action_run_audit:transport_unavailable")
            return
        # Self-loop guard (defensive): never republish a record that is
        # already a republished audit-entry. Saga does not subscribe
        # object.audit-entry today, so this cannot fire - but if a future
        # change wires that subscription, the audited_topic marker stops an
        # infinite audit-of-an-audit loop.
        if payload.get("audited_topic"):
            self.record_behavior("action_run_audit:ignored_audit_entry")
            return
        # Empty correlation -> the audit-entry (a correlation-partitioned
        # topic) would carry an empty partition key, losing ordering, and
        # Norns cannot dedup it per action. The append-only chain already has
        # the record; skip the bus republish rather than emit an unkeyed one.
        if not correlation_id:
            self.record_behavior("action_run_audit:missing_correlation")
            return
        result = outcome_result(str(payload.get("state", "")))
        # Prefer a directly-stamped canonical ``result`` when present (mirrors
        # Norns' precedence, which reads ``result`` before falling back to
        # ``state``). Without this, a producer that emitted only a canonical
        # ``result`` - with a ``state`` Saga cannot map - would be dropped here
        # yet learned by Norns, an asymmetry between writer and reader.
        direct = str(payload.get("result", "")).strip().lower()
        if direct in RESULT_VALUES:
            result = direct
        action_type = str(payload.get("action_type", ""))
        state = str(payload.get("state") or "").strip().lower()
        non_learnable = result is None and state in _NON_LEARNABLE_TERMINAL_STATES
        if not action_type:
            self.record_behavior("action_run_audit:missing_action_type")
            return
        if result is None and not non_learnable:
            self.record_behavior("action_run_audit:unmappable_state")
            return
        shadow_mode = bool(payload.get("shadow_mode", False))
        if shadow_mode and result is not None:
            result = f"shadow_{result}"
        idempotency_key = stable_idempotency_key(
            "audit-entry:action-run",
            correlation_id,
            action_type,
            state,
            result,
            shadow_mode,
            payload.get("idempotency_key"),
        )
        observed_at = str(payload.get("terminal_at") or "")
        if shadow_mode and result is not None and not observed_at:
            observed_at = self._clock().isoformat()
        await self._publish_audit_entry_with_outbox(
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "audited_topic": "object.action-run",
                "action_type": action_type,
                **({"result": result} if result is not None else {}),
                "non_learnable": non_learnable,
                "resource_id": payload.get("resource_id"),
                "shadow_mode": shadow_mode,
                "shadow_observation_id": correlation_id,
                "observed_at": observed_at,
                "operator_reviewed": False,
                "operator_agreed": False,
                "policy_escape": payload.get("policy_escape") is True,
                "initiator_principal": payload.get("initiator_principal"),
            }
        )
        self.record_behavior(
            "action_run_audit:non_learnable" if non_learnable else "action_run_audit:published"
        )

    async def escalate_to_github_issue(
        self,
        *,
        fingerprint: str,
        emitting_agent: str,
        intent_category: str,
        failure_reason_code: str,
        correlation_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation_id = f"handoff:{fingerprint}:{correlation_id}"
        issue_number, created, occurrence_count = await self._mutate_github_issue(
            operation_id=operation_id,
            fingerprint=fingerprint,
            emitting_agent=emitting_agent,
            intent_category=intent_category,
            failure_reason_code=failure_reason_code,
            correlation_id=correlation_id,
            context=_bounded_handoff_context(context),
        )
        await self._append_issue_audit(
            fingerprint=fingerprint,
            issue_number=issue_number,
            created=created,
            correlation_id=correlation_id,
            operation_id=operation_id,
        )
        if self.bus is not None:
            await self._publish_issue(
                fingerprint=fingerprint,
                issue_number=issue_number,
                created=created,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
        return {
            "issue_number": issue_number,
            "created": created,
            "occurrence_count": occurrence_count,
        }

    async def _mutate_github_issue(
        self,
        *,
        operation_id: str,
        fingerprint: str,
        emitting_agent: str,
        intent_category: str,
        failure_reason_code: str,
        correlation_id: str,
        emitted_at: str = "",
        context: dict[str, Any] | None = None,
        require_idempotent: bool = False,
    ) -> tuple[int, bool, int]:
        durable_prior = await self._load_durable_fingerprint(fingerprint)
        prior = durable_prior or self._fingerprint_index.get(fingerprint)
        replay = bool(prior and prior.get("last_correlation_id") == correlation_id)
        observed_at = emitted_at or "unknown"
        first_seen = str(prior.get("first_seen") or observed_at) if prior else observed_at
        prior_count = int(prior.get("occurrence_count", 0)) if prior is not None else 0
        occurrence_count = prior_count if replay else (prior_count + 1 if prior else 1)
        last_seen = str(prior.get("last_seen") or observed_at) if replay and prior else observed_at
        labels = _fingerprint_labels(fingerprint)
        title = f"[{intent_category}] {emitting_agent} handoff"
        body_lines = [
            f"Fingerprint: `{fingerprint}`",
            f"First seen: {first_seen}",
            f"Last seen: {last_seen}",
            f"Occurrence count: {occurrence_count}",
            f"Emitting agent: {emitting_agent}",
            f"Failure reason: {failure_reason_code}",
            f"Correlation id: {correlation_id}",
        ]
        if context:
            for k, v in sorted(_bounded_handoff_context(context).items()):
                body_lines.append(f"- {k}: {v}")
        body = "\n".join(body_lines)
        if durable_prior is not None:
            await self.rehydrate_issue_tracker()
            if not isinstance(self.github, IdempotentIssueTrackerAdapter):
                raise RuntimeError("Saga durable handoff requires an idempotent issue adapter")
            issue_result = _create_or_comment_once(
                self.github,
                operation_id=operation_id,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
            )
            if inspect.isawaitable(issue_result):
                issue, _created = await asyncio.wait_for(
                    issue_result,
                    timeout=self._issue_timeout_seconds,
                )
            else:
                issue, _created = issue_result
            updated = await self._increment_durable_fingerprint(
                fingerprint,
                last_correlation_id=correlation_id,
                first_seen=first_seen,
                last_seen=last_seen,
            )
            if updated is None:
                raise RuntimeError("durable issue fingerprint disappeared during increment")
            self._fingerprint_index.set(fingerprint, updated)
            return issue.number, False, int(updated["occurrence_count"])
        if self._durable_state_store is not None and not await self._claim_fingerprint_creation(
            fingerprint,
            operation_id=operation_id,
            correlation_id=correlation_id,
        ):
            creating_operation = await self._fingerprint_creation_operation(fingerprint)
            if creating_operation == operation_id and isinstance(
                self.github, IdempotentIssueTrackerAdapter
            ):
                pass
            else:
                await self.rehydrate_issue_tracker()
                durable_after_claim = await self._load_durable_fingerprint(fingerprint)
                if durable_after_claim is not None:
                    updated = await self._increment_durable_fingerprint(
                        fingerprint,
                        last_correlation_id=correlation_id,
                        first_seen=first_seen,
                        last_seen=last_seen,
                    )
                    if updated is None:
                        raise RuntimeError("durable issue fingerprint disappeared during increment")
                    self._fingerprint_index.set(fingerprint, updated)
                    return (
                        int(updated["issue_number"]),
                        False,
                        int(updated["occurrence_count"]),
                    )
                self.record_behavior("handoff:fingerprint_claim_busy")
                raise RuntimeError("issue fingerprint mutation is already in progress")
        if isinstance(self.github, IdempotentIssueTrackerAdapter):
            issue_result = _create_or_comment_once(
                self.github,
                operation_id=operation_id,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
            )
        elif require_idempotent:
            raise RuntimeError("Saga handoff requires an idempotent issue-tracker adapter")
        else:
            issue_result = _create_or_comment(
                self.github,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
            )
        if inspect.isawaitable(issue_result):
            try:
                issue, created = await asyncio.wait_for(
                    issue_result,
                    timeout=self._issue_timeout_seconds,
                )
            except TimeoutError:
                self.record_behavior("handoff:issue_timeout")
                raise
        else:
            issue, created = issue_result
        occurrence_count = 1 + len(issue.comments)
        fingerprint_state = {
            "issue_number": issue.number,
            "occurrence_count": occurrence_count,
            "last_correlation_id": correlation_id,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "open": issue.open,
        }
        self._put_fingerprint_index(fingerprint, fingerprint_state)
        await self._put_durable_fingerprint(fingerprint, fingerprint_state)
        return issue.number, created, occurrence_count

    def _put_fingerprint_index(self, fingerprint: str, value: dict[str, Any]) -> None:
        self._fingerprint_index.set(fingerprint, value)
        self.state_store.data[_FINGERPRINT_BUCKET] = dict(self._fingerprint_index.items())

    async def _load_durable_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        if self._durable_state_store is None:
            return None
        stored = await self._durable_state_store.read_state(_fingerprint_key(fingerprint))
        if stored is None:
            return None
        if stored.get("status") == "creating":
            return None
        issue_number = stored.get("issue_number")
        occurrence_count = stored.get("occurrence_count")
        if (
            stored.get("schema_version") != "1.0.0"
            or not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number < 1
            or not isinstance(occurrence_count, int)
            or isinstance(occurrence_count, bool)
            or occurrence_count < 1
        ):
            raise RuntimeError("durable issue fingerprint record is malformed")
        return dict(stored)

    async def _claim_fingerprint_creation(
        self,
        fingerprint: str,
        *,
        operation_id: str,
        correlation_id: str,
    ) -> bool:
        if self._durable_state_store is None:
            return True
        key = _fingerprint_key(fingerprint)
        return await self._durable_state_store.write_state_if_absent(
            key,
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "fingerprint": fingerprint,
                "status": "creating",
                "operation_id": operation_id,
                "last_correlation_id": correlation_id,
            },
        )

    async def _fingerprint_creation_operation(self, fingerprint: str) -> str | None:
        if self._durable_state_store is None:
            return None
        stored = await self._durable_state_store.read_state(_fingerprint_key(fingerprint))
        if stored is None or stored.get("status") != "creating":
            return None
        operation_id = stored.get("operation_id")
        return str(operation_id) if isinstance(operation_id, str) and operation_id else None

    async def _increment_durable_fingerprint(
        self,
        fingerprint: str,
        *,
        last_correlation_id: str,
        first_seen: str,
        last_seen: str,
    ) -> dict[str, Any] | None:
        if self._durable_state_store is None:
            return None
        key = _fingerprint_key(fingerprint)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None:
                return None
            current = await self._load_durable_fingerprint(fingerprint)
            if current is None:
                return None
            revision = int(stored.get("revision", 1))
            updated = {
                **current,
                "occurrence_count": int(current["occurrence_count"]) + 1,
                "last_correlation_id": last_correlation_id,
                "first_seen": first_seen,
                "last_seen": last_seen,
            }
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {**updated, "revision": revision + 1},
                expected_revision=revision,
            )
            if advanced:
                return updated
        raise RuntimeError("issue fingerprint occurrence CAS retry limit exceeded")

    async def _put_durable_fingerprint(self, fingerprint: str, value: dict[str, Any]) -> None:
        if self._durable_state_store is None:
            return
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "fingerprint": fingerprint,
            "status": "complete",
            **value,
        }
        key = _fingerprint_key(fingerprint)
        created = await self._durable_state_store.write_state_if_absent(key, record)
        if created:
            return
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None:
                continue
            revision = int(stored.get("revision", 1))
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {**record, "revision": revision + 1},
                expected_revision=revision,
            )
            if advanced:
                return
        raise RuntimeError("issue fingerprint CAS retry limit exceeded")

    async def _append_issue_audit(
        self,
        *,
        fingerprint: str,
        issue_number: int,
        created: bool,
        correlation_id: str,
        operation_id: str,
    ) -> None:
        await self._append_audit(
            principal="Saga",
            topic="object.issue",
            correlation_id=correlation_id,
            payload={
                "idempotency_key": operation_id,
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "created": created,
            },
        )

    async def _publish_issue(
        self,
        *,
        fingerprint: str,
        issue_number: int,
        created: bool,
        correlation_id: str,
        operation_id: str,
    ) -> None:
        if self.bus is None:
            return
        await self.bus.publish(
            "Saga",
            "object.issue",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": operation_id,
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "created": created,
            },
        )

    async def close_issue(self, *, fingerprint: str, closed_by_pr: str) -> None:
        result = self.github.close(fingerprint, closed_by_pr=closed_by_pr)
        if inspect.isawaitable(result):
            await result
        state = self.state_store.get(_FINGERPRINT_BUCKET, fingerprint) or {}
        state["closed_by_pr"] = closed_by_pr
        state["open"] = False
        self._put_fingerprint_index(fingerprint, state)

    async def scan_issue_closures(self) -> int:
        closed = 0
        now = self._clock()
        for fingerprint, evidence in tuple(self._issue_close_eligibility.items()):
            if not _issue_close_evidence_is_eligible(evidence, now=now):
                continue
            fingerprint_state = await self._current_fingerprint_state(fingerprint)
            if fingerprint_state is None:
                self.record_behavior("issue_close:missing_fingerprint_state")
                continue
            if _fingerprint_recurred_since_clean(fingerprint_state, evidence):
                self.record_behavior("issue_close:recurrence_after_clean")
                continue
            issue = self.github.issues.get(fingerprint)
            if issue is None or not issue.open:
                continue
            fingerprint_state = await self._current_fingerprint_state(fingerprint)
            if fingerprint_state is None:
                self.record_behavior("issue_close:missing_fingerprint_state")
                continue
            if _fingerprint_recurred_since_clean(fingerprint_state, evidence):
                self.record_behavior("issue_close:recurrence_after_clean")
                continue
            closed_by_pr = str(evidence["promotion_pr"])
            await self.close_issue(fingerprint=fingerprint, closed_by_pr=closed_by_pr)
            correlation_id = str(evidence["correlation_id"])
            idempotency_key = stable_idempotency_key(
                "issue-auto-close",
                fingerprint,
                closed_by_pr,
                correlation_id,
            )
            await self._append_audit(
                principal="Saga",
                topic="object.issue",
                correlation_id=correlation_id,
                payload={
                    "producer_principal": "Saga",
                    "kind": "issue_auto_close",
                    "correlation_id": correlation_id,
                    "idempotency_key": idempotency_key,
                    "fingerprint": fingerprint,
                    "issue_number": issue.number,
                    "closed_by_pr": closed_by_pr,
                    "mimir_promotion_recorded_at": evidence["promotion_recorded_at"],
                    "clean_regression_started_at": evidence["clean_regression_started_at"],
                    "execution_authority": False,
                },
            )
            if self.bus is not None:
                await self._publish_issue(
                    fingerprint=fingerprint,
                    issue_number=issue.number,
                    created=False,
                    correlation_id=correlation_id,
                    operation_id=idempotency_key,
                )
            closed += 1
        if closed:
            self.record_behavior("maintenance_tick:issue_close_scan_closed", closed)
        return closed

    async def _current_fingerprint_state(self, fingerprint: str) -> dict[str, Any] | None:
        durable = await self._load_durable_fingerprint(fingerprint)
        if durable is not None:
            return durable
        local = self._fingerprint_index.get(fingerprint)
        return dict(local) if isinstance(local, Mapping) else None

    def replay_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return self.audit_chain.entries_for_correlation(correlation_id)

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        verify = getattr(self.audit_chain, "verify", None)
        if callable(verify):
            verify()
        self._last_chain_verified_entries = len(self.audit_chain.entries)
        if self._last_chain_verified_entries:
            self.record_behavior("maintenance_tick:audit_chain_verified")
        await self.scan_issue_closures()
        compacted = await self.compact_fingerprint_index()
        if compacted:
            self.record_behavior("maintenance_tick:fingerprint_index_compacted", compacted)

    async def compact_fingerprint_index(self) -> int:
        compacted = 0
        while len(self._fingerprint_index) > _FINGERPRINT_RETENTION:
            oldest = next(iter(self._fingerprint_index))
            self._fingerprint_index.pop(oldest, None)
            compacted += 1
        self.state_store.data[_FINGERPRINT_BUCKET] = dict(self._fingerprint_index.items())
        if self._durable_state_store is not None:
            compacted += await self._durable_state_store.delete_states_beyond(
                _FINGERPRINT_PREFIX,
                retain_newest=_FINGERPRINT_RETENTION,
            )
        return compacted

    def health(self) -> dict[str, Any]:
        entries = len(self.audit_chain.entries)
        durable = self.durable_audit
        verified_entries = self._last_chain_verified_entries
        integrity_kpi = (
            {
                "value": 1.0,
                "evidence_state": "measured",
                "numerator": verified_entries,
                "denominator": entries,
                "unit": "ratio",
            }
            if durable and entries > 0 and verified_entries >= entries
            else {
                "value": None,
                "evidence_state": "insufficient_sample",
                "numerator": verified_entries,
                "denominator": entries,
                "unit": "ratio",
            }
        )
        return {
            "agent": self.spec.name,
            "status": "ok" if durable else "degraded",
            "status_reason": "ready" if durable else "audit_not_durable",
            "audit_durability": "durable" if durable else "process_local",
            "audit_backend_available": True,
            "audit_entries": entries,
            "chain_verification": {
                "verified_entries": verified_entries,
                "entries": entries,
                "evidence_state": integrity_kpi["evidence_state"],
            },
            "pending_audit_outbox": self._audit_outbox_pending,
            "last_audit_outbox_recovered": self._last_audit_outbox_recovered,
            "audit_outbox_scan_limit": _AUDIT_OUTBOX_PENDING_SCAN_LIMIT,
            "fingerprint_index_size": len(self._fingerprint_index),
            "fingerprint_retention": _FINGERPRINT_RETENTION,
            "issue_auto_close": (
                "evidence_available"
                if self._issue_close_eligibility
                else "awaiting_promotion_evidence"
                if self._issue_close_promotion_evidence_producer_bound
                else "awaiting_promotion_evidence_producer"
            ),
            "issue_auto_close_producer_bound": (
                self._issue_close_promotion_evidence_producer_bound
            ),
            "issue_auto_close_evidence_count": len(self._issue_close_eligibility),
            "kpis": {"audit_chain_integrity_rate": integrity_kpi},
            "behavior": self.behavior_snapshot(),
        }

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Audit answers rest on chain entries; an empty chain proves nothing."""
        return bool(self.audit_chain.entries)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        entries = self.audit_chain.entries
        facts = {
            **capability_facts(self.spec),
            "audit_entries": len(entries),
            # The chain head is the tamper-evidence anchor: any earlier entry
            # is verifiable only against the hash that currently seals it.
            "chain_head_seq": entries[-1].seq if entries else None,
            "chain_head_hash": entries[-1].entry_hash if entries else None,
            "issues_total": len(self.github.issues),
            "issues_open": sum(1 for issue in self.github.issues.values() if issue.open),
            "fingerprint_index_size": len(self._fingerprint_index),
            "correlation_id": None,
            "matched_entries": [],
        }
        known = {e.correlation_id for e in entries if e.correlation_id}
        corr = mentioned(question, known)
        if corr:
            scoped = self.audit_chain.entries_for_correlation(corr[0])
            facts.update(
                {
                    "correlation_id": corr[0],
                    "matched_entries": [
                        {
                            "seq": e.seq,
                            "principal": e.principal,
                            "topic": e.topic,
                            "prev_hash": e.prev_hash,
                            "entry_hash": e.entry_hash,
                            "payload_digest": e.payload_digest,
                        }
                        for e in scoped
                    ],
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            actors = ", ".join(sorted({e.principal for e in scoped})) or "none"
            answer = (
                f"Correlation {corr[0]!r}: {len(scoped)} audit entr(ies), actor(s): {actors}. "
                f"Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 거버넌스 계층의 추가 전용 auditor이자 handoff-to-issue 소유자인 Saga입니다. "
                "Odin에게 보고합니다. 모든 최종 수명 주기 상태를 해시로 연결된 AuditEntry에 "
                "추가하고 중복을 제거해 필요한 Issue를 생성합니다. 저는 hard dependency이므로 "
                "감사 근거가 필요한 전이는 사용할 수 없을 때 fail-closed로 중단돼야 합니다. "
                "작업을 판단하거나 승인하거나 관리 리소스를 변경하지 않습니다. 이 대화 포트는 "
                "읽기 전용이며 작업 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 "
                "진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 않습니다. 이 런타임은 "
                f"AuditEntry {facts['audit_entries']}건, 전체 Issue {facts['issues_total']}건, "
                f"열린 Issue {facts['issues_open']}건을 기록했습니다. 근거: {evidence_ref}."
            )
        else:
            audit_state = (
                f"The latest sealed entry is sequence {facts['chain_head_seq']}."
                if entries
                else "The audit chain is empty."
            )
            answer = (
                "I am Saga, the governance-layer append-only auditor and handoff-to-issue owner. "
                "I report to Odin. I append every terminal lifecycle state to a hash-linked "
                "AuditEntry chain and deduplicate required Issue materialization. I am a hard "
                "dependency, so transitions that require audit evidence must fail closed when I "
                "am unavailable. I never judge, approve, or mutate managed resources. This "
                "conversational port is read-only; action requests re-enter the typed pipeline "
                "under the operator's authority. I do not reveal hidden system prompts. This "
                f"runtime records {facts['audit_entries']} AuditEntries, {facts['issues_total']} "
                f"Issues, and {facts['issues_open']} open Issues. {audit_state} "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


def compute_fingerprint(
    *,
    intent_category: str,
    resource_type: str,
    normalized_selector: str,
    primary_agent: str,
    failure_reason_code: str,
) -> str:
    """Deterministic SHA-256 fingerprint over the §6.4 handoff components."""
    material = "|".join(
        (
            intent_category,
            resource_type,
            normalized_selector,
            primary_agent,
            failure_reason_code,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _bounded_handoff_context(raw: Mapping[str, Any] | object | None) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    sanitized: dict[str, str] = {}
    for key, value in sorted(raw.items()):
        name = str(key)
        if name not in _HANDOFF_CONTEXT_KEYS:
            continue
        if len(sanitized) >= _MAX_HANDOFF_CONTEXT_ITEMS:
            break
        rendered = str(value).strip()
        if not rendered or len(rendered) > _MAX_HANDOFF_CONTEXT_VALUE_CHARS:
            continue
        sanitized[name] = rendered
    return sanitized


def _fingerprint_labels(fingerprint: str) -> tuple[str, ...]:
    if len(fingerprint) == 64 and all(character in "0123456789abcdef" for character in fingerprint):
        return (f"fdai:fp:{fingerprint}",)
    return ()


def _create_or_comment_once(
    github: IdempotentIssueTrackerAdapter,
    *,
    operation_id: str,
    fingerprint: str,
    title: str,
    body: str,
    labels: tuple[str, ...],
) -> tuple[GitHubIssue, bool] | Awaitable[tuple[GitHubIssue, bool]]:
    try:
        return github.create_or_comment_once(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
            labels=labels,
        )
    except TypeError as exc:
        if "labels" not in str(exc):
            raise
        return github.create_or_comment_once(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
        )


def _create_or_comment(
    github: IssueTrackerAdapter,
    *,
    fingerprint: str,
    title: str,
    body: str,
    labels: tuple[str, ...],
) -> tuple[GitHubIssue, bool] | Awaitable[tuple[GitHubIssue, bool]]:
    try:
        return github.create_or_comment(
            fingerprint=fingerprint,
            title=title,
            body=body,
            labels=labels,
        )
    except TypeError as exc:
        if "labels" not in str(exc):
            raise
        return github.create_or_comment(
            fingerprint=fingerprint,
            title=title,
            body=body,
        )


def _audit_outbox_key(payload: Mapping[str, Any]) -> str:
    correlation_id = str(payload.get("correlation_id") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    if not correlation_id or not idempotency_key:
        raise RuntimeError("Saga audit outbox payload requires correlation_id and idempotency_key")
    digest = hashlib.sha256(f"{correlation_id}\0{idempotency_key}".encode()).hexdigest()
    return f"{_AUDIT_OUTBOX_PREFIX}{digest}"


def _published_audit_outbox_tombstone(
    stored: Mapping[str, Any], *, revision: int
) -> dict[str, Any]:
    payload = stored.get("payload")
    payload_digest = (
        _payload_digest(payload)
        if isinstance(payload, Mapping)
        else str(stored.get("payload_digest") or "")
    )
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "status": "published",
        "correlation_id": str(stored.get("correlation_id") or ""),
        "idempotency_key": str(stored.get("idempotency_key") or ""),
        "payload_digest": payload_digest,
        "retention_window": str(_AUDIT_OUTBOX_TOMBSTONE_RETENTION),
    }


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return f"sha256:{canonical_json_digest(payload)}"


def _fingerprint_key(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{_FINGERPRINT_PREFIX}{digest}"


def _issue_close_evidence_is_eligible(evidence: Mapping[str, Any], *, now: datetime) -> bool:
    if not str(evidence.get("fingerprint") or "") or not str(evidence.get("promotion_pr") or ""):
        return False
    if not str(evidence.get("correlation_id") or ""):
        return False
    clean_started_raw = evidence.get("clean_regression_started_at")
    if not isinstance(clean_started_raw, str):
        return False
    try:
        clean_started = datetime.fromisoformat(clean_started_raw)
    except ValueError:
        return False
    if clean_started.tzinfo is None:
        clean_started = clean_started.replace(tzinfo=UTC)
    return now >= clean_started + _ISSUE_CLOSE_CLEAN_WINDOW


def _fingerprint_recurred_since_clean(
    fingerprint_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    clean_started_raw = evidence.get("clean_regression_started_at")
    last_seen_raw = fingerprint_state.get("last_seen")
    occurrence_count = fingerprint_state.get("occurrence_count")
    if (
        not isinstance(clean_started_raw, str)
        or not isinstance(last_seen_raw, str)
        or not isinstance(occurrence_count, int)
        or isinstance(occurrence_count, bool)
        or occurrence_count < 1
    ):
        return True
    try:
        clean_started = datetime.fromisoformat(clean_started_raw)
        last_seen = datetime.fromisoformat(last_seen_raw)
    except ValueError:
        return True
    if clean_started.tzinfo is None:
        clean_started = clean_started.replace(tzinfo=UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return occurrence_count > 1 and last_seen > clean_started


__all__ = ["Saga", "compute_fingerprint"]
