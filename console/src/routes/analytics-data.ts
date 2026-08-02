import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { OperatorApiError } from "../api";
import type { AutonomyPayload, DashboardKpi } from "../types";
import type { AsyncState } from "../components/ui";
import type { GatesSummary } from "./dashboard.model";

export interface AnalyticsData {
  readonly kpi: DashboardKpi;
  readonly autonomy: AutonomyPayload | null;
  readonly gates: GatesSummary | null;
}

interface AnalyticsDataOptions {
  readonly includeGates?: boolean;
}

async function optional<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof OperatorApiError && (error.status === 404 || error.status === 501)) {
      return null;
    }
    throw error;
  }
}

export async function loadAnalyticsData(
  client: OperatorApiClient,
  options: AnalyticsDataOptions = {},
): Promise<AnalyticsData> {
  const [kpi, autonomy, gates] = await Promise.all([
    client.dashboardMetrics(),
    optional(() => client.autonomy()),
    options.includeGates
      ? optional(() => client.panel<GatesSummary>("/kpi/promotion-gates"))
      : Promise.resolve(null),
  ]);
  return { kpi, autonomy, gates };
}

export function useAnalyticsData(
  client: OperatorApiClient,
  options: AnalyticsDataOptions = {},
): AsyncState<AnalyticsData> {
  const [state, setState] = useState<AsyncState<AnalyticsData>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await loadAnalyticsData(client, options);
        if (!cancelled) setState({ status: "ready", data });
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, options.includeGates]);
  return state;
}
