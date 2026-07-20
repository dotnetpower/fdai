"""Twenty-question, ten-rubric architecture behavior quality gate."""

# Frozen natural-language evaluation cases intentionally remain one record per line.
# ruff: noqa: E501

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fdai.delivery.read_api.routes.chat_behavior_evidence import (
    RepositoryBehaviorEvidenceResolver,
    render_behavior_answer,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIN_AVERAGE_SCORE = 9.5
_HANGUL = re.compile(r"[가-힣]")
_CITATION_FIELDS = {"path", "symbol", "line_start", "line_end", "blob_sha"}
_KO_HEADINGS = (
    "핵심 답변",
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


@dataclass(frozen=True, slots=True)
class ArchitectureCase:
    question: str
    behavior_id: str
    status: str
    essential: str


CASES = (
    ArchitectureCase(
        "규칙이 매칭되는 이벤트는 어느 tier로 보내?",
        "architecture.trust-tier-routing",
        "implemented",
        "T0",
    ),
    ArchitectureCase(
        "resource_type을 찾지 못한 이벤트를 router가 추측해?",
        "architecture.trust-tier-routing",
        "implemented",
        "abstain",
    ),
    ArchitectureCase(
        "근거 citation이 없는 T2 proposal은 다음 단계로 갈 수 있어?",
        "architecture.t2-quality-gate",
        "implemented",
        "grounding 부재",
    ),
    ArchitectureCase(
        "cross-check quorum이 깨지면 decision은 뭐가 돼?",
        "architecture.t2-quality-gate",
        "implemented",
        "disagree",
    ),
    ArchitectureCase(
        "initiator와 approver가 같아도 승인 완료돼?",
        "architecture.human-approval-separation",
        "implemented",
        "자기 승인",
    ),
    ArchitectureCase(
        "HIL ticket은 어떤 경우에 최종 approved가 돼?",
        "architecture.human-approval-separation",
        "implemented",
        "quorum",
    ),
    ArchitectureCase(
        "accuracy와 sample이 기준을 넘으면 action mode가 어떻게 바뀌어?",
        "architecture.shadow-promotion",
        "implemented",
        "모든 gate",
    ),
    ArchitectureCase(
        "policy escape가 생긴 promoted action은 계속 enforce야?",
        "architecture.shadow-promotion",
        "implemented",
        "자동 강등",
    ),
    ArchitectureCase(
        "blast radius가 cap을 넘는 action도 PR을 발행해?",
        "architecture.executor-safety",
        "implemented",
        "blast-radius",
    ),
    ArchitectureCase(
        "idempotency key가 같은 요청이 경쟁하면 몇 번 publish해?",
        "architecture.executor-safety",
        "implemented",
        "두 번째 PR",
    ),
    ArchitectureCase(
        "브라우저 principal이 Thor 권한으로 Azure를 호출하나?",
        "architecture.console-identity-boundary",
        "configured",
        "서로 다른 boundary",
    ),
    ArchitectureCase(
        "승인 버튼이 곧바로 substrate mutation을 실행해?",
        "architecture.console-identity-boundary",
        "configured",
        "직접 실행하지 않습니다",
    ),
    ArchitectureCase(
        "같은 idempotency_key가 최근 cache에 있으면 ingest 결과는?",
        "architecture.event-ingest-dedup",
        "implemented",
        "None을 반환",
    ),
    ArchitectureCase(
        "FIFO에서 빠진 오래된 event key가 다시 오면 어떻게 돼?",
        "architecture.event-ingest-dedup",
        "implemented",
        "다시 통과",
    ),
    ArchitectureCase(
        "failed action-run을 받은 Vidar는 어떤 contract를 사용해?",
        "architecture.vidar-rollback",
        "implemented",
        "rollback contract",
    ),
    ArchitectureCase(
        "rollback executor가 receipt를 안 주면 성공으로 기록해?",
        "architecture.vidar-rollback",
        "implemented",
        "receipt 부재",
    ),
    ArchitectureCase(
        "채팅에서 운영 명령을 말하면 Bragi가 executor를 호출하나?",
        "architecture.bragi-translator",
        "implemented",
        "직접 호출하지 않습니다",
    ),
    ArchitectureCase(
        "Bragi가 모르는 domain 질문은 owner를 추측해?",
        "architecture.bragi-translator",
        "implemented",
        "날조하지 않고",
    ),
    ArchitectureCase(
        "Azure provider가 미구성인 local panel은 샘플 Incident를 만들어?",
        "architecture.local-evidence-parity",
        "configured",
        "unavailable",
    ),
    ArchitectureCase(
        "pytest fixture가 interactive local의 audit evidence로 표시될 수 있어?",
        "architecture.local-evidence-parity",
        "configured",
        "test fixture",
    ),
)


def _git(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("git executable is unavailable")
    return subprocess.run(  # noqa: S603 - fixed executable, no shell
        (executable, *args),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _citations_are_current(citations: list[dict[str, Any]]) -> bool:
    return bool(citations) and all(
        set(citation) == _CITATION_FIELDS
        and _git("hash-object", "--", str(citation["path"])) == citation["blob_sha"]
        for citation in citations
    )


def _citations_are_precise(citations: list[dict[str, Any]]) -> bool:
    for citation in citations:
        path = REPO_ROOT / str(citation["path"])
        lines = path.read_text(encoding="utf-8").splitlines()
        start = int(citation["line_start"])
        end = int(citation["line_end"])
        if not 1 <= start <= end <= len(lines):
            return False
        fragment = "\n".join(lines[start - 1 : end])
        if str(citation["symbol"]).rsplit(".", 1)[-1] not in fragment:
            return False
    return True


def _direct_answer_matches_focus(evidence: dict[str, Any], answer: str) -> bool:
    localized = evidence.get("localized", {}).get("ko", {})
    focus_field = {
        "exclusions": "exclusions",
        "process": "processing_steps",
        "safety": "safety_and_fallback",
        "trigger": "trigger",
        "why": "outcomes",
    }.get(evidence.get("answer_focus"), "outcomes")
    values = localized.get(focus_field, [])
    lead = answer.split("\n\n", 1)[0]
    return bool(values) and str(values[0]) in lead and len(answer) <= 1_500


async def test_twenty_architecture_questions_average_at_least_9_5() -> None:
    resolver = RepositoryBehaviorEvidenceResolver(REPO_ROOT)
    scores: list[int] = []

    for case in CASES:
        raw = await resolver.resolve(case.question)
        assert raw is not None
        evidence = dict(raw)
        answer = render_behavior_answer(evidence, locale="ko")
        citations = [dict(item) for item in evidence.get("citations", [])]
        rubric = (
            evidence.get("behavior_id") == case.behavior_id,
            evidence.get("status") == "matched",
            _citations_are_current(citations),
            _citations_are_precise(citations),
            evidence.get("implementation_status") == case.status
            and bool(evidence.get("owner"))
            and evidence.get("grants_action_authority") is False,
            all(f"**{heading}**" in answer for heading in _KO_HEADINGS),
            case.essential in answer,
            bool(evidence.get("exclusions")) and bool(evidence.get("safety_and_fallback")),
            len(_HANGUL.findall(answer)) >= 80 and "def " not in answer and "class " not in answer,
            _direct_answer_matches_focus(evidence, answer),
        )
        scores.append(sum(rubric))

    average = sum(scores) / len(scores)
    assert average >= MIN_AVERAGE_SCORE, {
        "average": average,
        "minimum": MIN_AVERAGE_SCORE,
        "scores": scores,
    }
