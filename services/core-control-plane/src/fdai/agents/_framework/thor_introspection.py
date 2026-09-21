"""Read-only conversational projection over Thor-owned ActionRun state."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.action_run_state import (
    TERMINAL_ACTION_RUN_STATES as _TERMINAL_STATES,
)
from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.role_answers import thor_role_answer
from fdai.agents._framework.thor_action_run import ActionRun


def evidence_available(runs: dict[str, ActionRun]) -> bool:
    """Return whether Thor has dispatched state to ground an answer."""
    return bool(runs)


def introspect(
    *,
    spec: AgentSpec,
    runs: dict[str, ActionRun],
    shadow_forced: bool,
    question: str,
    context: dict[str, Any],
) -> IntrospectionResult:
    """Render bounded evidence about Thor's owned ActionRun projection."""
    active = [run for run in runs.values() if run.state not in _TERMINAL_STATES]
    facts = {
        **capability_facts(spec),
        "total_runs": len(runs),
        "active_runs": len(active),
        "shadow_forced": shadow_forced,
    }
    selectors = list(runs) + [run.resource_id for run in runs.values() if run.resource_id]
    keys = set(mentioned(question, selectors))
    target = next(
        (
            run
            for run in runs.values()
            if run.correlation_id in keys or (run.resource_id and run.resource_id in keys)
        ),
        None,
    )
    if target is not None:
        facts.update(
            {
                "correlation_id": target.correlation_id,
                "action_type": target.action_type,
                "resource_id": target.resource_id,
                "state": target.state.value,
                "state_history": [state.value for state in target.history],
                "verdict": target.verdict,
                "quorum_required": target.quorum_required,
                "outcome": target.outcome,
                "shadow_mode": target.shadow_mode,
                "rollback_contract": target.rollback_contract,
                "rollback_ref": target.rollback_ref,
            }
        )
        evidence_ref = agent_state_evidence_ref(spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        location = f" on {target.resource_id}" if target.resource_id else ""
        answer = (
            f"ActionRun {target.correlation_id!r} ({target.action_type}) is "
            f"{target.state.value}{location}. Evidence: {evidence_ref}."
        )
        return IntrospectionResult(answer=answer, facts=facts)
    evidence_ref = agent_state_evidence_ref(spec.name, facts)
    facts["evidence_refs"] = [evidence_ref]
    answer = thor_role_answer(str(context.get("locale")), len(runs), len(active), evidence_ref)
    return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["evidence_available", "introspect"]
