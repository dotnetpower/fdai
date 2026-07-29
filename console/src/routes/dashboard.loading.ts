import type { ReadApiClient } from "../api";
import { ReadApiError } from "../api";
import { withStartupTransportRetry } from "../bootstrap-retry";
import type {
  AutonomyPayload,
  DashboardKpi,
  FinOpsPayload,
} from "../types";
import type { GatesSummary } from "./dashboard.model";

export interface DashboardOverviewData {
  readonly kpi: DashboardKpi;
  readonly finops: FinOpsPayload | null;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
}

type DashboardOverviewClient = Pick<
  ReadApiClient,
  "dashboardMetrics" | "finops" | "panel" | "autonomy"
>;

export async function loadDashboardOverview(
  client: DashboardOverviewClient,
  publishBackbone: (data: DashboardOverviewData) => void,
): Promise<DashboardOverviewData> {
  const kpi = await withStartupTransportRetry(() => client.dashboardMetrics());
  publishBackbone({ kpi, finops: null, gates: null, autonomy: null });

  const [finops, gates, autonomy] = await Promise.all([
    optionalOverview(() => client.finops(), [404]),
    optionalOverview(
      () => client.panel<GatesSummary>("/kpi/promotion-gates"),
      [404, 501],
    ),
    optionalOverview(() => client.autonomy(), [404, 501, 502]),
  ]);
  return { kpi, finops, gates, autonomy };
}

async function optionalOverview<T>(
  load: () => Promise<T>,
  unavailableStatuses: readonly number[],
): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof ReadApiError && unavailableStatuses.includes(error.status)) return null;
    throw error;
  }
}
