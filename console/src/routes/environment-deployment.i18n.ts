import { getLocale } from "../i18n";

const en = {
  recover: "Open readiness", retrySource: "Reload deployment evidence",
  retrySourceHint: "Reconnects the read-only evidence source. It does not start or retry a deployment.",
  search: "Find an observer target", status: "Proposal status", all: "All statuses",
  count: "Showing {shown} of {total} loaded observer targets",
  noMatches: "No observer targets match these filters.", clear: "Clear filters",
  expired: "Expired evidence", unavailable: "No current evidence", blockers: "Known blockers",
  missing: "Missing evidence", noBlockers: "No blockers reported", noMissing: "No missing evidence reported",
  unknownReason: "Source-reported prerequisite", kubernetesRead: "Kubernetes read access",
  persistentStorage: "Persistent storage evidence", currentExpiry: "Evidence expired at",
  neverObserved: "No current proposal was provided by the source.",
  expiredHint: "This proposal is no longer current. Refresh evidence to request a new observation, not an installation.",
  sourceError: "Observer evidence could not be loaded or validated.",
  lastFetched: "Last successful read completed: {time}",
  notFetched: "No successful observer-evidence read yet",
} as const;
const ko: Record<keyof typeof en, string> = {
  recover: "준비 상태 열기", retrySource: "배포 근거 다시 불러오기",
  retrySourceHint: "읽기 전용 근거 원본에 다시 연결합니다. 배포를 시작하거나 다시 시도하지 않습니다.",
  search: "관측 대상 찾기", status: "제안 상태", all: "모든 상태",
  count: "불러온 관측 대상 {total}개 중 {shown}개 표시",
  noMatches: "필터와 일치하는 관측 대상이 없습니다.", clear: "필터 초기화",
  expired: "근거 만료됨", unavailable: "현재 근거 없음", blockers: "확인된 차단 요인",
  missing: "누락된 근거", noBlockers: "보고된 차단 요인 없음", noMissing: "보고된 누락 근거 없음",
  unknownReason: "원본에서 보고한 사전 조건", kubernetesRead: "Kubernetes 읽기 접근 권한",
  persistentStorage: "영구 저장소 근거", currentExpiry: "근거 만료 시각",
  neverObserved: "원본에서 현재 제안을 제공하지 않았습니다.",
  expiredHint: "이 제안은 더 이상 유효하지 않습니다. 근거를 새로 고치면 설치가 아니라 새 관측 결과를 요청합니다.",
  sourceError: "관측 근거를 불러오거나 검증하지 못했습니다.",
  lastFetched: "마지막 조회 성공 시각: {time}",
  notFetched: "아직 관측 근거 조회에 성공하지 못했습니다",
};
export function environmentUxText(key: keyof typeof en, values: Readonly<Record<string, string | number>> = {}): string {
  return ((getLocale() === "ko" ? ko[key] : undefined) || en[key])
    .replace(/\{(\w+)\}/g, (token, name: string) => String(values[name] ?? token));
}
export function observerReasonLabel(code: string): string {
  return environmentUxText(code === "kubernetes_read" ? "kubernetesRead"
    : code === "persistent_storage" ? "persistentStorage" : "unknownReason");
}
