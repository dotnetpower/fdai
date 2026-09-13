import { copy, FAMILY_COLORS, type Agent, type AgentId } from "./model";

/** Curated visual positions and capability labels, not runtime bindings or a call graph. */
export const agents = [
  { id: "Huginn", family: "observe", position: [-21, 3, 1], role: copy("Event collector", "이벤트 수집"),
    capabilities: [copy("Event intake", "이벤트 수신"), copy("Deduplication", "중복 제거"), copy("Change intake", "변경 수신")] },
  { id: "Heimdall", family: "observe", position: [-13, 11, 4], role: copy("Independent observer", "독립 관측"),
    capabilities: [copy("Signal observation", "신호 관측"), copy("Drift detection", "드리프트 탐지"), copy("Effect observation", "효과 관측")] },
  { id: "Forseti", family: "reason", position: [-3, 5, 10], role: copy("Evidence-grounded judge", "근거 기반 판정"),
    capabilities: [copy("Rule evaluation", "규칙 평가"), copy("Safety judgment", "안전성 판정"), copy("Evidence review", "근거 검토")] },
  { id: "Odin", family: "reason", position: [0, 16, -1], role: copy("Portfolio arbitration", "포트폴리오 중재"),
    capabilities: [copy("Priority arbitration", "우선순위 중재"), copy("Policy context", "정책 맥락"), copy("Portfolio outcomes", "포트폴리오 결과")] },
  { id: "Var", family: "act", position: [10, 10, 4], role: copy("Human approval channel", "사람 승인 채널"),
    capabilities: [copy("Approval request", "승인 요청"), copy("Human decision", "사람의 결정"), copy("Approval record", "승인 기록")] },
  { id: "Thor", family: "act", position: [20, 2, 2], role: copy("Sole privileged executor", "유일한 권한 실행자"),
    capabilities: [copy("Safety preflight", "실행 전 안전 검사"), copy("Action dispatch", "액션 전달"), copy("Run receipt", "실행 접수 기록")] },
  { id: "Vidar", family: "act", position: [16, -9, -1], role: copy("Recovery coordinator", "복구 조정"),
    capabilities: [copy("Recovery readiness", "복구 준비"), copy("Rollback request", "롤백 요청"), copy("Recovery tracking", "복구 추적")] },
  { id: "Saga", family: "remember", position: [5, -14, 5], role: copy("Independent audit", "독립 감사"),
    capabilities: [copy("Audit intent", "감사 의도 기록"), copy("Outcome record", "결과 기록"), copy("Evidence trail", "근거 이력")] },
  { id: "Bragi", family: "reason", position: [-20, -8, 2], role: copy("Language interface", "자연어 인터페이스"),
    capabilities: [copy("Typed intent", "타입화된 의도"), copy("Tool translation", "도구 요청 변환"), copy("Explanation", "설명")] },
  { id: "Mimir", family: "remember", position: [-8, -13, -2], role: copy("Rule lifecycle", "규칙 수명 주기"),
    capabilities: [copy("Rule knowledge", "규칙 지식"), copy("Rule lifecycle", "규칙 수명 주기"), copy("Catalog context", "카탈로그 맥락")] },
  { id: "Muninn", family: "remember", position: [-12, 0, -12], role: copy("State and context memory", "상태와 맥락 기억"),
    capabilities: [copy("State snapshots", "상태 스냅샷"), copy("Context index", "맥락 인덱스"), copy("Case history", "사례 이력")] },
  { id: "Norns", family: "remember", position: [3, -3, -13], role: copy("Governed pattern learning", "통제된 패턴 학습"),
    capabilities: [copy("Recurring patterns", "반복 패턴"), copy("Inert rule candidates", "비활성 규칙 후보"), copy("Learning evidence", "학습 근거")] },
  { id: "Njord", family: "observe", position: [-4, 12, -13], role: copy("Cost governance", "비용 거버넌스"),
    capabilities: [copy("Cost signals", "비용 신호"), copy("Cost anomalies", "비용 이상"), copy("Cost context", "비용 맥락")] },
  { id: "Freyr", family: "observe", position: [12, 9, -10], role: copy("Capacity intelligence", "용량 분석"),
    capabilities: [copy("Capacity signals", "용량 신호"), copy("Demand forecasts", "수요 예측"), copy("Capacity evidence", "용량 근거")] },
  { id: "Loki", family: "act", position: [10, -5, 12], role: copy("Resilience experiments", "복원력 실험"),
    capabilities: [copy("Experiment proposal", "실험 제안"), copy("Experiment scope", "실험 범위"), copy("Resilience evidence", "복원력 근거")] },
] as const satisfies readonly Agent[];

export const agentById = new Map(agents.map((agent) => [agent.id, agent]));

/** Identity styling only. Loki's red never changes its role or denotes a failed state. */
export function agentColor(id: AgentId): string {
  if (id === "Loki") return "#ff747d";
  return FAMILY_COLORS[agentById.get(id)!.family];
}
