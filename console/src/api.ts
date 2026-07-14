/**
 * Read API client. The console makes exactly three kinds of GET call
 * against the API defined in `src/fdai/delivery/read_api/main.py`.
 * All routes are read-only; there are NO helpers here for POST / PUT /
 * DELETE / PATCH - the read-only invariant is enforced by not writing
 * such helpers in the first place (see app-shape.instructions.md).
 */

import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";
import type {
  ApiError,
  AuditPage,
  AutonomyPayload,
  DashboardKpi,
  FinOpsPayload,
  HilQueuePage,
  IncidentPage,
  IncidentStatusFilter,
} from "./types";

export class ReadApiClient {
  #config: ConsoleConfig;
  #auth: AuthContext;

  constructor(config: ConsoleConfig, auth: AuthContext) {
    this.#config = config;
    this.#auth = auth;
  }

  get readApiBaseUrl(): string {
    return this.#config.readApiBaseUrl;
  }

  readonly authorizationHeader = async (): Promise<string | null> => {
    return this.#auth.getAuthorizationHeader();
  };

  async listAudit(opts: { limit?: number; cursor?: string; correlationId?: string } = {}): Promise<AuditPage> {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts.cursor !== undefined) params.set("cursor", opts.cursor);
    if (opts.correlationId !== undefined) params.set("correlation_id", opts.correlationId);
    return decodeAuditPage(await this.#get<unknown>("/audit", params));
  }

  async listIncidents(opts: {
    status?: IncidentStatusFilter;
    limit?: number;
    cursor?: string;
  } = {}): Promise<IncidentPage> {
    const params = new URLSearchParams();
    if (opts.status !== undefined) params.set("status", opts.status);
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts.cursor !== undefined) params.set("cursor", opts.cursor);
    return decodeIncidentPage(await this.#get<unknown>("/incidents", params));
  }

