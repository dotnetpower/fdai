/**
 * Read API client. The console makes exactly three kinds of GET call
 * against the API defined in `src/aiopspilot/delivery/read_api/main.py`.
 * All routes are read-only; there are NO helpers here for POST / PUT /
 * DELETE / PATCH — the read-only invariant is enforced by not writing
 * such helpers in the first place (see app-shape.instructions.md).
 */

import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";
import type {
  ApiError,
  AuditPage,
  DashboardKpi,
  HilQueuePage,
} from "./types";

export class ReadApiClient {
  #config: ConsoleConfig;
  #auth: AuthContext;

  constructor(config: ConsoleConfig, auth: AuthContext) {
    this.#config = config;
    this.#auth = auth;
  }

  async listAudit(opts: { limit?: number; cursor?: string } = {}): Promise<AuditPage> {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts.cursor !== undefined) params.set("cursor", opts.cursor);
    return this.#get<AuditPage>("/audit", params);
  }

  async dashboardMetrics(): Promise<DashboardKpi> {
    return this.#get<DashboardKpi>("/kpi");
  }

  async listHilQueue(opts: { limit?: number } = {}): Promise<HilQueuePage> {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    return this.#get<HilQueuePage>("/hil-queue", params);
  }

  async #get<T>(path: string, params?: URLSearchParams): Promise<T> {
    const url = new URL(path, this.#config.readApiBaseUrl);
    if (params && params.toString().length > 0) {
      url.search = params.toString();
    }
    const headers: Record<string, string> = { accept: "application/json" };
    const authHeader = await this.#auth.getAuthorizationHeader();
    if (authHeader !== null) headers["authorization"] = authHeader;
    const response = await fetch(url.toString(), {
      method: "GET",
      headers,
      credentials: "omit",
    });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as ApiError;
        message = body.error?.message ?? message;
      } catch {
        /* body was not JSON — fall through */
      }
      throw new ReadApiError(response.status, message);
    }
    return (await response.json()) as T;
  }
}

export class ReadApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ReadApiError";
    this.status = status;
  }
}
