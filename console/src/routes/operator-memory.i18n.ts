import { getLocale } from "../i18n";

const en = {
  clear: "Clear filters", refresh: "Refresh memory evidence", retry: "Retry memory evidence",
  lastChecked: "Last successful fetch: {time}", neverChecked: "No successful fetch yet",
  applied: "Displayed scope: {scope}", all: "All scopes", pending: "Filter changes have not been applied.",
  count: "{entries} loaded memory entries, {compactions} loaded compaction candidates",
  coverage: "This request asks for up to 100 memory entries. The source does not provide a complete total or pagination.",
  resourceGroup: "Resource group", resource: "Resource", active: "Active", expired: "Expired", superseded: "Superseded",
  approved: "Approved", rejected: "Rejected", pendingReview: "Pending review", proposed: "Proposed",
  unknownState: "Unrecognized state: {state}", details: "Review complete record", id: "Record identifier",
  created: "Created", expires: "Expires", noExpiry: "No expiry specified", unavailable: "Unavailable",
  replacement: "Replacement memory", noReplacement: "No replacement reference supplied",
  reviewReason: "Review reason", noReview: "Not reviewed", noReason: "No review reason supplied",
  copy: "Copy reference", copied: "Reference copied", copyFailed: "Copy failed. Select and copy the reference manually.",
  body: "Complete memory text", sources: "Source references",
  invalidFilters: "Invalid URL filters were ignored. Select a supported scope and a reference of at most 256 characters.",
} as const;
const ko: Record<keyof typeof en, string> = {
  clear: "필터 초기화", refresh: "메모리 근거 새로 고침", retry: "메모리 근거 다시 불러오기",
  lastChecked: "마지막 조회 성공: {time}", neverChecked: "아직 조회에 성공하지 못했습니다",
  applied: "표시 중인 범위: {scope}", all: "모든 범위", pending: "필터 변경 사항을 아직 적용하지 않았습니다.",
  count: "메모리 항목 {entries}개, 압축 검토 후보 {compactions}개를 불러왔습니다",
  coverage: "이 요청은 메모리 항목을 최대 100개 조회합니다. 원본에서 전체 개수나 페이지 정보를 제공하지 않습니다.",
  resourceGroup: "리소스 그룹", resource: "리소스", active: "활성", expired: "만료됨", superseded: "대체됨",
  approved: "승인됨", rejected: "거부됨", pendingReview: "검토 대기", proposed: "제안됨",
  unknownState: "알 수 없는 상태: {state}", details: "전체 기록 검토", id: "기록 식별자",
  created: "생성 시각", expires: "만료 시각", noExpiry: "만료 시각이 지정되지 않음", unavailable: "확인할 수 없음",
  replacement: "대체 메모리", noReplacement: "대체 기록 참조가 제공되지 않음",
  reviewReason: "검토 이유", noReview: "검토되지 않음", noReason: "검토 이유가 제공되지 않음",
  copy: "참조 복사", copied: "참조를 복사했습니다", copyFailed: "복사하지 못했습니다. 참조를 직접 선택해 복사하세요.",
  body: "전체 메모리 내용", sources: "원본 참조",
  invalidFilters: "잘못된 URL 필터를 무시했습니다. 지원되는 범위와 256자 이하의 참조를 선택하세요.",
};
export function memoryUxText(key: keyof typeof en, values: Readonly<Record<string, string | number>> = {}): string {
  return ((getLocale() === "ko" ? ko[key] : undefined) || en[key])
    .replace(/\{(\w+)\}/g, (token, name: string) => String(values[name] ?? token));
}

export function memoryScopeLabel(scope: string): string {
  return scope === "resource-group" ? memoryUxText("resourceGroup")
    : scope === "resource" ? memoryUxText("resource") : scope || memoryUxText("all");
}

export function memoryStateLabel(state: string): string {
  const known = {
    active: "active", expired: "expired", superseded: "superseded", approved: "approved",
    rejected: "rejected", pending: "pendingReview", pending_review: "pendingReview", proposed: "proposed",
  } as const;
  return Object.hasOwn(known, state)
    ? memoryUxText(known[state as keyof typeof known])
    : memoryUxText("unknownState", { state });
}
