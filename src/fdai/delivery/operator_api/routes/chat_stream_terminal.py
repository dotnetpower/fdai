"""Pure terminal frame and payload assembly for streamed chat turns."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.delivery.operator_api.routes.chat_answer_quality import AnswerQualityResult
from fdai.delivery.operator_api.routes.chat_evidence_enrichment import _web_search_summary
from fdai.delivery.operator_api.routes.chat_intent_graph_execution import (
    public_intent_graph_evidence,
)
from fdai.delivery.operator_api.routes.chat_route_common import assurance_policy_summary
from fdai.delivery.operator_api.routes.chat_verification import AnswerVerification

TurnTimingPhase = Literal[
    "semantic_plan",
    "evidence",
    "generation",
    "quality_review",
    "verification",
]
TurnTimingStatus = Literal["completed", "corrected", "degraded", "failed", "unverified"]

_MAX_TURN_TIMING_PHASES: Final[int] = 8
_TURN_TIMING_PHASES: Final[frozenset[str]] = frozenset(
    {"semantic_plan", "evidence", "generation", "quality_review", "verification"}
)


@dataclass(frozen=True, slots=True)
class TurnTimingToken:
    phase: TurnTimingPhase
    started_monotonic: float


@dataclass(slots=True)
class TurnTimingRecorder:
    started_monotonic: float = field(default_factory=time.monotonic)
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    _phases: list[dict[str, Any]] = field(default_factory=list, init=False)
    _active: set[str] = field(default_factory=set, init=False)

    def begin(self, phase: TurnTimingPhase) -> TurnTimingToken:
        if phase not in _TURN_TIMING_PHASES:
            raise ValueError("turn timing phase is not allowlisted")
        if phase in self._active or any(item["phase"] == phase for item in self._phases):
            raise ValueError("turn timing phase is duplicated")
        if len(self._phases) + len(self._active) >= _MAX_TURN_TIMING_PHASES:
            raise ValueError("turn timing phase cap exceeded")
        self._active.add(phase)
        return TurnTimingToken(phase=phase, started_monotonic=time.monotonic())

    def complete(self, token: TurnTimingToken, *, status: TurnTimingStatus) -> None:
        if token.phase not in self._active:
            raise ValueError("turn timing phase is not active")
        completed_monotonic = time.monotonic()
        if completed_monotonic < token.started_monotonic:
            raise ValueError("turn timing monotonic clock moved backward")
        self._active.remove(token.phase)
        self._phases.append(
            {
                "phase": token.phase,
                "status": status,
                "started_at": self._timestamp(token.started_monotonic),
                "completed_at": self._timestamp(completed_monotonic),
                "duration_ms": int((completed_monotonic - token.started_monotonic) * 1000),
            }
        )

    def snapshot(self) -> dict[str, Any]:
        if self._active:
            raise ValueError("turn timing has active phases")
        completed_monotonic = time.monotonic()
        return {
            "schema_version": 1,
            "started_at": self.started_at.isoformat(),
            "completed_at": self._timestamp(completed_monotonic),
            "duration_ms": max(0, int((completed_monotonic - self.started_monotonic) * 1000)),
            "phases": sorted(self._phases, key=lambda item: str(item["started_at"])),
        }

    def _timestamp(self, monotonic_value: float) -> str:
        offset = max(0.0, monotonic_value - self.started_monotonic)
        return (self.started_at + timedelta(seconds=offset)).isoformat()


def verification_events(
    provisional_answer: str,
    verification: AnswerVerification,
    revision: int,
) -> tuple[tuple[tuple[str, dict[str, Any]], ...], int]:
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "verification",
            {
                "phase": "verifying",
                "label": "Verifying answer against evidence",
                "completed": 0,
                "total": verification.checks_total,
            },
        ),
        (
            "verification",
            {
                "phase": verification.status,
                "label": f"Verification {verification.status}",
                "completed": verification.checks_completed,
                "total": verification.checks_total,
                "authority": verification.authority,
                "evidence_refs": list(verification.evidence_refs),
                "reason_code": verification.reason_code,
            },
        ),
    ]
    if verification.answer != provisional_answer:
        revision += 1
        events.append(
            (
                "revision",
                {
                    "answer": verification.answer,
                    "replaces_revision": revision - 1,
                    "status": verification.status,
                    "reason_code": verification.reason_code,
                    "evidence_refs": list(verification.evidence_refs),
                },
            )
        )
    return tuple(events), revision


def build_done_payload(
    *,
    verification: AnswerVerification,
    terminal_model: Any,
    terminal_router: Any,
    terminal_usage: Any,
    evidence_fast_path: bool,
    ontology_answer: str | None,
    health_answer: str | None,
    screen_answer: str | None,
    concept_answer: str | None,
    resource_answer: str | None,
    started: float,
    delegation: Mapping[str, Any] | None,
    enriched_context: Mapping[str, Any],
    answer_plan: AnswerPlan,
    answer_planning: Mapping[str, Any] | None,
    quality: AnswerQualityResult | None,
    resource_context: Mapping[str, str] | None,
    model_trace: Mapping[str, Any] | None,
    turn_timing: Mapping[str, Any] | None,
    trajectory_detail: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = None
    if resource_answer is not None:
        source = "evidence:read-investigation"
    elif evidence_fast_path:
        source = f"evidence:{verification.status}"
    elif ontology_answer is not None:
        source = "evidence:ontology-snapshot"
    elif health_answer is not None:
        source = "evidence:system-health"
    elif screen_answer is not None:
        source = "evidence:current-screen"
    elif concept_answer is not None:
        source = "evidence:fdai-glossary"

    payload: dict[str, Any] = {
        "answer": verification.answer,
        "model": terminal_model,
        "router": terminal_router,
        "usage": terminal_usage,
        "source": source,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "verification": verification.to_dict(),
        "delegation": delegation,
        "web_search": _web_search_summary(enriched_context),
        "answer_plan": answer_plan.to_dict(),
        "answer_planning": answer_planning,
        "code_artifacts": [
            artifact.to_dict() for artifact in extract_grounded_code(verification.answer)
        ],
    }
    if isinstance(enriched_context.get("_intent_graph"), Mapping):
        payload["intent_graph"] = dict(enriched_context["_intent_graph"])
    if isinstance(enriched_context.get("_intent_graph_evidence"), Mapping):
        graph_evidence = public_intent_graph_evidence(enriched_context["_intent_graph_evidence"])
        payload["intent_graph_evidence"] = graph_evidence
        payload["evidence_mode"] = graph_evidence.get("evidence_mode")
    if quality is not None:
        payload["answer_quality"] = quality.to_dict()
    if resource_context is not None:
        payload["resource_context"] = dict(resource_context)
    if model_trace is not None:
        payload["model_trace"] = dict(model_trace)
    if turn_timing is not None:
        payload["turn_timing"] = dict(turn_timing)
    if trajectory_detail is not None:
        payload["trajectory_detail"] = dict(trajectory_detail)
    policy_summary = assurance_policy_summary(enriched_context)
    if policy_summary is not None:
        payload["conversation_policy"] = policy_summary
    return payload
