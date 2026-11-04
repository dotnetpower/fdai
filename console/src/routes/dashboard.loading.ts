import type { OperatorApiClient } from "../api";
import { OperatorApiError } from "../api";
import { withStartupTransportRetry } from "../bootstrap-retry";
import type {
  AutonomyPayload,
  DashboardKpi,
} from "../types";
import type { CostGovernanceProjection } from "../api-cost-governance";
import type { GatesSummary } from "./dashboard.model";
import type { ConsoleDataMode } from "../console-data-mode";
import { DASHBOARD_SAMPLE_DATA } from "./dashboard.sample";
import {
  isCostGovernanceProjection,
  loadCostGovernance,
} from "./cost-governance.model";
import { isStencilPanelEnabled } from "../stencil-panels";

export interface DashboardOverviewData {
  readonly kpi: DashboardKpi;
  readonly cost: CostGovernanceProjection | null;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
  readonly optionalPending?: boolean;
}

type DashboardOverviewClient = Pick<
  OperatorApiClient,
  "dashboardMetrics" | "costGovernanceAvailability" | "costGovernance" | "panel" | "autonomy"
>;

export async function loadDashboardOverview(
  client: DashboardOverviewClient,
  publishBackbone: (data: DashboardOverviewData) => void,
): Promise<DashboardOverviewData> {
  const kpi = await withStartupTransportRetry(() => client.dashboardMetrics());
  publishBackbone({ kpi, cost: null, gates: null, autonomy: null, optionalPending: true });

  const [cost, gates, autonomy] = await Promise.all([
    isStencilPanelEnabled("cost-governance")
      ? optionalOverview(async () => {
          const result = await loadCostGovernance(client, "overview");
          return isCostGovernanceProjection(result) ? result : null;
        }, [403, 404, 503])
      : Promise.resolve(null),
    isStencilPanelEnabled("promotion-gates") || isStencilPanelEnabled("control-assurance")
      ? optionalOverview(
          () => client.panel<GatesSummary>("/kpi/promotion-gates"),
          [403, 404, 501, 503],
        )
      : Promise.resolve(null),
    isStencilPanelEnabled("operating-outcomes") ||
    isStencilPanelEnabled("trust-routing") ||
    isStencilPanelEnabled("control-assurance") ||
    isStencilPanelEnabled("verticals")
      ? optionalOverview(() => client.autonomy(), [403, 404, 501, 503])
      : Promise.resolve(null),
  ]);
  return { kpi, cost, gates, autonomy };
}

export async function loadDashboardOverviewForMode(
  mode: ConsoleDataMode,
  client: DashboardOverviewClient,
  publishBackbone: (data: DashboardOverviewData) => void,
): Promise<DashboardOverviewData> {
  if (mode === "sample") {
    publishBackbone(DASHBOARD_SAMPLE_DATA);
    return DASHBOARD_SAMPLE_DATA;
  }
  return loadDashboardOverview(client, publishBackbone);
}

async function optionalOverview<T>(
  load: () => Promise<T>,
  unavailableStatuses: readonly number[],
): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (
      error instanceof OperatorApiError
      && unavailableStatuses.includes(error.status)
      && (error.status !== 503 || error.kind === "projection-unavailable")
    ) return null;
    throw error;
  }
}
