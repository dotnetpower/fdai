import type { PlanDetail } from "./api";

export function planDisplayStatus(
  plan: Pick<PlanDetail, "status" | "expires_at">,
  now = Date.now(),
): { label: string; variant: "info" | "mute" | "warn" } {
  if (plan.status === "superseded") return { label: "Superseded", variant: "mute" };
  if (Date.parse(plan.expires_at) <= now) return { label: "Expired", variant: "warn" };
  return { label: "Open", variant: "info" };
}

export function planDispatchEligibility(
  plan: Pick<PlanDetail, "status" | "expires_at" | "reports">,
  now = Date.now(),
): { dispatchable: boolean; label: string; variant: "ok" | "info" | "warn" | "fail" | "mute" } {
  const latest = plan.reports.length > 0 ? plan.reports[plan.reports.length - 1]! : null;
  if (latest?.outcome === "applied") {
    return {
      dispatchable: false,
      label: "Terminal (applied) · Not dispatchable",
      variant: "ok",
    };
  }
  if (latest?.outcome === "rolled-back" || latest?.outcome === "rejected") {
    return {
      dispatchable: false,
      label: `Terminal (${latest.outcome}) · Not dispatchable`,
      variant: "fail",
    };
  }
  if (plan.status === "superseded") {
    return {
      dispatchable: false,
      label: "Superseded · Historical record only",
      variant: "mute",
    };
  }
  if (Date.parse(plan.expires_at) <= now) {
    return {
      dispatchable: false,
      label: "Expired · Not dispatchable",
      variant: "warn",
    };
  }
  if (latest?.outcome === "apply-started") {
    return {
      dispatchable: false,
      label: "In progress (apply-started) · Awaiting terminal effect report",
      variant: "warn",
    };
  }
  return {
    dispatchable: true,
    label: "Eligible for Agent dispatch within window",
    variant: "info",
  };
}
