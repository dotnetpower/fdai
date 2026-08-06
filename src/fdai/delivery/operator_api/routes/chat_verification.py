"""Deterministic terminal verification for progressive Command Deck answers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.delivery.operator_api.application.conversation.claims import (
    AtomicClaim,
    EvidenceManifest,
    ScreenClaimResult,
    verify_screen_claims,
)
from fdai.delivery.operator_api.routes import chat_verification_rendering as _rendering
from fdai.delivery.operator_api.routes.chat_behavior_evidence import (
    behavior_evidence_refs,
    render_behavior_answer,
)
from fdai.delivery.operator_api.routes.chat_intent_graph_execution import (
    public_intent_graph_evidence,
)
from fdai.delivery.operator_api.routes.chat_operational_verification import (
    verify_operational_evidence,
)
from fdai.delivery.operator_api.routes.chat_tool_contract_verification import (
    verify_tool_contract,
)
from fdai.delivery.operator_api.routes.chat_verification_result import (
    VerificationPayload,
    VerificationStatus,
)
from fdai.delivery.operator_api.routes.chat_verification_text import (
    answer_text_is_well_formed,
    answers_match,
)
from fdai.delivery.operator_api.routes.chat_vision_evidence import vision_evidence_refs

_agent_activity_lines = _rendering.agent_activity_lines
_incident_summary_line = _rendering.incident_summary_line
_integer = _rendering.integer
_mappings = _rendering.mappings
_notification_delivery_lines = _rendering.notification_delivery_lines
_optional_text = _rendering.optional_text
_recorded_detection_lines = _rendering.recorded_detection_lines
_recorded_failure_lines = _rendering.recorded_failure_lines
_strings = _rendering.strings
_text = _rendering.text
_topic_text = _rendering.topic_text

_AGENT_SELF_CAPABILITY_QUESTION = re.compile(
    r"\b(?:what\s+do\s+you\s+do|what\s+is\s+your\s+role|what\s+are\s+your\s+"
    r"responsibilities|describe\s+your\s+role|your\s+primary\s+work)\b"
    r"|(?:너|네|당신)(?:는|가)?\s*(?:주로\s*)?(?:어떤|무슨)?\s*(?:일|역할)"
    r"|(?:무슨\s*일|뭐\s*하는\s*일|담당하는\s*일)",
    re.IGNORECASE,
)
_AGENT_STATE_REF = re.compile(r"^agent-state:([A-Za-z][A-Za-z0-9-]*):sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AnswerVerification:
    """Canonical answer plus the trust state the UI may render."""

    status: VerificationStatus
    answer: str
    authority: str
    checks_completed: int
    checks_total: int
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None
    claims: tuple[AtomicClaim, ...] = ()
    evidence_manifest: EvidenceManifest | None = None
    failed_claim_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "authority": self.authority,
            "checks_completed": self.checks_completed,
            "checks_total": self.checks_total,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "claims": [claim.to_dict() for claim in self.claims],
            "failed_claim_ids": list(self.failed_claim_ids),
        }
        if self.evidence_manifest is not None:
            payload["evidence_manifest"] = self.evidence_manifest.to_dict()
        return payload


def _from_payload(payload: VerificationPayload) -> AnswerVerification:
    return AnswerVerification(
        status=payload.status,
        answer=payload.answer,
        authority=payload.authority,
        checks_completed=payload.checks_completed,
        checks_total=payload.checks_total,
        evidence_refs=payload.evidence_refs,
        reason_code=payload.reason_code,
    )


def _result(
    status: VerificationStatus,
    answer: str,
    reason_code: str,
    refs: tuple[str, ...] = (),
) -> AnswerVerification:
    return AnswerVerification(
        status=status,
        answer=answer,
        authority="server_read_model",
        checks_completed=1,
        checks_total=1,
        evidence_refs=refs,
        reason_code=reason_code,
    )


def _intent_graph_hold(
    view_context: Mapping[str, Any], *, locale: str | None
) -> AnswerVerification | None:
    raw = view_context.get("_intent_graph_evidence")
    if not isinstance(raw, Mapping) or raw.get("status") == "completed":
        return None
    public = public_intent_graph_evidence(raw)
    goals = public.get("goals")
    projected_goals = (
        [item for item in goals if isinstance(item, Mapping)] if isinstance(goals, list) else []
    )
    incomplete = [item for item in projected_goals if item.get("status") != "completed"]
    details = ", ".join(
        f"{_text(item.get('capability'), 'unknown')}: "
        f"{_text(item.get('reason') or item.get('status'), 'unavailable')}"
        for item in incomplete[:5]
    )
    korean = _is_korean(locale)
    answer = (
        "요청한 읽기 계획을 근거로 완료하지 못해 답변을 확정하지 않았습니다."
        if korean
        else "The requested read plan could not be completed from evidence, "
        "so no answer was finalized."
    )
    if details:
        answer += f" {'확인된 제한' if korean else 'Confirmed limits'}: {details}."
    refs = tuple(
        dict.fromkeys(
            ref for item in projected_goals for ref in _strings(item.get("evidence_refs"))
        )
    )
    return AnswerVerification(
        status="unverified",
        answer=answer,
        authority="server_intent_graph",
        checks_completed=sum(1 for item in projected_goals if item.get("status") == "completed"),
        checks_total=max(1, len(projected_goals)),
        evidence_refs=refs,
        reason_code=f"intent_graph_{public.get('status') or 'unavailable'}",
    )


def _verify_agent_self_capability(
    provisional: str,
    view_context: Mapping[str, Any],
    agent_evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> AnswerVerification | None:
    """Render a selected agent's role only from its content-addressed capability facts."""

    plan = view_context.get("_answer_plan")
    subject = plan.get("subject") if isinstance(plan, Mapping) else None
    if not isinstance(subject, str) or _AGENT_SELF_CAPABILITY_QUESTION.search(subject) is None:
        return None
    primary_agent = _optional_text(agent_evidence.get("primary_agent"))
    facts = agent_evidence.get("facts")
    if primary_agent is None or not isinstance(facts, Mapping):
        return None
    fact_agent = _optional_text(facts.get("agent"))
    layer = _optional_text(facts.get("layer"))
    owns = _strings(facts.get("owns"))
    domains = _strings(facts.get("question_domains"))
    refs = tuple(
        ref
        for ref in _strings(facts.get("evidence_refs"))
        if (match := _AGENT_STATE_REF.fullmatch(ref)) is not None
        and match.group(1) == primary_agent
    )
    if fact_agent != primary_agent or layer is None or not owns or not domains or not refs:
        return None

    owned_text = ", ".join(owns)
    domain_text = ", ".join(domain.replace("_", " ") for domain in domains)
    if _is_korean(locale):
        layer_text = {
            "pipeline": "파이프라인",
            "domain": "도메인",
            "governance": "거버넌스",
        }.get(layer, layer)
        answer = (
            f"저는 {primary_agent}이며 {layer_text} 계층의 에이전트입니다. "
            f"주로 {owned_text} 관련 신호를 담당합니다. "
            f"{domain_text} 영역의 질문에 답합니다."
        )
    else:
        answer = (
            f"I am {primary_agent}, a {layer}-layer agent. "
            f"My primary owned signals are {owned_text}. "
            f"I answer questions about {domain_text}."
        )
    return AnswerVerification(
        status=_changed(provisional, answer),
        answer=answer,
        authority="pantheon_runtime",
        checks_completed=1,
        checks_total=1,
        evidence_refs=tuple(dict.fromkeys(refs)),
        reason_code="agent_capability_facts",
    )


