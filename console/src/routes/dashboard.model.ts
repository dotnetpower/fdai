import type { AutonomyPayload, DashboardKpi } from "../types";

export type OverviewHealth = "healthy" | "attention" | "unknown";

export function overviewHealth(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards"> | null,
): OverviewHealth {
  const knownFailure =
    kpi.shadow_share < 0.95 ||
    kpi.hil_pending > 0 ||
    (policyEscapes !== null && policyEscapes > 0) ||
    (autonomy !== null && autonomy.guards.some((guard) => !guard.ok));
  if (knownFailure) return "attention";
  if (policyEscapes === null || autonomy === null) return "unknown";
  return "healthy";
}