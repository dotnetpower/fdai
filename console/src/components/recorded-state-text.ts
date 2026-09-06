import { getLocale } from "../i18n";
import type { RecordedStateFact } from "../recorded-resource-state";

const en = {
  heading: "Recorded resource state", boundary: "Stored values are not a current health verdict.",
  operational: "Operational", provisioning: "Provisioning", availability: "Availability",
  missing: "Not recorded", unknown: "Unknown", fresh: "Fresh at evaluation", stale: "Stale", freshness: "Freshness",
  unavailable: "Unavailable", sourceNotConnected: "State source not connected", notApplicable: "Not applicable", applicabilityUnknown: "Applicability unknown",
  evidence: "State evidence", source: "Source property", observed: "Observed at",
  recorded: "Recorded at", completeness: "Completeness", conflicts: "Conflicts", reason: "Reason",
  providerStateNotExposed: "The provider inventory does not expose operational state for this resource type.",
  stateNotApplicable: "A single operational state does not apply to this resource type.",
  stateSourceNotRecorded: "The expected provider operational state was not recorded.",
  stateApplicabilityUnknown: "Operational state applicability has not been reviewed for this resource type.",
  resourceTypeUnclassified: "The resource type is unclassified, so operational state applicability is unknown.",
  resourceHealthProjectionNotBound: "Azure Resource Health is not connected to recorded resource state for this resource type.",
};
const ko: Record<keyof typeof en, string> = {
  heading: "기록된 리소스 상태", boundary: "저장된 값은 현재 정상 여부의 판정이 아닙니다.",
  operational: "운영 상태", provisioning: "프로비저닝 상태", availability: "가용성",
  missing: "기록 없음", unknown: "알 수 없음", fresh: "평가 시점에 최신", stale: "오래된 근거", freshness: "최신성",
  unavailable: "사용 불가", sourceNotConnected: "상태 원본 미연결", notApplicable: "적용 대상 아님", applicabilityUnknown: "적용 여부 알 수 없음",
  evidence: "상태 근거", source: "출처 속성", observed: "관측 시각",
  recorded: "기록 시각", completeness: "완전성", conflicts: "충돌", reason: "이유",
  providerStateNotExposed: "공급자 인벤토리가 이 리소스 유형의 운영 상태를 제공하지 않습니다.",
  stateNotApplicable: "이 리소스 유형에는 단일 운영 상태가 적용되지 않습니다.",
  stateSourceNotRecorded: "예상한 공급자 운영 상태가 기록되지 않았습니다.",
  stateApplicabilityUnknown: "이 리소스 유형의 운영 상태 적용 여부를 아직 검토하지 않았습니다.",
  resourceTypeUnclassified: "리소스 유형이 미분류 상태이므로 운영 상태 적용 여부를 알 수 없습니다.",
  resourceHealthProjectionNotBound: "이 리소스 유형의 Azure Resource Health가 기록된 리소스 상태에 연결되지 않았습니다.",
};
export function recordedText(key: keyof typeof en): string {
  return (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
}

export function recordedStateValueText(fact: RecordedStateFact): string {
  if (fact.value !== null) return fact.value;
  if (fact.reason === "state_not_applicable") return recordedText("notApplicable");
  if (fact.reason === "resource_health_projection_not_bound") {
    return recordedText("sourceNotConnected");
  }
  if (
    fact.reason === "provider_operational_state_not_exposed"
    || fact.reason === "resource_type_unclassified"
  ) return recordedText("unavailable");
  if (fact.reason === "state_applicability_unknown") return recordedText("applicabilityUnknown");
  return recordedText("missing");
}

export function recordedStateReasonText(reason: string): string | null {
  const key = {
    provider_operational_state_not_exposed: "providerStateNotExposed",
    state_not_applicable: "stateNotApplicable",
    state_source_not_recorded: "stateSourceNotRecorded",
    state_applicability_unknown: "stateApplicabilityUnknown",
    resource_type_unclassified: "resourceTypeUnclassified",
    resource_health_projection_not_bound: "resourceHealthProjectionNotBound",
  }[reason] as keyof typeof en | undefined;
  return key === undefined ? null : recordedText(key);
}
