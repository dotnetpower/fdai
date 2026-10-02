"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

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
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.forseti_baseline_evaluation import (
    BaselineEvaluationAuditReference,
)
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.outbox_publication import (
    claim_expired,
)
from fdai.agents._framework.pantheon import _SAGA
from fdai.agents._framework.saga_audit_runtime import SagaAuditRuntimeMixin
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
from fdai.agents._framework.saga_handoff import (
    SagaHandoffJournal,
)
from fdai.agents._framework.saga_handoff_runtime import SagaHandoffRuntimeMixin
from fdai.agents._framework.saga_issue_maintenance import SagaIssueMaintenanceMixin
from fdai.agents._framework.saga_issue_runtime import SagaIssueRuntimeMixin
from fdai.agents._framework.saga_message_runtime import SagaMessageRuntimeMixin
from fdai.shared.providers.state_store import StateStore


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


class Saga(
    SagaAuditRuntimeMixin,
    SagaMessageRuntimeMixin,
    SagaHandoffRuntimeMixin,
    SagaIssueRuntimeMixin,
    SagaIssueMaintenanceMixin,
    Agent,
    HandoverKnowledgeMixin,
):
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
        self._issue_close_eligibility_rehydrated = False
        self._last_issue_close_eligibility_recovered = 0
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

    async def close_issue(self, *, fingerprint: str, closed_by_pr: str) -> None:
        await super().close_issue(fingerprint=fingerprint, closed_by_pr=closed_by_pr)

    async def bind_baseline_evaluation_audit(
        self, record: Mapping[str, Any]
    ) -> BaselineEvaluationAuditReference:
        """Append Saga-owned audit evidence for one baseline evaluation record."""

        kind = record.get("kind")
        if kind not in {"baseline_evaluation.outcome", "baseline_evaluation.completion"}:
            raise ValueError("baseline evaluation audit record kind is invalid")
        payload = {
            "schema_version": "1.0.0",
            "kind": kind,
            "record": dict(record),
            "recorded_at": self._clock().isoformat(),
            "owner_agent": "Saga",
            "execution_authority": False,
        }
        payload_digest = "sha256:" + canonical_json_digest(payload)
        audit_ref = "audit:" + payload_digest[7:39]
        audit_entry = {
            "action_kind": "baseline_evaluation.audit_bound",
            "audit_ref": audit_ref,
            "audit_digest": payload_digest,
            "payload": payload,
            "execution_authority": False,
        }
        if self._durable_state_store is not None:
            await self._durable_state_store.append_audit_entry(audit_entry)
        appended = self.audit_chain.append(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id=audit_ref,
            payload=audit_entry,
        )
        if inspect.isawaitable(appended):
            await appended
        return BaselineEvaluationAuditReference(ref=audit_ref, digest=payload_digest)

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


def _audit_outbox_claim_expired(row: Mapping[str, Any], now: datetime) -> bool:
    return claim_expired(
        claimed_at=row.get("claimed_at"),
        now=now,
        lease=_AUDIT_OUTBOX_CLAIM_LEASE,
    )


def _fingerprint_key(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{_FINGERPRINT_PREFIX}{digest}"


def _issue_close_eligibility_key(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{_ISSUE_CLOSE_ELIGIBILITY_PREFIX}{digest}"


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