def _changed(provisional: str, canonical: str) -> VerificationStatus:
    return "verified" if answers_match(provisional, canonical) else "corrected"


def _correct_concept_scope_additions(
    answer: str,
    view_context: Mapping[str, Any],
    claims: Sequence[AtomicClaim],
) -> tuple[str, ScreenClaimResult] | None:
    """Remove unsupported scope-only addenda from a glossary answer once."""

    if not isinstance(view_context.get("_concept_evidence"), Mapping):
        return None
    failed = tuple(claim for claim in claims if claim.status != "supported")
    if not failed or any(claim.kind != "scope" for claim in failed):
        return None
    corrected = answer
    for claim in sorted(failed, key=lambda item: item.start, reverse=True):
        corrected = corrected[: claim.start] + corrected[claim.end :]
    corrected = corrected.strip()
    if not corrected:
        return None
    verified = verify_screen_claims(corrected, view_context)
    if verified.overflow or not verified.manifest.complete or not verified.supported:
        return None
    return corrected, verified


def _correct_screen_unsupported_sentences(
    answer: str,
    view_context: Mapping[str, Any],
    result: ScreenClaimResult,
) -> tuple[str, ScreenClaimResult] | None:
    """Remove unsupported sentences when other screen claims are grounded."""

    if result.overflow or not result.manifest.complete:
        return None
    failed = tuple(claim for claim in result.claims if claim.status != "supported")
    supported = tuple(claim for claim in result.claims if claim.status == "supported")
    if not failed or not supported:
        return None
    corrected = answer
    for sentence in sorted({claim.text for claim in failed}, key=len, reverse=True):
        corrected = corrected.replace(sentence, "")
    corrected = corrected.strip()
    if not corrected:
        return None
    verified = verify_screen_claims(corrected, view_context)
    if (
        verified.overflow
        or not verified.manifest.complete
        or not verified.supported
        or not verified.claims
    ):
        return None
    return corrected, verified


