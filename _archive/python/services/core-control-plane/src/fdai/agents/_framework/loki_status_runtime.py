"""Health and introspection mixin for Loki."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.loki_adversarial import ChaosScenarioGenerator
from fdai.agents._framework.loki_reservations import LokiReservationJournal
from fdai.agents._framework.loki_runtime_records import ChaosProposal, _Reservation
from fdai.agents._framework.loki_scheduling import ChaosScheduleConfig
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.base import AgentSpec


class LokiStatusRuntimeMixin:
    """Report Loki evidence and conversational facts."""

    _reservation_journal: LokiReservationJournal | None
    _recurring_schedule: ChaosScheduleConfig | None
    _state_store: StateStore | None
    _reservations: dict[str, _Reservation]
    _scenario_generator: ChaosScenarioGenerator | None
    _cap: int
    _in_flight_targets: set[str]
    _held_proposals: deque[ChaosProposal]
    _blast_radius_adherent_attempts: int
    _blast_radius_attempts: int
    proposals: deque[ChaosProposal]
    _resilience_experiment_scores: dict[str, dict[str, float]]
    _resilience_scores: dict[str, tuple[float, str]]
    spec: AgentSpec

    if TYPE_CHECKING:

        def _now(self) -> datetime: ...

        def behavior_snapshot(self) -> dict[str, int]: ...

    def health(self) -> dict[str, Any]:
        durable = self._reservation_journal is not None
        scheduler_bound = self._recurring_schedule is not None and self._state_store is not None
        oldest_age = None
        if self._reservations:
            now = self._now()
            oldest_age = max(
                0.0,
                max(
                    (now - reservation.reserved_at).total_seconds()
                    for reservation in self._reservations.values()
                ),
            )
        return {
            "agent": "Loki",
            "status": "ok" if durable else "degraded",
            "ingress": {
                "chaos_schedule": "active",
                "recurring_scheduler": "active" if scheduler_bound else "disabled",
                "resilience_score": "active",
                "adversarial_generator": (
                    "bound" if self._scenario_generator is not None else "unbound"
                ),
                "reason": (
                    "event_subscriptions_and_scheduler_bound"
                    if scheduler_bound
                    else "recurring_scheduler_unbound"
                ),
            },
            "reservation": {
                "durability": "durable"
                if self._reservation_journal is not None
                else "process_local",
                "blast_radius_cap": self._cap,
                "in_flight_target_count": len(self._in_flight_targets),
                "oldest_active_age_seconds": oldest_age,
            },
            "degradation": {
                "domain_actions": "hil" if not durable else "advisory_available",
            },
            "held_proposals": len(self._held_proposals),
            "kpis": {
                "blast_radius_adherence_rate": _ratio_kpi(
                    self._blast_radius_adherent_attempts,
                    self._blast_radius_attempts,
                    reason="no_chaos_experiment_attempts",
                ),
                "resilience_improvement_delta": self._resilience_delta_kpi(),
                "unplanned_side_effect_rate": _ratio_kpi(
                    self.behavior_snapshot().get("chaos_proposal:side_effect", 0),
                    len(self.proposals),
                    reason="no_side_effect_denominator",
                ),
                "experiment_failure_rate": _ratio_kpi(
                    self.behavior_snapshot().get("chaos_proposal:publication_unavailable", 0),
                    len(self.proposals),
                    reason="no_experiment_failure_denominator",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    def _resilience_delta_kpi(self) -> dict[str, Any]:
        deltas = [
            values["post"] - values["baseline"]
            for values in self._resilience_experiment_scores.values()
            if "baseline" in values and "post" in values
        ]
        if not deltas:
            return _kpi_unavailable(
                "insufficient_sample",
                "missing_experiment_bound_baseline_or_post_observation",
            )
        return _kpi_measured(
            sum(deltas) / len(deltas),
            numerator=len(deltas),
            denominator=len(deltas),
            unit="score_delta",
        )

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Chaos answers rest on proposals made; the cap alone is config."""
        return bool(self.proposals or self._resilience_scores)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        accepted = [p for p in self.proposals if p.accepted]
        facts = {
            **capability_facts(self.spec),
            "blast_radius_cap": self._cap,
            "in_flight_targets": None if self._in_flight_targets else [],
            "in_flight_target_count": len(self._in_flight_targets),
            "proposals_total": len(self.proposals),
            "proposals_accepted": len(accepted),
            "held_proposals": len(self._held_proposals),
            "reservation_durability": (
                "durable" if self._reservation_journal is not None else "process_local"
            ),
            "resilience_score_available": bool(self._resilience_scores),
            "resilience_score_resource_count": len(self._resilience_scores),
            "resource_id": None,
            "resilience_score": None,
            "observed_at": None,
        }
        selected_tool = context.get("conversation_tool")
        intents = semantic_intents(context)
        if selected_tool == "read_resilience_scores" or intents.intersection(
            {"resilience_score", "resilience_scores"}
        ):
            resources = mentioned(question, self._resilience_scores)
            if resources:
                resource_id = resources[0]
                score, observed_at = self._resilience_scores[resource_id]
                facts.update(
                    {
                        "resource_id": resource_id,
                        "resilience_score": score,
                        "observed_at": observed_at,
                    }
                )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            if resources:
                answer = (
                    f"Resource {resources[0]!r}: retained resilience score "
                    f"{facts['resilience_score']:.3f} observed at {facts['observed_at']}. "
                    f"Evidence: {evidence_ref}."
                )
            elif self._resilience_scores:
                answer = (
                    "A retained resilience score is available. Name the exact resource to read "
                    f"its score. Evidence: {evidence_ref}."
                )
            else:
                answer = (
                    "No retained resilience score is bound to this conversational projection. "
                    f"Evidence: {evidence_ref}."
                )
            return IntrospectionResult(
                answer=answer,
                facts=facts,
            )
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 복원력 영역의 chaos advisory specialist인 Loki입니다. Forseti에게 "
                "보고합니다. ChaosExperiment와 ResilienceScore를 소유하고 검증된 dry-run, "
                "테스트된 recovery plan, stop condition 및 blast-radius 제한이 있는 실험만 "
                "제안합니다. 모든 실험은 HIL 승인이 필요하며 Forseti가 판단하고 Thor가 "
                "실행합니다. 저는 작업을 판단, 승인 또는 실행하지 않습니다. 이 대화 포트는 읽기 "
                "전용이며 실험 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 "
                "합니다. 질문에 명시되지 않은 target 식별자와 숨겨진 시스템 프롬프트는 공개하지 "
                f"않습니다. 이 런타임은 제안 {facts['proposals_total']}건, 승인된 제안 "
                f"{facts['proposals_accepted']}건, 진행 중 target "
                f"{facts['in_flight_target_count']}개를 추적하며 blast-radius 상한은 "
                f"{facts['blast_radius_cap']}입니다. 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Loki, the resilience-domain chaos advisory specialist. I report to Forseti. "
                "I own ChaosExperiment and ResilienceScore and propose experiments only with a "
                "verified dry-run, tested recovery plan, stop condition, and blast-radius limit. "
                "Every experiment requires HIL; Forseti judges and Thor executes. I never judge, "
                "approve, or execute an action. This conversational port is read-only; experiment "
                "requests re-enter the typed pipeline under the operator's authority. I do not "
                "reveal unnamed target identifiers or hidden system prompts. This runtime tracks "
                f"{facts['proposals_total']} proposals, {facts['proposals_accepted']} accepted, "
                f"and {facts['in_flight_target_count']} in-flight targets under a "
                f"{facts['blast_radius_cap']}-target cap. Evidence: {evidence_ref}."
            )
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
