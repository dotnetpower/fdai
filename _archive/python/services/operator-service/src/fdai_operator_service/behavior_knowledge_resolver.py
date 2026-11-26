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
# fmt: off
_SECTION_KEYS: Final[tuple[str, ...]] = ("trigger", "preconditions", "steps", "outcomes", "exclusions", "safety", "owner", "status", "citations")
_EN_HEADINGS: Final[Mapping[str, str]] = {"trigger": "Trigger", "preconditions": "Preconditions", "steps": "Processing steps", "outcomes": "Outcomes", "exclusions": "Exclusions", "safety": "Safety and fallback", "owner": "Owner", "status": "Implementation status", "citations": "Citations"}
_KO_HEADINGS: Final[Mapping[str, str]] = {"trigger": "트리거", "preconditions": "사전 조건", "steps": "처리 단계", "outcomes": "결과", "exclusions": "제외 사항", "safety": "안전 및 폴백 동작", "owner": "책임 주체", "status": "구현 상태", "citations": "근거 출처"}
_SUBJECT_TOKENS: Final[frozenset[str]] = frozenset(
    "incident id odin forseti saga issue fingerprint deduplication trust routing tier t0 t1 t2 "
    "quality gate risk var promotion shadow executor event ingest vidar rollback console identity "
    "thor bragi narrator web spa browser ui security vulnerability cve csaf waf caf mcsb wara "
    "rule policy rego secret token credential rbac entra xss code prompt ai llm iam jwt document "
    "rag upload webhook sse ssrf safeguard lock blast dryrun crosswalk cors csp msal storage "
    "sessionstorage sbom dsse ed25519 dependency supplychain audit ancestry keyvault jailbreak "
    "인시던트 오딘 포르세티 사가 이슈 중복 신뢰 라우팅 품질 게이트 승인 프로모션 실행기 롤백 콘솔 브라기 "
    "웹 브라우저 화면 보안 취약점 규칙 정책 프레임워크 비밀 토큰 자격 권한 계정 코드 프롬프트 인증 역할 "
    "문서 업로드 웹훅 스트리밍 안전장치 교차매핑 자율 실행 액션 스토리지 공급망 의존성 패키지 서명 "
    "감사 위변조 시크릿 키볼트 인젝션 탈옥".split()
)
_MECHANISM_TOKENS: Final[frozenset[str]] = frozenset(
    "how when why work behave created generated deduplicate arbitrate route verify fallback "
    "rollback separate compare difference vs safe secure security issue problem vulnerable "
    "vulnerability risk protect prevent guard isolate block check audit assess evaluate scan "
    "review hold expose leak enforce mutate authenticate authorize quarantine sign tamper "
    "어떻게 언제 왜 동작 작동 생성 병합 중재 라우팅 검증 롤백 분리 비교 차이 "
    "보안 안전 문제 없나 있나 취약점 위험 보호 방어 격리 차단 권한 유출 노출 감사 평가 점검 스캔 확인 보유 실행 인증 검역 서명 변조".split()
)
_OPERATIONAL_READ_PATTERNS: Final[tuple[str, ...]] = ("how many incidents", "list active incidents", "current incident count", "on this screen", "이 화면에", "현재 열린 인시던트 건수", "활성 인시던트 목록")
_ACTION_REQUEST_PATTERNS: Final[tuple[str, ...]] = ("approve action", "execute rollback now", "restart the cluster", "scale out the deployment", "지금 롤백 실행해줘", "클러스터 재시작해줘")
BehaviorOutcome = Literal["rendered", "comparison_rendered", "stale_abstained", "comparison_incomplete", "conflict_hold", "authority_fallback", "no_evidence"]
# fmt: on


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
    _sec_spec(
        "architecture.iam-rbac-and-token-boundary", "IAM.EntraID.RBAC.SelfProjection.NoExecutorToken", "Operator Service / IAM Family",
        ("FDAI에서 권한이나 RBAC, Entra ID 인증은 보안상 문제가 없나?", "How does FDAI enforce Entra ID authentication and RBAC token security?"),
        ("An operator or API client authenticates to the Operator Service.", "Entra ID JWT signature, issuer, audience, and tenant claims are validated.", ("Map verified App Roles and group claims to canonical OperatorRole (Reader, Contributor, Approver, Owner, BreakGlass) via GET /iam/self.", "Strip client-supplied principal_id, owner_principal_id, and role claims at HTTP ingress.", "Keep human bearer tokens strictly separate from Thor's workload Managed Identity."), "Every route enforces server-verified RBAC with execution_authority=false on read and proposal surfaces.", "Browser tokens and stewardship assignments never grant direct cloud or executor credentials.", "Expired, wrong-audience, or unmapped tokens fail closed with 401/403 before reading request bodies."),
        ("운영자 또는 API 클라이언트가 Operator Service에 인증을 요청할 때 시작합니다.", "Entra ID JWT 서명, 발급자(issuer), 대상(audience), 테넌트 클레임이 검증되어야 합니다.", ("검증된 앱 역할 및 그룹 클레임을 GET /iam/self를 통해 정규 역할(Reader, Contributor, Approver, Owner, BreakGlass)로 투영합니다.", "HTTP 진입점에서 클라이언트가 임의로 보낸 principal_id·권한 클레임을 즉시 제거합니다.", "사람의 인증 토큰과 Thor 실행기의 관리 ID(Managed Identity)를 철저히 분리합니다."), "모든 라우트는 서버가 검증한 RBAC를 강제하며 조회·제안 경로는 실행 권한(execution_authority=false)을 갖지 않습니다.", "브라우저 토큰이나 스튜어드십 배정은 클라우드 또는 실행기 자격 증명을 부여하지 않습니다.", "만료되었거나 대상(audience)이 불일치하거나 매핑되지 않은 토큰은 본문 처리 전에 401/403으로 차단합니다."),
        ("services/operator-service/src/fdai_operator_service/auth.py", "OperatorAuthenticator", 1, 80, "1" * 40),
    ),
    _sec_spec(
        "architecture.seven-safeguard-execution-boundary", "Execution.Thor.Vidar.SevenSafeguards.TwoPhaseAudit", "Huginn / Forseti / Var / Thor / Vidar / Saga",
        ("FDAI 자율 실행기나 액션이 임의로 리소스를 변경할 위험은 없나?", "How do the 7 constitutional safeguards protect autonomous action execution?"),
        ("A state-changing ActionType is proposed from detection or operator workflow.", "The ActionType is registered and evaluated through the 5-role Pantheon pipeline.", ("Require all 7 safeguards: stop condition, tested rollback, blast-radius limit, dry-run success, logical-target lock, stable idempotency key, and two-phase audit.", "Enforce distinct human approver (Var) and isolated workload executor (Thor) identities.", "Verify post-execution effects independently and trigger Vidar rollback on failure."), "No action executes without explicit human approval or valid standing authorization and all 7 safeguards.", "Broker acceptance or API 200 is never treated as operational effect verification.", "Any missing safeguard, lock conflict, or dry-run failure aborts execution and records an immutable Saga audit."),
        ("탐지 결과 또는 운영자 워크플로에서 상태 변경 ActionType이 제안될 때 시작합니다.", "해당 ActionType이 레지스트리에 등록되어 있고 5대 역할(Huginn·Forseti·Var·Thor·Saga) 파이프라인을 통과해야 합니다.", ("중단 조건, 검증된 롤백, 폭발 반경 제한, 드라이런 성공, 논리 대상 잠금, 멱등성 키, 2단계 감사의 7대 헌법적 안전장치를 모두 강제합니다.", "사람 승인자(Var)와 격리된 실행기(Thor)의 신원을 엄격히 분리합니다.", "실행 후 효과를 독립적으로 검증하고 실패 시 Vidar가 자동 롤백을 수행합니다."), "명시적 승인 또는 유효한 사전 권한과 7대 안전장치가 모두 충족되기 전에는 어떠한 리소스 변경도 실행되지 않으며 제안 자체는 실행 권한이 없습니다(execution_authority=false).", "브로커 수락이나 API 200 응답만으로 운영 효과가 검증되었다고 간주하지 않습니다.", "안전장치 누락, 잠금 충돌, 드라이런 실패가 발생하면 즉시 실행을 중단하고 불변 Saga 감사 로그를 기록합니다."),
        ("services/core-control-plane/src/fdai/core/executor/executor.py", "ShadowExecutor.execute", 1, 80, "2" * 40),
    ),
    _sec_spec(
        "architecture.governed-document-rag-boundary", "Documents.Ingestion.Quarantine.ACL.NoInstructionAuthority", "Document Ingestion API / Muninn / Bragi",
        ("FDAI에 업로드한 문서나 RAG 근거가 보안 문제를 일으키지 않나?", "How does FDAI secure uploaded documents and RAG retrieval against leaks or injection?"),
        ("An operator uploads a document on /documents or queries governed documents in chat.", "Quarantine storage, malware/safety scanning, and principal ACL bindings are active.", ("Scan uploads in quarantine for malware, active HTML/SVG/scripts, and sensitive data before chunking.", "Enforce principal role and group ACL scope on query.governed_documents retrieval.", "Stamp every GovernedDocumentExcerpt with content-addressed SHA-256 digests and instruction_authority=false."), "Authorized excerpts provide cited reference context only and never override system policy or grant execution authority (execution_authority=false).", "Unscoped or unverified uploads never enter the searchable governed document index.", "Cross-principal ACL mismatches or stale document revisions fail closed without leaking excerpt content."),
        ("운영자가 /documents에 문서를 업로드하거나 채팅에서 관리 문서를 조회할 때 시작합니다.", "격리(Quarantine) 저장소, 악성코드·안전성 검사, 주체별 ACL 바인딩이 활성화되어 있어야 합니다.", ("격리 단계에서 악성코드, 활성 HTML·SVG·스크립트, 민감 정보를 검사한 뒤에만 청킹·색인합니다.", "query.governed_documents 조회 시 호출 주체의 역할과 그룹 ACL 범위를 엄격히 필터링합니다.", "모든 발췌본(GovernedDocumentExcerpt)에 SHA-256 콘텐츠 다이제스트와 instruction_authority=false를 부여합니다."), "승인된 문서 발췌본은 출처가 명시된 참고 근거로만 사용되며 시스템 정책을 덮어쓰거나 실행 권한을 부여하지 않습니다(execution_authority=false).", "검역을 통과하지 못했거나 권한 범위가 없는 문서는 검색 인덱스에 노출되지 않습니다.", "권한 불일치나 리비전 불일치 시 발췌 내용을 유출하지 않고 안전하게 조회를 거부합니다."),
        ("services/core-control-plane/src/fdai/core/ontology_platform/governed_document_queries.py", "GovernedDocumentExcerpt", 51, 95, "3" * 40),
    ),
    _sec_spec(
        "architecture.rule-catalog-and-crosswalk-verification", "RuleCatalog.Crosswalk.WARA.WAF.CAF.MCSB.CSAF.SearchRules", "Mimir / Forseti / Operator Service",
        ("FDAI 탐지 규칙과 WARA·WAF·CAF·MCSB·CSAF 매핑은 어떻게 검증되나?", "How does FDAI verify detection rules and framework crosswalk mappings?"),
        ("Catalog snapshots or catalog.search_rules queries are evaluated across /rules.", "Exact ontology release digests and SHA-256 rule/framework catalog commitments are pinned.", ("Validate 52 active T0 Rego rules and 8,517 collected rules against canonical ResourceType and ActionType schemas.", "Cross-reference rules bidirectionally with Azure WARA, WAF, CAF, MCSB v1/v2, and MSRC CSAF 2.0 CVE advisories.", "Return candidate_only receipts with retrieval_receipt_digest and execution_authority=false."), "Operators and agents receive deterministic, citation-pinned rule and framework mappings without unverified inference.", "Collected reference rules never execute as active policy without explicit promotion and dual-principal activation.", "Digest mismatches or unpinned objective bindings degrade atomically to safe read-only fallbacks."),
        ("/rules 화면이나 catalog.search_rules에서 탐지 규칙·프레임워크 매핑을 조회할 때 시작합니다.", "정확한 온톨로지 릴리스 다이제스트와 SHA-256 규칙·프레임워크 카탈로그 해시가 고정되어 있어야 합니다.", ("52개 활성 T0 Rego 규칙과 8,517개 수집 규칙을 정규 ResourceType·ActionType 스키마로 검증합니다.", "탐지 규칙을 Azure WARA, WAF, CAF, MCSB v1/v2, MSRC CSAF 2.0 CVE 권고문과 양방향으로 교차 매핑합니다.", "retrieval_receipt_digest와 execution_authority=false가 포함된 읽기 전용 영수증을 반환합니다."), "운영자와 에이전트는 추측 없이 다이제스트로 검증된 규칙·프레임워크 교차 매핑과 아키텍처 가이드를 참조합니다.", "수집(Collected) 참조 규칙은 별도 승격과 요청자·승인자 교차 서명 없이는 활성 정책으로 실행되지 않습니다.", "다이제스트 불일치나 미검증 목표 바인딩이 감지되면 즉시 안전한 읽기 전용 폴백으로 전환합니다."),
        ("services/core-control-plane/src/fdai/core/ontology_platform/catalog_queries.py", "catalog_search_rules_function_type", 47, 143, "4" * 40),
    ),
    _sec_spec(
        "architecture.operator-transport-and-webhook-security", "Operator.Transport.SSE.WebhookHMAC.SSRF.UploadGuard", "Operator Service",
        ("FDAI 콘솔웹과 백엔드 간 통신이나 SSE 스트리밍, 웹훅에 보안상 문제는 없나?", "How does the Operator Service secure SSE streaming, webhooks, and external evidence against attacks?"),
        ("HTTP requests, SSE streams, webhooks, or image/web evidence reach the Operator Service.", "Strict payload byte caps, HMAC secrets, and SSRF/magic-byte validators are active.", ("Enforce bounded JSON/SSE frames (256 KiB cap), nosniff headers, and Unicode bidi/control-character sanitization.", "Verify HMAC signatures on incoming webhooks and reject loopback, link-local, or cloud IMDS URLs (169.254.169.254) against SSRF.", "Reject polyglot SVG/HTML/script magic bytes on image attachments before narrator resolution."), "Transport and webhook boundaries fail closed against XSS, SSRF, replay, and oversized payload attacks with execution_authority=false.", "Webhook or stream acceptance never bypasses Core semantic verification or action gates.", "Malformed frames, invalid HMACs, or private-network URLs are rejected immediately with audited error codes."),
        ("HTTP 요청, SSE 스트림, 웹훅, 이미지·웹 근거가 Operator Service 경계에 도달할 때 시작합니다.", "엄격한 페이로드 크기 상한, HMAC 서명 검증기, SSRF·매직 바이트 차단기가 활성화되어 있습니다.", ("JSON·SSE 프레임 크기 상한(256 KiB), nosniff 헤더, 유니코드 양방향(bidi)·제어 문자 제거를 강제합니다.", "수신 웹훅의 HMAC 서명을 검증하고 루프백·사설망·클라우드 IMDS(169.254.169.254) URL을 차단해 SSRF를 방어합니다.", "첨부 이미지에서 폴리글랏 SVG·HTML·스크립트 매직 바이트를 사전 차단합니다."), "전송·웹훅 경계는 XSS, SSRF, 재전송, 대용량 페이로드 공격에 대해 안전하게 차단(Fail-closed)하며 실행 권한(execution_authority=false)을 부여하지 않습니다.", "웹훅이나 스트림 수락이 Core의 의미 검증이나 액션 승인 관문을 우회할 수 없습니다.", "비정상 프레임, 유효하지 않은 HMAC, 사설망 URL은 즉시 거부되고 감사 코드로 기록됩니다."),
        ("services/operator-service/src/fdai_operator_service/families/conversation/transport.py", "read_json_body", 31, 80, "5" * 40),
    ),
    _sec_spec(
        "architecture.cors-csp-and-browser-storage-boundary", "Console.Browser.CORS.CSP.SessionStorage.XSS.ActiveContentRejection", "Operator Service / Console SPA",
        ("콘솔 브라우저 스토리지와 CORS·XSS 보안은 어떻게 처리되나요?", "How does the Console protect browser storage, CORS, and XSS boundaries?"),
        ("A browser session loads the Console SPA or renders projected code-security and operational artifacts.", "Explicit CORS origin allowlists, credentials: omit fetch policy, and active-content validators are active.", ("Restrict cross-origin API calls to FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS and omit cookies on chat/stream fetches.", "Reject script tags, data:text/html, meta refresh, and CSS @import at both persistence and Operator projection boundaries."), "Browser storage and rendered views stay free of active HTML/JS injection and cross-origin credential leakage with execution_authority=false.", "Browser-side origin checks do not replace server-side Entra JWT verification.", "Any projected artifact containing active HTML, meta refresh, or CSS @import is withheld fail-closed."),
        ("브라우저 세션이 Console SPA를 로드하거나 프로젝션된 보안·운영 아티팩트를 렌더링할 때 시작합니다.", "명시적 CORS 오리진 허용 목록, credentials: omit 호출 정책, 활성 콘텐츠 차단기가 적용됩니다.", ("교차 출처 API 호출을 FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS 허용 목록으로만 제한하고 채팅·스트림 요청에서 쿠키 전송을 생략합니다.", "스크립트 태그, data:text/html, meta refresh, CSS @import를 저장소와 Operator 프로젝션 양쪽 경계에서 모두 차단합니다."), "브라우저 스토리지와 화면 렌더링은 활성 HTML·JS 인젝션 및 자격 증명 유출로부터 격리되며 실행 권한(execution_authority=false)을 갖지 않습니다.", "브라우저 측 오리진 제한이 서버 측 Entra JWT 검증을 대체하지는 않습니다.", "활성 HTML, meta refresh, CSS @import가 포함된 아티팩트는 즉시 차단(Fail-closed)됩니다."),
        ("services/operator-service/src/fdai_operator_service/code_security_issue_projection.py", "project_code_security_issues", 1, 90, "6" * 40),
    ),
    _sec_spec(
        "architecture.supply-chain-and-dependency-security", "CodeSecurity.SupplyChain.Dependency.DSSE.Ed25519.RevocationGate", "Heimdall / Operator Service",
        ("오픈소스 의존성 취약점과 DSSE 서명 수정 팩은 어떻게 검증하나요?", "How does FDAI verify supply-chain dependency vulnerabilities and DSSE remediation packs?"),
        ("A dependency advisory (CVE/GHSA/OSV) or remediation pack export is evaluated.", "Curated advisory catalogs, CISA KEV flags, and Ed25519 DSSE signing/revocation registries are configured.", ("Ingest dependency findings, separate root-cause severity from KEV/exposure priority, and sign remediation manifests with Ed25519 DSSE.", "Verify RFC 8032 signatures and check the state-store revocation registry before any pack export."), "Supply-chain findings and remediation packs remain verifiable and revocable with execution_authority=false.", "Exporting or importing a remediation pack never produces fixed_verified without an independent rescan.", "Unsigned, tampered, or revoked remediation packs fail closed at the export gate."),
        ("오픈소스 의존성 보안 권고(CVE·GHSA·OSV)나 수정 팩(Remediation Pack) 내보내기가 평가될 때 시작합니다.", "검토된 보안 권고 카탈로그, CISA KEV 악용 여부, Ed25519 DSSE 서명·폐기 레지스트리가 구성되어 있습니다.", ("의존성 취약점을 수집해 근본 심각도와 KEV·노출도 기반 우선순위를 분리하고 수정 매니페스트에 Ed25519 DSSE 서명을 적용합니다.", "팩 내보내기 전 RFC 8032 서명을 검증하고 상태 저장소 폐기(Revocation) 레지스트리를 확인합니다."), "공급망 취약점과 수정 팩은 서명·폐기 검증이 보장되며 직접 실행 권한(execution_authority=false)을 부여하지 않습니다.", "수정 팩을 가져오거나 내보내는 것만으로 독립 재스캔 없이 fixed_verified 판정을 만들지 않습니다.", "미서명·위변조·폐기된 수정 팩은 내보내기 게이트에서 즉시 거부됩니다."),
        ("services/core-control-plane/src/fdai/core/security/code_findings/signing.py", "sign_pack_manifest", 1, 90, "7" * 40),
    ),
    _sec_spec(
        "architecture.audit-chain-and-tamper-evidence", "Saga.AuditChain.SHA256.HeadHashAncestry.TwoPhaseReceipt", "Saga / Operator Service",
        ("감사 로그 위변조 방지와 Saga 해시 체인은 어떻게 동작하나요?", "How does Saga prevent audit log tampering with hash-chained receipts?"),
        ("Every control-loop verdict, drift review, or two-phase execution intent reaches Saga.", "Append-only SHA-256 hash chaining and committed head-hash ancestry verification are active.", ("Chain each audit record to its predecessor SHA-256 digest and persist durable pre-dispatch and terminal receipts.", "Recover canonical audit windows by committed head-hash ancestry rather than sequence-only selection."), "Audit trails are tamper-evident and inspectable on /audit with execution_authority=false.", "Reading or verifying the audit chain never grants replay or mutation authority.", "Detached or hash-mismatched audit records fail integrity verification and trigger explicit alerts."),
        ("모든 제어 루프 판정, 드리프트 리뷰, 2단계 실행 의도가 Saga에 도달할 때 시작합니다.", "추가 전용(Append-only) SHA-256 해시 체인과 커밋된 헤드 해시 계보(Ancestry) 검증이 활성화되어 있습니다.", ("각 감사 레코드를 직전 SHA-256 다이제스트에 연쇄 결합하고 실행 전 의도와 최종 결과 영수증을 영속 기록합니다.", "단순 시퀀스 번호가 아닌 커밋된 헤드 해시 계보를 따라 정본 감사 윈도우를 복원합니다."), "감사 추적은 위변조 탐지가 가능하며 /audit 화면에서 읽기 전용(execution_authority=false)으로 점검할 수 있습니다.", "감사 체인을 조회하거나 검증하는 것은 재실행이나 상태 변경 권한을 부여하지 않습니다.", "분리된 이력이나 해시 불일치 레코드는 무결성 검증에서 즉시 거부됩니다."),
        ("services/core-control-plane/src/fdai/delivery/persistence/postgres_audit_history.py", "recover_canonical_audit_window", 1, 90, "8" * 40),
    ),
    _sec_spec(
        "architecture.secret-isolation-and-key-vault-boundary", "Config.Lifecycle.SecretIsolation.KeyVault.DatabaseRoleSeparation", "Operator Service / Deployment CLI",
        ("시크릿 유출 방지와 Key Vault·데이터베이스 권한 분리는 어떻게 되어 있나요?", "How does FDAI isolate secrets, Key Vault references, and database roles?"),
        ("Lifecycle configuration, deployment plans, or database connections are validated.", "Literal-secret scanners, private Key Vault references, and separated PostgreSQL roles (fdai_operator vs fdai_core) are enforced.", ("Reject literal secrets or tokens in lifecycle configuration, Terraform plans, chat turns, and logs.", "Bind versionless private Key Vault secret references and enforce least-privilege database roles."), "Configuration and persistence layers remain free of literal secrets with execution_authority=false.", "Holding a configuration reference or digest never exposes the underlying secret value.", "Any literal secret candidate or role mismatch is rejected before persistence or deployment."),
        ("수명 주기 설정, 배포 계획, 데이터베이스 연결이 검증될 때 시작합니다.", "리터럴 시크릿 차단기, 비공개 Key Vault 참조, 분리된 PostgreSQL 역할(fdai_operator 및 fdai_core)이 강제됩니다.", ("수명 주기 설정, Terraform 계획, 채팅 턴, 로그에 평문 시크릿이나 토큰이 포함되면 즉시 거부합니다.", "버전 없는 비공개 Key Vault 시크릿 참조만 결합하고 최소 권한 데이터베이스 역할을 강제합니다."), "설정 및 영속 계층은 평문 시크릿을 보유하지 않으며 실행 권한(execution_authority=false)을 부여하지 않습니다.", "설정 참조나 다이제스트를 조회해도 원본 시크릿 값은 절대 노출되지 않습니다.", "평문 시크릿 후보나 데이터베이스 역할 불일치는 저장 및 배포 전에 즉시 차단됩니다."),
        ("packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py", "validate_lifecycle_configuration", 250, 300, "9" * 40),
    ),
    _sec_spec(
        "architecture.ai-model-and-prompt-injection-defense", "Conversation.Adaptive.PromptInjectionDefense.VClaim.IndependentReview", "Bragi / Forseti / Mimir",
        ("LLM 프롬프트 인젝션이나 탈옥(Jailbreak) 공격은 어떻게 방어하나요?", "How does FDAI defend against LLM prompt injection and jailbreak attacks?"),
        ("An operator utterance, prior turn, or attachment enters the semantic or adaptive conversation pipeline.", "Strict system/data separation, schema-constrained model outputs, and independent review/V-CLAIM gates are active.", ("Keep untrusted user prose and attachments in structured data payloads, never in system prompt instructions.", "Validate every model output against strict JSON schemas, deterministic V-CLAIM evidence checks, and an independent AdaptiveReview pass."), "Prompt-injection, fabricated citations, and authority-escalation attempts are blocked with execution_authority=false.", "Model confidence scores or persuasive prose never grant operational or execution authority.", "Unsafe drafts or upstream HTTP 422 content/jailbreak blocks terminate safely without unverified output."),
        ("사용자 발화, 이전 대화 이력, 첨부 데이터가 의미 해석 또는 적응형 대화 파이프라인에 진입할 때 시작합니다.", "엄격한 시스템·데이터 분리, 스키마 제약 모델 출력, 독립 검토(AdaptiveReview)·V-CLAIM 검증 게이트가 활성화되어 있습니다.", ("신뢰할 수 없는 사용자 문장과 첨부 데이터를 시스템 프롬프트 지침과 분리된 구조화 데이터 페이로드로만 전달합니다.", "모든 모델 출력을 엄격한 JSON 스키마, 결정론적 V-CLAIM 근거 대조, 독립 검토(AdaptiveReview) 단계로 검증합니다."), "프롬프트 인젝션, 거짓 인용, 권한 상승 시도는 안전하게 차단되며 실행 권한(execution_authority=false)을 부여하지 않습니다.", "모델의 확신도 점수나 자연어 문장은 어떤 운영·실행 권한도 부여하지 않습니다.", "안전하지 않은 초안이나 업스트림 HTTP 422 콘텐츠·탈옥 필터 차단은 미검증 출력 없이 즉시 안전 종료됩니다."),
        ("services/core-control-plane/src/fdai/core/conversation/adaptive_prompt.py", "compose_adaptive_prompt", 145, 210, "a1" * 20),
    ),
)


