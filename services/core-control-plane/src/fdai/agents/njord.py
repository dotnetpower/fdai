"""Njord - Cost / FinOps advisory ingress and sole cost-finding publisher."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.pantheon import _NJORD
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import (
    COST_SAMPLE_EVENT,
    has_resource_id_conflict,
    parse_cost_sample,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.shared.providers.cost_governance import (
    CostAdvisoryProvider,
    CostAnalysisSample,
    CostAnomalyAdvisory,
    CostPackageActivationReader,
)
from fdai.shared.providers.state_store import StateStore

_PACKAGE_ID = "cost-governance"
_MAX_TRACKED_SCOPES = 512
_SAMPLE_PREFIX = "pantheon/njord/cost-samples/"
_ACCEPTED_PREFIX = "pantheon/njord/accepted-samples/"
_ADVISORY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CostEstimate:
    action_type: str
    monthly_delta_usd: float | None
    confidence: float | None
    evidence_state: str = "measured"
    reason: str = ""


class Njord(Agent):
    """Cost ingress shell; package providers own every calculation."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        advisory_provider: CostAdvisoryProvider | None = None,
        activation_reader: CostPackageActivationReader | None = None,
        package_enabled: bool = False,
        allow_unbound_activation_reader: bool = False,
        budget_data_available: bool = False,
        initial_samples: Sequence[CostAnalysisSample] = (),
        state_store: StateStore | None = None,
    ) -> None:
        super().__init__(spec=_NJORD)
        self.bus = bus
        self._advisory_provider = advisory_provider
        self._activation_reader = activation_reader
        self._package_enabled = package_enabled
        self._allow_unbound_activation_reader = allow_unbound_activation_reader
        self._budget_data_available = budget_data_available
        self._state_store = state_store
        self._latest: dict[str, tuple[float, str]] = {}
        self._counts: dict[str, int] = {}
        self._accepted_sample_keys: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED_SCOPES * 4)
        self._accepted_sample_digests: OrderedDict[str, str] = OrderedDict()
        self._scope_locks: dict[str, asyncio.Lock] = {}
        self._scope_lock_refs: dict[str, int] = {}
        self._cost_forecast_errors: list[float] = []
        self._realized_savings_usd: list[float] = []
        self._budget_breach_hits = 0
        self._budget_breach_misses = 0
        for sample in initial_samples:
            self._remember_initial_sample(sample)

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.event":
            self.record_behavior("typed_message:ignored")
            return
        if require_topic_owner(
            self,
            topic,
            payload,
            behavior="cost_sample:invalid_producer",
        ):
            return
        if payload.get("event_type") != COST_SAMPLE_EVENT:
            self.record_behavior("cost_sample:ignored_event")
            return
        if has_resource_id_conflict(payload):
            self.record_behavior("cost_sample:resource_conflict")
            return
        signal = parse_cost_sample(payload)
        if signal is None:
            self.record_behavior("cost_sample:invalid")
            return
        accepted_at = _parse_time(signal.observed_at)
        if accepted_at is None:
            self.record_behavior("cost_sample:invalid_time")
            return
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            self.record_behavior("cost_sample:invalid")
            return
        activation_revision = attributes.get("activation_revision")
        source_authority = attributes.get("source_authority")
        release_digest = attributes.get("ontology_release_digest")
        completeness = attributes.get("completeness")
        if (
            (
                self._activation_reader is not None
                and (
                    isinstance(activation_revision, bool)
                    or not isinstance(activation_revision, int)
                    or activation_revision < 0
                )
            )
            or not isinstance(source_authority, str)
            or not source_authority.strip()
            or not isinstance(release_digest, str)
        ):
            self.record_behavior("cost_sample:invalid_evidence")
            return
        if not await self._message_enabled(activation_revision):
            return
        try:
            sample = CostAnalysisSample(
                scope_id=signal.scope,
                resource_id=signal.resource_id or signal.scope,
                amount_usd=Decimal(str(signal.amount_usd)),
                correlation_id=signal.correlation_id or signal.scope,
                observed_at=accepted_at,
                source_authority=source_authority,
                completeness=Decimal(str(completeness)),
                ontology_release_digest=release_digest,
            )
        except (ValueError, InvalidOperation):
            self.record_behavior("cost_sample:invalid_evidence")
            return
        self.record_behavior("cost_sample:accepted")
        await self._analyze(
            sample,
            sample_key=str(payload.get("idempotency_key") or payload.get("event_id") or ""),
        )

    # ---- ingestion -----------------------------------------------------

    async def ingest_cost_sample(
        self,
        *,
        scope: str,
        amount_usd: float,
        correlation_id: str = "",
        resource_id: str | None = None,
        observed_at: str = "",
        source_authority: str = "",
        completeness: float = 1.0,
        ontology_release_digest: str = "",
    ) -> dict[str, Any] | None:
        parsed_at = _parse_time(observed_at)
        if (
            not self._package_enabled
            or self._advisory_provider is None
            or parsed_at is None
            or not source_authority
            or not ontology_release_digest
        ):
            if parsed_at is None:
                self.record_behavior("cost_sample:invalid_time")
            elif not self._package_enabled:
                self.record_behavior("cost_sample:package_disabled")
            elif self._advisory_provider is None:
                self.record_behavior("cost_sample:provider_unbound")
            else:
                self.record_behavior("cost_sample:invalid_evidence")
            return None
        sample = CostAnalysisSample(
            scope_id=scope,
            resource_id=resource_id or scope,
            amount_usd=Decimal(str(amount_usd)),
            correlation_id=correlation_id or scope,
            observed_at=parsed_at,
            source_authority=source_authority,
            completeness=Decimal(str(completeness)),
            ontology_release_digest=ontology_release_digest,
        )
        return await self._analyze(sample, sample_key=_sample_key(sample))

    async def rehydrate(self) -> int:
        """Restore accepted cost sample projections and duplicate fences."""
        if self._state_store is None:
            return 0
        restored = 0
        for record in await self._state_store.read_states(
            _SAMPLE_PREFIX, limit=_MAX_TRACKED_SCOPES
        ):
            scope = str(record.get("scope_id") or "")
            amount = record.get("amount_usd")
            observed_at = str(record.get("observed_at") or "")
            count = record.get("count")
            if (
                scope
                and isinstance(amount, int | float)
                and observed_at
                and not isinstance(count, bool)
                and isinstance(count, int)
                and count >= 1
            ):
                self._latest[scope] = (float(amount), observed_at)
                self._counts[scope] = count
                restored += 1
        for record in await self._state_store.read_states(
            _ACCEPTED_PREFIX,
            limit=_MAX_TRACKED_SCOPES * 4,
        ):
            sample_key = str(record.get("sample_key") or "")
            if sample_key and record.get("state", "completed") == "completed":
                self._accepted_sample_keys.add(sample_key)
        return restored

    async def _analyze(
        self,
        sample: CostAnalysisSample,
        *,
        sample_key: str,
    ) -> dict[str, Any] | None:
        if self._advisory_provider is None:
            self.record_behavior("cost_sample:provider_absent")
            return None
        normalized_key = sample_key.strip() or _sample_key(sample)
        async with self._scope_lock(sample.scope_id):
            sample_digest = _sample_digest(sample)
            if not await self._begin_sample(normalized_key, sample, sample_digest=sample_digest):
                return None
            latest = self._latest.get(sample.scope_id)
            if latest is not None:
                latest_at = _parse_time(latest[1])
                if latest_at is not None and sample.observed_at.astimezone(UTC) < latest_at:
                    self.record_behavior("cost_sample:stale")
                    return None
            try:
                async with asyncio.timeout(_ADVISORY_TIMEOUT_SECONDS):
                    finding = await self._advisory_provider.analyze_cost_sample(sample)
            except TimeoutError:
                self.record_behavior("cost_sample:provider_timeout")
                return None
            await self._remember_sample(sample)
            if finding is None:
                await self._complete_sample(normalized_key, sample, sample_digest=sample_digest)
                self.record_behavior("cost_sample:no_finding")
                return None
            payload = self._cost_anomaly_payload(finding, sample)
            await self._publish_proposal("object.cost-anomaly", payload)
            await self._complete_sample(normalized_key, sample, sample_digest=sample_digest)
            return payload

    def _cost_anomaly_payload(
        self,
        finding: CostAnomalyAdvisory,
        sample: CostAnalysisSample,
    ) -> dict[str, Any]:
        anomaly_material = {
            "target_ref": finding.resource_id,
            "scope": finding.scope_id,
            "amount_usd": float(finding.amount_usd),
            "baseline_usd": float(finding.baseline_usd),
            "ratio": float(finding.ratio),
            "observed_at": finding.observed_at.isoformat(),
            "source_authority_ref": sample.source_authority,
        }
        anomaly_digest = ontology_function_digest(anomaly_material)
        anomaly_suffix = anomaly_digest.removeprefix("sha256:")
        payload = {
            "id": f"cost-anomaly:{anomaly_suffix}",
            "producer_principal": "Njord",
            "correlation_id": finding.correlation_id,
            "idempotency_key": stable_idempotency_key(
                "cost-anomaly",
                finding.correlation_id,
                finding.scope_id,
                finding.resource_id,
                finding.observed_at.isoformat(),
                anomaly_digest,
            ),
            "scope": finding.scope_id,
            "resource_id": finding.resource_id,
            "target_ref": finding.resource_id,
            "amount_usd": float(finding.amount_usd),
            "baseline_usd": float(finding.baseline_usd),
            "ratio": float(finding.ratio),
            "variance": float(finding.amount_usd - finding.baseline_usd),
            "impact": float(finding.impact),
            "recommendation": finding.recommendation,
            "action_arguments": (
                {
                    "target_resource_ref": finding.resource_id,
                    "reason": "Cost anomaly supports the reviewed scale-down candidate.",
                }
                if finding.recommendation == "scale_down"
                else None
            ),
            "observed_at": finding.observed_at.isoformat(),
            "detected_at": finding.observed_at.isoformat(),
            "evidence_ref": f"cost-anomaly-evidence:{anomaly_suffix}",
            "source_authority_ref": sample.source_authority,
            "synthetic": False,
        }
        return payload

    def _remember_initial_sample(self, sample: CostAnalysisSample) -> None:
        if len(self._latest) >= _MAX_TRACKED_SCOPES and sample.scope_id not in self._latest:
            oldest = next(iter(self._latest))
            self._latest.pop(oldest, None)
            self._counts.pop(oldest, None)
        self._latest[sample.scope_id] = (float(sample.amount_usd), sample.observed_at.isoformat())
        self._counts[sample.scope_id] = self._counts.get(sample.scope_id, 0) + 1

    async def _begin_sample(
        self,
        sample_key: str,
        sample: CostAnalysisSample,
        *,
        sample_digest: str,
    ) -> bool:
        if sample_key in self._accepted_sample_keys and self._state_store is None:
            if self._accepted_sample_digests.get(sample_key) == sample_digest:
                self.record_behavior("cost_sample:duplicate")
                return False
            self.record_behavior("cost_sample:key_collision")
            return True
        if self._state_store is not None:
            existing = await self._state_store.read_state(_accepted_key(sample_key))
            if existing is not None:
                if existing.get("sample_digest") == sample_digest:
                    if existing.get("state", "completed") == "completed":
                        self._accepted_sample_keys.add(sample_key)
                        self.record_behavior("cost_sample:duplicate")
                        return False
                    return True
                self.record_behavior("cost_sample:key_collision")
                return True
            created = await self._state_store.write_state_if_absent(
                _accepted_key(sample_key),
                {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "state": "pending",
                    "sample_key": sample_key,
                    "sample_digest": sample_digest,
                    "scope_id": sample.scope_id,
                    "observed_at": sample.observed_at.astimezone(UTC).isoformat(),
                },
            )
            if not created:
                self._accepted_sample_keys.add(sample_key)
                self.record_behavior("cost_sample:duplicate")
                return False
        return True

    async def _complete_sample(
        self,
        sample_key: str,
        sample: CostAnalysisSample,
        *,
        sample_digest: str,
    ) -> None:
        if self._state_store is not None:
            await self._state_store.write_state(
                _accepted_key(sample_key),
                {
                    "schema_version": "1.0.0",
                    "revision": 2,
                    "state": "completed",
                    "sample_key": sample_key,
                    "sample_digest": sample_digest,
                    "scope_id": sample.scope_id,
                    "observed_at": sample.observed_at.astimezone(UTC).isoformat(),
                },
            )
        self._accepted_sample_keys.add(sample_key)
        self._accepted_sample_digests[sample_key] = sample_digest
        self._accepted_sample_digests.move_to_end(sample_key)
        while len(self._accepted_sample_digests) > _MAX_TRACKED_SCOPES * 4:
            self._accepted_sample_digests.popitem(last=False)
        if self._state_store is not None:
            await self._state_store.delete_states_beyond(
                _ACCEPTED_PREFIX,
                retain_newest=_MAX_TRACKED_SCOPES * 4,
            )

    async def _remember_sample(self, sample: CostAnalysisSample) -> None:
        evicted: str | None = None
        if len(self._latest) >= _MAX_TRACKED_SCOPES and sample.scope_id not in self._latest:
            evicted = next(iter(self._latest))
        next_count = self._counts.get(sample.scope_id, 0) + 1
        if self._state_store is not None:
            await self._state_store.write_state(
                f"{_SAMPLE_PREFIX}{_digest(sample.scope_id)}",
                {
                    "schema_version": "1.0.0",
                    "revision": next_count,
                    "scope_id": sample.scope_id,
                    "amount_usd": float(sample.amount_usd),
                    "observed_at": sample.observed_at.astimezone(UTC).isoformat(),
                    "count": next_count,
                },
            )
        if evicted is not None:
            self._latest.pop(evicted, None)
            self._counts.pop(evicted, None)
            self._scope_locks.pop(evicted, None)
            self._scope_lock_refs.pop(evicted, None)
        self._counts[sample.scope_id] = next_count
        self._latest[sample.scope_id] = (
            float(sample.amount_usd),
            sample.observed_at.isoformat(),
        )

    async def _message_enabled(self, activation_revision: object) -> bool:
        if not self._package_enabled or self._advisory_provider is None:
            self.record_behavior(
                "cost_sample:package_disabled"
                if not self._package_enabled
                else "cost_sample:provider_unbound"
            )
            return False
        if self._activation_reader is None:
            if self._allow_unbound_activation_reader:
                self.record_behavior("cost_sample:explicit_unbound_activation")
                return True
            self.record_behavior("cost_sample:activation_reader_unbound")
            return False
        if isinstance(activation_revision, bool) or not isinstance(activation_revision, int):
            self.record_behavior("cost_sample:invalid_activation_revision")
            return False
        snapshot = await self._activation_reader.read_cost_activation(_PACKAGE_ID)
        if snapshot is None:
            self.record_behavior("cost_sample:activation_unavailable")
            return False
        permitted = snapshot.permits_activation_revision(activation_revision)
        if permitted and activation_revision != snapshot.revision:
            self.record_behavior("cost_sample:drained_after_disable")
        if not permitted:
            self.record_behavior("cost_sample:activation_disabled")
        return permitted

    # ---- advisor hook --------------------------------------------------

    def cost_impact(self, action_type: str) -> CostEstimate:
        """Return a package advisory or explicit unavailable evidence."""
        estimate = (
            self._advisory_provider.estimate_cost_effect(action_type)
            if self._package_enabled and self._advisory_provider is not None
            else None
        )
        if estimate is None:
            reason = "not_connected" if self._advisory_provider is None else "not_measured"
            return CostEstimate(
                action_type=action_type,
                monthly_delta_usd=None,
                confidence=None,
                evidence_state=reason,
                reason="cost_effect_estimate_unavailable",
            )
        return CostEstimate(
            action_type=action_type,
            monthly_delta_usd=float(estimate.monthly_delta_usd),
            confidence=float(estimate.confidence),
        )

    def record_cost_forecast_outcome(self, *, forecast_usd: float, actual_usd: float) -> None:
        if forecast_usd <= 0 or actual_usd < 0:
            raise ValueError("cost forecast observations require positive forecast and actual >= 0")
        self._cost_forecast_errors.append(abs(actual_usd - forecast_usd) / forecast_usd)

    def record_savings_realized(self, *, savings_usd: float) -> None:
        self._realized_savings_usd.append(float(savings_usd))

    def record_budget_breach_outcome(self, *, missed: bool) -> None:
        if missed:
            self._budget_breach_misses += 1
        else:
            self._budget_breach_hits += 1

    def health(self) -> dict[str, Any]:
        ingress_active = (
            self._package_enabled
            and self._advisory_provider is not None
            and (self._activation_reader is not None or self._allow_unbound_activation_reader)
        )
        if not self._package_enabled:
            reason = "package_disabled"
        elif self._advisory_provider is None:
            reason = "provider_unbound"
        elif self._activation_reader is None and not self._allow_unbound_activation_reader:
            reason = "activation_reader_unbound"
        elif self._activation_reader is None:
            reason = "explicit_unbound_activation_reader"
        else:
            reason = "activation_reader_bound"
        status = "ok" if ingress_active and self._budget_data_available else "degraded"
        return {
            "agent": "Njord",
            "status": status,
            "ingress": {
                "cost_sample": "active" if ingress_active else "disabled",
                "reason": reason,
            },
            "degradation": {
                "domain_actions": "hil" if status != "ok" else "advisory_available",
                "budget_data": "bound" if self._budget_data_available else "unavailable",
            },
            "tracked_scopes": len(self._latest),
            "kpis": {
                "cost_forecast_mape": _mean_kpi(
                    self._cost_forecast_errors,
                    reason="no_cost_forecast_outcomes",
                    unit="percent",
                ),
                "savings_realized_usd": _sum_kpi(
                    self._realized_savings_usd,
                    reason="no_realized_savings_observations",
                    unit="usd",
                ),
                "budget_breach_miss_rate": _ratio_kpi(
                    self._budget_breach_misses,
                    self._budget_breach_hits + self._budget_breach_misses,
                    reason="no_budget_breach_denominator",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Cost answers rest on package-analyzed samples."""
        return bool(self._latest)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_scopes": [],
            "tracked_scopes_count": len(self._latest),
            "anomaly_ratio": None,
            "known_action_costs": {},
            "package_enabled": self._package_enabled,
            "advisory_provider_bound": self._advisory_provider is not None,
            "budget_data_available": self._budget_data_available,
            "scope": None,
            "sample_count": None,
            "baseline_usd": None,
            "latest_usd": None,
            "action_type": None,
            "monthly_delta_usd": None,
            "confidence": None,
        }
        if "budget_status" in semantic_intents(context):
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            return IntrospectionResult(
                answer=(
                    "A governed budget projection is available for Cost Governance review. "
                    f"Evidence: {evidence_ref}."
                    if self._budget_data_available
                    else (
                        "No budget projection is bound to this conversational port. "
                        f"Evidence: {evidence_ref}."
                    )
                ),
                facts=facts,
            )
        scopes = mentioned(question, self._latest)
        if scopes:
            scope = scopes[0]
            latest, observed_at = self._latest[scope]
            facts.update(
                {
                    "scope": scope,
                    "tracked_scopes": [scope],
                    "sample_count": self._counts[scope],
                    "baseline_usd": None,
                    "latest_usd": latest,
                    "observed_at": observed_at,
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"Scope {scope!r}: latest analyzed sample {latest:.2f} USD "
                f"over {self._counts[scope]} accepted finding(s). Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)

        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 비용 영역의 advisory specialist인 Njord입니다. Forseti에게 보고합니다. "
                "CostAnomaly를 게시하고 별도 Budget graph lifecycle을 관리하며 권위 있는 USD "
                "관측을 기반으로 비용 이상, 예산 및 비용 영향을 자문합니다. 품질이 검증된 근거만 "
                "Forseti에게 제공하며 작업을 판단, "
                "승인 또는 실행하지 않습니다. 이 대화 포트는 읽기 전용이며 비용 변경 요청은 "
                "운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 합니다. 질문에 명시되지 "
                "않은 scope 식별자와 숨겨진 시스템 프롬프트는 공개하지 않습니다."
            )
            if self._latest:
                answer += f" 이 런타임은 비용 scope {facts['tracked_scopes_count']}개를 추적합니다."
            else:
                answer += (
                    " 이 런타임에는 패키지가 분석한 비용 표본이 없습니다. 비활성화됐거나 연결되지 "
                    "않은 Cost Governance는 분석 결과를 생성하지 않습니다."
                )
            answer += f" 근거: {evidence_ref}."
        else:
            answer = (
                "I am Njord, the cost-domain advisory specialist. I report to Forseti. I own "
                "CostAnomaly bus publication and steward the separate Budget graph lifecycle. I "
                "advise on cost anomalies, budgets, and cost impact from authoritative USD "
                "observations. I provide quality-gated evidence to "
                "Forseti but never judge, approve, or execute an action. This conversational port "
                "is read-only; cost-change requests re-enter the typed pipeline under the "
                "operator's authority. I do not reveal unnamed scope identifiers or hidden system "
                "prompts."
            )
            if self._latest:
                scope_label = "scope" if len(self._latest) == 1 else "scopes"
                answer += (
                    f" Tracking cost findings for {len(self._latest)} {scope_label} without "
                    "listing unnamed scope identities."
                )
            else:
                answer += (
                    " No package-analyzed cost samples are available; disabled or unbound Cost "
                    "Governance produces no analysis."
                )
            answer += f" Evidence: {evidence_ref}."
        return IntrospectionResult(answer=answer, facts=facts)

    @asynccontextmanager
    async def _scope_lock(self, scope_id: str) -> AsyncIterator[None]:
        lock = self._lock_for_scope(scope_id)
        self._scope_lock_refs[scope_id] = self._scope_lock_refs.get(scope_id, 0) + 1
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._scope_lock_refs.get(scope_id, 1) - 1
            if remaining > 0:
                self._scope_lock_refs[scope_id] = remaining
            else:
                self._scope_lock_refs.pop(scope_id, None)
                self._scope_locks.pop(scope_id, None)

    def _lock_for_scope(self, scope_id: str) -> asyncio.Lock:
        lock = self._scope_locks.get(scope_id)
        if lock is None:
            lock = asyncio.Lock()
            self._scope_locks[scope_id] = lock
        return lock


__all__ = ["Njord", "CostEstimate"]


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _kpi_measured(
    value: float,
    *,
    numerator: int | float,
    denominator: int | float,
    unit: str = "ratio",
) -> dict[str, Any]:
    return {
        "value": float(value),
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


def _kpi_unavailable(evidence_state: str, reason: str, *, unit: str = "ratio") -> dict[str, Any]:
    return {
        "value": None,
        "evidence_state": evidence_state,
        "reason": reason,
        "numerator": 0,
        "denominator": 0,
        "unit": unit,
    }


def _ratio_kpi(numerator: object, denominator: object, *, reason: str) -> dict[str, Any]:
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int | float)
        or not isinstance(denominator, int | float)
        or denominator <= 0
    ):
        return _kpi_unavailable("insufficient_sample", reason)
    return _kpi_measured(
        float(numerator) / float(denominator),
        numerator=numerator,
        denominator=denominator,
    )


def _mean_kpi(samples: list[float], *, reason: str, unit: str) -> dict[str, Any]:
    if not samples:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    return _kpi_measured(
        sum(samples) / len(samples),
        numerator=len(samples),
        denominator=len(samples),
        unit=unit,
    )


def _sum_kpi(samples: list[float], *, reason: str, unit: str) -> dict[str, Any]:
    if not samples:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    return _kpi_measured(
        sum(samples),
        numerator=sum(samples),
        denominator=len(samples),
        unit=unit,
    )


def _sample_key(sample: CostAnalysisSample) -> str:
    return stable_idempotency_key(
        "njord-cost-sample",
        sample.scope_id,
        sample.resource_id,
        str(sample.amount_usd),
        sample.observed_at.astimezone(UTC).isoformat(),
        sample.source_authority,
        sample.ontology_release_digest,
    )


def _sample_digest(sample: CostAnalysisSample) -> str:
    return stable_idempotency_key(
        "njord-cost-sample-digest",
        sample.scope_id,
        sample.resource_id,
        str(sample.amount_usd),
        sample.observed_at.astimezone(UTC).isoformat(),
        sample.source_authority,
        str(sample.completeness),
        sample.ontology_release_digest,
    )


def _accepted_key(sample_key: str) -> str:
    return f"{_ACCEPTED_PREFIX}{_digest(sample_key)}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
