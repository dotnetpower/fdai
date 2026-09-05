import { getLocale } from "../i18n";
const en = {
  heading: "Recorded resource state", boundary: "Stored values are not a current health verdict.",
  operational: "Operational", provisioning: "Provisioning", availability: "Availability",
  missing: "Not recorded", unknown: "Unknown", fresh: "Fresh at evaluation", stale: "Stale", freshness: "Freshness",
  evidence: "State evidence", source: "Source property", observed: "Observed at",
  recorded: "Recorded at", completeness: "Completeness", conflicts: "Conflicts", reason: "Reason",
};
const ko: Record<keyof typeof en, string> = {
  heading: "기록된 리소스 상태", boundary: "저장된 값은 현재 정상 여부의 판정이 아닙니다.",
  operational: "운영 상태", provisioning: "프로비저닝 상태", availability: "가용성",
  missing: "기록 없음", unknown: "알 수 없음", fresh: "평가 시점에 최신", stale: "오래된 근거", freshness: "최신성",
  evidence: "상태 근거", source: "출처 속성", observed: "관측 시각",
  recorded: "기록 시각", completeness: "완전성", conflicts: "충돌", reason: "이유",
};
export function recordedText(key: keyof typeof en): string {
  return (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
}
