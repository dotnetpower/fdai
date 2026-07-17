import {
  decodeAutonomyPayload,
  decodeDashboardKpi,
  decodeScopeView,
} from "./api-insights";
import type { ReadApiTransport } from "./api-transport";
import type {
  AutonomyPayload,
  DashboardKpi,
  EffectiveScope,
  FinOpsPayload,
} from "./types";

export class InsightsApiClient {
  readonly #transport: ReadApiTransport;

  constructor(transport: ReadApiTransport) {
    this.#transport = transport;
  }

  async scope(): Promise<EffectiveScope> {
    return decodeScopeView(await this.#transport.getJson<unknown>("/scope"));
  }

  async dashboardMetrics(): Promise<DashboardKpi> {
    return decodeDashboardKpi(await this.#transport.getJson<unknown>("/kpi"));
  }

  async finops(): Promise<FinOpsPayload> {
    return this.#transport.getJson<FinOpsPayload>("/finops");
  }

  async autonomy(): Promise<AutonomyPayload> {
    return decodeAutonomyPayload(await this.#transport.getJson<unknown>("/kpi/autonomy"));
  }

  async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
    const search = params ? new URLSearchParams(params) : undefined;
    return this.#transport.getJson<T>(path, search);
  }
}
