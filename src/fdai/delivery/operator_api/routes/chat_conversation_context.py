"""Typed hold for context-dependent conversation continuations."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from fdai.delivery.operator_api.routes.chat_freshness_context import (
    parse_evidence_freshness_context,
)
from fdai.delivery.operator_api.routes.chat_history import completed_replay_payload
from fdai.delivery.operator_api.routes.chat_resource_result_context import (
    ambiguous_resource_candidates,
    ordinal_inventory_arguments,
    parse_resource_result_context,
)
from fdai.delivery.operator_api.routes.chat_source_failure_context import (
    parse_source_failure_context,
    source_failure_evidence_refs,
)
from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRole,
)

_LOG = logging.getLogger(__name__)
_MAX_CONTEXT_ANSWER_CHARS = 16_384
_MAX_EVIDENCE_REFS = 64
_MAX_REF_CHARS = 1_024

_CONTEXT_REQUIRED: Final = re.compile(
    r"\b(?:cancel\s+the\s+active\s+investigation|stop\s+the\s+current\s+conversational\s+"
    r"investigation|interrupt\s+the\s+active\s+investigation|applicable\s+runbook|"
    r"reviewed\s+runbook|trusted\s+runbook|governed\s+runbook|knowledge\s+sources|"
    r"enabled\s+knowledge\s+sources?|reviewed\s+knowledge\s+sources?|"
    r"durable\s+memory|explicitly\s+confirm\s+memory|reusable\s+lesson|"
    r"(?:reviewed|materialized)\s+lesson|second\s+resource|"
    r"item\s+two.{0,32}prior\s+resource\s+list|previous\s+result|multiple\s+"
    r"resources\s+match|same\s+match\s+score|equal\s+resource\s+candidates|"
    r"same\s+verified\s+answer|prior\s+verified\s+answer|same\s+evidence|"
    r"one\s+source\s+is\s+"
    r"unavailable|supported\s+facts\s+and\s+explicit\s+limits|prior\s+evidence|"
    r"failed\s+source|required\s+source\s+fails|missing\s+source|"
    r"cancel\s+that\s+investigation)\b|"
    r"(?:진행\s*중인\s*조사|active\s+investigation(?:을|를)?|현재\s*대화\s*조사|"
    r"관련된\s*런북|검토\s*완료\s*런북|trusted\s+runbook(?:이|을|를)?|지식\s*원본|"
    r"enabled\s+knowledge\s+source.{0,32}(?:승인\s*상태|last\s*refresh)|"
    r"해결\s*방법을\s*기억|해결책을\s*기억|memory(?:로|에)?\s*저장|"
    r"검토.{0,16}(?:lesson|레슨)|materialized(?:된)?\s*학습|"
    r"학습.{0,24}(?:내용|reuse|재사용)|두\s*번째로\s*말한\s*리소스|"
    r"(?:이전\s*목록의|방금\s*답변에서)\s*두\s*번째\s*(?:리소스|항목)|"
    r"이름이\s*같은\s*리소스|동일\s*이름\s*후보|리소스\s*이름이\s*모호|"
    r"같은\s*근거|이전\s+verified\s+answer|같은\s+citation|"
    r"데이터\s*원본이\s*실패|실패한\s+source|일부\s*원본이\s+unavailable)",
    re.IGNORECASE,
)

_REFORMAT: Final = re.compile(
    r"\b(?:same\s+(?:verified\s+)?answer|same\s+evidence|prior\s+(?:verified\s+)?"
    r"answer|prior\s+evidence).{0,48}(?:table|format)\b|"
    r"(?:같은\s*근거|이전\s*근거|이전\s+verified\s+answer|같은\s+citation)"
    r".{0,48}(?:표|형식)",
    re.IGNORECASE,
)
_PARTIAL_SOURCE: Final = re.compile(
    r"\b(?:one\s+source\s+is\s+unavailable|supported\s+facts\s+and\s+explicit\s+limits|"
    r"failed\s+source|separate\s+known\s+facts|required\s+source\s+fails|"
    r"verified\s+facts.{0,48}evidence\s+gaps|missing\s+source.{0,48}"
    r"(?:facts|limits))\b|"
    r"(?:데이터\s*원본이\s*실패|확인된\s*사실.{0,20}한계|실패한\s*원본|"
    r"실패한\s+source|일부\s*원본이\s+unavailable)",
    re.IGNORECASE,
)


class ConversationContextIntent(StrEnum):
    CANCEL_INVESTIGATION = "cancel_investigation"
    RUNBOOK = "runbook"
    KNOWLEDGE_SOURCES = "knowledge_sources"
    MEMORY = "memory"
    LEARNING = "learning"
    ORDINAL_RESOURCE = "ordinal_resource"
    AMBIGUITY = "ambiguity"
    REFORMAT = "reformat"
    PARTIAL_SOURCE = "partial_source"


_KNOWLEDGE_INTENTS: Final = frozenset(
    {
        ConversationContextIntent.RUNBOOK,
        ConversationContextIntent.KNOWLEDGE_SOURCES,
        ConversationContextIntent.MEMORY,
        ConversationContextIntent.LEARNING,
    }
)
_REQUIRED_CONTEXTS: Final[dict[ConversationContextIntent, tuple[str, ...]]] = {
    ConversationContextIntent.CANCEL_INVESTIGATION: ("active_investigation",),
    ConversationContextIntent.RUNBOOK: ("selected_incident_or_resource", "runbook_source"),
    ConversationContextIntent.KNOWLEDGE_SOURCES: ("knowledge_source_receipt",),
    ConversationContextIntent.MEMORY: ("prior_verified_answer", "memory_consent"),
    ConversationContextIntent.LEARNING: ("selected_incident", "reviewed_lesson"),
    ConversationContextIntent.ORDINAL_RESOURCE: ("prior_result_set",),
    ConversationContextIntent.AMBIGUITY: ("ambiguous_candidate_set",),
    ConversationContextIntent.REFORMAT: ("prior_verified_answer",),
    ConversationContextIntent.PARTIAL_SOURCE: ("source_failure_receipt",),
}


@dataclass(frozen=True, slots=True)
class VerifiedPriorContext:
    """Bounded context reconstructed from one durable assistant replay."""

    principal_id: str
    conversation_id: str
    turn_id: str
    status: str
    authority: str
    answer: str
    evidence_refs: tuple[str, ...]
    reason_code: str | None = None
    resource_context: Mapping[str, str] | None = None
    resource_result_context: Mapping[str, Any] | None = None
    source_failure_context: Mapping[str, Any] | None = None
    evidence_freshness_context: Mapping[str, object] | None = None
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "authority": self.authority,
            "answer": self.answer,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "resource_context": (
                dict(self.resource_context) if self.resource_context is not None else None
            ),
            "resource_result_context": (
                dict(self.resource_result_context)
                if self.resource_result_context is not None
                else None
            ),
            "source_failure_context": (
                dict(self.source_failure_context)
                if self.source_failure_context is not None
                else None
            ),
            "evidence_freshness_context": (
                dict(self.evidence_freshness_context)
                if self.evidence_freshness_context is not None
                else None
            ),
            "truncated": self.truncated,
        }


def needs_conversation_context(prompt: str) -> bool:
    return bool(_CONTEXT_REQUIRED.search(prompt))


def classify_conversation_context_intent(prompt: str) -> ConversationContextIntent | None:
    if not needs_conversation_context(prompt):
        return None
    if _REFORMAT.search(prompt):
        return ConversationContextIntent.REFORMAT
    if _PARTIAL_SOURCE.search(prompt):
        return ConversationContextIntent.PARTIAL_SOURCE
    normalized = prompt.casefold()
    if "cancel" in normalized or "취소" in prompt or "중단" in prompt:
        return ConversationContextIntent.CANCEL_INVESTIGATION
    if "runbook" in normalized or "런북" in prompt:
        return ConversationContextIntent.RUNBOOK
    if "knowledge source" in normalized or "지식 원본" in prompt:
        return ConversationContextIntent.KNOWLEDGE_SOURCES
    if "memory" in normalized or "기억" in prompt:
        return ConversationContextIntent.MEMORY
    if "lesson" in normalized or "학습" in prompt:
        return ConversationContextIntent.LEARNING
    if "second resource" in normalized or "item two" in normalized or "두 번째" in prompt:
        return ConversationContextIntent.ORDINAL_RESOURCE
    return ConversationContextIntent.AMBIGUITY


async def load_verified_prior_context(
    *,
    store: ConversationHistoryStore | None,
    principal_id: str,
    conversation_id: str,
) -> VerifiedPriorContext | None:
    """Load the newest usable assistant replay from the server-owned store."""

    if store is None:
        return None
    try:
        turns = await store.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=20,
        )
    except Exception as exc:  # noqa: BLE001 - context failure degrades to a typed hold
        _LOG.warning("verified prior context read failed: %s", type(exc).__name__)
        return None
    for turn in reversed(tuple(turns)):
        if turn.role is not ConversationTurnRole.ASSISTANT:
            continue
        payload = completed_replay_payload(turn)
        verification = payload.get("verification")
        if not isinstance(verification, Mapping):
            continue
        status = verification.get("status")
        authority = verification.get("authority")
        if status not in {"verified", "corrected", "unverified"}:
            continue
        if not isinstance(authority, str) or not 0 < len(authority) <= 128:
            continue
        reason_code = verification.get("reason_code")
        if reason_code is not None and (
            not isinstance(reason_code, str) or not 0 < len(reason_code) <= 256
        ):
            continue
        if authority == "server_conversation_context" and reason_code == "prior_context_required":
            continue
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *_bounded_evidence_refs(verification.get("evidence_refs")),
                    f"conversation-turn:{turn.turn_id}"[:_MAX_REF_CHARS],
                )
            )
        )
        resource_context = _bounded_resource_context(payload.get("resource_context"))
        resource_result_context = parse_resource_result_context(
            payload.get("resource_result_context")
        )
        source_failure_context = parse_source_failure_context(payload.get("source_failure_context"))
        try:
            freshness = parse_evidence_freshness_context(payload.get("evidence_freshness_context"))
        except ValueError:
            freshness = None
        answer = turn.content[:_MAX_CONTEXT_ANSWER_CHARS]
        return VerifiedPriorContext(
            principal_id=principal_id,
            conversation_id=conversation_id,
            turn_id=turn.turn_id,
            status=status,
            authority=authority,
            answer=answer,
            evidence_refs=evidence_refs,
            reason_code=reason_code,
            resource_context=resource_context,
            resource_result_context=resource_result_context,
            source_failure_context=source_failure_context,
            evidence_freshness_context=(freshness.to_dict() if freshness is not None else None),
            truncated=len(turn.content) > len(answer),
        )
    return None


@dataclass(frozen=True, slots=True)
class ConversationContextChatTools:
    fallback: ChatToolResolver | None = None
    contextual_fallback: Any = None
    contextual_predicate: Callable[[str], bool] | None = None
    contextual_routes: tuple[tuple[Callable[[str], bool], Any], ...] = ()
    knowledge_context: Any = None
    inventory_context: Any = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_conversation_context(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        return {
            "tool": "query_conversation_context",
            "authority": "server_conversation_context",
            "status": "abstain",
            "result": _required_context_result(prompt),
        }

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        intent = classify_conversation_context_intent(prompt)
        if intent is None:
            for predicate, resolver in self.contextual_routes:
                if not predicate(prompt):
                    continue
                contextual = getattr(resolver, "resolve_with_context", None)
                if callable(contextual):
                    resolved = await contextual(
                        prompt,
                        principal_id=principal_id,
                        context=context,
                    )
                    return dict(resolved) if isinstance(resolved, Mapping) else None
            if (
                self.contextual_fallback is not None
                and self.contextual_predicate is not None
                and self.contextual_predicate(prompt)
            ):
                contextual = getattr(self.contextual_fallback, "resolve_with_context", None)
                if callable(contextual):
                    resolved = await contextual(
                        prompt,
                        principal_id=principal_id,
                        context=context,
                    )
                    return dict(resolved) if isinstance(resolved, Mapping) else None
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        if context is None:
            return {
                "tool": "query_conversation_context",
                "authority": "server_conversation_context",
                "status": "abstain",
                "result": _required_context_result(prompt),
            }
        status = context.get("status")
        answer = context.get("answer")
        if not isinstance(status, str) or not isinstance(answer, str) or not answer:
            return {
                "tool": "query_conversation_context",
                "authority": "server_conversation_context",
                "status": "abstain",
                "result": _required_context_result(prompt),
            }
        if (
            intent in _KNOWLEDGE_INTENTS
            and status in {"verified", "corrected"}
            and self.knowledge_context is not None
        ):
            resolved = await self.knowledge_context.resolve_with_context(
                prompt,
                principal_id=principal_id,
                context=context,
                intent=intent,
            )
            if isinstance(resolved, Mapping):
                return dict(resolved)
        if intent is ConversationContextIntent.ORDINAL_RESOURCE:
            return await self._resolve_ordinal_resource(
                principal_id=principal_id,
                context=context,
            )
        if intent is ConversationContextIntent.AMBIGUITY:
            return self._resolve_ambiguity(context=context)
        if intent is ConversationContextIntent.REFORMAT and status != "unverified":
            result_status = "matched"
        elif intent is ConversationContextIntent.PARTIAL_SOURCE and (
            status == "unverified" or isinstance(context.get("source_failure_context"), Mapping)
        ):
            result_status = "matched"
        else:
            required = _required_context_result(prompt)
            required["available_prior_context"] = _context_kind(context)
            return {
                "tool": "query_conversation_context",
                "authority": "server_conversation_context",
                "status": "abstain",
                "result": required,
            }
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *_bounded_evidence_refs(context.get("evidence_refs")),
                    *source_failure_evidence_refs(context.get("source_failure_context")),
                )
            )
        )
        return {
            "tool": "query_conversation_context",
            "authority": "server_conversation_context",
            "status": "ok",
            "result": {
                "status": result_status,
                "intent": intent.value,
                "prior_status": status,
                "prior_authority": context.get("authority"),
                "prior_answer": answer,
                "evidence_refs": list(evidence_refs),
                "reason_code": context.get("reason_code"),
                "source_failure_context": context.get("source_failure_context"),
                "truncated": context.get("truncated") is True,
            },
        }

    async def _resolve_ordinal_resource(
        self,
        *,
        principal_id: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        arguments, reason = ordinal_inventory_arguments(context.get("resource_result_context"))
        if arguments is None or self.inventory_context is None:
            return _context_unavailable(
                ConversationContextIntent.ORDINAL_RESOURCE,
                reason or "inventory_context_unavailable",
                context,
            )
        try:
            resolved = await self.inventory_context.resolve_planned(
                "query_inventory",
                arguments,
                principal_id=principal_id,
            )
        except ValueError:
            return _context_unavailable(
                ConversationContextIntent.ORDINAL_RESOURCE,
                "ordinal_query_rejected",
                context,
            )
        except Exception:  # noqa: BLE001 - provider failure becomes a typed read hold
            return _context_unavailable(
                ConversationContextIntent.ORDINAL_RESOURCE,
                "ordinal_query_unavailable",
                context,
            )
        if not isinstance(resolved, Mapping):
            return _context_unavailable(
                ConversationContextIntent.ORDINAL_RESOURCE,
                "ordinal_query_unavailable",
                context,
            )
        result = resolved.get("result")
        resources = result.get("resources") if isinstance(result, Mapping) else None
        if (
            isinstance(result, Mapping)
            and result.get("status") == "matched"
            and isinstance(resources, list)
            and len(resources) != 1
        ):
            return _context_unavailable(
                ConversationContextIntent.ORDINAL_RESOURCE,
                "ordinal_requery_not_unique",
                context,
            )
        return dict(resolved)

    def _resolve_ambiguity(self, *, context: Mapping[str, Any]) -> dict[str, Any]:
        candidates, reason = ambiguous_resource_candidates(context.get("resource_result_context"))
        if reason not in {None, "no_equal_name_candidates"}:
            return _context_unavailable(
                ConversationContextIntent.AMBIGUITY,
                reason or "ambiguous_candidate_set_unavailable",
                context,
            )
        result_context = context.get("resource_result_context")
        evidence_ref = (
            result_context.get("evidence_ref") if isinstance(result_context, Mapping) else None
        )
        refs = tuple(
            dict.fromkeys(
                (
                    *_bounded_evidence_refs(context.get("evidence_refs")),
                    *((evidence_ref,) if isinstance(evidence_ref, str) else ()),
                )
            )
        )
        return {
            "tool": "query_conversation_context",
            "authority": "server_conversation_context",
            "status": "ok",
            "result": {
                "status": "matched",
                "intent": ConversationContextIntent.AMBIGUITY.value,
                "reason_code": reason,
                "candidates": [dict(candidate) for candidate in candidates],
                "evidence_refs": list(refs),
            },
        }


def render_conversation_context_answer(
    evidence: Mapping[str, Any], *, locale: str | None
) -> str | None:
    if evidence.get("tool") != "query_conversation_context":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if result.get("status") == "matched":
        intent = result.get("intent")
        if intent == ConversationContextIntent.REFORMAT.value:
            return _render_prior_answer_table(result, korean=korean)
        if intent == ConversationContextIntent.PARTIAL_SOURCE.value:
            return _render_source_failure(result, korean=korean)
        if intent == ConversationContextIntent.AMBIGUITY.value:
            return _render_ambiguity_candidates(result, korean=korean)
    required = result.get("required_context")
    context_label = (
        ", ".join(str(item) for item in required)
        if isinstance(required, list) and required
        else "verified prior context"
    )
    return (
        f"이 요청에는 {context_label} context가 필요합니다. 현재 conversation에서 검증된 "
        "record를 찾지 못했으므로 다른 화면, repository, agent 또는 narrator output으로 "
        "대체하지 않았습니다."
        if korean
        else (
            f"This request requires {context_label} context. No verified matching record was "
            "found in this conversation, so current-screen, repository, agent, or narrator "
            "output was not substituted."
        )
    )


def conversation_context_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return ()
    return _bounded_evidence_refs(result.get("evidence_refs"))


def _required_context_result(prompt: str) -> dict[str, Any]:
    intent = classify_conversation_context_intent(prompt)
    required_context = (
        list(_REQUIRED_CONTEXTS[intent]) if intent is not None else ["verified_prior_context"]
    )
    return {
        "status": "unavailable",
        "reason": "prior_context_required",
        "intent": intent.value if intent is not None else "unknown",
        "required_context": required_context,
    }


def _context_unavailable(
    intent: ConversationContextIntent,
    reason: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "tool": "query_conversation_context",
        "authority": "server_conversation_context",
        "status": "abstain",
        "result": {
            "status": "unavailable",
            "reason": reason,
            "intent": intent.value,
            "required_context": list(_REQUIRED_CONTEXTS[intent]),
            "evidence_refs": list(_bounded_evidence_refs(context.get("evidence_refs"))),
        },
    }


def _render_prior_answer_table(result: Mapping[str, Any], *, korean: bool) -> str:
    answer = _markdown_cell(result.get("prior_answer"))
    refs = _markdown_cell(", ".join(_bounded_evidence_refs(result.get("evidence_refs"))) or "none")
    labels = (
        ("항목", "값", "이전 검증 답변", "근거")
        if korean
        else (
            "Field",
            "Value",
            "Prior verified answer",
            "Evidence",
        )
    )
    return (
        f"| {labels[0]} | {labels[1]} |\n"
        "|---|---|\n"
        f"| {labels[2]} | {answer} |\n"
        f"| {labels[3]} | {refs} |"
    )


def _render_source_failure(result: Mapping[str, Any], *, korean: bool) -> str:
    source_context = parse_source_failure_context(result.get("source_failure_context"))
    if source_context is not None:
        sources = source_context["sources"]
        gaps = source_context["gaps"]
        available = [
            source
            for source in sources
            if isinstance(source, Mapping) and source.get("availability") == "available"
        ]
        lines = [
            (
                "확인된 source manifest의 사실과 한계입니다."
                if korean
                else "These are the confirmed source-manifest facts and limits."
            )
        ]
        for source in available:
            lines.append(
                f"- {'확인됨' if korean else 'Confirmed'}: {source.get('key')} - "
                f"{source.get('source')} ({source.get('availability')})"
            )
        for gap in gaps:
            if not isinstance(gap, Mapping):
                continue
            reason = gap.get("reason") or "source_unavailable"
            observed = gap.get("last_observed_at") or "unknown"
            lines.append(
                f"- {'한계' if korean else 'Limit'}: {gap.get('key')} - {gap.get('source')} "
                f"({gap.get('availability')}); reason {reason}; last observed {observed}"
            )
        lines.append(
            "누락된 source를 다른 authority로 대체하지 않았습니다."
            if korean
            else "The missing source was not replaced with another authority."
        )
        return "\n".join(lines)
    reason = str(result.get("reason_code") or "source_unavailable")
    refs = ", ".join(_bounded_evidence_refs(result.get("evidence_refs"))) or "none"
    return (
        f"이전 답변은 검증되지 않았습니다. 확인된 한계: {reason}. 소비된 근거: {refs}. "
        "누락된 원본을 다른 근거로 대체하지 않았습니다."
        if korean
        else (
            f"The prior answer was unverified. Confirmed limitation: {reason}. Evidence consumed: "
            f"{refs}. The missing source was not replaced with another authority."
        )
    )


def _render_ambiguity_candidates(result: Mapping[str, Any], *, korean: bool) -> str:
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return (
            "이전 complete result set에서 동일 이름 후보를 찾지 못했습니다. 후보를 추측하거나 "
            "다른 화면에서 가져오지 않았습니다."
            if korean
            else (
                "No equal-name candidates were found in the prior complete result set. No "
                "candidate was guessed or borrowed from another screen."
            )
        )
    headers = (
        ("이름", "유형", "리소스 그룹", "위치", "상태")
        if korean
        else ("Name", "Type", "Resource group", "Location", "Status")
    )
    lines = [
        f"| {' | '.join(headers)} |",
        "|---|---|---|---|---|",
    ]
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(candidate.get(key) or "-")
                for key in ("name", "resource_type", "resource_group", "location", "status")
            )
            + " |"
        )
    instruction = (
        "확인할 후보를 이름, 유형, 리소스 그룹으로 선택해 주세요."
        if korean
        else "Choose the candidate by name, type, and resource group."
    )
    return f"{instruction}\n\n" + "\n".join(lines)


def _context_kind(context: Mapping[str, Any]) -> str:
    if context.get("status") == "unverified":
        return "source_failure_receipt"
    if isinstance(context.get("source_failure_context"), Mapping):
        return "source_failure_receipt"
    if isinstance(context.get("resource_result_context"), Mapping):
        return "prior_result_set"
    if isinstance(context.get("resource_context"), Mapping):
        return "selected_resource"
    return "prior_verified_answer"


def _bounded_evidence_refs(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(
        value
        for value in raw[:_MAX_EVIDENCE_REFS]
        if isinstance(value, str) and 0 < len(value) <= _MAX_REF_CHARS
    )


def _bounded_resource_context(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, Mapping):
        return None
    allowed = {
        "name",
        "resource_type",
        "evidence_ref",
        "resource_group",
        "event_at",
        "event_status",
    }
    result = {
        str(key): value
        for key, value in raw.items()
        if key in allowed and isinstance(value, str) and 0 < len(value) <= 1_024
    }
    return result if {"name", "resource_type", "evidence_ref"}.issubset(result) else None


def _markdown_cell(value: object) -> str:
    return str(value or "").replace("\n", "<br>").replace("\r", "").replace("|", "\\|")


__all__ = [
    "ConversationContextChatTools",
    "ConversationContextIntent",
    "VerifiedPriorContext",
    "classify_conversation_context_intent",
    "conversation_context_evidence_refs",
    "load_verified_prior_context",
    "needs_conversation_context",
    "render_conversation_context_answer",
]
