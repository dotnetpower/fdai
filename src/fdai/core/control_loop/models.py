"""Typed terminal results returned by the control-loop orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.core.executor import ExecutionResult
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.core.rca import RcaResult
from fdai.core.tiers.t1_lightweight.tier import T1Decision
from fdai.core.tiers.t2_reasoning import T2Decision
from fdai.core.verticals.change_safety.detector import ChangeSafetyDecision


class ControlLoopOutcome(StrEnum):
    """Top-level outcome for one control-loop process call."""

    DEDUPED = "deduped"
    ABSTAINED_ROUTING = "abstained_routing"
    ABSTAINED_T0 = "abstained_t0"
    EXECUTED = "executed"
    ABSTAINED_ACTION_BUILD = "abstained_action_build"
    GOVERNANCE_OBSERVED = "governance_observed"
    HIL = "hil"
    DENIED = "denied"
    T1_REUSE_LOGGED = "t1_reuse_logged"
    T1_ABSTAINED = "t1_abstained"
    T2_PROPOSED_LOGGED = "t2_proposed_logged"
    T2_ESCALATED = "t2_escalated"
    T2_DENIED = "t2_denied"
    T2_ABSTAINED = "t2_abstained"
    OPERATOR_REQUEST_LOGGED = "operator_request_logged"
    CANARY_RECORDED = "canary_recorded"


@dataclass(frozen=True, slots=True)
class ControlLoopResult:
    """Aggregate typed result for one event."""

    outcome: ControlLoopOutcome
    tier: str
    decision: str
    resource_type: str | None
    citing_rule_ids: tuple[str, ...] = ()
    execution_results: tuple[
        ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult, ...
    ] = ()
    reason: str | None = None
    event_id: str | None = None
    change_safety_decision: ChangeSafetyDecision | None = None
    t1_decision: T1Decision | None = None
    t2_decision: T2Decision | None = None
    rca_result: RcaResult | None = None


__all__ = ["ControlLoopOutcome", "ControlLoopResult"]
