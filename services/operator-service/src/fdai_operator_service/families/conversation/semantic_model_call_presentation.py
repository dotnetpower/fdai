"""Localized live-only activity text for one semantic planning model call."""

from __future__ import annotations

from typing import TypedDict

from fdai_service_contracts.semantic_model_call_progress import SemanticModelCallProgress


class ModelCallActivity(TypedDict):
    phase: str
    label: str
    status: str
    event_id: str
    activity_id: str
    kind: str
    detail: str
    observed_at: str


# Reviewed stage names in the operator's language; the stage itself stays a closed code.
_STAGE_LABELS: dict[str, tuple[str, str]] = {
    "preflight": ("질문 분류", "Question routing"),
    "judgment": ("의미 판단", "Meaning judgment"),
    "form": ("질문 해석", "Question reading"),
    "blind_review": ("독립 제약 읽기", "Independent constraint reading"),
    "concept_chooser": ("개념 선택", "Concept selection"),
    "direction_reader": ("관계 방향 확인", "Relation direction check"),
    "ambiguity_reader": ("모호성 확인", "Ambiguity check"),
    "frame": ("질문 구조화", "Question framing"),
    "plan": ("조회 계획", "Read planning"),
}


def model_call_activity(call: SemanticModelCallProgress, *, locale: str) -> ModelCallActivity:
    """Return bounded presentation fields for one model call without model-authored content."""

    korean = locale.casefold().startswith("ko")
    korean_stage, english_stage = _STAGE_LABELS.get(call.stage, (call.stage, call.stage))
    label = f"{korean_stage} 모델 호출" if korean else f"{english_stage} model call"
    model = call.model or ("모델" if korean else "model")
    if call.status == "running":
        detail = f"{model} 응답 대기 중" if korean else f"waiting for {model}"
    else:
        seconds = (call.duration_ms or 0) / 1000
        outcome = (
            ("완료" if korean else "completed")
            if call.status == "completed"
            else ("실패" if korean else "failed")
        )
        detail = (
            f"{model} · {seconds:.1f}초 · {outcome}"
            if korean
            else f"{model} · {seconds:.1f} s · {outcome}"
        )
    return {
        "phase": f"model:{call.call_index}",
        "label": label,
        "status": call.status,
        "event_id": "0:planning",
        "activity_id": f"semantic:model:{call.call_index}",
        "kind": "model_call",
        "detail": detail,
        "observed_at": (call.completed_at or call.started_at).isoformat(),
    }


__all__ = ["ModelCallActivity", "model_call_activity"]
