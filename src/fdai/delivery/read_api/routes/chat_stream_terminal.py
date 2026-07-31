"""Pure terminal frame and payload assembly for streamed chat turns."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.delivery.read_api.routes.chat_answer_quality import AnswerQualityResult
from fdai.delivery.read_api.routes.chat_evidence_enrichment import _web_search_summary
from fdai.delivery.read_api.routes.chat_verification import AnswerVerification


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
    if quality is not None:
        payload["answer_quality"] = quality.to_dict()
    if resource_context is not None:
        payload["resource_context"] = dict(resource_context)
    if model_trace is not None:
        payload["model_trace"] = dict(model_trace)
    return payload
