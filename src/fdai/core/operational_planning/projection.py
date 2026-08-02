"""Bounded Planning Room projection over Process child events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind

from .models import OperationalPlan, PlanningPhase


def operational_plan_event_payload(plan: OperationalPlan) -> dict[str, object]:
    """Return an allowlisted read projection for one immutable plan."""
    assessments = {item.candidate_id: item for item in plan.assessments}
    return {
        "plan_id": plan.plan_id,
        "process_id": plan.process_id,
        "logic_release_digest": plan.logic_release_digest,
        "complete": plan.complete,
        "reason": plan.reason,
        "selected_option_id": plan.selection.selected_option_id,
        "requires_human_approval": plan.selection.requires_human_approval,
        "margin": plan.selection.margin,
        "candidates": [
            {
                "candidate_id": option.option_id,
                "action_type": option.action_type,
                "disposition": assessments[option.option_id].disposition.value,
                "reasons": list(assessments[option.option_id].reasons),
                "proposing_agents": list(option.proposing_agents),
                "logic_receipt_refs": list(option.logic_receipt_refs),
                "simulation_receipt_refs": list(option.simulation_receipt_refs),
                "constraint_evaluation_refs": list(option.constraint_evaluation_refs),
                "expected_effects": [
                    {
                        "objective_id": effect.objective_id,
                        "metric": effect.metric,
                        "expected_min": effect.expected_min,
                        "expected_max": effect.expected_max,
                        "confidence": effect.confidence,
                    }
                    for effect in option.effects
                ],
            }
            for option in plan.decision_case.options
        ],
    }


def project_planning_room(events: Sequence[ProcessEvent]) -> dict[str, object] | None:
    """Fold planning child events into one rebuildable, bounded read model."""
    planning_events = tuple(
        event for event in events if event.kind is ProcessEventKind.PLANNING_PHASE_RECORDED
    )
    if not planning_events:
        return None
    phases: list[dict[str, object]] = []
    final_plan: dict[str, object] | None = None
    seen: set[PlanningPhase] = set()
    for event in planning_events:
        raw_phase = event.payload.get("planning_phase")
        try:
            phase = PlanningPhase(str(raw_phase))
        except ValueError:
            continue
        if phase in seen:
            continue
        seen.add(phase)
        evidence = _bounded_strings(event.payload.get("evidence_refs"), limit=64)
        phases.append(
            {
                "phase": phase.value,
                "actor_agent": _bounded_text(event.payload.get("actor_agent"), 64),
                "recorded_at": event.recorded_at.isoformat(),
                "event_id": event.event_id,
                "evidence_refs": evidence,
            }
        )
        raw_plan = event.payload.get("operational_plan")
        if isinstance(raw_plan, Mapping):
            final_plan = _project_plan(raw_plan)
    current_phase = phases[-1]["phase"] if phases else "unknown"
    return {
        "current_phase": current_phase,
        "phase_count": len(phases),
        "phases": phases,
        "plan": final_plan,
    }


def _project_plan(value: Mapping[str, Any]) -> dict[str, object]:
    raw_candidates = value.get("candidates")
    candidates: list[dict[str, object]] = []
    if isinstance(raw_candidates, Sequence) and not isinstance(raw_candidates, str | bytes):
        for item in raw_candidates[:32]:
            if not isinstance(item, Mapping):
                continue
            candidates.append(
                {
                    "candidate_id": _bounded_text(item.get("candidate_id"), 256),
                    "action_type": _bounded_optional_text(item.get("action_type"), 256),
                    "disposition": _bounded_text(item.get("disposition"), 32),
                    "reasons": _bounded_strings(item.get("reasons"), limit=32),
                    "proposing_agents": _bounded_strings(item.get("proposing_agents"), limit=15),
                    "logic_receipt_refs": _bounded_strings(
                        item.get("logic_receipt_refs"), limit=32
                    ),
                    "simulation_receipt_refs": _bounded_strings(
                        item.get("simulation_receipt_refs"), limit=32
                    ),
                    "constraint_evaluation_refs": _bounded_strings(
                        item.get("constraint_evaluation_refs"), limit=32
                    ),
                    "expected_effects": _effects(item.get("expected_effects")),
                }
            )
    return {
        "plan_id": _bounded_text(value.get("plan_id"), 256),
        "logic_release_digest": _bounded_text(value.get("logic_release_digest"), 80),
        "complete": value.get("complete") is True,
        "reason": _bounded_text(value.get("reason"), 128),
        "selected_option_id": _bounded_optional_text(value.get("selected_option_id"), 256),
        "requires_human_approval": value.get("requires_human_approval") is True,
        "margin": _finite_number(value.get("margin")),
        "candidates": candidates,
    }


def _effects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    result: list[dict[str, object]] = []
    for item in value[:32]:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "objective_id": _bounded_text(item.get("objective_id"), 128),
                "metric": _bounded_text(item.get("metric"), 128),
                "expected_min": _finite_number(item.get("expected_min")),
                "expected_max": _finite_number(item.get("expected_max")),
                "confidence": _finite_number(item.get("confidence")),
            }
        )
    return result


def _bounded_strings(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [
        bounded
        for item in value[:limit]
        if (bounded := _bounded_optional_text(item, 512)) is not None
    ]


def _bounded_text(value: object, maximum: int) -> str:
    return _bounded_optional_text(value, maximum) or "unknown"


def _bounded_optional_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:maximum] if normalized else None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    normalized = float(value)
    return normalized if normalized == normalized and abs(normalized) != float("inf") else None


__all__ = ["operational_plan_event_payload", "project_planning_room"]
