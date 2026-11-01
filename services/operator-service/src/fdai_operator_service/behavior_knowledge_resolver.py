"""Server-owned behavior-knowledge resolver, deterministic renderer, and verifier."""
# ruff: noqa: E501

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
    "thor bragi narrator web spa browser ui security vulnerability cve csaf waf caf mcsb wara "
    "rule policy rego secret token credential rbac entra xss code prompt ai llm "
    "인시던트 오딘 포르세티 사가 이슈 중복 신뢰 라우팅 품질 게이트 승인 프로모션 실행기 롤백 콘솔 브라기 "
    "웹 브라우저 화면 보안 취약점 규칙 정책 프레임워크 비밀 토큰 자격 권한 계정 코드 프롬프트".split()
)
_MECHANISM_TOKENS: Final[frozenset[str]] = frozenset(
    "how when why work behave created generated deduplicate arbitrate route verify fallback "
    "rollback separate compare difference vs safe secure security issue problem vulnerable "
    "vulnerability risk protect prevent guard isolate block check audit assess evaluate scan "
    "review hold expose leak enforce mutate "
    "어떻게 언제 왜 동작 작동 생성 병합 중재 라우팅 검증 롤백 분리 비교 차이 "
    "보안 안전 문제 없나 있나 취약점 위험 보호 방어 격리 차단 권한 유출 노출 감사 평가 점검 스캔 확인 보유 실행".split()
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
        results = list(await self._index.search(request.raw_text, k=effective_k))
        if not results and self._seeds:
            results = list(self._search_registered_seeds(request.raw_text, k=effective_k))
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

    def _search_registered_seeds(
        self, raw_text: str, *, k: int
    ) -> Sequence[BehaviorSearchResultLike]:
        query_norm = " ".join(normalize_behavior_tokens(raw_text))
        query_tokens = set(normalize_behavior_tokens(raw_text))
        if not query_tokens:
            return ()
        scored: list[tuple[float, str, BehaviorSearchResultLike]] = []
        for seed_id, raw_seed in self._seeds.items():
            if not isinstance(raw_seed, BehaviorSpecLike):
                continue
            alias_norms = {
                " ".join(normalize_behavior_tokens(a)) for a in raw_seed.question_aliases
            }
            if query_norm in alias_norms:
                scored.append(
                    (
                        10.0,
                        seed_id,
                        BehaviorSearchResultLike(
                            spec=raw_seed, score=10.0, match_kind="exact_alias"
                        ),
                    )
                )
                continue
            ko_content = raw_seed.localized.get("ko")
            corpus = "\n".join(
                (
                    raw_seed.behavior_id,
                    raw_seed.subject_id,
                    *raw_seed.question_aliases,
                    *raw_seed.trigger,
                    *raw_seed.steps,
                    *raw_seed.outcomes,
                    *raw_seed.safety,
                    *(ko_content.trigger if ko_content else ()),
                    *(ko_content.steps if ko_content else ()),
                    *(ko_content.outcomes if ko_content else ()),
                    *(ko_content.safety if ko_content else ()),
                )
            )
            corpus_tokens = set(normalize_behavior_tokens(corpus))
            overlap = len(query_tokens & corpus_tokens) / len(query_tokens)
            if overlap >= RETRIEVAL_FLOOR:
                scored.append(
                    (
                        round(overlap, 6),
                        seed_id,
                        BehaviorSearchResultLike(
                            spec=raw_seed, score=round(overlap, 6), match_kind="hybrid"
                        ),
                    )
                )
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in scored[:k])


# fmt: off
def _sec_spec(
    behavior_id: str, subject_id: str, owner: str, aliases: tuple[str, ...],
    en: tuple[str, str, tuple[str, ...], str, str, str],
    ko: tuple[str, str, tuple[str, ...], str, str, str],
    src: tuple[str, str, int, int, str],
) -> BehaviorSpecLike:
    return BehaviorSpecLike(
        behavior_id=behavior_id, subject_kind="architecture_behavior", subject_id=subject_id,
        status="implemented", owner=owner, question_aliases=aliases,
        trigger=(en[0],), preconditions=(en[1],), steps=en[2], outcomes=(en[3],), exclusions=(en[4],), safety=(en[5],),
        sources=(BehaviorSourceLike(src[0], src[1], src[2], src[3], src[4]),), indexed_commit="b" * 40,
        localized={"ko": BehaviorContentLike(trigger=(ko[0],), preconditions=(ko[1],), steps=ko[2], outcomes=(ko[3],), exclusions=(ko[4],), safety=(ko[5],))},
    )


