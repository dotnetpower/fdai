import { getLocale } from "../i18n";
import type { RecordedStateFact } from "../recorded-resource-state";

const en = {
  heading: "Recorded resource state", boundary: "Stored values are not a current health verdict.",
  operational: "Operational", provisioning: "Provisioning", availability: "Availability", serving: "Serving",
  missing: "Not recorded", unknown: "Unknown", fresh: "Fresh at evaluation", stale: "Stale", freshness: "Freshness",
  notProvided: "Not provided", notObserved: "No recent successful request", notChecked: "Not checked",
  sourceUnavailable: "Source unavailable", invalidEvidence: "Invalid source evidence",
  unclassified: "Unclassified", sourceNotConnected: "State source not connected", notApplicable: "Not applicable", applicabilityUnknown: "Applicability unknown",
  evidence: "State evidence", source: "Source property", sourceIdentity: "Evidence source", authority: "Authority", observed: "Observed at",
  recorded: "Recorded at", completeness: "Completeness", conflicts: "Conflicts", reason: "Reason",
  providerStateNotExposed: "The provider inventory does not expose operational state for this resource type.",
  providerAvailabilityNotExposed: "Azure Resource Health does not expose availability for this resource type.",
  stateNotApplicable: "A single operational state does not apply to this resource type.",
  stateSourceNotRecorded: "The expected provider operational state was not recorded.",
  stateApplicabilityUnknown: "Operational state applicability has not been reviewed for this resource type.",
  resourceTypeUnclassified: "The resource type is unclassified, so operational state applicability is unknown.",
  resourceHealthProjectionNotBound: "Azure Resource Health is not connected to recorded resource state for this resource type.",
  resourceHealthNotModeled: "Azure Resource Health does not model this exact resource.",
  resourceHealthSourceUnavailable: "Azure Resource Health was unavailable for this observation.",
  resourceHealthTargetLimit: "This resource was outside the bounded Resource Health target set.",
  resourceHealthTargetUnresolved: "The exact Resource Health target could not be resolved.",
  resourceHealthUnauthorized: "The Resource Health read was not authorized.",
  resourceHealthResponseInvalid: "The Resource Health response could not be verified.",
  stateNotRecorded: "No state value was recorded.",
  stateValueInvalid: "The recorded state value was invalid.",
  stateMetadataNotRecorded: "The state value has no property-level observation metadata.",
  stateMetadataInvalid: "The state observation metadata is invalid.",
  stateAfterCutoff: "The state observation is later than its evidence cutoff.",
  modelServingNotObserved: "No successful request was observed for this deployment in the bounded metric window.",
  modelServingSourceUnavailable: "The model serving metric source was unavailable for this observation.",
  modelServingTargetLimit: "This deployment was outside the bounded model serving metric target set.",
  modelServingTargetUnresolved: "The exact provider target for model serving metrics could not be resolved.",
  modelServingResponseInvalid: "The model serving metric response could not be verified.",
};
const ko: Record<keyof typeof en, string> = {
  heading: "기록된 리소스 상태", boundary: "저장된 값은 현재 정상 여부의 판정이 아닙니다.",
  operational: "운영 상태", provisioning: "프로비저닝 상태", availability: "가용성", serving: "서비스 응답",
  missing: "기록 없음", unknown: "알 수 없음", fresh: "평가 시점에 최신", stale: "오래된 근거", freshness: "최신성",
  notProvided: "미제공", notObserved: "최근 성공 요청 없음", notChecked: "확인하지 않음",
  sourceUnavailable: "출처 사용 불가", invalidEvidence: "출처 근거 오류",
  unclassified: "미분류", sourceNotConnected: "상태 원본 미연결", notApplicable: "적용 대상 아님", applicabilityUnknown: "적용 여부 알 수 없음",
  evidence: "상태 근거", source: "출처 속성", sourceIdentity: "근거 출처", authority: "근거 권한", observed: "관측 시각",
  recorded: "기록 시각", completeness: "완전성", conflicts: "충돌", reason: "이유",
  providerStateNotExposed: "공급자 인벤토리가 이 리소스 유형의 운영 상태를 제공하지 않습니다.",
  providerAvailabilityNotExposed: "Azure Resource Health가 이 리소스 유형의 가용성을 제공하지 않습니다.",
  stateNotApplicable: "이 리소스 유형에는 단일 운영 상태가 적용되지 않습니다.",
  stateSourceNotRecorded: "예상한 공급자 운영 상태가 기록되지 않았습니다.",
  stateApplicabilityUnknown: "이 리소스 유형의 운영 상태 적용 여부를 아직 검토하지 않았습니다.",
  resourceTypeUnclassified: "리소스 유형이 미분류 상태이므로 운영 상태 적용 여부를 알 수 없습니다.",
  resourceHealthProjectionNotBound: "이 리소스 유형의 Azure Resource Health가 기록된 리소스 상태에 연결되지 않았습니다.",
  resourceHealthNotModeled: "Azure Resource Health가 이 정확한 리소스를 모델링하지 않습니다.",
  resourceHealthSourceUnavailable: "이번 관측에서 Azure Resource Health를 사용할 수 없었습니다.",
  resourceHealthTargetLimit: "이 리소스는 범위가 제한된 Resource Health 대상에서 제외됐습니다.",
  resourceHealthTargetUnresolved: "정확한 Resource Health 대상을 확인할 수 없습니다.",
  resourceHealthUnauthorized: "Resource Health 조회 권한이 없습니다.",
  resourceHealthResponseInvalid: "Resource Health 응답을 검증할 수 없습니다.",
  stateNotRecorded: "상태 값이 기록되지 않았습니다.",
  stateValueInvalid: "기록된 상태 값이 올바르지 않습니다.",
  stateMetadataNotRecorded: "상태 값에 속성 단위 관측 메타데이터가 없습니다.",
  stateMetadataInvalid: "상태 관측 메타데이터가 올바르지 않습니다.",
  stateAfterCutoff: "상태 관측 시각이 근거 기준 시점보다 늦습니다.",
  modelServingNotObserved: "제한된 메트릭 구간에 이 배포의 성공 요청이 관측되지 않았습니다.",
  modelServingSourceUnavailable: "이번 관측에서 모델 서비스 응답 메트릭 출처를 사용할 수 없었습니다.",
  modelServingTargetLimit: "이 배포는 범위가 제한된 모델 서비스 응답 메트릭 대상에서 제외됐습니다.",
  modelServingTargetUnresolved: "모델 서비스 응답 메트릭의 정확한 공급자 대상을 확인할 수 없습니다.",
  modelServingResponseInvalid: "모델 서비스 응답 메트릭 결과를 검증할 수 없습니다.",
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
  if (fact.reason === "provider_operational_state_not_exposed") {
    return recordedText("notProvided");
  }
  if (fact.reason === "provider_availability_state_not_exposed") {
    return recordedText("notProvided");
  }
  if (fact.reason === "model_serving_not_observed") return recordedText("notObserved");
  if (fact.reason === "model_serving_target_limit") return recordedText("notChecked");
  if (fact.reason === "model_serving_source_unavailable") return recordedText("sourceUnavailable");
  if (fact.reason === "model_serving_target_unresolved") return recordedText("sourceUnavailable");
  if (fact.reason === "model_serving_response_invalid") return recordedText("invalidEvidence");
  if (fact.reason === "resource_health_not_modeled") return recordedText("notProvided");
  if (fact.reason === "resource_health_target_limit") return recordedText("notChecked");
  if (fact.reason === "resource_health_source_unavailable") return recordedText("sourceUnavailable");
  if (fact.reason === "resource_health_transport_unavailable") return recordedText("sourceUnavailable");
  if (fact.reason === "resource_health_unauthorized") return recordedText("sourceUnavailable");
  if (fact.reason === "resource_health_target_unresolved") return recordedText("sourceUnavailable");
  if (fact.reason === "resource_health_response_invalid") return recordedText("invalidEvidence");
  if (fact.reason === "resource_health_response_too_large") return recordedText("invalidEvidence");
  if (fact.reason === "resource_type_unclassified") return recordedText("unclassified");
  if (fact.reason === "state_applicability_unknown") return recordedText("applicabilityUnknown");
  return recordedText("missing");
}

