import type { OperatorApiClient } from "../api";
import { OperatorApiError } from "../api";
import { withStartupTransportRetry } from "../bootstrap-retry";
import type {
  AutonomyPayload,
  DashboardKpi,
} from "../types";
import type { CostGovernanceProjection } from "../api-cost-governance";
import type { GatesSummary } from "./dashboard.model";

export interface DashboardOverviewData {
  readonly kpi: DashboardKpi;
  readonly cost: CostGovernanceProjection | null;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
}

type DashboardOverviewClient = Pick<
  OperatorApiClient,
  "dashboardMetrics" | "costGovernance" | "panel" | "autonomy"
>;

export async function loadDashboardOverview(
  client: DashboardOverviewClient,
  publishBackbone: (data: DashboardOverviewData) => void,
): Promise<DashboardOverviewData> {
  const kpi = await withStartupTransportRetry(() => client.dashboardMetrics());
  publishBackbone({ kpi, cost: null, gates: null, autonomy: null });

  const [cost, gates, autonomy] = await Promise.all([
    optionalOverview(() => client.costGovernance("overview"), [403, 404, 503]),
    optionalOverview(
      () => client.panel<GatesSummary>("/kpi/promotion-gates"),
      [404, 501, 503],
    ),
    optionalOverview(() => client.autonomy(), [404, 501, 502, 503]),
  ]);
  return { kpi, cost, gates, autonomy };
}

async function optionalOverview<T>(
  load: () => Promise<T>,
  unavailableStatuses: readonly number[],
): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof OperatorApiError && unavailableStatuses.includes(error.status)) return null;
    throw error;
  }
}
