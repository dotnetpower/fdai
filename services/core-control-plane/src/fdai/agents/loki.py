"""Loki - Chaos (Wave 5 behavior).

Loki schedules chaos experiments with a bounded blast_radius and
NEVER auto-executes. Every proposed experiment routes through Forseti
and Var as an HIL action; Loki merely emits the proposal.

Blast-radius accounting is deterministic: no matter how many
proposals come in per unit time, the cumulative in-flight target count
is capped by :pyattr:`blast_radius_cap`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.pantheon import _LOKI
from fdai.agents._framework.specialist_ingress import (
    CHAOS_SCHEDULE_EVENT,
    parse_chaos_schedule,
)

#: Cap on the retained proposal log. Loki appends one entry per proposal for
#: the process lifetime; the log is only read for recent-accepted diagnostics,
#: so a bounded ring is sufficient and stops an unbounded leak on a
#: long-running chaos scheduler.
_MAX_PROPOSALS = 1_000


@dataclass
class ChaosProposal:
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    accepted: bool
    reason: str
    causal_hypothesis_ref: str = ""
    impact_envelope_id: str = ""
    recovery_plan_id: str = ""


class Loki(Agent):
    """Wave-5 Loki: chaos scheduler with blast-radius cap."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        blast_radius_cap: int = 3,
    ) -> None:
        super().__init__(spec=_LOKI)
        self.bus = bus
        self._cap = blast_radius_cap
        self._in_flight_targets: set[str] = set()
        self.proposals: deque[ChaosProposal] = deque(maxlen=_MAX_PROPOSALS)

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.event" or payload.get("event_type") != CHAOS_SCHEDULE_EVENT:
            return
        signal = parse_chaos_schedule(payload)
        if signal is None:
            self.record_behavior("chaos_schedule:invalid")
            return
        self.record_behavior("chaos_schedule:accepted")
        await self.propose_experiment(
            experiment_id=signal.experiment_id,
            action_type=signal.action_type,
            targets=signal.targets,
            correlation_id=signal.correlation_id,
        )

    # ---- experiment scheduling ----------------------------------------

    async def propose_experiment(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
        correlation_id: str = "",
        causal_hypothesis_ref: str = "",
        refutation_query_ref: str = "",
        impact_envelope_id: str = "",
        recovery_plan_id: str = "",
        dry_run_receipt: str = "",
    ) -> ChaosProposal:
        # Enforce cap BEFORE emitting anything so a proposal storm does
        # not exceed the declared radius.
        available = self._cap - len(self._in_flight_targets)
        if available <= 0:
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="blast_radius_full",
            )
            self.proposals.append(proposal)
            return proposal
        selected = tuple(t for t in targets if t not in self._in_flight_targets)[:available]
        if not selected:
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="no_new_targets",
            )
            self.proposals.append(proposal)
            return proposal
        self._in_flight_targets.update(selected)
        proposal = ChaosProposal(
            experiment_id=experiment_id,
            action_type=action_type,
            targets=selected,
            accepted=True,
            reason="within_radius",
            causal_hypothesis_ref=causal_hypothesis_ref,
            impact_envelope_id=impact_envelope_id,
            recovery_plan_id=recovery_plan_id,
        )
        self.proposals.append(proposal)
        if self.bus is not None:
            await self.bus.publish(
                "Loki",
                "object.chaos-experiment",
                {
                    "producer_principal": "Loki",
                    "correlation_id": correlation_id or experiment_id,
                    "experiment_id": experiment_id,
                    "action_type": action_type,
                    "targets": list(selected),
                    "blast_radius_used": len(selected),
                    "causal_hypothesis_ref": causal_hypothesis_ref,
                    "refutation_query_ref": refutation_query_ref,
                    "impact_envelope_id": impact_envelope_id,
                    "recovery_plan_id": recovery_plan_id,
                    "dry_run_receipt": dry_run_receipt,
                    "human_approval_required": True,
                },
            )
        return proposal

    def release_targets(self, targets: tuple[str, ...]) -> None:
        """Called after experiment completion (Wave 5 test helper)."""
        for t in targets:
            self._in_flight_targets.discard(t)

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Chaos answers rest on proposals made; the cap alone is config."""
        return bool(self.proposals)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        accepted = [p for p in self.proposals if p.accepted]
        facts = {
            **capability_facts(self.spec),
            "blast_radius_cap": self._cap,
            "in_flight_targets": [],
            "in_flight_target_count": len(self._in_flight_targets),
            "proposals_total": len(self.proposals),
            "proposals_accepted": len(accepted),
            "resilience_score_available": False,
        }
        normalized_question = question.casefold()
        if "resilience" in normalized_question and "score" in normalized_question:
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            return IntrospectionResult(
                answer=(
                    "No retained resilience score is bound to this conversational projection. "
                    f"Evidence: {evidence_ref}."
                ),
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


__all__ = ["Loki", "ChaosProposal"]
