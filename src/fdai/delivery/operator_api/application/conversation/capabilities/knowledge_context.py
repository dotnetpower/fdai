"""Read-only knowledge, memory, and retained-learning chat projections."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from fdai.core.learning import PostTurnProposalKind, PostTurnReviewState
from fdai.core.operator_memory import OperatorMemoryProposalState
from fdai.core.skills import SkillProposalState

_TOKEN: Final = re.compile(r"[a-z0-9]+")
_GENERIC_SELECTOR_TOKENS: Final = frozenset(
    {"azure", "microsoft", "provider", "providers", "resource", "resources"}
)
_MAX_ITEMS = 50
_MAX_BODY_CHARS = 32_768


@dataclass(frozen=True, slots=True)
class KnowledgeContextChatTools:
    """Resolve server-owned context without writing memory or learning state."""

    skill_disclosure: Any = None
    skill_sources: Any = None
    skill_refresh_states: Any = None
    user_memories: Any = None
    post_turn_reviews: Any = None
    memory_proposals: Any = None
    operator_memories: Any = None
    skill_proposals: Any = None
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any],
        intent: object,
    ) -> dict[str, Any]:
        del prompt
        intent_value = getattr(intent, "value", str(intent))
        if context.get("principal_id") != principal_id:
            return _response(intent_value, "unavailable", reason="prior_context_principal_mismatch")
        turn_id = context.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            return _response(intent_value, "unavailable", reason="exact_prior_turn_required")
        if intent_value == "runbook":
            return self._runbook(context=context, turn_id=turn_id)
        if intent_value == "knowledge_sources":
            return await self._knowledge_sources(turn_id=turn_id)
        if intent_value == "memory":
            return await self._memory(principal_id=principal_id, turn_id=turn_id)
        if intent_value == "learning":
            return await self._learning(
                principal_id=principal_id,
                turn_id=turn_id,
            )
        return _response(intent_value, "unavailable", reason="unsupported_knowledge_intent")

    def _runbook(self, *, context: Mapping[str, Any], turn_id: str) -> dict[str, Any]:
        if self.skill_disclosure is None:
            return _response("runbook", "unavailable", reason="trusted_skill_catalog_unavailable")
        resource_context = context.get("resource_context")
        resource_type = (
            resource_context.get("resource_type") if isinstance(resource_context, Mapping) else None
        )
        if not isinstance(resource_type, str) or not resource_type.strip():
            return _response(
                "runbook",
                "empty",
                reason="selected_resource_type_required",
                evidence_refs=(f"conversation-turn:{turn_id}",),
            )
        selector_tokens = _tokens(resource_type) - _GENERIC_SELECTOR_TOKENS
        if not selector_tokens:
            return _response(
                "runbook",
                "empty",
                reason="resource_type_not_discriminating",
                evidence_refs=(f"conversation-turn:{turn_id}",),
            )
        try:
            index = self.skill_disclosure.list(query=resource_type, limit=_MAX_ITEMS)
        except (TypeError, ValueError) as exc:
            return _response("runbook", "unavailable", reason=type(exc).__name__)
        candidates: list[tuple[int, Mapping[str, Any]]] = []
        for raw_entry in index.get("entries", ()):
            if not isinstance(raw_entry, Mapping):
                continue
            descriptor = raw_entry.get("descriptor")
            if not isinstance(descriptor, Mapping):
                continue
            searchable = " ".join(
                (
                    str(descriptor.get("name") or ""),
                    str(descriptor.get("description") or ""),
                    *(
                        str(value)
                        for value in descriptor.get("required_tools", ())
                        if isinstance(value, str)
                    ),
                )
            )
            overlap = len(selector_tokens & _tokens(searchable))
            if overlap:
                candidates.append((overlap, descriptor))
        index_ref = _receipt_ref("trusted-skill-index", index)
        if not candidates:
            return _response(
                "runbook",
                "empty",
                reason="no_applicable_reviewed_runbook",
                evidence_refs=(f"conversation-turn:{turn_id}", index_ref),
            )
        candidates.sort(key=lambda item: (-item[0], str(item[1].get("name") or "")))
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            return _response(
                "runbook",
                "empty",
                reason="applicable_runbook_ambiguous",
                evidence_refs=(f"conversation-turn:{turn_id}", index_ref),
            )
        name = candidates[0][1].get("name")
        if not isinstance(name, str) or not name:
            return _response("runbook", "unavailable", reason="skill_descriptor_invalid")
        try:
            loaded = self.skill_disclosure.load(name)
        except (TypeError, ValueError) as exc:
            return _response("runbook", "unavailable", reason=type(exc).__name__)
        descriptor = loaded.get("descriptor")
        replay = loaded.get("replay")
        body = loaded.get("body")
        if not isinstance(descriptor, Mapping) or not isinstance(replay, Mapping):
            return _response("runbook", "unavailable", reason="trusted_skill_receipt_invalid")
        if not isinstance(body, str) or not body.strip() or len(body) > _MAX_BODY_CHARS:
            return _response("runbook", "unavailable", reason="trusted_skill_body_invalid")
        runbook_ref = _receipt_ref("trusted-runbook", loaded)
        return _response(
            "runbook",
            "matched",
            evidence_refs=(f"conversation-turn:{turn_id}", index_ref, runbook_ref),
            data={
                "resource_type": resource_type,
                "name": name,
                "version": descriptor.get("version"),
                "source": descriptor.get("source"),
                "body": body,
                "body_sha256": replay.get("body_sha256"),
                "required_tools": descriptor.get("required_tools", []),
            },
        )

    async def _knowledge_sources(self, *, turn_id: str) -> dict[str, Any]:
        if self.skill_sources is None or self.skill_refresh_states is None:
            return _response(
                "knowledge_sources",
                "unavailable",
                reason="knowledge_source_registry_unavailable",
            )
        try:
            sources = await self.skill_sources.list(enabled_only=True)
            now = self.clock()
            projected = []
            collection = {
                "source_ids": [source.source_id for source in sources],
                "total_enabled": len(sources),
            }
            refs = [
                f"conversation-turn:{turn_id}",
                _receipt_ref("knowledge-source-collection", collection),
            ]
            for source in sources[:_MAX_ITEMS]:
                refresh = await self.skill_refresh_states.get(source.source_id)
                item = _project_source(source, refresh=refresh, now=now)
                projected.append(item)
                refs.append(_receipt_ref("knowledge-source", item))
        except Exception as exc:  # noqa: BLE001 - typed read degradation
            return _response("knowledge_sources", "unavailable", reason=type(exc).__name__)
        return _response(
            "knowledge_sources",
            "matched" if projected else "empty",
            reason=None if projected else "no_enabled_knowledge_sources",
            evidence_refs=tuple(refs),
            data={
                "sources": projected,
                "observed_at": now.isoformat(),
                "total_enabled": len(sources),
                "returned": len(projected),
                "truncated": len(sources) > len(projected),
            },
        )

    async def _memory(self, *, principal_id: str, turn_id: str) -> dict[str, Any]:
        if self.user_memories is None:
            return _response("memory", "unavailable", reason="user_memory_store_unavailable")
        try:
            now = self.clock()
            active = await self.user_memories.list_active(
                principal_id=principal_id,
                now=now,
                limit=_MAX_ITEMS,
            )
        except Exception as exc:  # noqa: BLE001 - typed read degradation
            return _response("memory", "unavailable", reason=type(exc).__name__)
        if any(item.principal_id != principal_id for item in active):
            return _response("memory", "unavailable", reason="memory_principal_mismatch")
        matches = tuple(
            item
            for item in active
            if item.source_turn_id == turn_id
            and item.superseded_by is None
            and (item.expires_at is None or item.expires_at > now)
        )
        refs = [f"conversation-turn:{turn_id}"]
        projected = []
        for item in matches:
            view = {
                "memory_id": item.memory_id,
                "category": item.category.value,
                "body": item.body,
                "source_turn_id": item.source_turn_id,
                "consented_at": item.consented_at.isoformat(),
                "created_at": item.created_at.isoformat(),
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                "visibility": "principal_only",
            }
            projected.append(view)
            refs.append(f"user-memory:{item.memory_id}")
        return _response(
            "memory",
            "matched" if projected else "empty",
            reason=None if projected else "explicit_memory_consent_required",
            evidence_refs=tuple(refs),
            data={
                "persisted": bool(projected),
                "memories": projected,
                "would_store": {
                    "category": "context",
                    "body_source": "prior_verified_answer",
                    "source_turn_id": turn_id,
                    "consent": "explicit_confirmed_request",
                    "provenance": "durable_assistant_turn",
                    "visibility": "principal_only",
                    "write_performed_by_chat": False,
                },
            },
        )

    async def _learning(self, *, principal_id: str, turn_id: str) -> dict[str, Any]:
        if self.post_turn_reviews is None:
            return _response("learning", "unavailable", reason="post_turn_review_store_unavailable")
        review_id = _review_id(turn_id)
        lookup_ref = _receipt_ref(
            "post-turn-review-lookup",
            {"review_id": review_id, "turn_id": turn_id},
        )
        try:
            review = await self.post_turn_reviews.get(review_id)
        except LookupError:
            return _response(
                "learning",
                "empty",
                reason="no_post_turn_review",
                evidence_refs=(f"conversation-turn:{turn_id}", lookup_ref),
            )
        except Exception as exc:  # noqa: BLE001 - typed read degradation
            return _response("learning", "unavailable", reason=type(exc).__name__)
        if review.principal_scope != _principal_scope(principal_id):
            return _response("learning", "unavailable", reason="review_principal_mismatch")
        review_ref = f"post-turn-review:{review.review_id}"
        if (
            review.state is not PostTurnReviewState.ROUTED
            or review.proposal_kind is None
            or review.proposal_ref is None
        ):
            return _response(
                "learning",
                "empty",
                reason=f"review_{review.state.value}",
                evidence_refs=(f"conversation-turn:{turn_id}", review_ref),
                data={"review_state": review.state.value, "reusable": False},
            )
        if review.proposal_kind is PostTurnProposalKind.OPERATOR_MEMORY:
            return await self._retained_memory_lesson(
                turn_id=turn_id,
                review_ref=review_ref,
                proposal_id=review.proposal_ref,
            )
        if review.proposal_kind is PostTurnProposalKind.SKILL_DRAFT:
            return await self._retained_skill_lesson(
                turn_id=turn_id,
                review_ref=review_ref,
                proposal_id=review.proposal_ref,
            )
        return _response(
            "learning",
            "empty",
            reason="proposal_not_reusable_knowledge",
            evidence_refs=(f"conversation-turn:{turn_id}", review_ref),
        )

    async def _retained_memory_lesson(
        self,
        *,
        turn_id: str,
        review_ref: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        if self.memory_proposals is None:
            return _response("learning", "unavailable", reason="memory_proposal_store_unavailable")
        if self.operator_memories is None:
            return _response("learning", "unavailable", reason="operator_memory_store_unavailable")
        try:
            proposal = await self.memory_proposals.get(proposal_id)
        except Exception as exc:  # noqa: BLE001 - proposal receipt integrity
            return _response("learning", "unavailable", reason=type(exc).__name__)
        refs = (f"conversation-turn:{turn_id}", review_ref, proposal.proposal_id)
        if proposal.state is not OperatorMemoryProposalState.MATERIALIZED:
            return _response(
                "learning",
                "empty",
                reason=f"lesson_{proposal.state.value}",
                evidence_refs=refs,
                data={"reviewed": proposal.reviewed_by is not None, "reusable": False},
            )
        if proposal.materialized_entry_id is None:
            return _response(
                "learning",
                "unavailable",
                reason="materialized_entry_identity_missing",
                evidence_refs=refs,
            )
        try:
            active_entries = await self.operator_memories.list_active_for_scope(
                scope_kind=proposal.scope_kind,
                scope_ref=proposal.scope_ref,
            )
        except Exception as exc:  # noqa: BLE001 - typed read degradation
            return _response("learning", "unavailable", reason=type(exc).__name__)
        active_entry = next(
            (entry for entry in active_entries if entry.id == proposal.materialized_entry_id),
            None,
        )
        if active_entry is None or active_entry.source_ref != proposal.proposal_id:
            return _response(
                "learning",
                "empty",
                reason="materialized_lesson_inactive",
                evidence_refs=refs,
                data={"reviewed": True, "retained": False, "reusable": False},
            )
        return _response(
            "learning",
            "matched",
            evidence_refs=(
                *refs,
                f"operator-memory:{proposal.materialized_entry_id}",
                *proposal.evidence_refs,
            ),
            data={
                "kind": "operator_memory",
                "lesson": proposal.body,
                "reviewed_by": proposal.reviewed_by,
                "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
                "retained": True,
                "reusable": True,
                "reuse_conditions": [
                    f"exact {proposal.scope_kind.value} scope {proposal.scope_ref}",
                    "materialized entry remains active and not superseded",
                ],
            },
        )

    async def _retained_skill_lesson(
        self,
        *,
        turn_id: str,
        review_ref: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        if self.skill_proposals is None or self.skill_disclosure is None:
            return _response("learning", "unavailable", reason="skill_lesson_store_unavailable")
        try:
            proposal = await self.skill_proposals.get(proposal_id)
        except Exception as exc:  # noqa: BLE001 - proposal receipt integrity
            return _response("learning", "unavailable", reason=type(exc).__name__)
        refs = (f"conversation-turn:{turn_id}", review_ref, proposal.proposal_id)
        if proposal.state is not SkillProposalState.MATERIALIZED:
            return _response(
                "learning",
                "empty",
                reason=f"lesson_{proposal.state.value}",
                evidence_refs=refs,
                data={"reviewed": proposal.reviewed_by is not None, "reusable": False},
            )
        try:
            loaded = self.skill_disclosure.load(proposal.skill_name)
        except (TypeError, ValueError) as exc:
            return _response("learning", "unavailable", reason=type(exc).__name__)
        body = loaded.get("body")
        descriptor = loaded.get("descriptor")
        if not isinstance(body, str) or not isinstance(descriptor, Mapping):
            return _response("learning", "unavailable", reason="materialized_skill_invalid")
        skill_ref = _receipt_ref("trusted-skill-lesson", loaded)
        return _response(
            "learning",
            "matched",
            evidence_refs=(*refs, skill_ref),
            data={
                "kind": "runtime_skill",
                "lesson": body,
                "skill_name": proposal.skill_name,
                "reviewed_by": proposal.reviewed_by,
                "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
                "retained": True,
                "reusable": True,
                "reuse_conditions": [
                    "runtime skill remains enabled and trust verification passes",
                    "required tools and allowed agent remain eligible",
                ],
            },
        )


def render_knowledge_context_answer(
    evidence: Mapping[str, Any], *, locale: str | None
) -> str | None:
    if evidence.get("tool") != "query_knowledge_context":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    intent = result.get("intent")
    status = result.get("status")
    raw_data = result.get("data")
    data = cast(Mapping[str, Any], raw_data) if isinstance(raw_data, Mapping) else {}
    reason = str(result.get("reason") or "not_observed")
    if status == "unavailable":
        return (
            f"지식 context를 확인할 수 없습니다. 확인된 한계: {reason}. "
            "다른 원본으로 대체하지 않았습니다."
            if korean
            else f"Knowledge context is unavailable. Confirmed limit: {reason}. "
            "No other source was substituted."
        )
    if intent == "runbook":
        return _render_runbook(data, status=status, reason=reason, korean=korean)
    if intent == "knowledge_sources":
        return _render_sources(data, status=status, reason=reason, korean=korean)
    if intent == "memory":
        return _render_memory(data, status=status, korean=korean)
    if intent == "learning":
        return _render_learning(data, status=status, reason=reason, korean=korean)
    if intent == "configuration_baseline":
        return _render_configuration_baseline(data, status=status, reason=reason, korean=korean)
    return None


def knowledge_context_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    refs = result.get("evidence_refs")
    if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
        return ()
    return tuple(value for value in refs if isinstance(value, str) and value)


def _response(
    intent: str,
    status: str,
    *,
    reason: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool": "query_knowledge_context",
        "authority": "server_knowledge_context",
        "status": "ok" if status in {"matched", "empty"} else "abstain",
        "result": {
            "intent": intent,
            "status": status,
            "reason": reason,
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "data": dict(data or {}),
        },
    }


def _project_source(source: Any, *, refresh: Any, now: datetime) -> dict[str, Any]:
    last_refresh = refresh.last_refresh_at if refresh is not None else None
    next_refresh = refresh.next_refresh_at if refresh is not None else None
    error_count = refresh.error_count if refresh is not None else 0
    retry_at = refresh.retry_at if refresh is not None else None
    policy_deadline = (
        last_refresh + timedelta(seconds=source.refresh_interval_seconds)
        if last_refresh is not None
        else None
    )
    deadlines = tuple(value for value in (policy_deadline, next_refresh) if value is not None)
    effective_deadline = min(deadlines) if deadlines else None
    if refresh is None or last_refresh is None:
        freshness = "unknown"
        fresh: bool | None = None
    elif last_refresh > now:
        freshness = "invalid_future_observation"
        fresh = False
    elif error_count:
        freshness = "error"
        fresh = False
    elif effective_deadline is not None and now > effective_deadline:
        freshness = "stale"
        fresh = False
    else:
        freshness = "current"
        fresh = True
    return {
        "source_id": source.source_id,
        "kind": source.kind.value,
        "location": source.location,
        "owner": source.owner,
        "allowed_path": source.allowed_path,
        "enabled": source.enabled,
        "connected": last_refresh is not None and error_count == 0 and last_refresh <= now,
        "authorized": source.trust_tier.value == "organization_approved",
        "authorization_basis": "organization_approved_registry",
        "trust_tier": source.trust_tier.value,
        "refresh_policy": source.refresh_policy.value,
        "last_refresh_at": last_refresh.isoformat() if last_refresh else None,
        "next_refresh_at": next_refresh.isoformat() if next_refresh else None,
        "last_revision": refresh.last_revision if refresh is not None else None,
        "last_error_kind": refresh.last_error_kind if refresh is not None else None,
        "error_count": error_count,
        "retry_at": retry_at.isoformat() if retry_at is not None else None,
        "freshness": freshness,
        "fresh": fresh,
    }


def _render_runbook(data: Mapping[str, Any], *, status: object, reason: str, korean: bool) -> str:
    if status != "matched":
        return (
            "선택된 context에 적용 가능한 검토 완료 런북을 찾지 못했습니다. "
            f"확인 결과: {reason}. 추천을 생성하지 않았습니다."
            if korean
            else "No reviewed runbook was applicable to the selected context. "
            f"Result: {reason}. No recommendation was generated."
        )
    name = data.get("name")
    version = data.get("version")
    source = data.get("source")
    body_sha256 = data.get("body_sha256")
    body = data.get("body")
    return (
        f"적용 런북: {name} {version}\n출처: {source}\n본문 SHA-256: {body_sha256}\n\n{body}"
        if korean
        else f"Applicable runbook: {name} {version}\n"
        f"Source: {source}\n"
        f"Body SHA-256: {body_sha256}\n\n{body}"
    )


def _render_sources(data: Mapping[str, Any], *, status: object, reason: str, korean: bool) -> str:
    sources = data.get("sources")
    if status != "matched" or not isinstance(sources, Sequence) or not sources:
        return (
            f"활성화된 지식 원본이 없습니다. 확인 결과: {reason}."
            if korean
            else f"No enabled knowledge sources were observed. Result: {reason}."
        )
    headers = (
        ("원본", "위치", "승인", "최신성", "마지막 갱신")
        if korean
        else ("Source", "Location", "Authorized", "Freshness", "Last refresh")
    )
    rows = [f"| {' | '.join(headers)} |", "|---|---|---|---|---|"]
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        rows.append(
            "| "
            + " | ".join(
                (
                    _cell(source.get("source_id")),
                    _cell(source.get("location")),
                    _cell(source.get("authorized")),
                    _cell(source.get("freshness")),
                    _cell(source.get("last_refresh_at") or "not observed"),
                )
            )
            + " |"
        )
    if data.get("truncated") is True:
        rows.append(
            f"\n표시 제한: {data.get('returned')}/{data.get('total_enabled')} 원본."
            if korean
            else f"\nDisplay limit: {data.get('returned')}/{data.get('total_enabled')} sources."
        )
    return "\n".join(rows)


def _render_memory(data: Mapping[str, Any], *, status: object, korean: bool) -> str:
    persisted = status == "matched" and data.get("persisted") is True
    memories = data.get("memories")
    if persisted and isinstance(memories, Sequence):
        lines = ["저장된 principal 전용 memory:" if korean else "Persisted principal-only memory:"]
        for item in memories:
            if isinstance(item, Mapping):
                body = _cell(item.get("body"))
                source_turn = _cell(item.get("source_turn_id"))
                consented_at = _cell(item.get("consented_at"))
                lines.append(f"- {body} (source turn: {source_turn}, consented: {consented_at})")
        return "\n".join(lines)
    return (
        "아직 memory를 저장하지 않았습니다. 명시적 확인이 있으면 이전 검증 답변, "
        "source turn ID, consent 시각, category와 선택적 만료 시각을 현재 principal에게만 "
        "보이도록 저장합니다. 이 조회는 쓰기를 수행하지 않았습니다."
        if korean
        else "No memory was stored. With explicit confirmation, the prior verified answer, "
        "source turn ID, consent time, category, and optional expiry would be visible only to "
        "the current principal. This read performed no write."
    )


def _render_learning(data: Mapping[str, Any], *, status: object, reason: str, korean: bool) -> str:
    if status != "matched":
        return (
            f"검토되고 보존된 재사용 lesson이 없습니다. 확인 결과: {reason}. "
            "후보나 초안은 학습 완료로 계산하지 않았습니다."
            if korean
            else "No reviewed and retained reusable lesson was observed. "
            f"Result: {reason}. A candidate or draft was not counted as learned."
        )
    conditions = data.get("reuse_conditions")
    rendered_conditions = (
        "\n".join(f"- {_cell(value)}" for value in conditions)
        if isinstance(conditions, Sequence) and not isinstance(conditions, (str, bytes))
        else "- none"
    )
    lesson = data.get("lesson")
    reviewer = data.get("reviewed_by")
    return (
        f"보존된 lesson: {lesson}\n검토자: {reviewer}\n재사용 조건:\n{rendered_conditions}"
        if korean
        else f"Retained lesson: {lesson}\nReviewed by: {reviewer}\n"
        f"Reuse conditions:\n{rendered_conditions}"
    )


def _render_configuration_baseline(
    data: Mapping[str, Any],
    *,
    status: object,
    reason: str,
    korean: bool,
) -> str:
    if status != "matched":
        return (
            f"동결된 구성 기준선을 확인할 수 없습니다. 확인 결과: {reason}."
            if korean
            else f"The frozen configuration baseline is unavailable. Result: {reason}."
        )
    document = _cell(data.get("document_name"))
    source = f"출처: {document}" if korean else f"Source: {document}"
    version_heading = (
        "1) 기준선 버전과 생성 UTC" if korean else "1) Baseline version and creation UTC"
    )
    version = _cell(data.get("version"))
    created_at = _cell(data.get("created_at"))
    resource_heading = "2) 리소스와 SKU 또는 tier" if korean else "2) Resources with SKU or tier"
    resources = data.get("resources")
    resource_lines = ["- unknown"]
    if isinstance(resources, Sequence) and not isinstance(resources, (str, bytes)):
        rendered = [
            f"- {_cell(item.get('name'))}: {_cell(item.get('sku_or_tier'))}"
            for item in resources
            if isinstance(item, Mapping)
        ]
        if rendered:
            resource_lines = rendered
    topology_heading = "3) 토폴로지 관계" if korean else "3) Topology relationships"
    topology = data.get("topology")
    topology_lines: list[str] = []
    if isinstance(topology, Sequence) and not isinstance(topology, (str, bytes)):
        topology_lines = [
            f"- {_cell(item.get('source'))} {_cell(item.get('relation'))} "
            f"{_cell(item.get('target'))}"
            for item in topology
            if isinstance(item, Mapping)
        ]
    if not topology_lines:
        topology_lines = [
            "- 구조화된 토폴로지 관계가 동결되지 않아 unknown입니다."
            if korean
            else "- No structured topology relationships were frozen; topology is unknown."
        ]
    counters = (
        f"Mutation {data.get('mutation_count', 0)}, "
        f"approval {data.get('approval_request_count', 0)}, "
        f"mitigation {data.get('mitigation_execution_count', 0)}, unsupported claim "
        f"{data.get('unsupported_claim_count', 0)}"
    )
    return "\n".join(
        (
            version_heading,
            f"Version: {version}",
            f"Creation UTC: {created_at}",
            source,
            "",
            resource_heading,
            *resource_lines,
            source,
            "",
            topology_heading,
            *topology_lines,
            source,
            "",
            counters,
        )
    )


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(value.casefold()))


def _receipt_ref(prefix: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{prefix}:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _review_id(turn_id: str) -> str:
    return f"review-{hashlib.sha256(turn_id.encode()).hexdigest()[:32]}"


def _principal_scope(principal_id: str) -> str:
    return f"principal-{hashlib.sha256(principal_id.encode()).hexdigest()[:32]}"


def _cell(value: object) -> str:
    return str(value).replace("\n", " ").replace("\r", "").replace("|", "\\|")


__all__ = [
    "KnowledgeContextChatTools",
    "knowledge_context_evidence_refs",
    "render_knowledge_context_answer",
]
