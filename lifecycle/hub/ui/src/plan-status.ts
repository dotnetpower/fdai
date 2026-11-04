import type { PlanDetail } from "./api";
import { tr, type HubLocale } from "./locale";

export function planDisplayStatus(
  plan: Pick<PlanDetail, "status" | "expires_at">,
  now = Date.now(),
  locale: HubLocale = "en",
): { label: string; variant: "info" | "mute" | "warn" } {
  if (plan.status === "superseded") {
    return { label: tr(locale, "Superseded", "대체됨"), variant: "mute" };
  }
  if (Date.parse(plan.expires_at) <= now) {
    return { label: tr(locale, "Expired", "만료됨"), variant: "warn" };
  }
  return { label: tr(locale, "Open", "열림"), variant: "info" };
}

export function planDispatchEligibility(
  plan: Pick<PlanDetail, "status" | "expires_at" | "reports">,
  now = Date.now(),
  locale: HubLocale = "en",
): { dispatchable: boolean; label: string; variant: "ok" | "info" | "warn" | "fail" | "mute" } {
  const latest = plan.reports.length > 0 ? plan.reports[plan.reports.length - 1]! : null;
  if (latest?.outcome === "applied") {
    return {
      dispatchable: false,
      label: tr(
        locale,
        "Terminal (applied) · Not dispatchable",
        "종료됨 (적용 완료) · 실행 대상 아님",
      ),
      variant: "ok",
    };
  }
  if (latest?.outcome === "rolled-back" || latest?.outcome === "rejected") {
    return {
      dispatchable: false,
      label: tr(
        locale,
        `Terminal (${latest.outcome}) · Not dispatchable`,
        `종료됨 (${latest.outcome}) · 실행 대상 아님`,
      ),
      variant: "fail",
    };
  }
  if (plan.status === "superseded") {
    return {
      dispatchable: false,
      label: tr(locale, "Superseded · Historical record only", "대체됨 · 이력 기록 전용"),
      variant: "mute",
    };
  }
  if (Date.parse(plan.expires_at) <= now) {
    return {
      dispatchable: false,
      label: tr(locale, "Expired · Not dispatchable", "만료됨 · 실행 대상 아님"),
      variant: "warn",
    };
  }
  if (latest?.outcome === "apply-started") {
    return {
      dispatchable: false,
      label: tr(
        locale,
        "In progress (apply-started) · Awaiting terminal effect report",
        "진행 중 (apply-started) · 최종 적용 보고 대기 중",
      ),
      variant: "warn",
    };
  }
  return {
    dispatchable: true,
    label: tr(
      locale,
      "Eligible for Agent dispatch within window",
      "유지보수 구간 내 에이전트 실행 적격",
    ),
    variant: "info",
  };
}
