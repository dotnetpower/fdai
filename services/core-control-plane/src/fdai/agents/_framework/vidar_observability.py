"""Health and conversational introspection mixin for Vidar."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
)
from fdai.agents._framework.vidar_rollback_records import (
    RollbackExecutor,
    RollbackRecord,
    _kpi_ratio,
)
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.base import AgentSpec


class VidarObservabilityMixin:
    """Expose recovery state without adding execution or judgment authority."""

    _state_store: StateStore | None
    records: list[RollbackRecord]
    _published_rollbacks: BoundedLruSet[tuple[str, str]]
    _rehearsal_receipts: BoundedLruDict[str, dict[str, object]]
    _dr_outcomes: BoundedLruDict[str, dict[str, object]]
    _last_dr_readiness: dict[str, object]
    _allow_process_local_rollback: bool
    _executors: dict[str, RollbackExecutor]
    spec: AgentSpec
    _durable_publication_pending: int
    _rollback_path_validations: BoundedLruDict[str, dict[str, object]]

    if TYPE_CHECKING:

        def behavior_snapshot(self) -> dict[str, int]: ...

    def health(self) -> dict[str, Any]:
        durability = "durable" if self._state_store is not None else "process_local"
        local_publication_pending = sum(
            1
            for rec in self.records
            if rec.correlation_id
            and (rec.correlation_id, rec.action_run_identity) not in self._published_rollbacks
        )
        terminal_records = [
            rec for rec in self.records if rec.state in {"succeeded", "failed", "execution_unknown"}
        ]
        succeeded = sum(1 for rec in terminal_records if rec.state == "succeeded")
        validation_failures = sum(
            1
            for rec in terminal_records
            if rec.state == "failed" and "validation" in rec.notes.lower()
        )
        rehearsal_receipts = [receipt for _, receipt in self._rehearsal_receipts.items()]
        rehearsal_passed = sum(1 for rec in rehearsal_receipts if rec.get("outcome") == "passed")
        rehearsal_failed = sum(1 for rec in rehearsal_receipts if rec.get("outcome") == "failed")
        rehearsal_held = sum(1 for rec in rehearsal_receipts if rec.get("outcome") == "held")
        dr_outcomes = [outcome for _, outcome in self._dr_outcomes.items()]
        mttr_samples = [
            sample.get("recovery_time_seconds")
            for sample in dr_outcomes
            if isinstance(sample.get("recovery_time_seconds"), int | float)
        ]
        readiness_validated = self._last_dr_readiness.get("validated_action_types", 0)
        readiness_missing = self._last_dr_readiness.get("missing_action_types", 0)
        if not isinstance(readiness_validated, int):
            readiness_validated = 0
        if not isinstance(readiness_missing, int):
            readiness_missing = 0
        if readiness_validated + readiness_missing:
            path_failure_numerator = readiness_missing
            path_failure_denominator = readiness_validated + readiness_missing
        else:
            path_failure_numerator = validation_failures
            path_failure_denominator = len(terminal_records)
        durable_ready = self._state_store is not None or self._allow_process_local_rollback
        action_specific_ready = bool(readiness_validated) and not bool(readiness_missing)
        executor_ready = bool(self._executors) or action_specific_ready
        status = "ok" if durable_ready and executor_ready else "degraded"
        return {
            "agent": self.spec.name,
            "status": status,
            "status_reason": "ready" if status == "ok" else "rollback_dependency_incomplete",
            "rollback_durability": durability,
            "process_local_rollback_allowed": self._allow_process_local_rollback,
            "rollback_executor_bound": executor_ready,
            "rollback_publication_pending": max(
                local_publication_pending,
                self._durable_publication_pending,
            ),
            "rollback_path_validation": {
                "evidence_state": self._last_dr_readiness["evidence_state"],
                "paths": dict(self._rollback_path_validations.items()),
            },
            "dr_readiness_score": dict(self._last_dr_readiness),
            "rollback_rehearsal": {
                "evidence_state": (
                    "unbound"
                    if rehearsal_held and not rehearsal_passed
                    else "measured"
                    if rehearsal_receipts
                    else "not_observed"
                ),
                "receipts": len(rehearsal_receipts),
                "passed": rehearsal_passed,
                "failed": rehearsal_failed,
                "held": rehearsal_held,
            },
            "rollback_outcomes": {
                "attempts": len(terminal_records),
                "succeeded": succeeded,
                "failed": sum(1 for rec in terminal_records if rec.state == "failed"),
                "refused": sum(1 for rec in terminal_records if rec.state == "refused"),
                "execution_unknown": sum(
                    1 for rec in terminal_records if rec.state == "execution_unknown"
                ),
                "validation_failures": validation_failures,
            },
            "mttr_samples": {
                "count": len(mttr_samples),
                "unit": "seconds",
                "evidence_state": "measured" if mttr_samples else "not_observed",
            },
            "kpis": {
                "rollback_success_rate": _kpi_ratio(succeeded, len(terminal_records)),
                "rollback_path_validation_failure_rate": _kpi_ratio(
                    path_failure_numerator,
                    path_failure_denominator,
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Recovery answers rest on rollbacks performed; none is a real gap."""
        return bool(self.records)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        recs = self.records
        facts = {
            **capability_facts(self.spec),
            "rollbacks_recorded": len(recs),
            "last_correlation_id": None,
            "last_action_type": None,
            "last_state": None,
            "last_contract": None,
            "last_rollback_ref": None,
        }
        if recs:
            last = recs[-1]
            facts.update(
                {
                    "last_correlation_id": last.correlation_id,
                    "last_action_type": last.action_type,
                    "last_state": last.state,
                    "last_contract": last.contract,
                    # The proof the rollback ran, not just that it was
                    # attempted. None when the contract produced no artifact.
                    "last_rollback_ref": last.rollback_ref,
                }
            )
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 파이프라인 Rollback 및 재해 복구 principal인 Vidar입니다. Thor에게 "
                "보고합니다. 실패한 ActionRun을 받아 테스트된 복구 계약으로 Rollback을 조정하고 "
                "증적을 기록합니다. 저는 hard dependency이므로 사용할 수 없으면 새 변경은 "
                "안전하게 중단돼야 합니다. 원래 작업을 판단하거나 승인하거나 실행하지 않습니다. "
                "이 대화 포트는 읽기 전용이며 복구 요청은 운영자 권한으로 타입이 지정된 "
                "파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 공개하지 않습니다."
            )
            if recs:
                answer += (
                    f" 이 런타임은 Rollback {len(recs)}건을 기록했으며 마지막 기록은 "
                    f"{last.action_type}의 {last.state} 상태와 {last.contract} 계약입니다."
                )
            else:
                answer += " 이 런타임에서 수행한 Rollback은 없습니다."
            answer += f" 근거: {evidence_ref}."
        else:
            answer = (
                "I am Vidar, the pipeline Rollback and disaster-recovery principal. I report to "
                "Thor. I receive failed ActionRuns, coordinate their tested recovery contracts, "
                "and record the evidence. I am a hard dependency, so new changes must stop safely "
                "when I am unavailable. I do not judge, approve, or execute the original action. "
                "This conversational port is read-only; recovery requests re-enter the typed "
                "pipeline under the operator's authority. I do not reveal hidden system prompts."
            )
            if recs:
                rollback_label = "Rollback" if len(recs) == 1 else "Rollbacks"
                answer += (
                    f" This runtime records {len(recs)} {rollback_label}; the latest is "
                    f"{last.action_type} in {last.state} through {last.contract}."
                )
            else:
                answer += " No Rollback has been performed in this runtime."
            answer += f" Evidence: {evidence_ref}."
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["VidarObservabilityMixin"]