export function recordedStateReasonText(reason: string): string | null {
  const key = {
    provider_operational_state_not_exposed: "providerStateNotExposed",
    provider_availability_state_not_exposed: "providerAvailabilityNotExposed",
    state_not_applicable: "stateNotApplicable",
    state_source_not_recorded: "stateSourceNotRecorded",
    state_applicability_unknown: "stateApplicabilityUnknown",
    resource_type_unclassified: "resourceTypeUnclassified",
    resource_health_projection_not_bound: "resourceHealthProjectionNotBound",
    resource_health_not_modeled: "resourceHealthNotModeled",
    resource_health_source_unavailable: "resourceHealthSourceUnavailable",
    resource_health_transport_unavailable: "resourceHealthSourceUnavailable",
    resource_health_target_limit: "resourceHealthTargetLimit",
    resource_health_target_unresolved: "resourceHealthTargetUnresolved",
    resource_health_unauthorized: "resourceHealthUnauthorized",
    resource_health_response_invalid: "resourceHealthResponseInvalid",
    resource_health_response_too_large: "resourceHealthResponseInvalid",
    state_not_recorded: "stateNotRecorded",
    state_value_invalid: "stateValueInvalid",
    state_metadata_not_recorded: "stateMetadataNotRecorded",
    state_metadata_invalid: "stateMetadataInvalid",
    state_after_cutoff: "stateAfterCutoff",
    model_serving_not_observed: "modelServingNotObserved",
    model_serving_source_unavailable: "modelServingSourceUnavailable",
    model_serving_target_limit: "modelServingTargetLimit",
    model_serving_target_unresolved: "modelServingTargetUnresolved",
    model_serving_response_invalid: "modelServingResponseInvalid",
  }[reason] as keyof typeof en | undefined;
  return key === undefined ? null : recordedText(key);
}
