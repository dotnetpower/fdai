"""Forecast outcome, health, and introspection mixin for Freyr."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.freyr_sampling import run_recurring_sampling
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
)
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.base import AgentSpec
    from fdai.agents._framework.freyr_capacity_runtime import SizingRecommendation
    from fdai.agents._framework.freyr_sampling import CapacityUtilizationSampler
    from fdai.core.capacity import CapacityGraduationController


class FreyrStatusRuntimeMixin:
    """Report Freyr evidence and maintain recurring sampling."""

    _forecast_errors: list[float]
    _provisioning_observations: int
    _over_provisioned: int
    _under_provisioned: int
    _samples: BoundedLruDict[str, list[float]]
    _state_store: StateStore | None
    _graduation_controller: CapacityGraduationController | None
    _utilization_sampler: CapacityUtilizationSampler | None
    _source_time_missing_samples: int
    _clock: Callable[[], datetime]
    _recurring_sample_limit: int
    _recurring_sample_timeout: timedelta
    spec: AgentSpec
    _up: float
    _down: float

    if TYPE_CHECKING:

        def behavior_snapshot(self) -> dict[str, int]: ...

        async def ingest_utilization(
            self,
            *,
            resource_id: str,
            utilization: float,
            correlation_id: str = "",
            observed_at: str = "",
            sample_key: str = "",
        ) -> None: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        def sizing_advice(self, resource_id: str) -> SizingRecommendation: ...

    def record_capacity_forecast_outcome(
        self,
        *,
        resource_id: str,
        forecast_utilization: float,
        actual_utilization: float,
        provisioned: str = "right_sized",
    ) -> None:
        if (
            not resource_id
            or not 0 <= forecast_utilization <= 1
            or not 0 <= actual_utilization <= 1
        ):
            raise ValueError(
                "capacity outcome requires a resource and utilization values in [0, 1]"
            )
        self._forecast_errors.append(abs(actual_utilization - forecast_utilization))
        self._provisioning_observations += 1
        if provisioned == "over":
            self._over_provisioned += 1
        elif provisioned == "under":
            self._under_provisioned += 1
        elif provisioned != "right_sized":
            raise ValueError("provisioned MUST be over, under, or right_sized")

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Capacity answers rest on utilization samples; thresholds alone are config."""
        return bool(len(self._samples))

    def health(self) -> dict[str, Any]:
        durable_state = "durable" if self._state_store is not None else "process_local"
        controller_bound = self._graduation_controller is not None
        sampler_bound = self._utilization_sampler is not None
        status = "ok" if controller_bound and self._state_store is not None else "degraded"
        return {
            "agent": "Freyr",
            "status": status,
            "ingress": {
                "capacity_sample": "active",
                "recurring_sampling": "active" if sampler_bound else "disabled",
                "capacity_graduation": ("active" if controller_bound else "disabled"),
                "reason": (
                    "sampler_and_graduation_bound"
                    if controller_bound and sampler_bound
                    else "utilization_sampler_unbound"
                    if not sampler_bound
                    else "graduation_controller_unbound"
                ),
            },
            "state": {
                "forecast_durability": durable_state,
                "source_time_missing_samples": self._source_time_missing_samples,
            },
            "degradation": {
                "domain_actions": "hil" if status != "ok" else "advisory_available",
            },
            "tracked_resources": len(self._samples),
            "kpis": {
                "capacity_forecast_error": _mean_kpi(
                    self._forecast_errors,
                    reason="no_capacity_forecast_outcomes",
                    unit="absolute_utilization_delta",
                ),
                "over_provisioning_rate": _ratio_kpi(
                    self._over_provisioned,
                    self._provisioning_observations,
                    reason="no_provisioning_denominator",
                ),
                "under_provisioning_rate": _ratio_kpi(
                    self._under_provisioned,
                    self._provisioning_observations,
                    reason="no_provisioning_denominator",
                ),
                "scale_race_rate": _ratio_kpi(
                    self.behavior_snapshot().get(
                        "capacity_graduation:cost_evidence_uncorrelated", 0
                    ),
                    self.behavior_snapshot().get("capacity_graduation:cost_evidence_retained", 0)
                    + self.behavior_snapshot().get(
                        "capacity_graduation:cost_evidence_uncorrelated", 0
                    ),
                    reason="no_scale_race_denominator",
                ),
                "throttle_event_rate": _ratio_kpi(
                    self.behavior_snapshot().get("capacity_sample:stale", 0),
                    self.behavior_snapshot().get("capacity_sample:accepted", 0),
                    reason="no_throttle_denominator",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    async def maintenance_tick(self) -> None:
        maintenance_tick = getattr(super(), "maintenance_tick", None)
        if maintenance_tick is not None:
            await maintenance_tick()
        await run_recurring_sampling(
            sampler=self._utilization_sampler,
            clock=self._clock,
            ingest=self.ingest_utilization,
            record_behavior=self.record_behavior,
            limit=self._recurring_sample_limit,
            timeout_seconds=self._recurring_sample_timeout.total_seconds(),
        )

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_resources": [],
            "tracked_resources_count": len(self._samples),
            "scale_up_threshold": self._up,
            "scale_down_threshold": self._down,
            "resource_id": None,
            "current_util": None,
            "forecast_util": None,
            "recommendation": None,
        }
        resources = mentioned(question, tuple(resource for resource, _ in self._samples.items()))
        if resources:
            rid = resources[0]
            advice = self.sizing_advice(rid)
            facts.update(
                {
                    "resource_id": rid,
                    "tracked_resources": [rid],
                    "current_util": advice.current_util,
                    "forecast_util": advice.forecast_util,
                    "recommendation": advice.action,
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"Resource {rid!r}: current util {advice.current_util:.0%}, "
                f"forecast {advice.forecast_util:.0%} -> recommend {advice.action}. "
                f"Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 용량 영역의 advisory specialist인 Freyr입니다. Forseti에게 보고합니다. "
                "CapacityForecast와 CapacityGraduationRecommendation을 게시하고 별도 "
                "SizingRecommendation graph lifecycle을 관리하며 권위 있는 사용률 근거로 크기 "
                "조정을 자문합니다. Forseti가 판단하고 "
                "Thor가 실행하며 저는 작업을 판단, 승인 또는 실행하지 않습니다. 이 대화 포트는 "
                "읽기 전용이며 용량 변경 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 "
                "진입해야 합니다. 질문에 명시되지 않은 resource 식별자와 숨겨진 시스템 프롬프트는 "
                "공개하지 않습니다."
            )
            if len(self._samples):
                answer += (
                    f" 이 런타임은 resource {facts['tracked_resources_count']}개의 용량을 "
                    "추적합니다."
                )
            else:
                answer += (
                    " 현재 결론은 용량 확대 보류 및 실행 없음입니다. 이 런타임에는 사용률 "
                    "표본이 없어 크기 조정을 권고할 근거가 없습니다. Freyr는 용량 근거와 "
                    "권고를 제공하고, Heimdall은 관측 및 변경 영향 근거를 수집하고 검증하며, "
                    "Odin은 모든 안전 제약을 통과한 선택지 사이의 충돌만 중재합니다. "
                    "Forseti가 판정하고, 필요한 독립적인 인간 승인은 Var가 기록하며, Thor만 "
                    "실행합니다. 실행에는 중지 조건, 시험된 롤백, blast-radius 제한, 성공한 "
                    "dry-run, logical-target lock, 안정적인 idempotency key, append-only audit "
                    "intent와 terminal closure의 일곱 가지 안전장치가 모두 필요하며 효과도 "
                    "독립적으로 검증해야 합니다. 필요한 근거를 끝내 확보하지 못하면 실행하지 "
                    "않고 no-op, deny 또는 human review로 종결한 뒤 audit record를 남깁니다."
                )
            answer += f" 근거: {evidence_ref}."
        else:
            answer = (
                "I am Freyr, the capacity-domain advisory specialist. I report to Forseti. I own "
                "CapacityForecast and CapacityGraduationRecommendation bus publication and "
                "steward the separate SizingRecommendation graph lifecycle. I advise sizing from "
                "authoritative utilization evidence. Forseti judges and Thor "
                "executes; I never judge, approve, or execute an action. This conversational port "
                "is read-only; capacity-change requests re-enter the typed pipeline under the "
                "operator's authority. I do not reveal unnamed resource identifiers or hidden "
                "system prompts."
            )
            if len(self._samples):
                resource_label = "resource" if len(self._samples) == 1 else "resources"
                answer += (
                    f" Tracking capacity for {len(self._samples)} {resource_label} without "
                    "listing unnamed resource identities."
                )
            else:
                answer += (
                    " The current decision is to hold the capacity increase and take no action. "
                    "No utilization samples are available, so there is no evidence for a sizing "
                    "recommendation. Freyr supplies capacity evidence and advice, Heimdall "
                    "collects and verifies observation and change-impact evidence, and Odin "
                    "arbitrates only among options that pass every safety constraint. Forseti "
                    "judges, Var records any required independent human approval, and only Thor "
                    "executes. Execution requires all seven safeguards: a stop condition, tested "
                    "rollback, blast-radius limit, successful dry-run, logical-target lock, "
                    "stable idempotency key, and append-only audit intent with terminal closure; "
                    "effects also require independent verification. If the evidence cannot be "
                    "completed, close without execution as no-op, deny, or human review and "
                    "retain an audit record."
                )
            answer += f" Evidence: {evidence_ref}."
        return IntrospectionResult(answer=answer, facts=facts)


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