DEFAULT_SECURITY_BEHAVIOR_SPECS: Final[tuple[BehaviorSpecLike, ...]] = (
    _sec_spec(
        "architecture.console-web-security-posture", "Console.Web.Security.Boundary.RBAC.NoPrivilegedIdentity", "Operator Service / Console SPA",
        ("FDAI 콘솔웹이 보안상 문제가 없나?", "콘솔 웹에 보안 문제가 없나요?", "Is the FDAI Console web application secure?", "Does the FDAI Console web hold privileged credentials or execution authority?"),
        ("An operator inspects or questions the security posture of the FDAI Console web SPA.", "Entra ID authentication and server-verified GET /iam/self RBAC projection are active.", ("Render read-only projections and digest-verified guidance without dangerouslySetInnerHTML or arbitrary SVG/JS.", "Keep cloud credentials, secrets, and Thor's executor identity strictly outside the browser and Operator API.", "Route any state-changing request through the 5-role ActionType pipeline (Huginn, Forseti, Var, Thor, Saga) with 7 safeguards."), "The Console SPA has zero execution authority (execution_authority=false) and cannot mutate cloud resources directly; code and CVE findings are tracked on /code-security and /rules.", "Architectural isolation in the SPA does not substitute for live TLS, network, or tenant IAM verification in a deployed environment.", "Unverified digests, untrusted URLs, or missing RBAC claims fail closed without rendering or granting capability."),
        ("운영자가 FDAI 콘솔 웹(SPA)의 보안성이나 권한 경계를 점검·질문할 때 시작합니다.", "Entra ID 인증과 서버가 검증한 GET /iam/self RBAC 역할 투영이 적용됩니다.", ("dangerouslySetInnerHTML이나 임의의 SVG·HTML·JS 실행 없이 다이제스트가 검증된 읽기 전용 투영만 렌더링합니다.", "클라우드 자격 증명, 비밀값, Thor 실행기 신원을 브라우저 및 Operator API 외부에 철저히 격리합니다.", "모든 상태 변경 제안은 5대 역할 ActionType 파이프라인(Huginn·Forseti·Var·Thor·Saga)과 7대 안전장치를 거치도록 강제합니다."), "콘솔 웹은 직접 실행 권한이 전혀 없으며(execution_authority=false) 브라우저에서 리소스를 직접 변경할 수 없고, 코드 스캔은 /code-security, CVE 노출은 /rules에서 확인합니다.", "콘솔 아키텍처의 권한 분리 설계만으로 실제 배포 환경의 네트워크·TLS·테넌트 IAM 설정 완결성을 대체하지는 않습니다.", "다이제스트 불일치, 허용되지 않은 외부 URL, 누락된 RBAC 클레임은 즉시 차단(Fail-closed)됩니다."),
        (".github/instructions/app-shape.instructions.md", "Layer Boundaries (security)", 1, 60, "a" * 40),
    ),
    _sec_spec(
        "architecture.code-security-review-governance", "CodeSecurity.Review.SARIF.KataSandbox.VerificationPack", "Heimdall / Forseti / Saga",
        ("FDAI 자체 코드 보안 취약점 스캔과 검증은 어떻게 하나요?", "How does FDAI scan and verify code security issues?"),
        ("A repository revision or scheduled code-security scan request is evaluated.", "Signed source snapshots and isolated Kata sandbox scanner/verifier bindings are configured.", ("Run multi-lens static/dynamic scanners and verify candidate findings inside isolated Kata sandboxes.", "Aggregate P0-P4 priority, severity, confidence, and known-exploited counts into read-only Operator projections (/code-security)."), "Verified code-security reviews and adjudication packs are published with execution_authority=false.", "Code security scan projections never auto-merge code or mutate production infrastructure.", "Malformed or truncated SARIF/review records are withheld with explicit gap codes."),
        ("저장소 리비전 또는 예약된 코드 보안 스캔 요청이 평가될 때 시작합니다.", "서명된 소스 스냅샷과 격리된 Kata 샌드박스 스캐너·검증기 바인딩이 필요합니다.", ("다중 렌즈 정적·동적 스캐너를 실행하고 격리된 Kata 샌드박스에서 후보 취약점을 재현·검증합니다.", "P0-P4 우선순위, 심각도, 신뢰도, 악용 확인 건수를 읽기 전용 Operator 투영(/code-security)으로 집계합니다."), "검증된 코드 보안 리뷰와 판정 팩이 실행 권한 없이(execution_authority=false) 제공됩니다.", "코드 보안 스캔 결과는 코드를 자동 병합하거나 운영 인프라를 직접 변경하지 않습니다.", "손상되거나 잘린 리뷰·팩 레코드는 추측하지 않고 명시적인 gap 코드와 함께 보류합니다."),
        ("services/operator-service/src/fdai_operator_service/code_security_review_projection.py", "CodeSecurityReviewProjection", 1, 50, "c" * 40),
    ),
    _sec_spec(
        "architecture.rules-and-framework-shadow-boundary", "Rules.WAF.CAF.MCSB.WARA.ShadowAssessment.NoAuthority", "Forseti / Operator Service",
        ("FDAI 규칙 화면과 프레임워크 평가는 보안상 안전한가요?", "Are FDAI detection rules and framework assessments safe by default?"),
        ("An operator views or filters Detection Rules, WAF, CAF, MCSB, WARA, or MSRC CSAF on /rules.", "Authoritative catalog snapshots and SHA-256 digest-pinned guidance are loaded.", ("Evaluate T0 Rego rules and framework requirements in shadow mode against immutable inventory generations.", "Require distinct requester and approver principals before any Rule activation generation pointer changes."), "All /rules views and framework assessments emit read-only findings with execution_authority=false.", "Catalog presence, illustrated guidance, or a failed rule never triggers an unapproved mutation.", "Missing, stale, or cross-generation evidence remains explicitly unknown rather than assumed compliant."),
        ("운영자가 /rules 화면에서 탐지 규칙, WAF, CAF, MCSB, WARA, MSRC CSAF를 조회·평가할 때 시작합니다.", "권위 있는 카탈로그 스냅샷과 SHA-256 다이제스트로 고정된 가이드가 로드되어야 합니다.", ("불변 인벤토리 세대를 대상으로 T0 Rego 규칙과 프레임워크 요구사항을 Shadow 모드로 평가합니다.", "규칙 활성화 세대 포인터 변경 시 요청자와 분리된 승인자의 서명을 필수로 검증합니다."), "모든 /rules 화면과 프레임워크 평가는 실행 권한이 없는(execution_authority=false) 읽기 전용 결과를 반환합니다.", "카탈로그 등록, 도해 설명, 규칙 위반 판정만으로 승인 없는 리소스 변경이 실행되지 않습니다.", "근거가 누락·만료되었거나 세대가 다르면 준수로 가정하지 않고 명시적인 알 수 없음(Unknown)으로 유지합니다."),
        ("services/operator-service/src/fdai_operator_service/workflow_rule_projection.py", "rule_activation_status_payload", 513, 560, "d" * 40),
    ),
    _sec_spec(
        "architecture.msrc-csaf-vulnerability-governance", "MsrcCsaf.CVE.KEV.CVSS.VersionWindow.Heimdall.Drift", "Heimdall / Forseti / Norns / Saga",
        ("MSRC CSAF 2.0 CVE 취약점 평가는 어떻게 동작하나요?", "How does FDAI evaluate MSRC CSAF 2.0 CVE vulnerabilities?"),
        ("An operator or scheduled runner evaluates MSRC CSAF 2.0 security advisories against inventory.", "Signed MSRC CSAF 2.0 advisories and canonical ResourceType crosswalk shards are loaded.", ("Evaluate resource version-train windows and workaround predicates deterministically in shadow mode.", "Compute P0-P3 exploitability priority tiers from CISA KEV / exploit status, CVSS v3.1 vectors, and runtime exposure.", "Heimdall projects exposure drift to Forseti and Saga while Norns extracts inert RuleCandidates."), "Vulnerability exposure is classified as affected, mitigated, fixed, not_applicable, or unknown with execution_authority=false.", "Missing or stale resource version telemetry is never assumed patched or safe.", "Unmapped or ambiguous product families fail closed to unknown/blocked without auto-remediation."),
        ("운영자 또는 평가 러너가 인벤토리를 대상으로 MSRC CSAF 2.0 보안 권고문을 평가할 때 시작합니다.", "서명 검증된 MSRC CSAF 2.0 권고문과 정규 ResourceType 교차 매핑 샤드가 로드되어야 합니다.", ("리소스 버전 트레인 구간과 임시 완화(Workaround) 속성 조건을 Shadow 모드에서 결정론적으로 평가합니다.", "실제 악용 여부(KEV), CVSS v3.1 공격 표면 벡터, 노출 상태를 결합해 P0-P3 우선순위 등급을 산출합니다.", "Heimdall이 노출 드리프트를 Forseti·Saga로 전달하고 Norns가 불활성 RuleCandidate를 추출합니다."), "취약점 노출 상태가 실행 권한 없이(execution_authority=false) affected, mitigated, fixed, not_applicable, unknown으로 분류됩니다.", "리소스 버전 원격 분석 정보가 없거나 오래된 경우 패치 완료로 가정하지 않습니다.", "미지원 또는 모호한 제품 매핑은 자동 조치를 수행하지 않고 알 수 없음(Unknown)·차단 상태로 안전하게 보류합니다."),
        ("services/core-control-plane/src/fdai/core/security/csaf/runtime.py", "MsrcCsafAssessmentRuntime", 1, 80, "e" * 40),
    ),
    _sec_spec(
        "architecture.ai-security-guardrails", "AISecurity.MCSB.OWASPLLM.MITREATLAS.PromptInjection.HIL", "Bragi / QualityGate / RiskGate / Var",
        ("FDAI는 프롬프트 인젝션과 AI 보안을 어떻게 방어하나요?", "How does FDAI defend against prompt injection and AI security risks?"),
        ("Untrusted natural language, uploaded documents, or external telemetry enter an AI/LLM path.", "MCSB v2 AI-1..AI-7 controls, OWASP LLM Top 10 (2025), and MITRE ATLAS guardrails apply.", ("Separate untrusted data from system instructions and strip client-asserted authority or citations at ingress.", "Validate every model proposal against strict schemas, V-CLAIM evidence checks, and multi-model QualityGate consensus.", "Gate any state-changing ActionType through Forseti risk classification, Var HIL approval, and Thor isolated execution."), "Language and retrieved documents never grant execution authority (execution_authority=false); unverified claims or prompt-injected actions are rejected.", "Probabilistic prompt instructions alone are never trusted as a security boundary for privileged mutations.", "Ambiguous, conflicting, or policy-violating model outputs abstain or hold with an immutable audit record."),
        ("비신뢰 자연어 입력, 업로드 문서, 외부 원격 분석 데이터가 AI·LLM 경로에 유입될 때 시작합니다.", "MCSB v2 AI-1..AI-7 통제와 OWASP LLM Top 10 (2025), MITRE ATLAS 보안 가드레일이 적용됩니다.", ("비신뢰 데이터를 시스템 지침과 분리하고 클라이언트가 주장하는 권한·인용 필드를 진입 시점에 제거합니다.", "모든 모델 제안을 엄격한 스키마, V-CLAIM 근거 대조, 다중 모델 QualityGate 교차 검증으로 확인합니다.", "상태를 변경하는 모든 ActionType은 Forseti 위험 분류, Var 인간 승인(HIL), Thor 격리 실행기를 거치도록 강제합니다."), "자연어 발화나 검색 문서는 실행 권한을 절대 부여하지 못하며(execution_authority=false), 미검증 주장이나 인젝션 시도는 거부됩니다.", "확률적인 프롬프트 지시문 단독으로는 권한 있는 작업의 보안 경계로 신뢰하지 않습니다.", "모호하거나 충돌하거나 정책을 위반하는 모델 출력은 즉시 기권(Abstain)·보류(Hold)하고 감사 원장에 기록합니다."),
        ("services/core-control-plane/src/fdai/core/quality_gate/gate.py", "QualityGate.evaluate", 1, 80, "f" * 40),
    ),
)
# fmt: on


__all__ = [
    "DEFAULT_SECURITY_BEHAVIOR_SPECS",
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
