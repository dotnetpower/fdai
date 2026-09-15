"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable
from typing import Any, Protocol

from fdai_service_contracts.test_context import TestContextApplication

from fdai.agents._framework.action_semantics import RESULT_VALUES, outcome_result
from fdai.agents._framework.adapters import (
    AuditEntry,
    IdempotentIssueTrackerAdapter,
    InMemoryAuditChain,
    InMemoryGithubIssueAdapter,
    InMemoryStateStore,
    IssueTrackerAdapter,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _SAGA
from fdai.agents._framework.saga_handoff import (
    HandoffIssueCheckpoint,
    SagaHandoffJournal,
)
from fdai.shared.providers.state_store import StateStore

_FINGERPRINT_BUCKET = "issue_fingerprint_index"


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


class Saga(Agent):
    """Wave-2 Saga: audit chain + GitHub Issue dedup."""

    def __init__(
        self,
        *,
        audit_chain: SagaAuditChain | None = None,
        state_store: InMemoryStateStore | None = None,
        durable_state_store: StateStore | None = None,
        github: IssueTrackerAdapter | None = None,
    ) -> None:
        super().__init__(spec=_SAGA)
        self.audit_chain: SagaAuditChain = audit_chain or InMemoryAuditChain()
        self.state_store = state_store or InMemoryStateStore()
        self._durable_state_store = durable_state_store
        self._handoff_journal = SagaHandoffJournal(
            local_store=self.state_store,
            durable_store=durable_state_store,
        )
        self._handoff_lock = asyncio.Lock()
        self.github = github or InMemoryGithubIssueAdapter()

    @property
    def durable_audit(self) -> bool:
        """Return whether the configured audit chain survives restart."""
        return bool(getattr(self.audit_chain, "durable", False))

    async def rehydrate_issue_tracker(self) -> int:
        """Restore a durable issue projection when the adapter supports it."""
        rehydrate = getattr(self.github, "rehydrate", None)
        if not callable(rehydrate):
            return 0
        restored = rehydrate()
        return int(await restored if inspect.isawaitable(restored) else restored)

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

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        principal = str(payload.get("producer_principal", "unknown"))
        correlation_id = str(payload.get("correlation_id") or "")
        await self._append_audit(
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload=payload,
        )
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
            await self._republish_catalog_review_outcome(payload, correlation_id)
        if topic == "object.policy" and payload.get("kind") == "test_context_revision":
            if principal != "Mimir" or self.bus is None:
                raise ValueError("context application requires Mimir policy and Saga audit transport")
            application = TestContextApplication.model_validate(payload.get("application"))
            if application.request_key != correlation_id:
                raise ValueError("context application correlation mismatch")
            await self.bus.publish("Saga", "object.audit-entry", {
                "kind": "test_context_application", "audited_topic": "object.policy",
                "correlation_id": correlation_id,
                "idempotency_key": "test-context-application:" + application.command_digest,
                "application": application.model_dump(mode="json"),
                "execution_authority": False,
            })
        if topic == "object.handoff-escalation":
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
        if self.bus is None or not correlation_id:
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": str(payload.get("idempotency_key") or ""),
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
        async with self._handoff_lock:
            await self._materialize_handoff_locked(payload, correlation_id)

    async def _materialize_handoff_locked(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        escalation_id = str(payload.get("escalation_id") or payload.get("id") or "")
        emitting_agent = str(payload.get("emitting_agent") or "")
        intent_category = str(payload.get("intent_category") or "")
        failure_reason = str(payload.get("failure_reason_code") or "")
        normalized_selector = str(payload.get("normalized_selector") or "")
        if not all(
            (escalation_id, correlation_id, emitting_agent, intent_category, failure_reason)
        ):
            self.record_behavior("handoff:invalid")
            return
        fingerprint = compute_fingerprint(
            intent_category=intent_category,
            resource_type=str(payload.get("resource_type") or ""),
            normalized_selector=normalized_selector,
            primary_agent=emitting_agent,
            failure_reason_code=failure_reason,
        )
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
        if self.bus is None:
            self.record_behavior("handoff:publication_pending")
            raise RuntimeError("Saga issue publication bus is unavailable")
        if not checkpoint.published:
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

    async def _republish_forecast_outcome(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Seal a bounded forecast result onto Saga's public audit stream."""
        if self.bus is None or not correlation_id:
            return
        outcome_id = str(payload.get("outcome_id") or "")
        if not outcome_id:
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": str(payload.get("idempotency_key") or ""),
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

    async def _republish_document_decision(
        self, payload: dict[str, Any], correlation_id: str
    ) -> None:
        """Seal a document decision before the ingestion worker may act."""
        if self.bus is None or not correlation_id:
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
                "idempotency_key": str(payload.get("idempotency_key") or ""),
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
        if self.bus is None or not correlation_id:
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
                "idempotency_key": str(payload.get("idempotency_key") or ""),
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
        if self.bus is None:
            return
        # Self-loop guard (defensive): never republish a record that is
        # already a republished audit-entry. Saga does not subscribe
        # object.audit-entry today, so this cannot fire - but if a future
        # change wires that subscription, the audited_topic marker stops an
        # infinite audit-of-an-audit loop.
        if payload.get("audited_topic"):
            return
        # Empty correlation -> the audit-entry (a correlation-partitioned
        # topic) would carry an empty partition key, losing ordering, and
        # Norns cannot dedup it per action. The append-only chain already has
        # the record; skip the bus republish rather than emit an unkeyed one.
        if not correlation_id:
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
        if result is None or not action_type:
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "audited_topic": "object.action-run",
                "action_type": action_type,
                "result": result,
                "resource_id": payload.get("resource_id"),
                # Carry the shadow flag so the learner can tell a real
                # execution from a judged-and-logged shadow one (a shadow
                # 'success' is not evidence about the action's real safety).
                "shadow_mode": bool(payload.get("shadow_mode", False)),
                "shadow_observation_id": correlation_id,
                "observed_at": str(payload.get("terminal_at") or ""),
                "operator_reviewed": False,
                "operator_agreed": False,
                "policy_escape": payload.get("policy_escape") is True,
                "initiator_principal": payload.get("initiator_principal"),
            },
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
            context=context,
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
        context: dict[str, Any] | None = None,
        require_idempotent: bool = False,
    ) -> tuple[int, bool, int]:
        title = f"[{intent_category}] {emitting_agent} handoff"
        body_lines = [
            f"Fingerprint: `{fingerprint}`",
            f"Emitting agent: {emitting_agent}",
            f"Failure reason: {failure_reason_code}",
            f"Correlation id: {correlation_id}",
        ]
        if context:
            for k, v in sorted(context.items()):
                body_lines.append(f"- {k}: {v}")
        body = "\n".join(body_lines)

        if isinstance(self.github, IdempotentIssueTrackerAdapter):
            issue_result = self.github.create_or_comment_once(
                operation_id=operation_id,
                fingerprint=fingerprint,
                title=title,
                body=body,
            )
        elif require_idempotent:
            raise RuntimeError("Saga handoff requires an idempotent issue-tracker adapter")
        else:
            issue_result = self.github.create_or_comment(
                fingerprint=fingerprint,
                title=title,
                body=body,
            )
        issue, created = await issue_result if inspect.isawaitable(issue_result) else issue_result
        occurrence_count = 1 + len(issue.comments)
        self.state_store.put(
            _FINGERPRINT_BUCKET,
            fingerprint,
            {
                "issue_number": issue.number,
                "occurrence_count": occurrence_count,
                "last_correlation_id": correlation_id,
            },
        )
        return issue.number, created, occurrence_count

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
        self.state_store.put(_FINGERPRINT_BUCKET, fingerprint, state)

    def replay_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return self.audit_chain.entries_for_correlation(correlation_id)

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
    """Deterministic fingerprint per `agent-pantheon.md` \u00a76.4."""
    material = "|".join(
        (
            intent_category,
            resource_type,
            normalized_selector,
            primary_agent,
            failure_reason_code,
        )
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()  # noqa: S324 - fingerprint id, not security


__all__ = ["Saga", "compute_fingerprint"]
