"""Pure terminal frame and payload assembly for streamed chat turns."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.delivery.operator_api.projections.conversation.presentation import (
    response_presentation_artifact,
)
from fdai.delivery.operator_api.projections.conversation.provenance import web_search_summary
from fdai.delivery.operator_api.projections.conversation.terminal.llm_usage import (
    response_llm_usage_analysis_context,
    response_llm_usage_chart_artifact,
)
from fdai.delivery.operator_api.projections.conversation.terminal.resource_context import (
    response_resource_result_context,
)
from fdai.delivery.operator_api.projections.conversation.terminal.source_failure import (
    response_source_failure_context,
)

if TYPE_CHECKING:
    from fdai.delivery.operator_api.application.conversation.verification import AnswerVerification

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
_MAX_INCIDENT_CANDIDATES: Final[int] = 5
_MAX_INCIDENT_FIELD_CHARS: Final[int] = 512
_MAX_PUBLIC_EVIDENCE_REFS: Final[int] = 12
_ASSURANCE_POLICY_KEY: Final[str] = "_conversation_assurance_policy"


class _QualityProjection(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class _FreshnessProjection(Protocol):
    def to_dict(self) -> dict[str, object]: ...


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


def response_incident_candidates(
    enriched_context: Mapping[str, Any],
    *,
    verification: AnswerVerification,
    locale: str | None = None,
) -> dict[str, Any] | None:
    if verification.reason_code != "ambiguous_incident":
        return None
    evidence = enriched_context.get("_operational_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("status") != "ambiguous":
        return None
    raw_candidates = evidence.get("candidates")
    if not isinstance(raw_candidates, list):
        return None
    candidates: list[dict[str, str]] = []
    for raw in raw_candidates[:_MAX_INCIDENT_CANDIDATES]:
        if not isinstance(raw, Mapping):
            return None
        correlation_id = _incident_candidate_field(raw.get("correlation_id"))
        if correlation_id is None:
            return None
        raw_incident_id = raw.get("incident_id")
        incident_id = _incident_candidate_field(raw_incident_id)
        if raw_incident_id is None:
            incident_id = _incident_candidate_field(f"INC-{correlation_id}")
        if incident_id is None:
            return None
        projected = {"incident_id": incident_id, "correlation_id": correlation_id}
        for field_name in ("title", "severity", "status", "last_updated_at"):
            normalized = _incident_candidate_field(raw.get(field_name))
            if normalized is None:
                return None
            projected[field_name] = normalized
        candidates.append(projected)
    if not candidates:
        return None
    return {
        "schema_version": 1,
        "locale": _incident_candidate_locale(locale),
        "candidates": candidates,
    }


def _incident_candidate_field(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if len(normalized) > _MAX_INCIDENT_FIELD_CHARS or any(
        character in normalized for character in ("\x00", "\r", "\n")
    ):
        return None
    return normalized


def _incident_candidate_locale(locale: str | None) -> str:
    if not isinstance(locale, str):
        return "en"
    primary = locale.strip().lower().split("-", 1)[0].split("_", 1)[0]
    return "ko" if primary == "ko" else "en"


def public_intent_graph_evidence(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Remove provider payloads from the browser-persisted execution ledger."""

    public_goals: list[dict[str, Any]] = []
    goals = raw.get("goals")
    if isinstance(goals, list):
        for item in goals[:8]:
            if not isinstance(item, Mapping):
                continue
            receipt = {
                key: item[key]
                for key in (
                    "goal_id",
                    "task_id",
                    "intent",
                    "capability",
                    "evidence_mode",
                    "status",
                    "duration_ms",
                    "depends_on",
                    "reason",
                    "blocked_by",
                    "started_at",
                    "completed_at",
                )
                if key in item
            }
            refs = _collect_evidence_refs(item.get("evidence"))
            if refs:
                receipt["evidence_refs"] = refs
            public_goals.append(receipt)
    return {
        "schema_version": 1,
        "status": str(raw.get("status") or "unavailable"),
        "evidence_mode": str(raw.get("evidence_mode") or "held_for_review"),
        "goals": public_goals,
    }