class _EmptyBehaviorIndex:
    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResultLike]:
        del query, k
        return ()


def resolve_security_behavior_sync(raw_text: str, *, locale: str = "en", top_k: int = 5) -> BehaviorResolutionResult:
    """Synchronously resolve security and architecture behavior questions over built-in specs."""
    resolver = OperatorBehaviorKnowledgeResolver(_EmptyBehaviorIndex(), seeds=DEFAULT_SECURITY_BEHAVIOR_SPECS)
    loc: Literal["en", "ko"] = "ko" if locale.startswith("ko") else "en"
    req = BehaviorTurnRequest(raw_text=raw_text, locale=loc, top_k=top_k)
    _validate_query_text(req.raw_text)
    effective_k = _validate_top_k(top_k)
    fallback_reason = resolver._check_authority_fallback(req.raw_text)
    if fallback_reason is not None:
        return resolver._fallback_result(req.locale, fallback_reason, False, 0)
    results = list(resolver._search_registered_seeds(req.raw_text, k=effective_k))
    if not results or results[0].score < RETRIEVAL_FLOOR:
        return resolver._fallback_result(req.locale, "below_retrieval_floor", False, 0, len(results))
    top = results[0]
    citations = tuple(BehaviorCitationRecord(s.path, s.symbol, s.line_start, s.line_end, s.blob_sha, top.spec.indexed_commit) for s in top.spec.sources)
    sections, rendered = resolver._renderer.render_single(top.spec, locale=req.locale, citations=citations)
    meta = resolver._verifier.verify(sections=sections, rendered_text=rendered, citations=citations, stale_sources=top.stale_sources, client_evidence_stripped=False, stripped_claim_count=0)
    return BehaviorResolutionResult(True, False, "rendered", None, req.locale, (top.spec.behavior_id,), sections, rendered, meta, total_candidates=len(results))


def grounded_behavior_code_artifacts(raw_text: str, *, locale: str = "en") -> list[dict[str, str]]:
    """Build schema-valid ``code_artifacts`` for a matched security/behavior contract."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return []
    try:
        resolved = resolve_security_behavior_sync(raw_text, locale=locale)
    except Exception:  # noqa: BLE001 - optional artifact grounding must never fail presentation
        return []
    if not resolved.handled or resolved.outcome != "rendered" or not resolved.rendered_text or not resolved.verification.citations:
        return []
    citations = [f"{c.path}:{c.line_start}-{c.line_end}#{c.symbol}" for c in resolved.verification.citations]
    content = resolved.rendered_text[:64_000]
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    behavior_id = resolved.behavior_ids[0] if resolved.behavior_ids else "security.behavior"
    detail = f"{behavior_id} ({', '.join(citations)})"[:4_096]
    return [{"artifact_ref": f"code:sha256:{sha256}", "language": "markdown", "content": content, "sha256": sha256, "validation_status": "valid", "validation_detail": detail}]
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
    "grounded_behavior_code_artifacts",
    "normalize_behavior_tokens",
    "resolve_security_behavior_sync",
]
