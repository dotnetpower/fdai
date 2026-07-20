"""Server-owned behavior evidence resolution for Command Deck answers."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdai.delivery.behavior_knowledge import InMemoryBehaviorKnowledgeIndex
from fdai.delivery.behavior_knowledge.seeds import (
    SEED_SOURCE_PATHS,
    build_seed_behavior_specs,
)
from fdai.delivery.behavior_knowledge.source_freshness import GitTrackedSourceValidator
from fdai.shared.providers.behavior_knowledge import BehaviorKnowledgeIndex, BehaviorSpec

_BEHAVIOR_SUBJECT = re.compile(
    r"(?:\b(?:incident(?:\s*id)?|odin|issues?|arbitration)\b|"
    r"(?:incident|odin|issues?)(?=[가-힣]))"
    "|인시던트|오딘|이슈|중복|개입|생성",
    re.IGNORECASE,
)
_COMPARISON_INTENT = re.compile(
    r"\b(?:compare|comparison|difference|different|versus|vs\.?)\b|비교|차이|달라",
    re.IGNORECASE,
)
_NEGATIVE_INTENT = re.compile(
    r"\b(?:does not|doesn't|not|never|exclude[ds]?)\b|않|아닌|제외",
    re.IGNORECASE,
)
_SAFETY_INTENT = re.compile(
    r"\b(?:safe|safety|fallback|fail|approval|human)\b|안전|실패|승인|사람",
    re.IGNORECASE,
)
_PROCESS_INTENT = re.compile(
    r"\b(?:how|process|steps?|generate[ds]?|handle[ds]?)\b|어떻게|방식|절차|생성|처리",
    re.IGNORECASE,
)
_WHY_INTENT = re.compile(r"\bwhy\b|왜|이유", re.IGNORECASE)
_WHEN_INTENT = re.compile(r"\bwhen\b|언제|조건", re.IGNORECASE)
_BEHAVIOR_INTENT = re.compile(
    r"\b(?:how|why|when|what|explain|generate[ds]?|dedup(?:e|lication)?|intervene[ds]?)\b"
    "|어떻게|왜|언제|어떤|방식|설명|생성|중복|개입|묶",
    re.IGNORECASE,
)


def is_behavior_question(prompt: str) -> bool:
    """Return whether the prompt asks about an indexed system behavior."""
    return bool(_BEHAVIOR_SUBJECT.search(prompt) and _BEHAVIOR_INTENT.search(prompt))


class BehaviorEvidenceResolver:
    """Resolve one behavior question into bounded structured evidence."""

    def __init__(self, index: BehaviorKnowledgeIndex) -> None:
        self._index = index

    async def resolve(self, prompt: str) -> Mapping[str, Any] | None:
        results = tuple(await self._index.search(prompt, k=5))
        if not results:
            return None
        exact = tuple(result for result in results if result.match_kind == "exact_alias")
        if len(exact) > 1:
            return {
                "status": "conflict",
                "authority": "behavior_knowledge_index",
                "behavior_ids": [result.spec.behavior_id for result in exact],
            }
        if _COMPARISON_INTENT.search(prompt) and len(results) >= 2:
            selected_results = results[:2]
            stale_sources = tuple(
                source for result in selected_results for source in result.stale_sources
            )
            if stale_sources:
                return {
                    "status": "stale",
                    "authority": "behavior_knowledge_index",
                    "behavior_ids": [result.spec.behavior_id for result in selected_results],
                    "citations": [source.citation() for source in stale_sources],
                }
            behaviors = [_behavior_payload(result.spec) for result in selected_results]
            return {
                "status": "comparison",
                "authority": "behavior_knowledge_index",
                "behavior_id": "comparison:"
                + ":".join(result.spec.behavior_id for result in selected_results),
                "behaviors": behaviors,
                "answer_focus": "comparison",
                "citations": _deduplicated_citations(behaviors),
                "indexed_commit": selected_results[0].spec.indexed_commit,
                "trusted_as_instructions": False,
                "grants_action_authority": False,
            }

        selected = results[0]
        if selected.stale:
            return {
                "status": "stale",
                "authority": "behavior_knowledge_index",
                "behavior_id": selected.spec.behavior_id,
                "indexed_commit": selected.spec.indexed_commit,
                "citations": [source.citation() for source in selected.stale_sources],
            }
        return {
            **_behavior_payload(selected.spec),
            "status": "matched",
            "authority": "behavior_knowledge_index",
            "answer_focus": _answer_focus(prompt),
            "trusted_as_instructions": False,
            "grants_action_authority": False,
        }


class RepositoryBehaviorEvidenceResolver:
    """Lazily seed behavior evidence from one tracked repository checkout."""

    def __init__(self, repository_root: Path | str) -> None:
        self._validator = GitTrackedSourceValidator(repository_root)
        self._resolver: BehaviorEvidenceResolver | None = None
        self._unavailable = False
        self._lock = asyncio.Lock()

    async def resolve(self, prompt: str) -> Mapping[str, Any] | None:
        await self._ensure_ready()
        if self._resolver is None:
            return {
                "status": "unavailable",
                "authority": "behavior_knowledge_index",
            }
        return await self._resolver.resolve(prompt)

    async def _ensure_ready(self) -> None:
        if self._resolver is not None or self._unavailable:
            return
        async with self._lock:
            if self._resolver is not None or self._unavailable:
                return
            indexed_commit = await self._validator.head_commit()
            blob_shas = {
                path: blob_sha
                for path in SEED_SOURCE_PATHS
                if (blob_sha := await self._validator.current_blob_sha(path)) is not None
            }
            if indexed_commit is None or blob_shas.keys() != SEED_SOURCE_PATHS:
                self._unavailable = True
                return
            index = InMemoryBehaviorKnowledgeIndex(source_validator=self._validator)
            for spec in build_seed_behavior_specs(
                indexed_commit=indexed_commit,
                blob_shas=blob_shas,
            ):
                await index.upsert(spec)
            self._resolver = BehaviorEvidenceResolver(index)


def _behavior_payload(spec: BehaviorSpec) -> dict[str, Any]:
    return {
        "behavior_id": spec.behavior_id,
        "subject_kind": spec.subject_kind,
        "subject_id": spec.subject_id,
        "implementation_status": spec.status,
        "owner": spec.owner,
        "trigger": list(spec.trigger),
        "preconditions": list(spec.preconditions),
        "processing_steps": list(spec.steps),
        "outcomes": list(spec.outcomes),
        "exclusions": list(spec.exclusions),
        "safety_and_fallback": list(spec.safety),
        "citations": [source.citation() for source in spec.sources],
        "indexed_commit": spec.indexed_commit,
        "extractor_version": spec.extractor_version,
        "source_manifest_hash": spec.source_manifest_hash,
        "localized": {
            locale: {
                "trigger": list(content.trigger),
                "preconditions": list(content.preconditions),
                "processing_steps": list(content.steps),
                "outcomes": list(content.outcomes),
                "exclusions": list(content.exclusions),
                "safety_and_fallback": list(content.safety),
            }
            for locale, content in spec.localized.items()
        },
    }


def _deduplicated_citations(behaviors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for behavior in behaviors:
        for citation in behavior["citations"]:
            key = tuple(citation.values())
            if key not in seen:
                seen.add(key)
                citations.append(citation)
    return citations


def _answer_focus(prompt: str) -> str:
    if _COMPARISON_INTENT.search(prompt):
        return "comparison"
    if _NEGATIVE_INTENT.search(prompt):
        return "exclusions"
    if _SAFETY_INTENT.search(prompt):
        return "safety"
    if _WHY_INTENT.search(prompt):
        return "why"
    if _WHEN_INTENT.search(prompt):
        return "trigger"
    if _PROCESS_INTENT.search(prompt):
        return "process"
    return "summary"


def render_behavior_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str:
    """Render a terminal answer from behavior evidence without model inference."""
    korean = bool(locale and locale.casefold().startswith("ko"))
    status = evidence.get("status")
    if status == "stale":
        return (
            "구현 근거의 blob hash가 색인 시점과 달라 현재 동작으로 확정하지 않았습니다. "
            "행동 지식을 다시 색인한 뒤 확인해야 합니다."
            if korean
            else "The source blob hash has changed since indexing, so this behavior is not "
            "confirmed as current. Reindex behavior knowledge before relying on it."
        )
    if status == "conflict":
        return (
            "서로 충돌하는 행동 계약이 검색되어 답변을 확정하지 않았습니다. "
            "권위 근거를 조정한 뒤 다시 확인해야 합니다."
            if korean
            else "Conflicting behavior contracts were retrieved, so the answer was not finalized. "
            "Resolve the authority conflict before relying on it."
        )
    if status in {"none", "unavailable"}:
        return (
            "현재 검증 가능한 행동 근거를 찾지 못해 답변을 확정하지 않았습니다."
            if korean
            else "No current verifiable behavior evidence was found, so the answer "
            "was not finalized."
        )
    if status != "matched":
        if status == "comparison":
            return _render_comparison_answer(evidence, korean=korean)
        return (
            "행동 근거 상태를 검증할 수 없어 답변을 확정하지 않았습니다."
            if korean
            else "The behavior evidence state could not be verified, so the answer "
            "was not finalized."
        )

    rendered_evidence = _localized_evidence(evidence, locale="ko") if korean else evidence
    labels = (
        (
            "Trigger",
            "Preconditions",
            "Processing steps",
            "Outcomes",
            "Exclusions / does-not-mean",
            "Safety and fallback behavior",
            "Owner",
            "Implementation status",
            "Citations / provenance",
        )
        if not korean
        else (
            "트리거",
            "사전 조건",
            "처리 단계",
            "결과",
            "제외 사항 / 의미하지 않는 것",
            "안전 및 fallback 동작",
            "담당",
            "구현 상태",
            "인용 / 출처",
        )
    )
    sections = [
        _lead_section(rendered_evidence, korean=korean),
        _list_section(labels[0], rendered_evidence.get("trigger")),
        _list_section(labels[1], rendered_evidence.get("preconditions")),
        _list_section(labels[2], rendered_evidence.get("processing_steps"), ordered=True),
        _list_section(labels[3], rendered_evidence.get("outcomes")),
        _list_section(labels[4], rendered_evidence.get("exclusions")),
        _list_section(labels[5], rendered_evidence.get("safety_and_fallback")),
        f"**{labels[6]}**\n{rendered_evidence.get('owner', 'unknown')}",
        f"**{labels[7]}**\n{rendered_evidence.get('implementation_status', 'unknown')}",
        _citation_section(labels[8], rendered_evidence),
    ]
    return "\n\n".join(sections)


def _localized_evidence(evidence: Mapping[str, Any], *, locale: str) -> dict[str, Any]:
    rendered = dict(evidence)
    localized = evidence.get("localized")
    if not isinstance(localized, Mapping):
        return rendered
    content = localized.get(locale)
    if not isinstance(content, Mapping):
        return rendered
    for field in (
        "trigger",
        "preconditions",
        "processing_steps",
        "outcomes",
        "exclusions",
        "safety_and_fallback",
    ):
        value = content.get(field)
        if isinstance(value, list):
            rendered[field] = value
    return rendered


def _lead_section(evidence: Mapping[str, Any], *, korean: bool) -> str:
    focus = str(evidence.get("answer_focus") or "summary")
    field_by_focus = {
        "exclusions": "exclusions",
        "process": "processing_steps",
        "safety": "safety_and_fallback",
        "trigger": "trigger",
        "why": "outcomes",
    }
    field = field_by_focus.get(focus, "outcomes")
    raw = evidence.get(field)
    values = [str(item) for item in raw[:2]] if isinstance(raw, list) else []
    title = "핵심 답변" if korean else "Direct answer"
    return f"**{title}**\n" + "\n".join(f"- {value}" for value in values)


def _render_comparison_answer(evidence: Mapping[str, Any], *, korean: bool) -> str:
    raw = evidence.get("behaviors")
    behaviors = [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []
    title = "비교 요약" if korean else "Comparison summary"
    comparison_lines = [
        f"- **{item.get('subject_id', item.get('behavior_id', 'unknown'))}**: "
        + "; ".join(str(value) for value in item.get("outcomes", [])[:2])
        for item in behaviors
    ]

    def combined(field: str) -> list[str]:
        return [
            f"{item.get('subject_id')}: {value}"
            for item in behaviors
            for value in item.get(field, [])
        ]

    sections = [
        f"**{title}**\n" + "\n".join(comparison_lines),
        _list_section("Trigger", combined("trigger")),
        _list_section("Preconditions", combined("preconditions")),
        _list_section("Processing steps", combined("processing_steps"), ordered=True),
        _list_section("Outcomes", combined("outcomes")),
        _list_section("Exclusions / does-not-mean", combined("exclusions")),
        _list_section("Safety and fallback behavior", combined("safety_and_fallback")),
        "**Owner**\n" + ", ".join(str(item.get("owner")) for item in behaviors),
        "**Implementation status**\n"
        + ", ".join(str(item.get("implementation_status")) for item in behaviors),
        _citation_section("Citations / provenance", evidence),
    ]
    return "\n\n".join(sections)


def behavior_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    citations = evidence.get("citations")
    if not isinstance(citations, list):
        return ()
    refs = []
    for citation in citations:
        if not isinstance(citation, Mapping):
            continue
        path = citation.get("path")
        line_start = citation.get("line_start")
        line_end = citation.get("line_end")
        blob_sha = citation.get("blob_sha")
        if isinstance(path, str) and isinstance(line_start, int) and isinstance(line_end, int):
            refs.append(f"{path}#L{line_start}-L{line_end}@{blob_sha}")
    return tuple(refs)


def _list_section(label: str, raw: Any, *, ordered: bool = False) -> str:
    values = [str(item) for item in raw] if isinstance(raw, list) else []
    if not values:
        values = ["Not declared."]
    lines = [
        f"{index}. {value}" if ordered else f"- {value}" for index, value in enumerate(values, 1)
    ]
    return f"**{label}**\n" + "\n".join(lines)


def _citation_section(label: str, evidence: Mapping[str, Any]) -> str:
    citations = evidence.get("citations")
    lines = []
    if isinstance(citations, list):
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            lines.append(
                "- "
                f"{citation.get('path')}::{citation.get('symbol')} "
                f"L{citation.get('line_start')}-L{citation.get('line_end')} "
                f"blob {citation.get('blob_sha')}"
            )
    lines.append(f"- indexed commit {evidence.get('indexed_commit', 'unknown')}")
    return f"**{label}**\n" + "\n".join(lines)


__all__ = [
    "BehaviorEvidenceResolver",
    "RepositoryBehaviorEvidenceResolver",
    "behavior_evidence_refs",
    "is_behavior_question",
    "render_behavior_answer",
]
