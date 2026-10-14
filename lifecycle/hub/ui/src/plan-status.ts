import type { PlanDetail } from "./api";

export function planDisplayStatus(
  plan: Pick<PlanDetail, "status" | "expires_at">,
  now = Date.now(),
): { label: string; variant: "info" | "mute" | "warn" } {
  if (plan.status === "superseded") return { label: "Superseded", variant: "mute" };
  if (Date.parse(plan.expires_at) <= now) return { label: "Expired", variant: "warn" };
  return { label: "Open", variant: "info" };
}