def _collect_evidence_refs(value: object) -> list[str]:
    refs: list[str] = []

    def visit(candidate: object, depth: int) -> None:
        if depth > 3 or len(refs) >= _MAX_PUBLIC_EVIDENCE_REFS:
            return
        if isinstance(candidate, Mapping):
            for key, nested in list(candidate.items())[:32]:
                if key in {"evidence_ref", "trace_ref"} and isinstance(nested, str):
                    refs.append(nested[:512])
                elif key in {"evidence_refs", "source_refs"} and isinstance(nested, list):
                    refs.extend(
                        item[:512]
                        for item in nested[: _MAX_PUBLIC_EVIDENCE_REFS - len(refs)]
                        if isinstance(item, str)
                    )
                else:
                    visit(nested, depth + 1)
        elif isinstance(candidate, list):
            for nested in candidate[:32]:
                visit(nested, depth + 1)

    visit(value, 0)
    return list(dict.fromkeys(ref for ref in refs if ref))[:_MAX_PUBLIC_EVIDENCE_REFS]


def assurance_policy_summary(view_context: Mapping[str, Any]) -> dict[str, str] | None:
    """Project one bounded public summary from the server-owned policy context."""

    raw = view_context.get(_ASSURANCE_POLICY_KEY)
    if not isinstance(raw, Mapping):
        return None
    summary: dict[str, str] = {}
    for key in ("candidate_id", "policy_digest", "stage", "target"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            return None
        summary[key] = value
    return summary


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
    freshness_answer: str | None,
    started: float,
    delegation: Mapping[str, Any] | None,
    enriched_context: Mapping[str, Any],
    response_locale: str | None,
    answer_plan: AnswerPlan,
    answer_planning: Mapping[str, Any] | None,
    quality: _QualityProjection | None,
    resource_context: Mapping[str, str] | None,
    freshness_context: _FreshnessProjection | None,
    model_trace: Mapping[str, Any] | None,
    turn_timing: Mapping[str, Any] | None,
    trajectory_detail: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = None
    if resource_answer is not None:
        source = "evidence:read-investigation"
    elif freshness_answer is not None:
        source = "evidence:freshness"
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
        "web_search": web_search_summary(enriched_context),
        "answer_plan": answer_plan.to_dict(),
        "answer_planning": answer_planning,
        "code_artifacts": [
            artifact.to_dict() for artifact in extract_grounded_code(verification.answer)
        ],
    }
    incident_candidates = response_incident_candidates(
        enriched_context,
        verification=verification,
        locale=response_locale,
    )
    if incident_candidates is not None:
        payload["incident_candidates"] = incident_candidates
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
    resource_result_context = response_resource_result_context(
        enriched_context,
        verification_status=verification.status,
    )
    if resource_result_context is not None:
        payload["resource_result_context"] = resource_result_context
    source_failure_context = response_source_failure_context(
        enriched_context,
        verification_status=verification.status,
    )
    if source_failure_context is not None:
        payload["source_failure_context"] = source_failure_context
    analysis_context = response_llm_usage_analysis_context(
        enriched_context,
        verification_status=verification.status,
    )
    if analysis_context is not None:
        payload["analysis_context"] = analysis_context
    context_locale = enriched_context.get("_locale")
    locale = response_locale or (context_locale if isinstance(context_locale, str) else None)
    chart_artifact = response_llm_usage_chart_artifact(
        enriched_context,
        verification_status=verification.status,
        answer_format=answer_plan.format.value,
        locale=locale,
    )
    if chart_artifact is not None:
        payload["chart_artifact"] = chart_artifact
    presentation_artifact = response_presentation_artifact(
        enriched_context,
        answer_plan=answer_plan,
        verification_status=verification.status,
        evidence_refs=verification.evidence_refs,
        locale=locale,
    )
    if presentation_artifact is not None:
        payload["presentation_artifact"] = presentation_artifact
    if freshness_context is not None:
        payload["evidence_freshness_context"] = freshness_context.to_dict()
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


__all__ = [
    "TurnTimingRecorder",
    "TurnTimingStatus",
    "TurnTimingToken",
    "assurance_policy_summary",
    "build_done_payload",
    "public_intent_graph_evidence",
    "response_incident_candidates",
    "verification_events",
]
