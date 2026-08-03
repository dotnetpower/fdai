"""Typed context hold for governed action lifecycle questions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final

from fdai.delivery.operator_api.read_model import (
    MAX_LIMIT,
    AuditItem,
    AuditQueryFilters,
    ConsoleReadModel,
    HilQueueItem,
)
from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver

_ACTION_CONTEXT: Final = re.compile(
    r"\b(?:propos(?:e|al)|mitigation|impact\s+limit|stop\s+condition|dry\s+run|rollback|"
    r"human\s+approval|who\s+may\s+approve|execute\s+the\s+approved|mitigation\s+outcome|"
    r"approval\s+requirement|approver\s+role|who\s+can\s+approve|separate\s+from\s+execution|"
    r"recovery\s+criteria|retrying\s+this\s+action|approved\s+action.{0,24}retried|"
    r"duplicate\s+change|duplication|action\s+receipt)\b|"
    r"(?:완화\s*(?:방안|제안)|영향\s*범위|중지\s*조건|롤백|사람\s*승인|승인자|"
    r"승인\s*(?:필요성|역할)|실행\s*주체|승인된\s*완화|작업\s*후|해결됐|"
    r"중복\s*변경|실행\s*요청)",
    re.IGNORECASE,
)
_EXPLICIT_ACTION_DRAFT: Final = re.compile(
    r"\b(?:draft|prepare|create)\b.{0,32}\b(?:action|change|restart|scale|rollback)\b|"
    r"\b(?:action|change|restart|scale|rollback)\b.{0,32}\bdraft\b|"
    r"(?:작업|변경|재시작|확장|롤백).{0,24}(?:초안|draft)|"
    r"(?:초안|draft).{0,24}(?:작업|변경|재시작|확장|롤백)",
    re.IGNORECASE,
)
_SAFETY: Final = re.compile(
    r"\b(?:impact\s+limit|stop\s+condition|dry\s+run|rollback|blast\s+radius)\b|"
    r"(?:영향\s*범위|중지\s*조건|dry\s*run|롤백)",
    re.IGNORECASE,
)
_APPROVAL: Final = re.compile(
    r"\b(?:human\s+approval|who\s+may\s+approve|approver)\b|사람\s*승인|승인자",
    re.IGNORECASE,
)
_EXECUTION: Final = re.compile(
    r"\b(?:execute\s+the\s+approved|stream.{0,24}progress)\b|승인된\s*완화|실행\s*진행",
    re.IGNORECASE,
)
_VERIFICATION: Final = re.compile(
    r"\b(?:mitigation\s+outcome|recovery\s+criteria|action\s+receipt|verify)\b|"
    r"(?:작업\s*후|해결됐|복구\s*기준|action\s*receipt)",
    re.IGNORECASE,
)
_IDEMPOTENCY: Final = re.compile(
    r"\b(?:retry|retrying|duplicate|duplication|idempotenc)\w*\b|"
    r"(?:재시도|중복\s*변경|중복)",
    re.IGNORECASE,
)


class ActionContextIntent(StrEnum):
    PROPOSAL = "proposal"
    SAFETY = "safety"
    APPROVAL = "approval"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    IDEMPOTENCY = "idempotency"


def needs_action_context(prompt: str) -> bool:
    """Return whether a turn asks about one governed action lifecycle."""

    return bool(_ACTION_CONTEXT.search(prompt))


def is_explicit_action_draft_request(prompt: str) -> bool:
    """Return whether a concrete action draft is requested without lifecycle claims."""

    return bool(_EXPLICIT_ACTION_DRAFT.search(prompt)) and not needs_action_context(prompt)


def classify_action_context_intent(prompt: str) -> ActionContextIntent:
    if _IDEMPOTENCY.search(prompt):
        return ActionContextIntent.IDEMPOTENCY
    if _VERIFICATION.search(prompt):
        return ActionContextIntent.VERIFICATION
    if _EXECUTION.search(prompt):
        return ActionContextIntent.EXECUTION
    if _APPROVAL.search(prompt):
        return ActionContextIntent.APPROVAL
    if _SAFETY.search(prompt):
        return ActionContextIntent.SAFETY
    return ActionContextIntent.PROPOSAL


@dataclass(frozen=True, slots=True)
class ActionContextChatTools:
    """Hold action lifecycle questions until exact governed context exists."""

    read_model: ConsoleReadModel | None = None
    fallback: ChatToolResolver | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_action_context(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        return {
            "tool": "query_action_context",
            "authority": "server_action_context",
            "status": "abstain",
            "result": {"status": "unavailable", "reason": "exact_action_context_required"},
        }

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not needs_action_context(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        if self.read_model is None or context is None or context.get("kind") != "action":
            return await self.resolve(prompt, principal_id=principal_id)
        selectors = _selectors(context)
        if not selectors:
            return await self.resolve(prompt, principal_id=principal_id)
        try:
            hil_page = await self.read_model.list_hil_queue(
                limit=MAX_LIMIT,
                search=(
                    selectors.get("approval_id")
                    or selectors.get("action_id")
                    or selectors.get("idempotency_key")
                ),
            )
            correlated_page = await self.read_model.list_audit(
                limit=MAX_LIMIT,
                correlation_id=selectors.get("correlation_id"),
            )
        except Exception as exc:  # noqa: BLE001 - read boundary fails closed
            result: Mapping[str, Any] = {
                "status": "unavailable",
                "reason": type(exc).__name__,
            }
        else:
            intent = classify_action_context_intent(prompt)
            hil = [item for item in hil_page.items if _hil_matches(item, selectors)]
            canonical_selectors = dict(selectors)
            if len(hil) == 1:
                canonical_selectors.setdefault("action_id", hil[0].action_id)
                canonical_selectors.setdefault("approval_id", hil[0].approval_id)
                canonical_selectors.setdefault("idempotency_key", hil[0].idempotency_key)
            for item in correlated_page.items:
                if not _audit_can_establish_identity(item, selectors):
                    continue
                action_id = _entry_value(item.entry, "action_id")
                idempotency_key = _entry_value(item.entry, "idempotency_key")
                if action_id:
                    canonical_selectors.setdefault("action_id", action_id)
                if idempotency_key:
                    canonical_selectors.setdefault("idempotency_key", idempotency_key)
            exact_action_id = canonical_selectors.get("action_id")
            exact_idempotency = canonical_selectors.get("idempotency_key")
            try:
                exact_page = await self.read_model.list_audit(
                    limit=MAX_LIMIT,
                    filters=AuditQueryFilters(
                        action_id=exact_action_id,
                        idempotency_key=exact_idempotency,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - read boundary fails closed
                result = {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                }
                exact_page = None
            if exact_page is None:
                audit = []
            else:
                audit_by_seq = {
                    item.seq: item
                    for item in (*correlated_page.items, *exact_page.items)
                    if _audit_matches(item, canonical_selectors)
                }
                audit = list(audit_by_seq.values())
            if exact_page is None:
                pass
            elif (
                len(hil) > 1
                or not audit
                or not _selectors_confirmed(canonical_selectors, hil, audit)
                or not _intent_context_complete(intent, canonical_selectors)
            ):
                result = {
                    "status": "unavailable",
                    "reason": "exact_action_context_not_found",
                }
            else:
                result = _project_action_context(
                    canonical_selectors,
                    audit,
                    intent=intent,
                    truncated=(
                        correlated_page.next_cursor is not None
                        or exact_page.next_cursor is not None
                        or hil_page.total > len(hil_page.items)
                    ),
                )
        return {
            "tool": "query_action_context",
            "authority": "server_action_context",
            "result": dict(result),
        }


def render_action_context_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str | None:
    if evidence.get("tool") != "query_action_context":
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return (
            "정확한 ActionType, target resource, proposal 또는 action receipt가 필요합니다. "
            "해당 context가 없으므로 제안, 승인, 실행, 결과 또는 idempotency를 확인하지 않았습니다."
            if korean
            else (
                "Exact ActionType, target resource, proposal, or action receipt context "
                "is required. "
                "No proposal, approval, execution, outcome, or idempotency claim was verified."
            )
        )
    intent = str(result.get("intent") or "proposal")
    action_type = _text(result.get("action_type"), "unknown")
    target = _text(result.get("target_resource_ref"), "unknown")
    if intent == ActionContextIntent.SAFETY:
        return _safety_answer(result, korean=korean)
    if intent == ActionContextIntent.APPROVAL:
        return _approval_answer(result, korean=korean)
    if intent == ActionContextIntent.EXECUTION:
        return _execution_answer(result, korean=korean)
    if intent == ActionContextIntent.VERIFICATION:
        return _verification_answer(result, korean=korean)
    if intent == ActionContextIntent.IDEMPOTENCY:
        return _idempotency_answer(result, korean=korean)
    return (
        f"기록된 proposal은 {action_type}이며 target은 {target}입니다. "
        "이 답변은 변경을 실행하지 않습니다."
        if korean
        else (
            f"The recorded proposal is {action_type} for target {target}. "
            "This answer does not execute a change."
        )
    )


def action_context_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    refs = result.get("evidence_refs") if isinstance(result, Mapping) else None
    if not isinstance(refs, list):
        return ()
    return tuple(ref for ref in refs if isinstance(ref, str) and 0 < len(ref) <= 1_024)


def _selectors(context: Mapping[str, Any]) -> dict[str, str]:
    selectors = {
        key: value.strip()
        for key in ("action_id", "approval_id", "idempotency_key", "correlation_id")
        if isinstance((value := context.get(key)), str) and value.strip()
    }
    primary = ("action_id", "approval_id", "idempotency_key")
    return selectors if any(key in selectors for key in primary) else {}


def _hil_matches(item: HilQueueItem, selectors: Mapping[str, str]) -> bool:
    return all(
        key == "correlation_id"
        and item.correlation_id == value
        or key == "action_id"
        and item.action_id == value
        or key == "approval_id"
        and item.approval_id == value
        or key == "idempotency_key"
        and item.idempotency_key == value
        for key, value in selectors.items()
    )


def _audit_matches(item: AuditItem, selectors: Mapping[str, str]) -> bool:
    primary = {
        key: value
        for key, value in selectors.items()
        if key in {"action_id", "approval_id", "idempotency_key"}
    }
    matched = False
    for key, expected in primary.items():
        observed = _entry_value(item.entry, key)
        if observed is None:
            continue
        if observed != expected:
            return False
        matched = True
    if not matched:
        return False
    correlation = selectors.get("correlation_id")
    return correlation is None or item.correlation_id in {None, correlation}


def _audit_can_establish_identity(item: AuditItem, selectors: Mapping[str, str]) -> bool:
    correlation = selectors.get("correlation_id")
    if correlation is not None and item.correlation_id != correlation:
        return False
    for key in ("action_id", "approval_id", "idempotency_key"):
        expected = selectors.get(key)
        if expected is not None and _entry_value(item.entry, key) != expected:
            return False
    return bool(
        _entry_value(item.entry, "action_id") and _entry_value(item.entry, "idempotency_key")
    )


def _selectors_confirmed(
    selectors: Mapping[str, str],
    hil: list[HilQueueItem],
    audit: list[AuditItem],
) -> bool:
    for key, expected in selectors.items():
        if key == "correlation_id":
            observed = any(item.correlation_id == expected for item in hil) or any(
                item.correlation_id == expected for item in audit
            )
        else:
            observed = any(
                key == "action_id"
                and item.action_id == expected
                or key == "approval_id"
                and item.approval_id == expected
                or key == "idempotency_key"
                and item.idempotency_key == expected
                for item in hil
            ) or any(_entry_value(item.entry, key) == expected for item in audit)
        if not observed:
            return False
    return True


def _intent_context_complete(
    intent: ActionContextIntent,
    selectors: Mapping[str, str],
) -> bool:
    if intent is ActionContextIntent.APPROVAL:
        return "approval_id" in selectors
    if intent in {
        ActionContextIntent.EXECUTION,
        ActionContextIntent.VERIFICATION,
        ActionContextIntent.IDEMPOTENCY,
    }:
        return "action_id" in selectors and "idempotency_key" in selectors
    return "action_id" in selectors


def _entry_value(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if isinstance(value, str):
        return value
    for nested_key in ("action", "proposal", "receipt"):
        nested = entry.get(nested_key)
        value = nested.get(key) if isinstance(nested, Mapping) else None
        if isinstance(value, str):
            return value
    return None


def _project_action_context(
    selectors: Mapping[str, str],
    audit: list[AuditItem],
    *,
    intent: ActionContextIntent,
    truncated: bool,
) -> dict[str, Any]:
    ordered = sorted(audit, key=lambda item: item.seq)
    latest = tuple(reversed(ordered))
    action_type = _latest_entry(latest, "action_type")
    target = _latest_entry(latest, "target_resource_ref", "resource_id")
    refs = [f"audit:{item.correlation_id or 'none'}:{item.seq}" for item in ordered[:50]]
    approval_id = selectors.get("approval_id")
    if approval_id:
        refs.append(f"approval:{approval_id}")
    idempotency_key = selectors.get("idempotency_key")
    if idempotency_key:
        refs.append(f"idempotency:sha256:{sha256(idempotency_key.encode()).hexdigest()}")
    receipt_rows = [item for item in ordered if _receipt_matches_identity(item, selectors)]
    execution_rows = [item for item in receipt_rows if _is_execution(item)]
    verification_rows = [item for item in receipt_rows if _is_verification(item)]
    duplicate_rows = [item for item in receipt_rows if _is_duplicate(item)]
    stop_condition = _latest_entry(latest, "stop_condition")
    rollback_kind = _latest_entry(latest, "rollback_kind")
    rollback_reference = _latest_entry(latest, "rollback_reference", "rollback_ref")
    blast_radius_summary = _latest_entry(latest, "blast_radius_summary")
    audit_approval = _approval_state(latest)
    resolved_approval = audit_approval if audit_approval != "unknown" else None
    approval_status = resolved_approval or audit_approval or "unknown"
    return {
        "status": "matched",
        "intent": intent.value,
        "action_id": selectors.get("action_id"),
        "approval_id": approval_id,
        "action_type": action_type,
        "target_resource_ref": target,
        "mode": _latest_mode(latest),
        "stop_condition": stop_condition,
        "rollback_kind": rollback_kind,
        "rollback_reference": rollback_reference,
        "blast_radius_summary": blast_radius_summary,
        "approval_status": approval_status,
        "approval_reasons": [],
        "execution_receipt_count": len(execution_rows),
        "verification_receipt_count": len(verification_rows),
        "latest_outcome": _latest_entry(tuple(reversed(verification_rows)), "outcome", "status"),
        "duplicate_receipt_count": len(duplicate_rows),
        "truncated": truncated or len(ordered) > 50,
        "evidence_refs": list(dict.fromkeys(refs)),
    }


def _receipt_matches_identity(item: AuditItem, selectors: Mapping[str, str]) -> bool:
    action_id = selectors.get("action_id")
    idempotency_key = selectors.get("idempotency_key")
    if action_id is None or idempotency_key is None:
        return False
    return (
        _entry_value(item.entry, "action_id") == action_id
        and _entry_value(item.entry, "idempotency_key") == idempotency_key
    )


def _latest_entry(items: tuple[AuditItem, ...], *keys: str) -> str | None:
    for item in items:
        for key in keys:
            value = _entry_value(item.entry, key)
            if value:
                return value[:512]
    return None


def _latest_mode(items: tuple[AuditItem, ...]) -> str | None:
    return items[0].mode if items else None


def _approval_state(items: tuple[AuditItem, ...]) -> str:
    aliases = {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "deny": "denied",
        "denied": "denied",
        "timeout": "expired",
        "timed_out": "expired",
        "expired": "expired",
    }
    for item in items:
        raw = _latest_entry((item,), "approval_status", "approval_decision", "decision")
        if raw is not None and (normalized := aliases.get(raw.casefold())) is not None:
            return normalized
        kind = item.action_kind.casefold()
        for token, normalized in aliases.items():
            if kind == f"hil.{token}" or kind.startswith(f"hil.{token}."):
                return normalized
    return "unknown"


def _is_execution(item: AuditItem) -> bool:
    kind = item.action_kind.casefold()
    phase = _entry_value(item.entry, "audit_phase")
    return (
        kind.startswith(("executor.", "action.execute"))
        or item.actor.casefold().startswith("fdai.core.executor")
        and phase == "terminal"
    )


def _is_verification(item: AuditItem) -> bool:
    kind = item.action_kind.casefold()
    return any(token in kind for token in ("final", "effect", "verified", "outcome"))


def _is_duplicate(item: AuditItem) -> bool:
    kind = item.action_kind.casefold()
    outcome = _entry_value(item.entry, "outcome") or ""
    normalized = outcome.casefold()
    return (
        "duplicate" in kind
        or "idempot" in kind
        or normalized in {"already_applied", "rejected_idempotency_conflict"}
        or "duplicate" in normalized
        or "idempotency_conflict" in normalized
    )


def _text(value: object, fallback: str) -> str:
    return " ".join(value.split())[:512] if isinstance(value, str) and value.strip() else fallback


def _safety_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    stop = _text(result.get("stop_condition"), "not recorded")
    rollback_kind = _text(result.get("rollback_kind"), "not recorded")
    rollback = _text(result.get("rollback_reference"), rollback_kind)
    blast = _text(result.get("blast_radius_summary"), "not recorded")
    return (
        f"기록된 stop condition은 {stop}, rollback은 {rollback}, blast radius는 "
        f"{blast}입니다. Dry-run receipt는 별도 audit evidence가 없으면 확인되지 않습니다."
        if korean
        else (
            f"Recorded stop condition: {stop}; rollback: {rollback}; blast radius: "
            f"{blast}. A dry-run receipt is not confirmed unless separately present in "
            "audit evidence."
        )
    )


def _approval_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    status = _text(result.get("approval_status"), "unknown")
    approval_id = _text(result.get("approval_id"), "not recorded")
    return (
        f"사람 승인 상태는 {status}이고 approval id는 {approval_id}입니다. 승인 가능한 "
        "사람은 현재 App Role과 separation-of-duty 검사를 통과해야 하며 이 read "
        "projection은 개인을 지정하지 않습니다."
        if korean
        else (
            f"Human approval status is {status}; approval id: {approval_id}. An approver "
            "must pass current App Role and separation-of-duty checks; this read projection "
            "does not nominate a person."
        )
    )


def _execution_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    count = int(result.get("execution_receipt_count") or 0)
    return (
        "이 read-only 답변은 작업을 실행하지 않았습니다. 현재 bounded audit에는 "
        f"execution receipt {count}개가 있습니다. 실행은 별도의 승인된 governed path에서만 "
        "가능합니다."
        if korean
        else (
            "This read-only answer did not execute the action. The bounded audit currently "
            f"contains {count} execution receipt(s). Execution is allowed only through the "
            "separately authorized governed path."
        )
    )


def _verification_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    count = int(result.get("verification_receipt_count") or 0)
    outcome = _text(result.get("latest_outcome"), "not recorded")
    return (
        f"Effect verification receipt는 {count}개이고 latest outcome은 {outcome}입니다. "
        "Receipt가 없으면 복구를 확인한 것으로 간주하지 않습니다."
        if korean
        else (
            f"Effect verification receipts: {count}; latest outcome: {outcome}. Recovery is "
            "not considered confirmed when no receipt exists."
        )
    )


def _idempotency_answer(result: Mapping[str, Any], *, korean: bool) -> str:
    executions = int(result.get("execution_receipt_count") or 0)
    duplicates = int(result.get("duplicate_receipt_count") or 0)
    truncated = result.get("truncated") is True
    korean_limit = (
        "조회가 truncated되어 중복 없음은 증명할 수 없습니다."
        if truncated
        else "현재 bounded ledger에서만 중복 effect가 관찰되지 않았는지 판단할 수 있습니다."
    )
    english_limit = (
        "The query was truncated, so absence of duplication is not proven."
        if truncated
        else "Only the current bounded ledger can show whether duplicate effects were observed."
    )
    return (
        f"동일 idempotency context의 execution receipt는 {executions}개, duplicate "
        f"receipt는 {duplicates}개입니다. {korean_limit}"
        if korean
        else (
            f"This idempotency context has {executions} execution receipt(s) and "
            f"{duplicates} duplicate receipt(s). {english_limit}"
        )
    )


__all__ = [
    "ActionContextChatTools",
    "ActionContextIntent",
    "action_context_evidence_refs",
    "classify_action_context_intent",
    "is_explicit_action_draft_request",
    "needs_action_context",
    "render_action_context_answer",
]