  async dashboardMetrics(): Promise<DashboardKpi> {
    return decodeDashboardKpi(await this.#get<unknown>("/kpi"));
  }

  /**
   * Fetch the FinOps cost summary (`GET /finops`). This is a fork opt-in
   * panel; callers MUST tolerate a 404 (`ReadApiError` status 404) as
   * "cost axis not served here" rather than a hard failure.
   */
  async finops(): Promise<FinOpsPayload> {
    return this.#get<FinOpsPayload>("/finops");
  }

  /**
   * Fetch the autonomy measurement summary (`GET /kpi/autonomy`). Opt-in
   * like {@link finops}; callers MUST tolerate a 404 as "measurement
   * surface not served here".
   */
  async autonomy(): Promise<AutonomyPayload> {
    return this.#get<AutonomyPayload>("/kpi/autonomy");
  }

  async listHilQueue(opts: { limit?: number } = {}): Promise<HilQueuePage> {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    return decodeHilQueuePage(await this.#get<unknown>("/hil-queue", params));
  }

  /**
   * Fetch a fork-supplied read-only panel payload. Backs the `ReadPanel`
   * seam in `src/fdai/delivery/read_api/panels.py`: a fork registers
   * a GET route on the API and a matching console panel, then reads it
   * here. This is GET-only like every other call - a panel MUST NOT mutate
   * state (see app-shape.instructions.md § Operator console).
   */
  async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
    const search = params ? new URLSearchParams(params) : undefined;
    return this.#get<T>(path, search);
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
        /* body was not JSON - fall through */
      }
      throw new ReadApiError(response.status, message);
    }
    // Success-path parse is also fallible - a proxy that returns text/html
    // on a stray 200 (a login page, a WAF interstitial) would otherwise
    // throw SyntaxError and break the uniform ReadApiError contract every
    // caller catches on. Wrap it so the error type stays consistent.
    try {
      return (await response.json()) as T;
    } catch {
      throw new ReadApiError(
        response.status,
        `response body was not JSON (${response.headers.get("content-type") ?? "no content-type"})`,
      );
    }
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

export function decodeAuditPage(value: unknown): AuditPage {
  const root = apiRecord(value, "audit page");
  if (!Array.isArray(root["items"])) throw contractError("audit page.items MUST be an array");
  const cursor = root["next_cursor"];
  if (cursor !== null && typeof cursor !== "string") {
    throw contractError("audit page.next_cursor MUST be a string or null");
  }
  return {
    items: root["items"].map((raw, index) => {
      const item = apiRecord(raw, `audit page.items[${index}]`);
      return {
        seq: apiPositiveInteger(item, "seq", "audit item"),
        event_id: apiString(item, "event_id", "audit item"),
        correlation_id: apiNullableString(item, "correlation_id", "audit item"),
        actor: apiString(item, "actor", "audit item"),
        action_kind: apiString(item, "action_kind", "audit item"),
        mode: apiMode(item["mode"]),
        entry: apiRecord(item["entry"], "audit item.entry") as Record<string, unknown>,
        entry_hash: apiString(item, "entry_hash", "audit item"),
        previous_hash: apiString(item, "previous_hash", "audit item"),
        recorded_at: apiString(item, "recorded_at", "audit item"),
      };
    }),
    next_cursor: cursor,
  };
}

export function decodeIncidentPage(value: unknown): IncidentPage {
  const root = apiRecord(value, "incident page");
  if (!Array.isArray(root["items"])) throw contractError("incident page.items MUST be an array");
  const cursor = root["next_cursor"];
  if (cursor !== null && typeof cursor !== "string") {
    throw contractError("incident page.next_cursor MUST be a string or null");
  }
  return {
    items: root["items"].map((raw, index) => {
      const item = apiRecord(raw, `incident page.items[${index}]`);
      return {
        correlation_id: apiString(item, "correlation_id", "incident item"),
        incident_id: apiNullableString(item, "incident_id", "incident item"),
        ticket_id: apiNullableString(item, "ticket_id", "incident item"),
        title: apiString(item, "title", "incident item"),
        severity: apiString(item, "severity", "incident item"),
        status: apiIncidentStatus(item["status"]),
        status_source: apiStatusSource(item["status_source"]),
        disposition: apiString(item, "disposition", "incident item"),
        verdict: apiString(item, "verdict", "incident item"),
        vertical: apiString(item, "vertical", "incident item"),
        opened_at: apiString(item, "opened_at", "incident item"),
        last_updated_at: apiString(item, "last_updated_at", "incident item"),
        latest_mode: apiMode(item["latest_mode"]),
        history_count: apiPositiveInteger(item, "history_count", "incident item"),
      };
    }),
    next_cursor: cursor,
  };
}

export function decodeDashboardKpi(value: unknown): DashboardKpi {
  const root = apiRecord(value, "dashboard KPI");
  return {
    event_count: apiNonNegativeInteger(root, "event_count", "dashboard KPI"),
    shadow_share: apiRatio(root, "shadow_share", "dashboard KPI"),
    enforce_share: apiRatio(root, "enforce_share", "dashboard KPI"),
    hil_pending: apiNonNegativeInteger(root, "hil_pending", "dashboard KPI"),
    by_action_kind: apiNumberRecord(root["by_action_kind"], "dashboard KPI.by_action_kind"),
    by_outcome: apiNumberRecord(root["by_outcome"], "dashboard KPI.by_outcome"),
    by_tier: apiNumberRecord(root["by_tier"], "dashboard KPI.by_tier"),
    last_recorded_at: apiNullableString(root, "last_recorded_at", "dashboard KPI"),
  };
}

export function decodeHilQueuePage(value: unknown): HilQueuePage {
  const root = apiRecord(value, "HIL queue page");
  if (!Array.isArray(root["items"])) throw contractError("HIL queue page.items MUST be an array");
  return {
    items: root["items"].map((raw, index) => {
      const item = apiRecord(raw, `HIL queue page.items[${index}]`);
      return {
        idempotency_key: apiString(item, "idempotency_key", "HIL queue item"),
        event_id: apiString(item, "event_id", "HIL queue item"),
        action_kind: apiString(item, "action_kind", "HIL queue item"),
        reason: apiString(item, "reason", "HIL queue item"),
        requested_at: apiString(item, "requested_at", "HIL queue item"),
        correlation_id: apiNullableString(item, "correlation_id", "HIL queue item"),
      };
    }),
    total: apiNonNegativeInteger(root, "total", "HIL queue page"),
  };
}

function contractError(message: string): ReadApiError {
  return new ReadApiError(502, `invalid read API response: ${message}`);
}

function apiRecord(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw contractError(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function apiString(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  if (typeof value[key] !== "string") throw contractError(`${label}.${key} MUST be a string`);
  return value[key];
}

function apiNullableString(value: Readonly<Record<string, unknown>>, key: string, label: string): string | null {
  if (value[key] === null) return null;
  return apiString(value, key, label);
}

function apiNumber(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw contractError(`${label}.${key} MUST be a finite number`);
  }
  return value[key];
}

function apiNonNegativeInteger(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const number = apiNumber(value, key, label);
  if (!Number.isInteger(number) || number < 0) {
    throw contractError(`${label}.${key} MUST be a non-negative integer`);
  }
  return number;
}

function apiPositiveInteger(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const number = apiNonNegativeInteger(value, key, label);
  if (number < 1) throw contractError(`${label}.${key} MUST be a positive integer`);
  return number;
}

function apiRatio(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const number = apiNumber(value, key, label);
  if (number < 0 || number > 1) throw contractError(`${label}.${key} MUST be between 0 and 1`);
  return number;
}

function apiNumberRecord(value: unknown, label: string): Record<string, number> {
  const raw = apiRecord(value, label);
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(raw)) {
    if (typeof item !== "number" || !Number.isFinite(item) || !Number.isInteger(item) || item < 0) {
      throw contractError(`${label}.${key} MUST be a non-negative integer`);
    }
    result[key] = item;
  }
  return result;
}

function apiMode(value: unknown): "shadow" | "enforce" {
  if (value === "shadow" || value === "enforce") return value;
  throw contractError("audit item.mode MUST be shadow or enforce");
}

function apiIncidentStatus(value: unknown): "open" | "in_progress" | "resolved" {
  if (value === "open" || value === "in_progress" || value === "resolved") return value;
  throw contractError("incident item.status MUST be open, in_progress, or resolved");
}

function apiStatusSource(value: unknown): "incident_lifecycle" | "audit_projection" {
  if (value === "incident_lifecycle" || value === "audit_projection") return value;
  throw contractError("incident item.status_source MUST name a supported projection source");
}
