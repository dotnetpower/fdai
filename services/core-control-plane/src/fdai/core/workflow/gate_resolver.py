"""Resolve workflow gate references against authoritative evidence providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.workflow.workflow_runtime import WorkflowGuardEvaluator

CHANGE_WINDOW_GATE_REF = "change-window.active"


class ChangeWindowGateEvidence(Protocol):
    async def is_active(self, *, target_ref: str, at: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class ChangeWindowWorkflowGuardEvaluator:
    """Evaluate ChangeWindow gates and delegate unrelated gate references."""

    change_windows: ChangeWindowGateEvidence
    fallback: WorkflowGuardEvaluator | None = None

    async def evaluate_context(
        self,
        *,
        rule_id: str,
        step_id: str,
        process_id: str,
        target_resource_id: str,
        at: datetime,
    ) -> bool:
        if rule_id == CHANGE_WINDOW_GATE_REF:
            return await self.change_windows.is_active(
                target_ref=target_resource_id,
                at=at,
            )
        if self.fallback is None:
            return False
        return await self.fallback.evaluate(
            rule_id=rule_id,
            step_id=step_id,
            process_id=process_id,
        )


__all__ = ["CHANGE_WINDOW_GATE_REF", "ChangeWindowWorkflowGuardEvaluator"]
