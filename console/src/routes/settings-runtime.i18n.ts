import { getLocale } from "../i18n";

const en = {
  discard: "Discard changes",
  search: "Find a policy",
  changedOnly: "Changed policies only",
  count: "Showing {shown} of {total} loaded policies",
  empty: "No runtime policies were returned by this source.",
  noMatches: "No policies match these filters.",
  clearFilters: "Clear filters",
  unavailableReason: "The source did not provide an unavailable reason.",
  numericError: "Enter a valid {type} from {min} to {max}.",
  objectError: "Enter a JSON object. Arrays, scalar values, and invalid JSON cannot be saved.",
  unbounded: "no limit",
  integer: "whole number",
  number: "number",
  pending: "Pending value: {value}",
  pendingReset: "Pending: remove the override and inherit {value}",
  conflictReview: "Your draft is preserved. Review the latest revision {revision} before applying it again.",
  reapply: "Use latest revision and keep this draft",
  cannotReapply: "Some drafted settings are no longer available or editable. Discard the draft to use the latest view.",
  retrySave: "Retry save",
  latest: "Latest server value",
  current: "Current value",
  proposed: "Your proposed value",
  technicalValue: "Complete structured value",
  invalidBatch: "Correct invalid policy fields before saving. Clear filters if a field is hidden.",
} as const;
const ko: Record<keyof typeof en, string> = {
  discard: "변경 사항 취소",
  search: "정책 찾기",
  changedOnly: "변경한 정책만 표시",
  count: "불러온 정책 {total}개 중 {shown}개 표시",
  empty: "이 원본에서 반환한 런타임 정책이 없습니다.",
  noMatches: "필터와 일치하는 정책이 없습니다.",
  clearFilters: "필터 초기화",
  unavailableReason: "원본에서 사용할 수 없는 이유를 제공하지 않았습니다.",
  numericError: "{min}에서 {max} 사이의 올바른 {type}를 입력하세요.",
  objectError: "JSON 객체를 입력하세요. 배열, 단일 값, 잘못된 JSON은 저장할 수 없습니다.",
  unbounded: "제한 없음",
  integer: "정수",
  number: "숫자",
  pending: "저장 대기 중인 값: {value}",
  pendingReset: "저장 후 재정의를 제거하고 {value} 값을 상속합니다",
  conflictReview: "초안을 보존했습니다. 다시 적용하기 전에 최신 버전 {revision}의 값을 검토하세요.",
  reapply: "최신 버전을 기준으로 초안 유지",
  cannotReapply: "초안의 일부 설정을 더 이상 사용하거나 편집할 수 없습니다. 최신 값을 사용하려면 초안을 취소하세요.",
  retrySave: "저장 다시 시도",
  latest: "최신 서버 값",
  current: "현재 값",
  proposed: "적용할 값",
  technicalValue: "전체 구조화 값",
  invalidBatch: "저장하기 전에 잘못된 정책 입력값을 수정하세요. 입력란이 보이지 않으면 필터를 초기화하세요.",
};

export function runtimeUxText(key: keyof typeof en, values: Readonly<Record<string, string | number>> = {}): string {
  return ((getLocale() === "ko" ? ko[key] : undefined) || en[key])
    .replace(/\{(\w+)\}/g, (token, name: string) => String(values[name] ?? token));
}
