import { copy, type AgentId, type Copy } from "../model";
import { functionById } from "../source-graph";

export interface IndependentWork {
  readonly agent: AgentId;
  readonly functionId: string;
  readonly period: number;
  readonly offset: number;
  readonly duration: number;
  readonly purpose: Copy;
}

/** Fail explicitly when source changes invalidate a displayed Python workflow step. */
export function requireFunction(id: string): string {
  if (!functionById.has(id)) throw new Error(`Required visualizer source function is missing: ${id}`);
  return id;
}

function lane(agent: AgentId, method: string, period: number, offset: number, duration: number, en: string, ko: string): IndependentWork {
  return {
    agent, functionId: requireFunction(`fdai.agents.${agent.toLowerCase()}.${agent}.${method}`),
    period, offset, duration, purpose: copy(en, ko),
  };
}

/** Independent read/observation illustrations; no lane grants approval or dispatches an action. */
export const independentWorkloads: readonly IndependentWork[] = [
  lane("Huginn", "ingest", 7.3, 0, 5.1, "Normalize collected signals", "수집 신호 정규화"),
  lane("Heimdall", "introspect", 9.1, 1.2, 6.2, "Review observation context", "관측 맥락 확인"),
  lane("Odin", "introspect", 13.7, 3.4, 5.2, "Inspect portfolio priorities", "포트폴리오 우선순위 조회"),
  lane("Forseti", "introspect", 10.9, 0.5, 5.4, "Inspect judgment evidence", "판정 근거 조회"),
  lane("Var", "pending_tickets", 12.3, 2.1, 4.8, "Read pending human decisions", "사람의 결정 대기열 조회"),
  lane("Thor", "health", 8.7, 4.6, 4.3, "Read executor health", "실행자 상태 조회"),
  lane("Vidar", "introspect", 14.9, 1.8, 6.1, "Inspect recovery readiness", "복구 준비 상태 조회"),
  lane("Saga", "introspect", 6.7, 3.1, 4.4, "Read audit evidence", "감사 근거 조회"),
  lane("Bragi", "prior_turns", 11.3, 6.7, 4.8, "Read conversation context", "대화 맥락 조회"),
  lane("Mimir", "pending_candidates", 15.1, 2.9, 6.6, "Inspect rule candidates", "규칙 후보 조회"),
  lane("Muninn", "get_context", 8.3, 0.8, 5.5, "Read state and case memory", "상태 및 사례 기억 조회"),
  lane("Norns", "occurrences", 16.7, 4.2, 7.3, "Read recurring patterns", "반복 패턴 조회"),
  lane("Njord", "cost_impact", 10.1, 5.9, 6.4, "Inspect cost context", "비용 맥락 확인"),
  lane("Freyr", "sizing_advice", 12.7, 1.5, 5.8, "Read capacity advice", "용량 권고 조회"),
  lane("Loki", "introspect", 17.9, 3.7, 7.1, "Inspect experiment evidence", "실험 근거 조회"),
];

/** Offset clocks represent a warm-running demo, never a shared sequential task queue. */
export function independentActivityAt(time: number) {
  return independentWorkloads.map((work) => {
    const phase = (Math.max(0, time) + work.offset) % work.period;
    const active = phase < work.duration;
    const progress = Math.min(1, phase / work.duration);
    const energy = active ? Math.min(1, phase / 0.5) * Math.min(1, (work.duration - phase) / 0.9) : 0;
    return { ...work, phase, active, progress, energy };
  });
}

export const ARG_WORKFLOWS = [
  {
    id: "resource-scan",
    owner: "Huginn",
    entry: requireFunction("fdai.delivery.azure.inventory.AzureResourceGraphInventory.full_snapshot"),
    query: requireFunction("fdai.delivery.azure.arg_query.AzureArgQueryFactory._fetch_all_pages"),
    purpose: copy("Resource inventory scan", "리소스 인벤토리 스캔"),
  },
  {
    id: "resource-changes",
    owner: "Huginn",
    entry: requireFunction("fdai.delivery.inventory_change_acceleration.run_resource_change_feed"),
    query: requireFunction("fdai.delivery.azure.arg_resource_changes.AzureResourceChangeFeed.poll"),
    purpose: copy("Resource change detection", "리소스 변경 감지"),
  },
] as const;
