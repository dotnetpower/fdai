"""Server-owned behavior-knowledge resolver, deterministic renderer, and verifier."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal, Protocol, runtime_checkable

RETRIEVAL_FLOOR: Final[float] = 0.05
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
_HANGUL_RE: Final[re.Pattern[str]] = re.compile(r"[가-힣]+")
_SECTION_KEYS: Final[tuple[str, ...]] = (
    "trigger",
    "preconditions",
    "steps",
    "outcomes",
    "exclusions",
    "safety",
    "owner",
    "status",
    "citations",
)
_EN_HEADINGS: Final[Mapping[str, str]] = {
    "trigger": "Trigger",
    "preconditions": "Preconditions",
    "steps": "Processing steps",
    "outcomes": "Outcomes",
    "exclusions": "Exclusions",
    "safety": "Safety and fallback",
    "owner": "Owner",
    "status": "Implementation status",
    "citations": "Citations",
}
_KO_HEADINGS: Final[Mapping[str, str]] = {
    "trigger": "트리거",
    "preconditions": "사전 조건",
    "steps": "처리 단계",
    "outcomes": "결과",
    "exclusions": "제외 사항",
    "safety": "안전 및 폴백 동작",
    "owner": "책임 주체",
    "status": "구현 상태",
    "citations": "근거 출처",
}
_SUBJECT_TOKENS: Final[frozenset[str]] = frozenset(
    "incident id odin forseti saga issue fingerprint deduplication trust routing tier t0 t1 t2 "
    "quality gate risk var promotion shadow executor event ingest vidar rollback console identity "
    "thor bragi narrator 인시던트 오딘 포르세티 사가 이슈 중복 신뢰 라우팅 품질 게이트 승인 프로모션 실행기 롤백 콘솔 브라기".split()  # noqa: E501
)
_MECHANISM_TOKENS: Final[frozenset[str]] = frozenset(
    "how when why work behave created generated deduplicate arbitrate route verify fallback "
    "rollback separate compare difference vs 어떻게 언제 왜 동작 작동 생성 병합 중재 라우팅 검증 롤백 분리 비교 차이".split()  # noqa: E501
)
_OPERATIONAL_READ_PATTERNS: Final[tuple[str, ...]] = (
    "how many incidents",
    "list active incidents",
    "current incident count",
    "on this screen",
    "이 화면에",
    "현재 열린 인시던트 건수",
    "활성 인시던트 목록",
)
_ACTION_REQUEST_PATTERNS: Final[tuple[str, ...]] = (
    "approve action",
    "execute rollback now",
    "restart the cluster",
    "scale out the deployment",
    "지금 롤백 실행해줘",
    "클러스터 재시작해줘",
)
BehaviorOutcome = Literal[
    "rendered",
    "comparison_rendered",
    "stale_abstained",
    "comparison_incomplete",
    "conflict_hold",
    "authority_fallback",
    "no_evidence",
]


def _validate_query_text(raw_text: str) -> str:
    if not isinstance(raw_text, str) or any(
        ord(ch) < 32 and ch not in {"\t", "\n"} for ch in raw_text
    ):
        raise ValueError("behavior query MUST NOT contain NUL or control characters")
    return raw_text


def _validate_top_k(top_k: int) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k MUST be an integer in [1, 20]")
    return top_k


@dataclass(frozen=True, slots=True)
class BehaviorSourceLike:
    path: str
    symbol: str
    line_start: int = 1
    line_end: int = 1
    blob_sha: str = ""


@dataclass(frozen=True, slots=True)
class BehaviorContentLike:
    trigger: tuple[str, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    outcomes: tuple[str, ...]
    exclusions: tuple[str, ...]
    safety: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BehaviorSpecLike:
    behavior_id: str
    subject_kind: str = "object_behavior"
    subject_id: str = ""
    status: str = "implemented"
    owner: str = ""
    question_aliases: tuple[str, ...] = ()
    trigger: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    safety: tuple[str, ...] = ()
    sources: tuple[BehaviorSourceLike, ...] = ()
    indexed_commit: str = ""
    localized: Mapping[str, BehaviorContentLike] = field(default_factory=dict)
    seed_id: str = ""


@dataclass(frozen=True, slots=True)
class BehaviorSearchResultLike:
    spec: BehaviorSpecLike
    score: float = 1.0
    match_kind: str = "exact_alias"
    stale: bool = False
    stale_sources: tuple[BehaviorSourceLike, ...] = ()


@runtime_checkable
class BehaviorSearchIndexPort(Protocol):
    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResultLike]: ...


@dataclass(frozen=True, slots=True)
class BehaviorCitationRecord:
    path: str
    symbol: str
    line_start: int
    line_end: int
    blob_sha: str
    indexed_commit: str
    authority: Literal["none"] = "none"


@dataclass(frozen=True, slots=True)
class BehaviorTurnRequest:
    raw_text: str
    locale: Literal["en", "ko"] = "en"
    client_evidence: tuple[Mapping[str, Any], ...] = ()
    client_citations: tuple[Mapping[str, Any], ...] = ()
    claimed_authority: str | None = None
    top_k: int = 5

    def __post_init__(self) -> None:
        _validate_query_text(self.raw_text)
        _validate_top_k(self.top_k)


@dataclass(frozen=True, slots=True)
class BehaviorVerificationMetadata:
    verified: bool
    authority: Literal["none"] = "none"
    read_only: Literal[True] = True
    can_approve: Literal[False] = False
    can_execute: Literal[False] = False
    client_evidence_stripped: bool = False
    stripped_claim_count: int = 0
    stale_withheld_count: int = 0
    reindex_required: bool = False
    citations: tuple[BehaviorCitationRecord, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BehaviorResolutionResult:
    handled: bool
    fallback_to_next_authority: bool
    outcome: BehaviorOutcome
    fallback_reason: str | None
    locale: Literal["en", "ko"]
    behavior_ids: tuple[str, ...] = ()
    sections: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    rendered_text: str = ""
    verification: BehaviorVerificationMetadata = field(
        default_factory=lambda: BehaviorVerificationMetadata(verified=False)
    )
    total_candidates: int = 0
    result_digest: str = ""

    def __post_init__(self) -> None:
        material = {
            "behavior_ids": list(self.behavior_ids),
            "fallback_reason": self.fallback_reason,
            "fallback_to_next_authority": self.fallback_to_next_authority,
            "handled": self.handled,
            "locale": self.locale,
            "outcome": self.outcome,
            "rendered_text": self.rendered_text,
            "total_candidates": self.total_candidates,
            "verified": self.verification.verified,
            "reasons": list(self.verification.reasons),
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        if not self.result_digest:
            object.__setattr__(self, "result_digest", expected)
        elif self.result_digest != expected:
            raise ValueError("BehaviorResolutionResult.result_digest mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            "handled": self.handled,
            "fallback_to_next_authority": self.fallback_to_next_authority,
            "outcome": self.outcome,
            "fallback_reason": self.fallback_reason,
            "locale": self.locale,
            "behavior_ids": list(self.behavior_ids),
            "sections": {k: list(v) for k, v in self.sections.items()},
            "rendered_text": self.rendered_text,
            "verification": asdict(self.verification),
            "total_candidates": self.total_candidates,
            "result_digest": self.result_digest,
        }

    def to_json(self) -> dict[str, object]:
        return self.to_dict()


def normalize_behavior_tokens(raw_text: str) -> tuple[str, ...]:
    _validate_query_text(raw_text)
    lowered = unicodedata.normalize("NFKC", raw_text).casefold()
    tokens: list[str] = []
    for word in _WORD_RE.findall(lowered.replace("_", " ").replace("-", " ").replace(".", " ")):
        if len(word) > 3 and word.endswith("ies"):
            tokens.append(f"{word[:-3]}y")
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            tokens.append(word[:-1])
        else:
            tokens.append(word)
    for run in _HANGUL_RE.findall(lowered):
        tokens.extend((run, *(run[i : i + 2] for i in range(len(run) - 1))))
    return tuple(tokens)


class DeterministicBehaviorRenderer:
    """Render structured behavior contracts in `en` or `ko` without source bodies."""

    def render_single(
        self,
        spec: BehaviorSpecLike,
        *,
        locale: Literal["en", "ko"],
        citations: tuple[BehaviorCitationRecord, ...],
    ) -> tuple[Mapping[str, tuple[str, ...]], str]:
        source = (spec.localized.get("ko") if locale == "ko" else None) or spec
        citation_lines = tuple(
            f"{c.path}#{c.symbol}:{c.line_start}-{c.line_end}@{c.blob_sha[:12]}" for c in citations
        )
        sections: dict[str, tuple[str, ...]] = {
            "trigger": tuple(source.trigger),
            "preconditions": tuple(source.preconditions),
            "steps": tuple(source.steps),
            "outcomes": tuple(source.outcomes),
            "exclusions": tuple(source.exclusions),
            "safety": tuple(source.safety),
            "owner": (spec.owner,),
            "status": (spec.status,),
            "citations": citation_lines,
        }
        headings = _KO_HEADINGS if locale == "ko" else _EN_HEADINGS
        blocks = [
            f"### {headings[key]}\n" + "\n".join(f"- {line}" for line in sections[key])
            for key in _SECTION_KEYS
        ]
        return sections, "\n\n".join(blocks)


class BehaviorAnswerVerifier:
    """Verify read-only authority, citation hygiene, and localized section completeness."""

    def verify(
        self,
        *,
        sections: Mapping[str, tuple[str, ...]],
        rendered_text: str,
        citations: tuple[BehaviorCitationRecord, ...],
        stale_sources: tuple[Any, ...],
        client_evidence_stripped: bool,
        stripped_claim_count: int,
    ) -> BehaviorVerificationMetadata:
        reasons: list[str] = []
        if tuple(sections) != _SECTION_KEYS or any(not sections.get(k) for k in _SECTION_KEYS):
            reasons.append("missing_required_sections")
        if not citations:
            reasons.append("missing_verified_citations")
        stale_keys = {(s.path, s.symbol) for s in stale_sources}
        if any((c.path, c.symbol) in stale_keys for c in citations):
            reasons.append("stale_citation_leaked")
        if any(c.authority != "none" or not c.blob_sha for c in citations):
            reasons.append("invalid_citation_authority")
        if "```" in rendered_text or re.search(
            r"(?m)^\s*(?:def|class)\s+[A-Za-z_]\w*\s*[:(]", rendered_text
        ):
            reasons.append("raw_code_body_detected")
        return BehaviorVerificationMetadata(
            verified=not reasons,
            client_evidence_stripped=client_evidence_stripped,
            stripped_claim_count=stripped_claim_count,
            stale_withheld_count=len(stale_sources),
            reindex_required=bool(stale_sources),
            citations=citations if not reasons else (),
            reasons=tuple(reasons),
        )


class OperatorBehaviorKnowledgeResolver:
    """Resolve Operator behavior questions from server-owned contracts only."""

    def __init__(
        self,
        index: BehaviorSearchIndexPort,
        *,
        renderer: DeterministicBehaviorRenderer | None = None,
        verifier: BehaviorAnswerVerifier | None = None,
        seeds: Sequence[Any] = (),
    ) -> None:
        self._index = index
        self._renderer = renderer or DeterministicBehaviorRenderer()
        self._verifier = verifier or BehaviorAnswerVerifier()
        self._registered_seed_ids: set[str] = set()
        self._seeds: dict[str, Any] = {}
        if seeds:
            self.register_seeds(seeds)

    def register_seed(self, seed: Any) -> None:
        raw_id = (
            (seed.get("seed_id") or seed.get("behavior_id"))
            if isinstance(seed, Mapping)
            else (getattr(seed, "seed_id", "") or getattr(seed, "behavior_id", ""))
        )
        seed_id = str(raw_id or "").strip()
        if not seed_id or seed_id in self._registered_seed_ids:
            raise ValueError(f"invalid or duplicate seed_id {seed_id!r}")
        self._registered_seed_ids.add(seed_id)
        self._seeds[seed_id] = seed

    def register_seeds(self, seeds: Sequence[Any]) -> None:
        for seed in seeds:
            self.register_seed(seed)

    async def resolve(
        self, request: BehaviorTurnRequest, *, top_k: int | None = None
    ) -> BehaviorResolutionResult:
        _validate_query_text(request.raw_text)
        effective_k = _validate_top_k(request.top_k if top_k is None else top_k)
        stripped_count = (
            len(request.client_evidence)
            + len(request.client_citations)
            + (1 if request.claimed_authority else 0)
        )
        stripped = stripped_count > 0
        fallback_reason = self._check_authority_fallback(request.raw_text)
        if fallback_reason is not None:
            return self._fallback_result(request.locale, fallback_reason, stripped, stripped_count)
        results = await self._index.search(request.raw_text, k=effective_k)
        cand_count = len(results)
        if not results or results[0].score < RETRIEVAL_FLOOR:
            return self._fallback_result(
                request.locale, "below_retrieval_floor", stripped, stripped_count, cand_count
            )
        is_comparison = any(
            tok in request.raw_text.casefold()
            for tok in ("compare", "difference between", " vs ", "비교", "차이")
        )
        if is_comparison and len([r for r in results if not r.stale][:2]) < 2:
            stale_cnt = sum(len(r.stale_sources) for r in results[:2])
            msg = (
                "검증 가능한 최신 동작 계약이 2개 미만이어서 비교 답변을 보류합니다."
                if request.locale == "ko"
                else "Comparison abstained: fewer than two fresh behavior contracts matched."
            )
            return self._abstain(
                "comparison_incomplete",
                request.locale,
                msg=msg,
                stripped=stripped,
                count=stripped_count,
                stale_cnt=stale_cnt,
                reason="comparison_requires_two_fresh_contracts",
                total_candidates=cand_count,
            )
        if (
            not is_comparison
            and len(results) >= 2
            and results[0].match_kind == "exact_alias"
            and results[1].match_kind == "exact_alias"
            and results[0].score == results[1].score
            and results[0].spec.behavior_id != results[1].spec.behavior_id
        ):
            return self._abstain(
                "conflict_hold",
                request.locale,
                ids=(results[0].spec.behavior_id, results[1].spec.behavior_id),
                stripped=stripped,
                count=stripped_count,
                reason="conflicting_exact_contracts",
                total_candidates=cand_count,
            )
        top = results[0]
        if top.stale:
            msg = (
                "인용된 원본 해시가 현재 추적 소스와 일치하지 않아 재색인이 필요합니다."
                if request.locale == "ko"
                else "Cited source blob hash is stale or untracked; reindexing is required."
            )
            return self._abstain(
                "stale_abstained",
                request.locale,
                ids=(top.spec.behavior_id,),
                msg=msg,
                stripped=stripped,
                count=stripped_count,
                stale_cnt=len(top.stale_sources),
                reindex=True,
                reason="stale_or_untracked_source",
                total_candidates=cand_count,
            )
        citations = tuple(
            BehaviorCitationRecord(
                s.path, s.symbol, s.line_start, s.line_end, s.blob_sha, top.spec.indexed_commit
            )
            for s in top.spec.sources
        )
        sections, rendered = self._renderer.render_single(
            top.spec, locale=request.locale, citations=citations
        )
        meta = self._verifier.verify(
            sections=sections,
            rendered_text=rendered,
            citations=citations,
            stale_sources=top.stale_sources,
            client_evidence_stripped=stripped,
            stripped_claim_count=stripped_count,
        )
        outcome: BehaviorOutcome = "comparison_rendered" if is_comparison else "rendered"
        return BehaviorResolutionResult(
            True,
            False,
            outcome,
            None,
            request.locale,
            (top.spec.behavior_id,),
            sections,
            rendered,
            meta,
            total_candidates=cand_count,
        )

    @staticmethod
    def _abstain(
        outcome: BehaviorOutcome,
        locale: Literal["en", "ko"],
        *,
        ids: tuple[str, ...] = (),
        msg: str = "",
        stripped: bool = False,
        count: int = 0,
        stale_cnt: int = 0,
        reindex: bool = False,
        reason: str,
        total_candidates: int = 0,
    ) -> BehaviorResolutionResult:
        meta = BehaviorVerificationMetadata(
            verified=False,
            client_evidence_stripped=stripped,
            stripped_claim_count=count,
            stale_withheld_count=stale_cnt,
            reindex_required=reindex or stale_cnt > 0,
            reasons=(reason,),
        )
        return BehaviorResolutionResult(
            True,
            False,
            outcome,
            None,
            locale,
            ids,
            rendered_text=msg,
            verification=meta,
            total_candidates=total_candidates,
        )

    @staticmethod
    def _fallback_result(
        locale: Literal["en", "ko"],
        reason: str,
        stripped: bool,
        count: int,
        total_candidates: int = 0,
    ) -> BehaviorResolutionResult:
        meta = BehaviorVerificationMetadata(
            verified=False,
            client_evidence_stripped=stripped,
            stripped_claim_count=count,
            reasons=(reason,),
        )
        return BehaviorResolutionResult(
            False,
            True,
            "authority_fallback",
            reason,
            locale,
            verification=meta,
            total_candidates=total_candidates,
        )

    @staticmethod
    def _check_authority_fallback(raw_text: str) -> str | None:
        folded = raw_text.casefold()
        if any(pat in folded for pat in _OPERATIONAL_READ_PATTERNS):
            return "operational_read"
        if any(pat in folded for pat in _ACTION_REQUEST_PATTERNS):
            return "action_request"
        tokens = set(normalize_behavior_tokens(raw_text))
        if not (tokens & _SUBJECT_TOKENS) or not (tokens & _MECHANISM_TOKENS):
            return "missing_behavior_subject_or_mechanism"
        return None


__all__ = [
    "RETRIEVAL_FLOOR",
    "BehaviorAnswerVerifier",
    "BehaviorCitationRecord",
    "BehaviorContentLike",
    "BehaviorResolutionResult",
    "BehaviorSearchIndexPort",
    "BehaviorSearchResultLike",
    "BehaviorSourceLike",
    "BehaviorSpecLike",
    "BehaviorTurnRequest",
    "BehaviorVerificationMetadata",
    "DeterministicBehaviorRenderer",
    "OperatorBehaviorKnowledgeResolver",
    "normalize_behavior_tokens",
]
