import type { OperatorApiTransport } from "./api-transport";
import type {
  AutonomyPayload,
  DashboardKpi,
  EffectiveScope,
  FinOpsPayload,
} from "./types";

export class InsightsApiClient {
  readonly #transport: OperatorApiTransport;

  constructor(transport: OperatorApiTransport) {
    this.#transport = transport;
  }

  async scope(): Promise<EffectiveScope> {
    const payload = await this.#transport.getJson<unknown>("/scope");
    const { decodeScopeView } = await import("./api-insights");
    return decodeScopeView(payload);
  }

  async dashboardMetrics(): Promise<DashboardKpi> {
    const payload = await this.#transport.getJson<unknown>("/kpi");
    const { decodeDashboardKpi } = await import("./api-insights");
    return decodeDashboardKpi(payload);
  }

  async finops(): Promise<FinOpsPayload> {
    return this.#transport.getJson<FinOpsPayload>("/finops");
  }

  async autonomy(): Promise<AutonomyPayload> {
    const payload = await this.#transport.getJson<unknown>("/kpi/autonomy");
    const { decodeAutonomyPayload } = await import("./api-insights");
    return decodeAutonomyPayload(payload);
  }

  async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
    const search = params ? new URLSearchParams(params) : undefined;
    return this.#transport.getJson<T>(path, search);
  }
}
