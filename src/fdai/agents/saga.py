"""Saga - Auditor (Wave 2 behavior).

Saga is the append-only audit principal and executor of
`governance.escalate-to-github-issue`. Every terminal state a topic
emits (verdict, action-run, rollback, approval, security-event) is
recorded on the audit chain by Saga's typed handler.
"""

from __future__ import annotations

import hashlib
import inspect
from typing import Any

from fdai.agents._framework.action_semantics import RESULT_VALUES, outcome_result
from fdai.agents._framework.adapters import (
    AuditEntry,
    InMemoryAuditChain,
    InMemoryGithubIssueAdapter,
    InMemoryStateStore,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _SAGA

_FINGERPRINT_BUCKET = "issue_fingerprint_index"


class Saga(Agent):
    """Wave-2 Saga: audit chain + GitHub Issue dedup."""

    def __init__(
        self,
        *,
        audit_chain: InMemoryAuditChain | None = None,
        state_store: InMemoryStateStore | None = None,
        github: InMemoryGithubIssueAdapter | None = None,
    ) -> None:
        super().__init__(spec=_SAGA)
        self.audit_chain = audit_chain or InMemoryAuditChain()
        self.state_store = state_store or InMemoryStateStore()
        self.github = github or InMemoryGithubIssueAdapter()

    @property
    def durable_audit(self) -> bool:
        """Return whether the configured audit chain survives restart."""
        return bool(getattr(self.audit_chain, "durable", False))

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
        correlation_id = str(payload.get("correlation_id", ""))
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
        if topic == "object.action-run":
            await self._republish_outcome(payload, correlation_id)

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

        issue, created = self.github.create_or_comment(
            fingerprint=fingerprint,
            title=title,
            body=body,
        )
        self.state_store.put(
            _FINGERPRINT_BUCKET,
            fingerprint,
            {
                "issue_number": issue.number,
                "occurrence_count": 1 + len(issue.comments),
                "last_correlation_id": correlation_id,
            },
        )
        await self._append_audit(
            principal="Saga",
            topic="object.issue",
            correlation_id=correlation_id,
            payload={
                "fingerprint": fingerprint,
                "issue_number": issue.number,
                "created": created,
            },
        )
        # Publish object.issue onto the bus (Saga is the single writer of the
        # Issue object type) so the discovery loop's fingerprint learner
        # (Norns) can count recurring handoffs and propose a new rule. A
        # bus-less Saga (unit scenarios) records to the append-only chain only.
        if self.bus is not None:
            await self.bus.publish(
                "Saga",
                "object.issue",
                {
                    "producer_principal": "Saga",
                    "correlation_id": correlation_id,
                    "fingerprint": fingerprint,
                    "issue_number": issue.number,
                    "created": created,
                },
            )
        return {
            "issue_number": issue.number,
            "created": created,
            "occurrence_count": 1 + len(issue.comments),
        }

    def close_issue(self, *, fingerprint: str, closed_by_pr: str) -> None:
        self.github.close(fingerprint, closed_by_pr=closed_by_pr)
        state = self.state_store.get(_FINGERPRINT_BUCKET, fingerprint) or {}
        state["closed_by_pr"] = closed_by_pr
        self.state_store.put(_FINGERPRINT_BUCKET, fingerprint, state)

    def replay_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return self.audit_chain.entries_for_correlation(correlation_id)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        entries = self.audit_chain.entries
        facts = {
            **capability_facts(self.spec),
            "audit_entries": len(entries),
        }
        known = {e.correlation_id for e in entries if e.correlation_id}
        corr = mentioned(question, known)
        if corr:
            scoped = self.audit_chain.entries_for_correlation(corr[0])
            facts.update(
                {
                    "correlation_id": corr[0],
                    "matched_entries": [
                        {"seq": e.seq, "principal": e.principal, "topic": e.topic} for e in scoped
                    ],
                }
            )
            actors = ", ".join(sorted({e.principal for e in scoped})) or "none"
            answer = f"Correlation {corr[0]!r}: {len(scoped)} audit entr(ies), actor(s): {actors}."
            return IntrospectionResult(answer=answer, facts=facts)
        if not entries:
            answer = (
                "Audit chain is empty; I record every terminal action-lifecycle "
                "event on an append-only chain."
            )
        else:
            last = entries[-1]
            answer = (
                f"{len(entries)} audit entr(ies) recorded; latest: {last.principal} "
                f"-> {last.topic}."
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
