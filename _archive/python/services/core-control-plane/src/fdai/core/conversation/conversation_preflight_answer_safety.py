"""Deterministic safety checks for model-authored general-knowledge answers."""

from __future__ import annotations

import re

_LINK_LIKE_TEXT = re.compile(
    r"\b[a-z0-9](?:[a-z0-9-]{0,62})\.[a-z]{2,63}\b",
    re.IGNORECASE,
)
_TECHNICAL_DOTTED_IDENTIFIERS = frozenset({"asp.net", "node.js"})
_SCOPE_NOUN = re.compile(
    r"\b(?:subscriptions?|resource\s+groups?)\b|(?:구독|리소스\s*그룹)",
    re.IGNORECASE,
)
_SCOPE_ASSERTION = re.compile(
    r"\b(?:contains?|has|holds?|stores?|reports?|shows?|includes?|runs?|"
    r"is\s+running|are\s+running|hosts?|manages?)\b|"
    r"(?:있습니다|보유|포함|처리|제공|저장|실행\s*중|호스팅|관리)",
    re.IGNORECASE,
)
_SCOPE_OBJECT = re.compile(
    r"\b(?:resources?|records?|items?|services?)\b|(?:리소스|레코드|항목|서비스)",
    re.IGNORECASE,
)
_FORBIDDEN_OPERATIONAL_CLAIMS = (
    re.compile(
        r"\b(?:i|we|fdai)\s+(?:have\s+)?"
        r"(?:verified|confirmed|observed|checked|queried|measured|executed|restarted|"
        r"deployed|changed|approved)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:your|current|live|production)\s+"
        r"(?:environment|deployment|resource|system|cluster|service|gateway|backend|model|"
        r"api|database|pod|container|workload|application|endpoint|queue|job|vm|server|"
        r"subscription|resource\s+group)s?\s+"
        r"(?:is|are|was|were|has|have|runs?|uses?|shows?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the|your|this|our)\s+"
        r"(?:environment|deployment|resource|system|cluster|service|gateway|backend|model|"
        r"api|database|pod|container|workload|application|endpoint|queue|job|vm|server)s?\s+"
        r"(?:is|are|was|were|has\s+been|have\s+been)\s+"
        r"(?:currently\s+)?"
        r"(?:healthy|unhealthy|running|degraded|available|unavailable|restarted|deployed|"
        r"changed|approved|executed)(?:\s+successfully)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:it|this|that|the\s+(?:environment|deployment|resource|system|cluster|service|"
        r"gateway|backend|model|api|database|pod|container|workload|application|endpoint|"
        r"queue|job|vm|server))"
        r"\s+(?:is|are|was|were|looks?|seems?)\s+"
        r"(?:healthy|unhealthy|running|degraded|available|unavailable|normal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:it|this|that)\s+"
        r"(?:restarted|deployed|changed|approved|executed|scaled|stopped|started)"
        r"(?:\s+successfully)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the|your|our|this)\s+"
        r"(?:environment|deployment|resource|system|cluster|service|gateway|backend|model|"
        r"api|database|pod|container|workload|application|endpoint|queue|job|vm|server)s?"
        r"\s+(?:restarted|deployed|changed|approved|executed|scaled|stopped|started)"
        r"(?:\s+successfully)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the|your|our|this)\s+(?:(?:production|live|current)\s+)?"
        r"(?:environment|deployment|resource|system|cluster|service|gateway|backend|model|"
        r"api|database|pod|container|workload|application|endpoint|queue|job|vm|server|"
        r"subscription|resource\s+group)s?"
        r"\s+(?:currently\s+)?"
        r"(?:contains?|has|holds?|stores?|reports?|shows?|serves?|processes?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:subscription|resource\s+group)s?\s+"
        r"(?:contains?|has|holds?|stores?|reports?|shows?)\s+\d+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the\s+)?(?:[a-z0-9_.-]+\s+){1,6}(?:subscription|resource\s+group)s?\s+"
        r"(?:contains?|has|holds?|stores?|reports?|shows?)\b.{0,48}"
        r"(?:resources?|records?|items?|services?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:subscription|resource\s+group)s?\s+\S{1,64}\s+"
        r"(?:contains?|has|holds?|stores?|reports?|shows?)\s+\d+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:subscription|resource\s+group)s?\s+"
        r"(?:(?!(?:contains?|has|holds?|stores?|reports?|shows?)\b)\S+\s+){1,6}"
        r"(?:contains?|has|holds?|stores?|reports?|shows?)\b.{0,48}"
        r"(?:resources?|records?|items?|services?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?]\s+)(?:please\s+)?"
        r"(?:restart|deploy|change|approve|execute|delete|scale|stop|start)\s+"
        r"(?:the\s+)?(?:current|live|production)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:restart|deploy|change|approve|execute|delete|scale|stop|start)\b"
        r".{0,48}\b(?:production|live)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:our|your|the|this)\s+(?:(?:production|live)\s+)?"
        r"(?:environment|deployment|resource|system|cluster|service|gateway|backend|model|"
        r"api|database|pod|container|workload|application|endpoint|queue|job|vm|server)s?\b"
        r".{0,40}\b(?:currently\s+)?(?:is|are|was|were|runs?|ran)\b"
        r".{0,40}\b(?:production|live|healthy|unhealthy|running|degraded)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:FDAI가|제가|저희가).{0,16}"
        r"(?:확인|검증|관찰|조회|측정|실행|재시작|배포|변경|승인)"
        r"(?:했|하였|했습니다|완료)",
    ),
    re.compile(
        r"(?:현재|실제|운영|프로덕션)\s*"
        r"(?:환경|배포|리소스|시스템|클러스터|서비스|게이트웨이|백엔드|모델|API|"
        r"데이터베이스|파드|컨테이너|워크로드|애플리케이션|엔드포인트|큐|작업|VM|서버)"
        r"(?:은|는|이|가).{0,24}"
        r"(?:정상|비정상|건강|실행 중|배포되|확인되|관찰되|측정되)",
    ),
    re.compile(
        r"(?:현재|실제|운영|프로덕션).{0,24}"
        r"(?:재시작|배포|변경|승인|실행|삭제|확장|중지|시작)"
        r"(?:하세요|하십시오|해 주세요|했습니다|됐|되었습니다)",
    ),
    re.compile(
        r"(?:환경|배포|리소스|시스템|클러스터|서비스|게이트웨이|백엔드|모델|API|"
        r"데이터베이스|파드|컨테이너|워크로드|애플리케이션|엔드포인트|큐|작업|VM|서버)"
        r"(?:은|는|이|가)\s*(?:현재\s*)?"
        r"(?:(?:정상|비정상|건강함|실행 중|사용 가능)(?:입니다|이에요)|"
        r"(?:재시작|배포|변경|승인|실행)(?:됐습니다|되었습니다|했습니다))",
    ),
    re.compile(
        r"(?:환경|배포|리소스|시스템|클러스터|서비스|게이트웨이|백엔드|모델|API|"
        r"데이터베이스|파드|컨테이너|워크로드|애플리케이션|엔드포인트|큐|작업|VM|서버)"
        r"(?:은|는|이|가).{0,32}"
        r"(?:운영\s*환경|프로덕션).{0,24}"
        r"(?:정상|비정상|건강|실행 중|재시작|배포|변경|승인|실행)",
    ),
    re.compile(
        r"(?:프로덕션|운영\s*환경)(?:은|는|이|가).{0,16}"
        r"(?:정상|비정상|건강|실행 중|재시작|배포|변경|승인|실행)",
    ),
    re.compile(
        r"(?:현재|실제|프로덕션|운영\s*환경|해당).{0,32}"
        r"(?:환경|배포|리소스|시스템|클러스터|서비스|게이트웨이|백엔드|모델|API|"
        r"데이터베이스|파드|컨테이너|워크로드|애플리케이션|엔드포인트|큐|작업|VM|서버|"
        r"구독|리소스\s*그룹)"
        r".{0,32}(?:있습니다|보유|포함|처리|제공|저장)",
    ),
    re.compile(
        r"(?:구독|리소스\s*그룹)(?:에는|은|는|이|가).{0,24}\d+개.{0,16}"
        r"(?:있습니다|보유|포함|처리|제공|저장)",
    ),
    re.compile(
        r"(?:구독|리소스\s*그룹)\s+\S{1,64}(?:에는|은|는|이|가).{0,24}\d+개"
        r".{0,16}(?:있습니다|보유|포함|처리|제공|저장)",
    ),
    re.compile(
        r"(?:구독|리소스\s*그룹)\s+\S+(?:\s+\S+){0,5}(?:에는|은|는|이|가)"
        r".{0,32}(?:리소스|레코드|항목|서비스).{0,20}"
        r"(?:있습니다|보유|포함|처리|제공|저장)",
    ),
    re.compile(
        r"\S+(?:\s+\S+){0,5}\s+(?:구독|리소스\s*그룹)(?:에는|은|는|이|가)"
        r".{0,32}(?:리소스|레코드|항목|서비스).{0,20}"
        r"(?:있습니다|보유|포함|처리|제공|저장)",
    ),
)


def general_answer_contains_link(answer: str) -> bool:
    """Return whether an answer contains a non-technical link or domain."""

    if "://" in answer or re.search(r"\[[^\]]+\]\([^)]+\)", answer):
        return True
    for match in _LINK_LIKE_TEXT.finditer(answer):
        token = match.group(0).casefold()
        quoted = (
            match.start() > 0
            and match.end() < len(answer)
            and answer[match.start() - 1] == "`"
            and answer[match.end()] == "`"
        )
        if token not in _TECHNICAL_DOTTED_IDENTIFIERS and not quoted:
            return True
    return False


def general_answer_contains_operational_claim(answer: str) -> bool:
    """Return whether a general answer claims current operational evidence."""

    clauses = re.split(r"(?:[!?。！？;]+|\.(?=\s|$))", answer)
    scope_assertion = any(
        _SCOPE_NOUN.search(clause)
        and _SCOPE_ASSERTION.search(clause)
        and _SCOPE_OBJECT.search(clause)
        for clause in clauses
    )
    return scope_assertion or any(
        pattern.search(answer) for pattern in _FORBIDDEN_OPERATIONAL_CLAIMS
    )


__all__ = ["general_answer_contains_link", "general_answer_contains_operational_claim"]
