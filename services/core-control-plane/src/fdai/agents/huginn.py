"""Huginn - Event Collector (Wave 3 behavior).

Huginn normalizes incoming raw signals into `Event` payloads, dedups
by stable key, and publishes to `object.event`. Wave 3 implements the
in-process ingestion; adapter integration for Azure Activity Log lives
behind a provider protocol added in a later wave.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.huginn_dedup import HuginnDedupJournal
from fdai.agents._framework.huginn_ingress_helpers import (
    _DEDUP_CAPACITY,
    _MAX_KPI_SAMPLES,
    _MAX_OPERATIONAL_CASE_ERRORS,
    DiscoveryProjector,
    HuginnIngressRejected,
)
from fdai.agents._framework.huginn_ingress_helpers import (
    _MAX_ATTR_KEYS as _MAX_ATTR_KEYS,
)
from fdai.agents._framework.huginn_ingress_helpers import (
    _MAX_FIELD_CHARS as _MAX_FIELD_CHARS,
)
from fdai.agents._framework.huginn_ingress_helpers import (
    HuginnIngressRejectedError as HuginnIngressRejectedError,
)
from fdai.agents._framework.huginn_ingress_runtime import HuginnIngressMixin
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.huginn_schema_learning import HuginnSchemaLearningLedger
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.pantheon import _HUGINN
from fdai.shared.providers.state_store import StateStore

_AlertNoisePayload = Mapping[str, Any]
_AlertNoiseVerifier = Callable[[_AlertNoisePayload], object]


class Huginn(HuginnIngressMixin, Agent):
    """Wave-3 Huginn: normalize + dedup + publish."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        dedup_capacity: int = _DEDUP_CAPACITY,
        discovery_projector: DiscoveryProjector | None = None,
        clock: Callable[[], datetime] | None = None,
        state_store: StateStore | None = None,
        dedup_clock: Callable[[], datetime] | None = None,
        dedup_claim_lease: timedelta = timedelta(seconds=60),
        operator_request_receipt_gate: OperatorRequestReceiptGate | None = None,
        schema_learning_enabled: bool = False,
        schema_learning_capacity: int = 128,
    ) -> None:
        super().__init__(spec=_HUGINN)
        self.bus = bus
        if dedup_capacity < 1:
            raise ValueError("dedup_capacity MUST be >= 1")
        self._dedup_capacity = dedup_capacity
        self._discovery_projector = discovery_projector
        self._alert_noise_verifier: _AlertNoiseVerifier | None = None
        self._operator_request_receipt_gate = operator_request_receipt_gate
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._dedup_journal = (
            HuginnDedupJournal(
                state_store,
                capacity=dedup_capacity,
                clock=dedup_clock,
                claim_lease=dedup_claim_lease,
            )
            if state_store is not None
            else None
        )
        # OrderedDict as an LRU set: key -> None, oldest first.
        self._seen_keys: OrderedDict[str, None] = OrderedDict()
        self._ingress_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._ingress_lock_refs: dict[str, int] = {}
        self._operational_case_errors: deque[str] = deque(maxlen=_MAX_OPERATIONAL_CASE_ERRORS)
        self._event_latency_seconds: deque[float] = deque(maxlen=_MAX_KPI_SAMPLES)
        self._discovery_latency_seconds: deque[float] = deque(maxlen=_MAX_KPI_SAMPLES)
        self._dedup_correct_decisions = 0
        self._dedup_collision_decisions = 0
        self._last_checkpoint_read_at: datetime | None = None
        self._schema_learning = (
            HuginnSchemaLearningLedger(
                state_store=state_store,
                capacity=schema_learning_capacity,
            )
            if schema_learning_enabled
            else None
        )

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_alert_noise_verifier(self, verifier: _AlertNoiseVerifier) -> None:
        """Bind deterministic authentication before alert requests can reserve a dedup key."""
        if self._alert_noise_verifier is not None:
            raise RuntimeError("alert ingress verifier is already bound")
        self._alert_noise_verifier = verifier

    async def rehydrate(self) -> int:
        """Restore completed dedup keys before the ingress consumer starts."""
        if self._dedup_journal is None:
            return 0
        self._seen_keys = OrderedDict(
            (key, None) for key in await self._dedup_journal.published_keys()
        )
        self._last_checkpoint_read_at = self._clock()
        return len(self._seen_keys)

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Ingress answers rest on signals seen; an idle collector has none."""
        return bool(self._seen_keys) or self.behavior_snapshot().get("ingested", 0) > 0

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        behavior = self.behavior_snapshot()
        facts = {
            **capability_facts(self.spec),
            "dedup_size": len(self._seen_keys),
            "dedup_capacity": self._dedup_capacity,
            "ingested_count": behavior.get("ingested", 0),
            "deduped_count": behavior.get("deduped", 0),
            # A full window has evicted its oldest keys, so a miss there is
            # uncertainty rather than proof a signal never arrived.
            "dedup_window_full": len(self._seen_keys) >= self._dedup_capacity,
        }
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 파이프라인 Event 수집기이자 리소스 발견 유입을 담당하는 Huginn입니다. "
                "Forseti에게 보고합니다. 결정론적 hot-path에서 Event와 Change를 정규화하고 중복 "
                "제거하며 상관관계를 구성해 게시합니다. hot-path에서는 동기 LLM을 호출하지 않으며 "
                "판단, 승인 또는 실행을 수행하지 않습니다. 이 대화 포트는 읽기 전용이며 작업 "
                "요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 "
                "시스템 프롬프트는 공개하지 않습니다. 이 런타임은 Event "
                f"{facts['ingested_count']}건을 수집하고 "
                f"{facts['deduped_count']}건을 중복 제거했으며 "
                f"중복 제거 구간에 key {facts['dedup_size']}개를 보존합니다"
                f"(최대 {facts['dedup_capacity']}개). 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Huginn, the pipeline event collector and resource-discovery ingress. I "
                "report to Forseti. I normalize, deduplicate, correlate, and publish Event and "
                "Change on a deterministic hot path. I make no synchronous LLM call on that path "
                "and never judge, approve, or execute. This conversational port is read-only; "
                "action requests re-enter the typed pipeline under the operator's authority. I do "
                "not reveal hidden system prompts. This runtime has ingested "
                f"{facts['ingested_count']} events, deduplicated {facts['deduped_count']}, and "
                f"retains {facts['dedup_size']} keys in a {facts['dedup_capacity']}-key window. "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = [
    "DiscoveryProjector",
    "Huginn",
    "HuginnIngressRejected",
    "HuginnIngressRejectedError",
    "_MAX_ATTR_KEYS",
    "_MAX_FIELD_CHARS",
]