def _is_korean(locale: str | None) -> bool:
    if locale is None:
        return False
    return locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko"


def verify_answer(
    provisional: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> AnswerVerification:
    """Verify one provisional answer and return its canonical revision.

    Screen-only answers can only be checked for consistency with the supplied
    browser snapshot. Operational answers are replaced with deterministic prose
    rendered from the server-owned evidence state, so unsupported model text
    never becomes the terminal conversation history.
    """

    if not answer_text_is_well_formed(provisional):
        korean = _is_korean(locale)
        return AnswerVerification(
            status="unverified",
            answer=(
                "답변에 유효하지 않은 문자가 포함되어 확정하지 않았습니다. 다시 시도해 주세요."
                if korean
                else "The answer contained invalid characters and was not finalized. Try again."
            ),
            authority="answer_text_integrity",
            checks_completed=0,
            checks_total=1,
            reason_code="answer_text_invalid",
        )

    tool_verification = verify_tool_contract(
        provisional,
        view_context,
        locale=locale,
        changed=_changed,
    )
    if tool_verification is not None:
        return _from_payload(tool_verification)

    graph_hold = _intent_graph_hold(view_context, locale=locale)
    if graph_hold is not None:
        return graph_hold

    behavior = view_context.get("_behavior_evidence")
    if isinstance(behavior, Mapping):
        answer = render_behavior_answer(behavior, locale=locale)
        state = behavior.get("status")
        behavior_refs = behavior_evidence_refs(behavior)
        if state in {"matched", "comparison"}:
            return AnswerVerification(
                status=_changed(provisional, answer),
                answer=answer,
                authority="behavior_knowledge_index",
                checks_completed=len(behavior_refs),
                checks_total=len(behavior_refs),
                evidence_refs=behavior_refs,
                reason_code="behavior_contract_fresh",
            )
        reason = {
            "stale": "behavior_source_stale",
            "conflict": "behavior_contract_conflict",
            "none": "behavior_evidence_absent",
            "unavailable": "behavior_index_unavailable",
        }.get(str(state), "behavior_evidence_unknown")
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="behavior_knowledge_index",
            checks_completed=0,
            checks_total=max(1, len(behavior_refs)),
            evidence_refs=behavior_refs,
            reason_code=reason,
        )

    raw = view_context.get("_operational_evidence")
    agent = view_context.get("_agent_evidence")
    if isinstance(agent, Mapping):
        handoff_from = agent.get("handoff_from")
        agent_answer = agent.get("answer")
        if (
            not isinstance(raw, Mapping)
            and isinstance(handoff_from, str)
            and not (isinstance(agent_answer, str) and agent_answer.strip())
        ):
            korean = _is_korean(locale)
            answer = (
                f"요청한 {handoff_from} 응답에서 근거를 확인하지 못해 Bragi가 현재 화면만으로 "
                "답변하지 않았습니다. 에이전트 근거가 준비된 뒤 다시 시도하거나 특정 "
                "인시던트 또는 리소스를 지정해 주세요."
                if korean
                else f"{handoff_from} could not provide grounded evidence for this request, so "
                "Bragi did not answer from the current screen. Retry after agent evidence is "
                "available or ask about a specific incident or resource."
            )
            return AnswerVerification(
                status="unverified",
                answer=answer,
                authority="pantheon_runtime",
                checks_completed=0,
                checks_total=1,
                reason_code="agent_evidence_unavailable",
            )
        capability = _verify_agent_self_capability(
            provisional,
            view_context,
            agent,
            locale=locale,
        )
        if capability is not None:
            return capability

    vision_refs = vision_evidence_refs(view_context.get("_attachments"))
    if vision_refs:
        return AnswerVerification(
            status="unverified",
            answer=provisional,
            authority="vision_narrator",
            checks_completed=0,
            checks_total=len(vision_refs),
            evidence_refs=vision_refs,
            reason_code="vision_interpretation_unverified",
        )

    if not isinstance(raw, Mapping):
        screen = verify_screen_claims(provisional, view_context)
        if screen.overflow or not screen.manifest.complete or not screen.supported:
            concept_correction = _correct_concept_scope_additions(
                provisional,
                view_context,
                screen.claims,
            )
            if concept_correction is not None:
                corrected, corrected_screen = concept_correction
                return AnswerVerification(
                    status="corrected",
                    answer=corrected,
                    authority=corrected_screen.manifest.authority,
                    checks_completed=len(corrected_screen.claims),
                    checks_total=len(corrected_screen.claims),
                    evidence_refs=tuple(
                        dict.fromkeys(
                            ref for claim in corrected_screen.claims for ref in claim.evidence_refs
                        )
                    ),
                    reason_code="concept_scope_claims_removed",
                    claims=corrected_screen.claims,
                    evidence_manifest=corrected_screen.manifest,
                )
            screen_correction = _correct_screen_unsupported_sentences(
                provisional,
                view_context,
                screen,
            )
            if screen_correction is not None:
                corrected, corrected_screen = screen_correction
                return AnswerVerification(
                    status="corrected",
                    answer=corrected,
                    authority=corrected_screen.manifest.authority,
                    checks_completed=len(corrected_screen.claims),
                    checks_total=len(corrected_screen.claims),
                    evidence_refs=tuple(
                        dict.fromkeys(
                            ref for claim in corrected_screen.claims for ref in claim.evidence_refs
                        )
                    ),
                    reason_code="screen_unsupported_sentences_removed",
                    claims=corrected_screen.claims,
                    evidence_manifest=corrected_screen.manifest,
                )
            korean = _is_korean(locale)
            answer = (
                "현재 화면 근거로 답변의 "
                "모든 사실 claim을 확인할 수 "
                "없어 답변을 확정하지 "
                "않았습니다. 화면의 범위를 "
                "줄이거나 구체적인 항목을 "
                "선택한 뒤 다시 질문해 주세요."
                if korean
                else "Not every factual claim could be confirmed from the current screen, "
                "so the answer was not finalized. Narrow the screen or select a specific "
                "item and ask again."
            )
            reason = (
                "screen_claim_overflow"
                if screen.overflow
                else (
                    "screen_snapshot_incomplete"
                    if not screen.manifest.complete
                    else "screen_claim_mismatch"
                )
            )

            return AnswerVerification(
                status="unverified",
                answer=answer,
                authority=screen.manifest.authority,
                checks_completed=sum(1 for claim in screen.claims if claim.status == "supported"),
                checks_total=len(screen.claims),
                evidence_refs=tuple(
                    dict.fromkeys(ref for claim in screen.claims for ref in claim.evidence_refs)
                ),
                reason_code=reason,
                claims=screen.claims,
                evidence_manifest=screen.manifest,
                failed_claim_ids=screen.failed_claim_ids,
            )
        return AnswerVerification(
            status="consistent",
            answer=provisional,
            authority=screen.manifest.authority,
            checks_completed=len(screen.claims),
            checks_total=len(screen.claims),
            evidence_refs=tuple(
                dict.fromkeys(ref for claim in screen.claims for ref in claim.evidence_refs)
            ),
            reason_code=(
                "screen_claims_supported" if screen.claims else "screen_no_checkable_claims"
            ),
            claims=screen.claims,
            evidence_manifest=screen.manifest,
        )

    operational_verification = verify_operational_evidence(
        provisional,
        raw,
        locale=locale,
        changed=_changed,
    )
    return _from_payload(operational_verification)


__all__ = [
    "AnswerVerification",
    "VerificationStatus",
    "verify_answer",
]
