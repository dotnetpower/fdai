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
  EffectiveScope,
  FinOpsPayload,
  HilQueuePage,
  IncidentPage,
  IncidentStatusFilter,
  RcaView,
} from "./types";
import {
  decodeRenderedReport,
  decodeReportingRegistry,
  decodeReportList,
  type RenderedReportView,
  type ReportingRegistry,
  type ReportList,
} from "./routes/reporting.model";
import {
  decodeIamAccessRequestPage,
  decodeIamOverview,
  decodeIamSelfStatus,
  decodeHumanIdentityResults,
  decodeIdentityRoster,
  type HumanIdentityResult,
  type IamAccessRequestPage,
  type IamOverview,
  type IamSelfStatus,
  type IdentityRosterItem,
} from "./routes/settings-iam.model";

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

  async listAudit(opts: {
    limit?: number;
    cursor?: string;
    correlationId?: string;
    mode?: string;
    tier?: string;
    action?: string;
    outcome?: string;
    vertical?: string;
    window?: string;
  } = {}): Promise<AuditPage> {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts.cursor !== undefined) params.set("cursor", opts.cursor);
    if (opts.correlationId !== undefined) params.set("correlation_id", opts.correlationId);
    if (opts.mode !== undefined) params.set("mode", opts.mode);
    if (opts.tier !== undefined) params.set("tier", opts.tier);
    if (opts.action !== undefined) params.set("action", opts.action);
    if (opts.outcome !== undefined) params.set("outcome", opts.outcome);
    if (opts.vertical !== undefined) params.set("vertical", opts.vertical);
    if (opts.window !== undefined) params.set("window", opts.window);
    return decodeAuditPage(await this.#get<unknown>("/audit", params));
  }

  async listIncidents(opts: {
    status?: IncidentStatusFilter;
    limit?: number;
    cursor?: string;
    vertical?: string;
  } = {}): Promise<IncidentPage> {
    const params = new URLSearchParams();
    if (opts.status !== undefined) params.set("status", opts.status);
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts.cursor !== undefined) params.set("cursor", opts.cursor);
    if (opts.vertical !== undefined) params.set("vertical", opts.vertical);
    return decodeIncidentPage(await this.#get<unknown>("/incidents", params));
  }

  /**
   * Fetch the RCA (root-cause analysis) view for one incident
   * (`GET /rca?correlation=...`). Read-only projection of the shadow
   * `rca.hypothesis` audit entries: tiered hypotheses, grounded
   * citations, and the linked response plan. An RCA hypothesis answers
   * "why", never "execute".
   */
  async rca(correlationId: string): Promise<RcaView> {
    const params = new URLSearchParams();
    params.set("correlation", correlationId);
    return decodeRcaView(await this.#get<unknown>("/rca", params));
  }

  /**
   * Fetch the effective monitoring / automated-action scope
   * (`GET /scope`). Opt-in like {@link finops}; callers MUST tolerate a
   * 404 as "scope view not served here". Read-only: authoring a scope
   * change is a policy-as-code PR, never a console write.
   */
  async scope(): Promise<EffectiveScope> {
    return decodeScopeView(await this.#get<unknown>("/scope"));
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
    return decodeAutonomyPayload(await this.#get<unknown>("/kpi/autonomy"));
  }

  async listHilQueue(opts: { limit?: number } = {}): Promise<HilQueuePage> {
    const params = new URLSearchParams();
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    return decodeHilQueuePage(await this.#get<unknown>("/hil-queue", params));
  }

  async iamOverview(): Promise<IamOverview> {
    return decodeIamOverview(await this.#get<unknown>("/iam"));
  }

  async iamSelf(): Promise<IamSelfStatus> {
    return decodeIamSelfStatus(await this.#get<unknown>("/iam/self"));
  }

  async searchIamUsers(query: string, limit = 20): Promise<readonly HumanIdentityResult[]> {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return decodeHumanIdentityResults(
      await this.#get<unknown>("/iam/directory/users", params),
    );
  }

  async iamRoster(): Promise<readonly IdentityRosterItem[]> {
    return decodeIdentityRoster(await this.#get<unknown>("/iam/directory/roster"));
  }

  async listIamAccessRequests(limit = 50, cursor = 0): Promise<IamAccessRequestPage> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor > 0) params.set("cursor", String(cursor));
    return decodeIamAccessRequestPage(await this.#get<unknown>("/iam/access-requests", params));
  }

  async reports(): Promise<ReportList> {
    return decodeReporting(decodeReportList, await this.#get<unknown>("/reports"));
  }

  async reportingRegistry(): Promise<ReportingRegistry> {
    return decodeReporting(
      decodeReportingRegistry,
      await this.#get<unknown>("/reports/registry"),
    );
  }

  async renderReport(
    reportId: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<RenderedReportView> {
    return decodeReporting(
      decodeRenderedReport,
      await this.#get<unknown>(`/reports/${encodeURIComponent(reportId)}/render`, new URLSearchParams(variables)),
    );
  }

  async downloadReport(
    reportId: string,
    format: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<Blob> {
    const params = new URLSearchParams(variables);
    params.set("format", format);
    const response = await this.#getResponse(
      `/reports/${encodeURIComponent(reportId)}/render`,
      params,
      format === "pdf" ? "application/pdf" : "application/octet-stream",
    );
    return response.blob();
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
    const response = await this.#getResponse(path, params, "application/json");
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

  async #getResponse(
    path: string,
    params: URLSearchParams | undefined,
    accept: string,
  ): Promise<Response> {
    const url = new URL(path, this.#config.readApiBaseUrl);
    if (params && params.toString().length > 0) {
      url.search = params.toString();
    }
    const headers: Record<string, string> = { accept };
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
    return response;
  }
}

function decodeReporting<T>(decode: (value: unknown) => T, value: unknown): T {
  try {
    return decode(value);
  } catch (error) {
    if (error instanceof ReadApiError) throw error;
    throw new ReadApiError(502, error instanceof Error ? error.message : String(error));
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

export function isOptionalReadApiUnavailable(error: unknown): error is ReadApiError {
  return error instanceof ReadApiError && (error.status === 404 || error.status === 501);
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
      const involvedAgents = item["involved_agents"];
      if (
        involvedAgents !== undefined &&
        (!Array.isArray(involvedAgents) ||
          !involvedAgents.every((agent) => typeof agent === "string"))
      ) {
        throw contractError("incident item.involved_agents MUST be an array of strings");
      }
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
        involved_agents: involvedAgents ?? [],
      };
    }),
    next_cursor: cursor,
  };
}

export function decodeRcaView(value: unknown): RcaView {
  const root = apiRecord(value, "RCA view");
  if (!Array.isArray(root["hypotheses"])) {
    throw contractError("RCA view.hypotheses MUST be an array");
  }
  const response = root["response"];
  return {
    correlation_id: apiString(root, "correlation_id", "RCA view"),
    incident_id: apiNullableString(root, "incident_id", "RCA view"),
    hypotheses: root["hypotheses"].map((raw, index) => {
      const item = apiRecord(raw, `RCA view.hypotheses[${index}]`);
      const citations = item["citations"];
      if (!Array.isArray(citations)) {
        throw contractError(`RCA view.hypotheses[${index}].citations MUST be an array`);
      }
      return {
        seq: apiPositiveInteger(item, "seq", "RCA hypothesis"),
        tier: apiRcaTier(item["tier"]),
        outcome: apiRcaOutcome(item["outcome"]),
        grounded: apiBoolean(item, "grounded", "RCA hypothesis"),
        cause: apiNullableString(item, "cause", "RCA hypothesis"),
        confidence: apiNullableRatio(item, "confidence", "RCA hypothesis"),
        reason: apiNullableString(item, "reason", "RCA hypothesis"),
        citations: citations.map((rawCitation, citationIndex) => {
          const citation = apiRecord(rawCitation, `RCA hypothesis.citations[${citationIndex}]`);
          return {
            kind: apiString(citation, "kind", "RCA citation"),
            ref: apiString(citation, "ref", "RCA citation"),
          };
        }),
        remediation_ref: apiNullableString(item, "remediation_ref", "RCA hypothesis"),
        causal_chain: decodeRcaCausalChain(item["causal_chain"]),
        mode: apiMode(item["mode"]),
        recorded_at: apiString(item, "recorded_at", "RCA hypothesis"),
      };
    }),
    response:
      response === null
        ? null
        : (() => {
            const item = apiRecord(response, "RCA view.response");
            return {
              verdict: apiString(item, "verdict", "RCA response"),
              decision: apiNullableString(item, "decision", "RCA response"),
              action_kind: apiNullableString(item, "action_kind", "RCA response"),
              mode: item["mode"] === null ? null : apiMode(item["mode"]),
              rollback_reference: apiNullableString(item, "rollback_reference", "RCA response"),
              recorded_at: apiNullableString(item, "recorded_at", "RCA response"),
            };
          })(),
  };
}

function decodeRcaCausalChain(value: unknown): RcaView["hypotheses"][number]["causal_chain"] {
  if (value === null || value === undefined) return null;
  const chain = apiRecord(value, "RCA causal chain");
  if (!Array.isArray(chain["hops"]) || chain["hops"].length === 0) {
    throw contractError("RCA causal chain.hops MUST be a non-empty array");
  }
  return {
    root_event_id: apiString(chain, "root_event_id", "RCA causal chain"),
    failure_event_id: apiString(chain, "failure_event_id", "RCA causal chain"),
    confidence: apiRatio(chain, "confidence", "RCA causal chain"),
    ambiguity: apiPositiveInteger(chain, "ambiguity", "RCA causal chain"),
    hops: chain["hops"].map((raw, index) => {
      const hop = apiRecord(raw, `RCA causal chain.hops[${index}]`);
      const leadSeconds = apiNumber(hop, "lead_seconds", "RCA causal hop");
      if (leadSeconds < 0) throw contractError("RCA causal hop.lead_seconds MUST be non-negative");
      return {
        cause_event_id: apiString(hop, "cause_event_id", "RCA causal hop"),
        effect_event_id: apiString(hop, "effect_event_id", "RCA causal hop"),
        cause_resource_ref: apiString(hop, "cause_resource_ref", "RCA causal hop"),
        effect_resource_ref: apiString(hop, "effect_resource_ref", "RCA causal hop"),
        lead_seconds: leadSeconds,
        relationship: apiString(hop, "relationship", "RCA causal hop"),
        confidence: apiRatio(hop, "confidence", "RCA causal hop"),
      };
    }),
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

export function decodeAutonomyPayload(value: unknown): AutonomyPayload {
  const root = apiRecord(value, "autonomy measurement");
  const source = apiRecord(root["source"], "autonomy measurement.source");
  const sourceKind = apiString(source, "kind", "autonomy measurement.source");
  if (sourceKind !== "audit" && sourceKind !== "measurement" && sourceKind !== "synthetic") {
    throw contractError("autonomy measurement.source.kind MUST be audit, measurement, or synthetic");
  }
  const success = apiRecord(root["success"], "autonomy measurement.success");
  const leading = apiRecord(root["leading"], "autonomy measurement.leading");
  const rules = apiRecord(root["rules"], "autonomy measurement.rules");
  const tier = apiRecord(root["tier"], "autonomy measurement.tier");
  const bands = apiRecord(tier["bands"], "autonomy measurement.tier.bands");
  if (!Array.isArray(root["guards"])) {
    throw contractError("autonomy measurement.guards MUST be an array");
  }
  if (!Array.isArray(root["verticals"])) {
    throw contractError("autonomy measurement.verticals MUST be an array");
  }
  return {
    synthetic: apiBoolean(root, "synthetic", "autonomy measurement"),
    window_days: apiPositiveInteger(root, "window_days", "autonomy measurement"),
    sample_size: apiNonNegativeInteger(root, "sample_size", "autonomy measurement"),
    confidence: root["confidence"] === null
      ? null
      : apiRatio(root, "confidence", "autonomy measurement"),
    source: {
      name: apiString(source, "name", "autonomy measurement.source"),
      kind: sourceKind,
      as_of: apiNullableString(source, "as_of", "autonomy measurement.source"),
    },
    rules: {
      active: apiNonNegativeInteger(rules, "active", "autonomy measurement.rules"),
      candidates_30d: apiNonNegativeInteger(rules, "candidates_30d", "autonomy measurement.rules"),
      promoted_30d: apiNonNegativeInteger(rules, "promoted_30d", "autonomy measurement.rules"),
    },
    success: {
      auto_resolution_rate: decodeMetric(success["auto_resolution_rate"], "success.auto_resolution_rate"),
      human_touchpoints_per_100: decodeMetric(success["human_touchpoints_per_100"], "success.human_touchpoints_per_100"),
      mttr_seconds: decodeMetric(success["mttr_seconds"], "success.mttr_seconds"),
      change_lead_time_seconds: decodeMetric(success["change_lead_time_seconds"], "success.change_lead_time_seconds"),
      cost_per_resolved_event_usd: decodeMetric(success["cost_per_resolved_event_usd"], "success.cost_per_resolved_event_usd"),
    },
    leading: {
      mixed_model_disagreement_rate: decodeMetric(leading["mixed_model_disagreement_rate"], "leading.mixed_model_disagreement_rate"),
      verifier_failure_rate: decodeMetric(leading["verifier_failure_rate"], "leading.verifier_failure_rate"),
      shadow_divergence_rate: decodeMetric(leading["shadow_divergence_rate"], "leading.shadow_divergence_rate"),
    },
    guards: root["guards"].map((raw, index) => {
      const item = apiRecord(raw, `autonomy measurement.guards[${index}]`);
      return {
        key: apiString(item, "key", "autonomy guard"),
        value: apiNumber(item, "value", "autonomy guard"),
        baseline: apiNumber(item, "baseline", "autonomy guard"),
        threshold: apiNumber(item, "threshold", "autonomy guard"),
        ok: apiBoolean(item, "ok", "autonomy guard"),
      };
    }),
    verticals: root["verticals"].map((raw, index) => {
      const item = apiRecord(raw, `autonomy measurement.verticals[${index}]`);
      return {
        key: apiString(item, "key", "autonomy vertical"),
        events: apiNonNegativeInteger(item, "events", "autonomy vertical"),
        auto_resolved: apiNonNegativeInteger(item, "auto_resolved", "autonomy vertical"),
        open_risks: apiNonNegativeInteger(item, "open_risks", "autonomy vertical"),
        monthly_savings: apiNumber(item, "monthly_savings", "autonomy vertical"),
      };
    }),
    tier: {
      mix: decodeFiniteNumberRecord(tier["mix"], "autonomy measurement.tier.mix"),
      bands: Object.fromEntries(
        Object.entries(bands).map(([key, raw]) => {
          if (!Array.isArray(raw) || raw.length !== 2 || raw.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
            throw contractError(`autonomy measurement.tier.bands.${key} MUST be two finite numbers`);
          }
          return [key, [raw[0], raw[1]] as const];
        }),
      ),
    },
    trend: Object.fromEntries(
      Object.entries(apiRecord(root["trend"], "autonomy measurement.trend")).map(([key, raw]) => {
        if (!Array.isArray(raw) || raw.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
          throw contractError(`autonomy measurement.trend.${key} MUST be finite numbers`);
        }
        return [key, raw];
      }),
    ),
  };
}

function decodeMetric(value: unknown, label: string): AutonomyPayload["success"]["auto_resolution_rate"] {
  const item = apiRecord(value, `autonomy measurement.${label}`);
  const direction = apiString(item, "direction", `autonomy measurement.${label}`);
  if (direction !== "higher" && direction !== "lower") {
    throw contractError(`autonomy measurement.${label}.direction MUST be higher or lower`);
  }
  return {
    value: apiNumber(item, "value", `autonomy measurement.${label}`),
    baseline: apiNumber(item, "baseline", `autonomy measurement.${label}`),
    direction,
  };
}

function decodeFiniteNumberRecord(value: unknown, label: string): Record<string, number> {
  const raw = apiRecord(value, label);
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(raw)) {
    if (typeof item !== "number" || !Number.isFinite(item)) {
      throw contractError(`${label}.${key} MUST be a finite number`);
    }
    result[key] = item;
  }
  return result;
}

export function decodeScopeView(value: unknown): EffectiveScope {
  const root = apiRecord(value, "scope view");
  return {
    monitoring: decodeScopeAxis(root["monitoring"], "monitoring"),
    action: decodeScopeAxis(root["action"], "action"),
    executor_boundary: decodeExecutorBoundary(root["executor_boundary"]),
  };
}

function decodeScopeAxis(value: unknown, expected: "monitoring" | "action"): EffectiveScope["monitoring"] {
  const root = apiRecord(value, `scope view.${expected}`);
  const axis = root["axis"];
  if (axis !== expected) throw contractError(`scope view.${expected}.axis MUST be ${expected}`);
  if (!Array.isArray(root["entries"])) {
    throw contractError(`scope view.${expected}.entries MUST be an array`);
  }
  return {
    axis: expected,
    entries: root["entries"].map((raw, index) => {
      const item = apiRecord(raw, `scope view.${expected}.entries[${index}]`);
      return {
        address: apiString(item, "address", "scope entry"),
        level: apiScopeLevel(item["level"]),
        subscription: apiString(item, "subscription", "scope entry"),
        resource_group: apiNullableString(item, "resource_group", "scope entry"),
        state: apiScopeState(item["state"]),
      };
    }),
  };
}

function decodeExecutorBoundary(value: unknown): EffectiveScope["executor_boundary"] {
  const root = apiRecord(value, "scope view.executor_boundary");
  if (!Array.isArray(root["resource_groups"])) {
    throw contractError("scope view.executor_boundary.resource_groups MUST be an array");
  }
  return {
    resource_groups: root["resource_groups"].map((raw, index) => {
      if (typeof raw !== "string") {
        throw contractError(`scope view.executor_boundary.resource_groups[${index}] MUST be a string`);
      }
      return raw;
    }),
    note: apiNullableString(root, "note", "scope view.executor_boundary"),
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
        approval_id: apiOptionalString(item, "approval_id", "HIL queue item"),
        action_id: apiOptionalString(item, "action_id", "HIL queue item"),
        target_resource_ref: apiOptionalString(item, "target_resource_ref", "HIL queue item"),
        mode: apiOptionalString(item, "mode", "HIL queue item"),
        stop_condition: apiOptionalString(item, "stop_condition", "HIL queue item"),
        rollback_kind: apiOptionalString(item, "rollback_kind", "HIL queue item"),
        rollback_reference: apiOptionalNullableString(item, "rollback_reference", "HIL queue item"),
        blast_radius_scope: apiOptionalString(item, "blast_radius_scope", "HIL queue item"),
        blast_radius_count: apiOptionalNullableNonNegativeInteger(item, "blast_radius_count", "HIL queue item"),
        blast_radius_rate_per_minute: apiOptionalNullableNonNegativeInteger(item, "blast_radius_rate_per_minute", "HIL queue item"),
        blast_radius_summary: apiOptionalString(item, "blast_radius_summary", "HIL queue item"),
        reasons: apiOptionalStringArray(item, "reasons", "HIL queue item"),
        citing_rule_ids: apiOptionalStringArray(item, "citing_rule_ids", "HIL queue item"),
        ttl_expires_at: apiOptionalNullableString(item, "ttl_expires_at", "HIL queue item"),
      };
    }),
    total: apiNonNegativeInteger(root, "total", "HIL queue page"),
    detail_level: apiHilDetailLevel(root["detail_level"]),
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

function apiOptionalString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  return value[key] === undefined ? "" : apiString(value, key, label);
}

function apiOptionalNullableString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return value[key] === undefined ? null : apiNullableString(value, key, label);
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

function apiOptionalNullableNonNegativeInteger(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (value[key] === undefined) return null;
  if (value[key] === null) return null;
  return apiNonNegativeInteger(value, key, label);
}

function apiOptionalStringArray(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): readonly string[] {
  const items = value[key];
  if (items === undefined) return [];
  if (!Array.isArray(items) || items.some((item) => typeof item !== "string")) {
    throw contractError(`${label}.${key} MUST be an array of strings`);
  }
  return items;
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

function apiRcaTier(value: unknown): "t0" | "t1" | "t2" | "unknown" {
  if (value === "t0" || value === "t1" || value === "t2" || value === "unknown") return value;
  throw contractError("RCA hypothesis.tier MUST be t0, t1, t2, or unknown");
}

function apiRcaOutcome(value: unknown): "grounded" | "abstained" | "unknown" {
  if (value === "grounded" || value === "abstained" || value === "unknown") return value;
  throw contractError("RCA hypothesis.outcome MUST be grounded, abstained, or unknown");
}

function apiHilDetailLevel(value: unknown): "full" | "count_only" {
  if (value === undefined || value === "full") return "full";
  if (value === "count_only") return "count_only";
  throw contractError("HIL queue page.detail_level MUST be full or count_only");
}

function apiBoolean(value: Readonly<Record<string, unknown>>, key: string, label: string): boolean {
  if (typeof value[key] !== "boolean") throw contractError(`${label}.${key} MUST be a boolean`);
  return value[key];
}

function apiNullableRatio(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (value[key] === null) return null;
  return apiRatio(value, key, label);
}

function apiScopeLevel(value: unknown): "subscription" | "resource_group" {
  if (value === "subscription" || value === "resource_group") return value;
  throw contractError("scope entry.level MUST be subscription or resource_group");
}

function apiScopeState(value: unknown): "included" | "excluded" {
  if (value === "included" || value === "excluded") return value;
  throw contractError("scope entry.state MUST be included or excluded");
}
