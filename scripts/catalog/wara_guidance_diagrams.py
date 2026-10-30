"""Repository-authored conceptual graphs, not screenshots or environment observations."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from wara_guidance_edges_ko import EDGES_KO
from wara_guidance_graphs import GRAPHS
from wara_guidance_labels_ko import LABELS_KO
from wara_guidance_reliability import localized

# Node tuples: id, English label, Korean label, role. Edges describe architecture,
# state transitions or evidence supply, never a rule-to-check-to-pass pipeline.
BLUEPRINTS: dict[str, tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str, str]]]] = {
    "zone-redundancy": (
        [
            ("workload", "Workload path", "워크로드 경로", "subject"),
            ("setting", "Zone configuration", "영역 구성", "configuration"),
            ("first", "Failure domain A", "장애 범위 A", "dependency"),
            ("second", "Failure domain B", "장애 범위 B", "dependency"),
            ("state", "State and capacity", "데이터와 용량", "dependency"),
            ("evidence", "Placement observations", "배치 확인 결과", "evidence"),
        ],
        [
            ("workload", "setting", "uses", "solid"),
            ("setting", "first", "supported placement", "solid"),
            ("setting", "second", "supported placement", "solid"),
            ("workload", "state", "also requires", "solid"),
            ("evidence", "setting", "observes effective zones", "dashed"),
            ("evidence", "state", "checks surviving capacity", "dashed"),
        ],
    ),
    "regional-failover": (
        [
            ("workload", "Clients", "클라이언트", "subject"),
            ("setting", "Routing policy", "라우팅 정책", "configuration"),
            ("first", "Primary region", "주 지역", "dependency"),
            ("second", "Secondary region", "보조 지역", "dependency"),
            ("state", "Regional state strategy", "지역 데이터 전략", "configuration"),
            ("evidence", "Readiness observations", "준비 상태 확인", "evidence"),
        ],
        [
            ("workload", "setting", "requests", "solid"),
            ("setting", "first", "primary route", "solid"),
            ("setting", "second", "eligible alternate", "dashed"),
            ("first", "state", "state dependency", "solid"),
            ("second", "state", "recovery dependency", "solid"),
            ("evidence", "setting", "route and health evidence", "dashed"),
            ("evidence", "second", "capacity and dependency evidence", "dashed"),
        ],
    ),
    "replication": (
        [
            ("workload", "Workload", "워크로드", "subject"),
            ("setting", "Replica topology", "복제본 구조", "configuration"),
            ("first", "Serving or source copy", "처리 또는 원본 사본", "dependency"),
            ("second", "Additional copy", "추가 사본", "dependency"),
            ("evidence", "Readiness and lag", "준비 상태와 지연", "evidence"),
        ],
        [
            ("workload", "setting", "selects topology", "solid"),
            ("setting", "first", "assigns source", "solid"),
            ("setting", "second", "assigns additional copy", "solid"),
            ("first", "second", "sync or workload distribution", "dashed"),
            ("evidence", "second", "observes readiness and independence", "dashed"),
        ],
    ),
    "backup-restore": (
        [
            ("workload", "Protected object", "보호 대상", "subject"),
            ("setting", "Protection policy", "보호 정책", "configuration"),
            ("copy", "Retained recovery point", "보존된 복구 지점", "dependency"),
            ("target", "Isolated restore target", "격리된 복원 대상", "outcome"),
            ("evidence", "Restore observations", "복원 확인 결과", "evidence"),
        ],
        [
            ("setting", "workload", "protects selected state", "solid"),
            ("workload", "copy", "supported capture", "solid"),
            ("copy", "target", "authorized restore", "dashed"),
            ("evidence", "copy", "checks freshness and consistency", "dashed"),
            ("evidence", "target", "validates application state", "dashed"),
        ],
    ),
    "recovery-exercise": (
        [
            ("workload", "Recovery source", "복구 원본", "subject"),
            ("setting", "Point and target selection", "시점과 대상 선택", "configuration"),
            ("target", "Isolated recovered workload", "격리된 복구 워크로드", "outcome"),
            ("dependencies", "Target dependencies", "대상 의존 리소스", "dependency"),
            ("evidence", "Time and integrity results", "시간과 무결성 결과", "evidence"),
        ],
        [
            ("workload", "setting", "available recovery state", "solid"),
            ("setting", "target", "authorized exercise", "dashed"),
            ("target", "dependencies", "requires", "solid"),
            ("evidence", "target", "observes function and timing", "dashed"),
            ("evidence", "dependencies", "checks reachability", "dashed"),
        ],
    ),
    "retention": (
        [
            ("workload", "Live object or version", "현재 개체 또는 버전", "subject"),
            ("setting", "Retention and purge policy", "보존 및 제거 정책", "configuration"),
            ("retained", "Recoverable retained state", "복구 가능한 보존 상태", "dependency"),
            ("expired", "Expiry or permanent removal", "만료 또는 영구 제거", "outcome"),
            ("evidence", "Recovery-window evidence", "복구 기간 확인", "evidence"),
        ],
        [
            ("setting", "retained", "defines protection window", "solid"),
            ("workload", "retained", "delete or overwrite", "solid"),
            ("retained", "workload", "authorized recovery", "dashed"),
            ("retained", "expired", "documented expiry rules", "solid"),
            ("evidence", "retained", "checks effective protection", "dashed"),
        ],
    ),
    "monitoring": (
        [
            ("workload", "Observed resource or flow", "관찰 리소스 또는 흐름", "subject"),
            ("signal", "Metric or health event", "메트릭 또는 상태 이벤트", "dependency"),
            ("setting", "Alert condition and scope", "경고 조건과 범위", "configuration"),
            ("owner", "Response destination", "대응 수신 대상", "outcome"),
            ("evidence", "Samples and delivery receipt", "표본과 전달 기록", "evidence"),
        ],
        [
            ("workload", "signal", "emits", "solid"),
            ("signal", "setting", "evaluated in window", "solid"),
            ("setting", "owner", "notifies on condition", "solid"),
            ("evidence", "signal", "checks recent collection", "dashed"),
            ("evidence", "owner", "confirms test delivery", "dashed"),
        ],
    ),
    "private-network": (
        [
            ("workload", "Client network", "클라이언트 네트워크", "subject"),
            ("dns", "Private DNS path", "프라이빗 DNS 경로", "dependency"),
            ("setting", "Approved private connection", "승인된 프라이빗 연결", "configuration"),
            ("service", "Authorized service", "접근 권한이 있는 서비스", "outcome"),
            ("evidence", "DNS and request observations", "DNS와 요청 확인", "evidence"),
        ],
        [
            ("workload", "dns", "resolves service", "solid"),
            ("dns", "setting", "returns private path", "solid"),
            ("workload", "setting", "connects over allowed network", "solid"),
            ("setting", "service", "service-specific access", "solid"),
            ("evidence", "dns", "checks each client network", "dashed"),
            ("evidence", "service", "verifies data-plane access", "dashed"),
        ],
    ),
    "dns-resolution": (
        [
            ("workload", "Required client networks", "필수 클라이언트 네트워크", "subject"),
            ("first", "Resolver path A", "확인자 경로 A", "dependency"),
            ("second", "Resolver path B", "확인자 경로 B", "dependency"),
            ("setting", "Zone records and links", "영역 레코드와 링크", "configuration"),
            ("target", "Returned target address", "반환된 대상 주소", "outcome"),
            ("evidence", "Query and reachability results", "조회와 접근 결과", "evidence"),
        ],
        [
            ("workload", "first", "DNS query", "solid"),
            ("workload", "second", "independent supported path", "dashed"),
            ("first", "setting", "resolves records", "solid"),
            ("second", "setting", "resolves records", "solid"),
            ("setting", "target", "answer, not health proof", "solid"),
            ("evidence", "target", "checks backend separately", "dashed"),
        ],
    ),
    "network-redundancy": (
        [
            ("workload", "Source network", "원본 네트워크", "subject"),
            ("first", "Independent edge path A", "독립 경계 경로 A", "dependency"),
            ("second", "Independent edge path B", "독립 경계 경로 B", "dependency"),
            ("setting", "Sessions and route policy", "세션과 경로 정책", "configuration"),
            ("target", "Destination network", "대상 네트워크", "outcome"),
            ("evidence", "Path and convergence evidence", "경로와 수렴 확인", "evidence"),
        ],
        [
            ("workload", "first", "path A", "solid"),
            ("workload", "second", "path B", "solid"),
            ("first", "target", "forwards", "solid"),
            ("second", "target", "forwards", "solid"),
            ("setting", "first", "controls session", "dashed"),
            ("setting", "second", "controls session", "dashed"),
            ("evidence", "target", "checks traffic after path loss", "dashed"),
        ],
    ),
}

# These are intentionally different architecture/state families. Related controls
# share a shape while their exact setting and observation remain GUID-authored.
SHAPE_GROUPS = {
    "health-probe": (
        "Backend or resource state",
        "백엔드 또는 리소스 상태",
        "Probe or state semantics",
        "프로브 또는 상태 의미",
        "Health-aware consumer",
        "상태 신호 소비자",
    ),
    "capacity": (
        "Demand",
        "수요",
        "Effective capacity limit",
        "유효 용량 한도",
        "Usable headroom",
        "가용 여유 용량",
    ),
    "autoscale": (
        "Demand signal",
        "수요 신호",
        "Bounds and cooldown",
        "범위와 대기 시간",
        "Serving capacity",
        "처리 용량",
    ),
    "eligibility": (
        "Required capability",
        "필요 기능",
        "SKU support matrix",
        "SKU 지원 표",
        "Compatible deployment",
        "호환 배포",
    ),
    "patch-workflow": (
        "Eligible target",
        "지원 대상",
        "Scope and assigned window",
        "범위와 할당 시간대",
        "Updated workload",
        "업데이트된 워크로드",
    ),
    "event-drain": (
        "Infrastructure event",
        "인프라 이벤트",
        "Guest event handler",
        "게스트 이벤트 처리기",
        "Prepared workload",
        "준비된 워크로드",
    ),
    "supported-migration": (
        "Current version",
        "현재 버전",
        "Supported migration path",
        "지원 이전 경로",
        "Validated target version",
        "검증된 대상 버전",
    ),
    "staged-deployment": (
        "Versioned desired state",
        "버전 관리 상태",
        "Candidate and cutover policy",
        "후보와 전환 정책",
        "Serving replacement",
        "처리 대체 대상",
    ),
    "bounded-recovery": (
        "Health condition",
        "상태 조건",
        "Bounded repair policy",
        "제한된 복구 정책",
        "Recovered instance",
        "복구된 인스턴스",
    ),
    "bounded-retry": (
        "Transient request failure",
        "일시적 요청 오류",
        "Backoff and attempt budget",
        "지연과 시도 제한",
        "Result or terminal failure",
        "결과 또는 최종 실패",
    ),
    "connection-drain": (
        "Serving backend",
        "처리 중인 백엔드",
        "Drain or disruption policy",
        "정리 또는 중단 정책",
        "Completed in-flight work",
        "기존 작업 완료",
    ),
    "cache": (
        "API request",
        "API 요청",
        "Cache key and expiry",
        "캐시 키와 만료",
        "Valid cached response",
        "유효한 캐시 응답",
    ),
    "log-delivery": (
        "Service event",
        "서비스 이벤트",
        "Categories and destination",
        "범주와 대상",
        "Retained log records",
        "보존 로그 기록",
    ),
    "dns-cache": (
        "Authoritative record",
        "권한 있는 레코드",
        "TTL and cache policy",
        "TTL과 캐시 정책",
        "Client address selection",
        "클라이언트 주소 선택",
    ),
    "network-path": (
        "Source traffic",
        "원본 트래픽",
        "Effective path or route",
        "실제 경로나 라우팅",
        "Reachable destination",
        "접근 가능한 대상",
    ),
    "network-capacity": (
        "Peak network demand",
        "최대 네트워크 수요",
        "Address, port or link budget",
        "주소, 포트 또는 링크 용량",
        "Accepted connections",
        "수락된 연결",
    ),
    "identity-boundary": (
        "Access principal",
        "접근 주체",
        "Authentication policy",
        "인증 정책",
        "Intended authorized access",
        "의도한 승인 접근",
    ),
    "security-boundary": (
        "Incoming operation",
        "수신 작업",
        "Effective protection rules",
        "실제 보호 규칙",
        "Allowed or denied operation",
        "허용 또는 거부 작업",
    ),
    "key-lifecycle": (
        "Protected data or TLS leg",
        "보호 데이터 또는 TLS 구간",
        "Key or protocol policy",
        "키 또는 프로토콜 정책",
        "Compatible protected access",
        "호환 보호 접근",
    ),
    "storage-dependencies": (
        "Persistent or temporary state",
        "영속 또는 임시 상태",
        "Supported storage layout",
        "지원 저장소 배치",
        "Accessible workload state",
        "접근 가능한 업무 상태",
    ),
    "isolation-boundary": (
        "Workload ownership",
        "워크로드 소유권",
        "Placement and separation",
        "배치와 분리",
        "Isolated lifecycle or capacity",
        "격리된 수명 주기 또는 용량",
    ),
    "configuration-contract": (
        "Deployed artifact",
        "배포 아티팩트",
        "Effective scoped setting",
        "실제 범위별 설정",
        "Expected runtime behavior",
        "예상 런타임 동작",
    ),
    "durable-workflow": (
        "Input or task state",
        "입력 또는 작업 상태",
        "Checkpoint and replay policy",
        "체크포인트와 재실행 정책",
        "Reconciled outputs",
        "조정된 출력",
    ),
    "data-lineage": (
        "Source dataset",
        "원본 데이터셋",
        "Quality and ownership boundary",
        "품질과 소유권 경계",
        "Accepted or quarantined data",
        "수용 또는 격리 데이터",
    ),
    "data-export": (
        "Selected source tables",
        "선택한 원본 테이블",
        "Export rule and redundancy",
        "내보내기 규칙과 중복",
        "Independent exported records",
        "독립 내보내기 기록",
    ),
    "recovery-objectives": (
        "Business impact",
        "업무 영향",
        "Approved SLO, RTO and RPO",
        "승인된 SLO, RTO와 RPO",
        "Measurable recovery budget",
        "측정 가능한 복구 예산",
    ),
    "critical-flows": (
        "Business outcomes",
        "업무 결과",
        "Criticality and flow map",
        "중요도와 흐름 지도",
        "Prioritized recovery flows",
        "우선 복구 흐름",
    ),
    "data-partition": (
        "Data and access patterns",
        "데이터와 접근 패턴",
        "Partition-key strategy",
        "분할 키 전략",
        "Distributed partition load",
        "분산된 분할 부하",
    ),
    "failure-modes": (
        "Critical dependency graph",
        "중요 의존성 그래프",
        "Fault and impact analysis",
        "결함과 영향 분석",
        "Prioritized mitigations",
        "우선 완화 대책",
    ),
    "model-throughput": (
        "Token and concurrency demand",
        "토큰과 동시 수요",
        "Model and provisioned units",
        "모델과 프로비저닝 단위",
        "Measured serving capacity",
        "측정된 처리 용량",
    ),
    "model-routing": (
        "Model requests",
        "모델 요청",
        "Global Standard deployment",
        "Global Standard 배포",
        "Service-managed placement",
        "서비스 관리 배치",
    ),
    "model-overflow": (
        "Provisioned request path",
        "프로비저닝 요청 경로",
        "Explicit overflow policy",
        "명시적 초과 처리 정책",
        "Eligible PAYG deployment",
        "적격 종량제 배포",
    ),
    "model-batch": (
        "Asynchronous request set",
        "비동기 요청 집합",
        "Supported batch deployment",
        "지원 일괄 배포",
        "Reconciled batch results",
        "조정된 일괄 결과",
    ),
    "model-geography": (
        "Data-handling requirements",
        "데이터 처리 요구",
        "Data Zone deployment type",
        "Data Zone 배포 유형",
        "Policy-reviewed model path",
        "정책 검토 모델 경로",
    ),
    "recovery-plan": (
        "Critical workload flow",
        "중요 업무 흐름",
        "Ordered recovery runbook",
        "순서가 있는 복구 지침",
        "Recovered business flow",
        "복구된 업무 흐름",
    ),
}

EDGE_LABELS = {
    "uses": "사용",
    "supported placement": "지원 배치",
    "also requires": "별도 필요",
    "observes effective zones": "실제 영역 확인",
    "checks surviving capacity": "잔여 용량 확인",
    "requests": "요청",
    "primary route": "주 경로",
    "eligible alternate": "적격 대체 경로",
    "state dependency": "데이터 의존성",
    "recovery dependency": "복구 의존성",
    "route and health evidence": "경로와 상태 근거",
    "capacity and dependency evidence": "용량과 의존성 근거",
}


def _node_detail(
    node_id: str,
    labels: dict[str, dict[str, str]],
    edges: list[tuple[str, str, str, str]],
) -> dict[str, str]:
    outgoing = [(target, relation) for source, target, relation, _ in edges if source == node_id]
    connections = outgoing or [
        (source, relation) for source, target, relation, _ in edges if target == node_id
    ]
    if not connections:
        raise ValueError(f"WARA diagram node has no authored relationship: {node_id}")
    relations = [
        (
            labels[neighbor],
            localized(relation, EDGE_LABELS.get(relation) or EDGES_KO.get(relation)),
        )
        for neighbor, relation in connections
    ]
    english = ", ".join(f"{label['en']} ({relation['en']})" for label, relation in relations)
    korean = (
        ", ".join(f"{label['ko']} ({relation['ko']})" for label, relation in relations)
        if all(label.get("ko") and relation.get("ko") for label, relation in relations)
        else None
    )
    return localized(
        f"{'Connects to' if outgoing else 'Connected from'}: {english}.",
        f"{'연결 대상' if outgoing else '연결 출발점'}: {korean}." if korean else None,
    )


def build_diagram(
    focus: str,
    observation: str,
    shape: str,
    description: dict[str, str],
    *,
    focus_ko: str | None = None,
    observation_ko: str | None = None,
) -> dict[str, Any]:
    nodes, edges = (BLUEPRINTS | GRAPHS)[shape]
    label_translations = {
        group[index]: group[index + 1] for group in SHAPE_GROUPS.values() for index in (0, 2, 4)
    }
    labels = {
        node_id: (
            localized(focus, focus_ko)
            if node_id == "setting"
            else localized(en, ko or label_translations.get(en) or LABELS_KO.get(en))
        )
        for node_id, en, ko, _ in nodes
    }
    return {
        "id": shape,
        "kind": shape,
        "title": localized(
            f"{focus}: configuration concept",
            f"{focus_ko}: 구성 개념" if focus_ko else None,
        ),
        "description": description,
        "nodes": [
            {
                "id": node_id,
                "label": labels[node_id],
                "detail": localized(observation, observation_ko)
                if node_id == "evidence"
                else _node_detail(node_id, labels, edges),
                "role": role,
            }
            for node_id, en, ko, role in nodes
        ],
        "edges": [
            {
                "from": a,
                "to": b,
                "label": localized(label, EDGE_LABELS.get(label) or EDGES_KO.get(label)),
                "style": style,
            }
            for a, b, label, style in edges
        ],
    }
