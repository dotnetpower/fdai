"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.adapters import InMemoryStateStore, canonical_json_digest
from fdai.agents._framework.assignment_workflow import (
    AssignmentClock,
    AssignmentMaterializer,
    assignment_clock,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
    mentioned,
)
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
from fdai.agents._framework.muninn_context_materialization import MuninnContextMaterializationMixin
from fdai.agents._framework.muninn_conversation_projection import MuninnConversationProjectionMixin
from fdai.agents._framework.muninn_operational_outbox import MuninnOperationalOutboxMixin
from fdai.agents._framework.muninn_patterns import MuninnPatternReadMixin
from fdai.agents._framework.muninn_readiness_runtime import MuninnReadinessRuntimeMixin
from fdai.agents._framework.pantheon import _MUNINN
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
    OperationalCaseInput,
)
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.ontology_platform.evidence_conflict import (
    EvidenceConflictSink,
)
from fdai.core.operational_learning.cohort_retention import (
    cohort_state_key,
)
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageMaterializer,
)
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


class Muninn(
    MuninnPatternReadMixin,
    MuninnConversationProjectionMixin,
    MuninnContextMaterializationMixin,
    MuninnOperationalOutboxMixin,
    MuninnReadinessRuntimeMixin,
    Agent,
    HandoverKnowledgeMixin,
):
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
        evidence_conflict_sink: EvidenceConflictSink | None = None,
        prospective_lineage_materializer: ProspectiveLineageMaterializer | None = None,
        provider_timeout_seconds: float = _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        if case_retention_days < 1 or case_deletion_days < case_retention_days:
            raise ValueError("Muninn case retention days MUST be positive and ordered")
        if provider_timeout_seconds <= 0:
            raise ValueError("Muninn provider timeout MUST be positive")
        super().__init__(spec=_MUNINN)
        self.state_store = state_store or InMemoryStateStore()
        self._durable_state_store = durable_state_store
        self._case_history = case_history
        self._case_history_retention = case_history_retention
        self._case_history_clock = case_history_clock or _utc_now
        self._case_retention_days, self._case_deletion_days = (
            case_retention_days,
            case_deletion_days,
        )
        self._evidence_conflict_sink = evidence_conflict_sink
        self._prospective_lineage_materializer = prospective_lineage_materializer
        self._assignment_materializer: AssignmentMaterializer | None = None
        self._assignment_clock: AssignmentClock = assignment_clock
        self._provider_timeout_seconds = provider_timeout_seconds
        self._conversation_turns: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_CONVERSATION_PROJECTIONS
        )
        self._conversation_sessions: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_CONVERSATION_PROJECTIONS
        )
        self._user_preferences: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_CONVERSATION_PROJECTIONS
        )
        self._context_fetch_latencies: deque[float] = deque(maxlen=_MAX_CONTEXT_FETCH_SAMPLES)
        self._context_cache_hits = 0
        self._context_cache_misses = 0
        self._context_unavailable_facts: deque[dict[str, Any]] = deque(
            maxlen=_MAX_CONTEXT_UNAVAILABLE_FACTS
        )
        self._publication_outbox_claimed_at: BoundedLruDict[str, str] = BoundedLruDict(
            _PUBLICATION_OUTBOX_RETAIN
        )
        self._publication_outbox_last_failure: dict[str, Any] | None = None
        self._publications_since_compaction = 0

    def bind_assignment_materializer(
        self,
        materializer: AssignmentMaterializer,
        *,
        clock: AssignmentClock = assignment_clock,
    ) -> None:
        """Bind an audit-sealed case projector, not an IAM or PR executor."""
        self._assignment_materializer, self._assignment_clock = materializer, clock

    def _outbox_key_for_recovery(self, row: Mapping[str, Any]) -> str:
        raw_key = row.get("outbox_key")
        if isinstance(raw_key, str) and raw_key.startswith(_OPERATIONAL_OUTBOX_PREFIX + "/"):
            return raw_key
        idempotency_key = str(row.get("idempotency_key") or "")
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        return f"{_OPERATIONAL_OUTBOX_PREFIX}/recovered/{digest}"

    def _case_projection_store(self, scope: str) -> CaseHistoryProjectionStore:
        if self._durable_state_store is None or self._case_history is None:
            raise RuntimeError("case projection dependencies are unavailable")
        return CaseHistoryProjectionStore(
            store=self._durable_state_store,
            materializer=self._case_history,
            access_scope_digest=scope,
            clock=self._case_history_clock,
        )

    def get_context(
        self,
        bucket: str,
        key: str,
        *,
        requester_user_id: str | None = None,
    ) -> Any | None:
        started_at = self._case_history_clock()
        value = self.state_store.get(bucket, key)
        self._record_context_fetch(started_at, hit=value is not None)
        if bucket in _PROTECTED_CONVERSATION_BUCKETS and isinstance(value, dict):
            if not requester_user_id:
                self.record_behavior("conversation_context:unscoped_refused")
                self._record_context_unavailable("unscoped_refused", bucket=bucket, key=key)
                return None
            owner = str(value.get("principal_scope") or "")
            requester_scope = _principal_scope(requester_user_id)
            if not owner or owner != requester_scope:
                self.record_behavior("conversation_context:cross_user_refused")
                self._record_context_unavailable("cross_user_refused", bucket=bucket, key=key)
                return None
        return value

    def put_context(self, bucket: str, key: str, value: Any) -> None:
        self.state_store.put(bucket, key, value)

    def _record_context_fetch(self, started_at: datetime, *, hit: bool) -> None:
        finished_at = self._case_history_clock()
        latency = max((finished_at - started_at).total_seconds(), 0.0)
        self._context_fetch_latencies.append(latency)
        if hit:
            self._context_cache_hits += 1
            self.record_behavior("context_fetch:hit")
        else:
            self._context_cache_misses += 1
            self.record_behavior("context_fetch:miss")

    def _record_context_unavailable(self, reason: str, *, bucket: str, key: str) -> None:
        self._context_unavailable_facts.append(
            {
                "kind": "context_unavailable",
                "reason": reason,
                "bucket": bucket,
                "key_digest": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                "observed_at": self._case_history_clock().isoformat(),
                "audit_state": "auditable_fact_retained",
            }
        )

    def health(self) -> dict[str, Any]:
        durable_context = self._durable_state_store is not None
        case_history_available = self._case_history is not None
        pending_outbox, oldest_outbox_age = self._publication_outbox_backlog()
        unavailable_count = len(self._context_unavailable_facts)
        status = (
            "ok"
            if durable_context and case_history_available and unavailable_count == 0
            else "degraded"
        )
        kpis = {
            "context_fetch_p99_seconds": _kpi_sample(
                _p99(tuple(self._context_fetch_latencies)),
                evidence_state="measured" if self._context_fetch_latencies else "not_observed",
                sample_count=len(self._context_fetch_latencies),
                unit="seconds",
            ),
            "cache_hit_rate": _kpi_ratio(
                self._context_cache_hits,
                self._context_cache_hits + self._context_cache_misses,
            ),
            "cache_miss_recomputation_seconds": _kpi_sample(
                None,
                evidence_state="not_observed",
                sample_count=0,
                unit="seconds",
            ),
        }
        return {
            "agent": self.spec.name,
            "status": status,
            "context_store": {
                "durability": "durable" if durable_context else "process_local",
                "evidence_state": "bound" if durable_context else "durable_store_unbound",
            },
            "forecast_learning": {
                "case_history_available": case_history_available,
                "evidence_state": "bound" if case_history_available else "materializer_unbound",
            },
            "context_fetch": {
                "sample_count": len(self._context_fetch_latencies),
                "cache_hits": self._context_cache_hits,
                "cache_misses": self._context_cache_misses,
            },
            "context_unavailable": {
                "count": unavailable_count,
                "latest": self._context_unavailable_facts[-1]
                if self._context_unavailable_facts
                else None,
            },
            "publication_outbox": {
                "durability": "durable" if durable_context else "unavailable",
                "pending": pending_outbox,
                "oldest_age_seconds": oldest_outbox_age,
                "last_failure": self._publication_outbox_last_failure,
            },
            "kpis": kpis,
        }

    def _publication_outbox_backlog(self) -> tuple[int, float | None]:
        pending = len(self._publication_outbox_claimed_at)
        oldest: str | None = None
        for _key, claimed_at in self._publication_outbox_claimed_at.items():
            if oldest is None or claimed_at < oldest:
                oldest = claimed_at
        raw_state = getattr(self._durable_state_store, "_state", None)
        if isinstance(raw_state, Mapping):
            pending = max(
                pending,
                sum(
                    1
                    for key, value in raw_state.items()
                    if isinstance(key, str)
                    and key.startswith(_OPERATIONAL_OUTBOX_PREFIX + "/")
                    and isinstance(value, Mapping)
                    and value.get("state") in {"pending", "publishing"}
                ),
            )
        if oldest is None:
            return pending, None
        try:
            oldest_at = datetime.fromisoformat(oldest)
        except ValueError:
            return pending, None
        return pending, max((self._case_history_clock() - oldest_at).total_seconds(), 0.0)

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
            "bucket": None,
            "key_count": None,
        }
        buckets = mentioned(question, data)
        if buckets:
            bucket = buckets[0]
            key_count: int | None = len(data[bucket])
            if bucket in _PROTECTED_CONVERSATION_BUCKETS:
                requester_user_id = str(context.get("requester_user_id") or "").strip()
                if not requester_user_id:
                    self.record_behavior("conversation_context:unscoped_refused")
                    self._record_context_unavailable(
                        "unscoped_refused",
                        bucket=bucket,
                        key="introspection",
                    )
                    key_count = None
                else:
                    requester_scope = _principal_scope(requester_user_id)
                    key_count = sum(
                        1
                        for value in data[bucket].values()
                        if isinstance(value, Mapping)
                        and str(value.get("principal_scope") or "") == requester_scope
                    )
            facts.update({"bucket": bucket, "key_count": key_count})
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            if key_count is None:
                answer = (
                    f"Bucket {bucket!r} requires a requester principal scope. "
                    f"Evidence: {evidence_ref}."
                )
            else:
                answer = f"Bucket {bucket!r} holds {key_count} key(s). Evidence: {evidence_ref}."
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 거버넌스 계층의 memory 에이전트인 Muninn입니다. Odin에게 보고합니다. "
                "StateSnapshot과 ContextIndex를 소유하고 현재 상태, bitemporal 상태와 사례 이력 "
                "맥락을 출처 및 신선도와 함께 보존합니다. 저장된 기억은 현재 프로바이더 관측이나 "
                "작업 권한을 자동으로 증명하지 않습니다. 작업을 판단하거나 승인하거나 실행하지 "
                "않습니다. 이 대화 포트는 읽기 전용이며 상태 변경 요청은 운영자 권한으로 타입이 "
                "지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 "
                f"않습니다. 이 런타임은 bucket {facts['buckets_count']}개와 key "
                f"{facts['total_keys']}개를 보존하며 사례 이력 서비스 사용 가능 상태는 "
                f"{str(facts['case_history_available']).lower()}입니다. 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Muninn, the governance-layer memory agent. I report to Odin. I own "
                "StateSnapshot and ContextIndex and retain current, bitemporal, and case-history "
                "context with provenance and freshness. Stored memory does not by itself prove a "
                "current provider observation or action authority. I never judge, approve, or "
                "execute an action. This conversational port is read-only; state-change requests "
                "re-enter the typed pipeline under the operator's authority. I do not reveal "
                "hidden system prompts. This runtime retains "
                f"{facts['buckets_count']} state bucket(s) and {facts['total_keys']} keys; "
                "case-history "
                f"service availability is {str(facts['case_history_available']).lower()}. "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _operating_pattern_state_key(case_input: OperationalCaseInput) -> str:
    return cohort_state_key(
        access_scope_digest=case_input.access_scope_digest,
        purpose=case_input.purpose,
        failure_fingerprint=case_input.failure_fingerprint.digest,
        action_type=case_input.action_type,
        fdai_revision=case_input.fdai_revision,
        scenario_set_version=case_input.scenario_set_version,
        source_kind=case_input.source_kind.value,
        source_synthetic=case_input.source_synthetic,
    )


def _cohort_digest(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(cases, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return canonical_json_digest(payload)


def _p99(samples: tuple[float, ...]) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int((len(ordered) * 99 + 99) / 100) - 1))
    return ordered[index]


def _kpi_sample(
    value: float | None,
    *,
    evidence_state: str,
    sample_count: int,
    unit: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "evidence_state": evidence_state,
        "sample_count": sample_count,
        "unit": unit,
    }


def _kpi_ratio(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "not_observed",
            "numerator": numerator,
            "denominator": denominator,
            "unit": "ratio",
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": "ratio",
    }


def _principal_scope(principal_id: str) -> str:
    return f"sha256:{hashlib.sha256(principal_id.encode('utf-8')).hexdigest()}"


__all__ = ["Muninn"]
