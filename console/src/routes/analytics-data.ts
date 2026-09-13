import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import type { AutonomyPayload, DashboardKpi } from "../types";
import type { AsyncState } from "../components/ui";
import type { GatesSummary } from "./dashboard.model";
import type { ConsoleDataMode } from "../console-data-mode";
import { DASHBOARD_SAMPLE_DATA } from "./dashboard.sample";

export interface AnalyticsData {
  readonly kpi: DashboardKpi;
  readonly autonomy: AutonomyPayload | null;
  readonly gates: GatesSummary | null;
}

interface AnalyticsDataOptions {
  readonly includeGates?: boolean;
  readonly dataMode?: ConsoleDataMode;
}

interface AutonomyRequestState {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
  readonly state: AsyncState<AutonomyPayload | null>;
}

async function optional<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) return null;
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

export async function loadAnalyticsDataForMode(
  mode: ConsoleDataMode,
  client: OperatorApiClient,
  options: AnalyticsDataOptions = {},
): Promise<AnalyticsData> {
  if (mode === "sample") return sampleAnalyticsData(options.includeGates);
  return loadAnalyticsData(client, options);
}

/** Load only the optional autonomy projection required by vertical outcomes. */
export async function loadAutonomyDataForMode(
  mode: ConsoleDataMode,
  client: OperatorApiClient,
): Promise<AutonomyPayload | null> {
  if (mode === "sample") return DASHBOARD_SAMPLE_DATA.autonomy;
  return optional(() => client.autonomy());
}

export function sampleAnalyticsData(includeGates = false): AnalyticsData {
  return {
    kpi: DASHBOARD_SAMPLE_DATA.kpi,
    autonomy: DASHBOARD_SAMPLE_DATA.autonomy,
    gates: includeGates ? DASHBOARD_SAMPLE_DATA.gates : null,
  };
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
        const data = await loadAnalyticsDataForMode(
          options.dataMode ?? "live",
          client,
          options,
        );
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
  }, [client, options.dataMode, options.includeGates]);
  return state;
}

/** Track the autonomy projection without coupling the route to unrelated KPI reads. */
export function useAutonomyData(
  client: OperatorApiClient,
  dataMode: ConsoleDataMode,
): AsyncState<AutonomyPayload | null> {
  const [request, setRequest] = useState<AutonomyRequestState>({
    client,
    dataMode,
    state: { status: "loading" },
  });
  useEffect(() => {
    let cancelled = false;
    setRequest({ client, dataMode, state: { status: "loading" } });
    void (async () => {
      try {
        const data = await loadAutonomyDataForMode(dataMode, client);
        if (!cancelled) {
          setRequest({ client, dataMode, state: { status: "ready", data } });
        }
      } catch (error) {
        if (!cancelled) {
          setRequest({
            client,
            dataMode,
            state: {
              status: "error",
              message: error instanceof Error ? error.message : String(error),
            },
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, dataMode]);
  return autonomyStateForRequest(request, client, dataMode);
}

/** Hide a completed result as soon as the active request identity changes. */
export function autonomyStateForRequest(
  request: AutonomyRequestState,
  client: OperatorApiClient,
  dataMode: ConsoleDataMode,
): AsyncState<AutonomyPayload | null> {
  return request.client === client && request.dataMode === dataMode
    ? request.state
    : { status: "loading" };
}
