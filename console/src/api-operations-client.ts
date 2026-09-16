import type { AgentOperationalActivityPage } from "./agent-operational-activity";
import type { OperatorApiTransport } from "./api-transport";
import type {
  AuditPage,
  HilQueuePage,
  IncidentPage,
  IncidentStatusFilter,
  RcaView,
} from "./types";

export interface AuditQuery {
  readonly limit?: number;
  readonly cursor?: string;
  readonly correlationId?: string;
  readonly mode?: string;
  readonly tier?: string;
  readonly action?: string;
  readonly outcome?: string;
  readonly vertical?: string;
  readonly window?: string;
  readonly fromSeq?: number;
  readonly throughSeq?: number;
  readonly includeSummary?: boolean;
}

export interface IncidentQuery {
  readonly status?: IncidentStatusFilter;
  readonly limit?: number;
  readonly cursor?: string;
  readonly search?: string;
  readonly vertical?: string;
  readonly severity?: string;
  readonly correlationId?: string;
}

export type IncidentInterventionAction =
  | "operator_guidance"
  | "close_as_development"
  | "create_development_exception"
  | "revoke_development_exception";

export interface IncidentInterventionBody {
  readonly action: IncidentInterventionAction;
  readonly incident_id: string;
  readonly correlation_id: string;
  readonly expected_state: "open" | "triaging" | "mitigated" | "resolved" | "closed";
  readonly comment: string;
  readonly duration?: "one_day" | "one_week" | "one_month" | "until_revoked";
  readonly exception_id?: string;
}

export interface IncidentInterventionReceipt {
  readonly request_id: string;
  readonly correlation_id: string | null;
  readonly dispatch_status: string;
  readonly accepted_at: string;
  readonly durably_queued: boolean;
}

export class OperationsApiClient {
  readonly #transport: OperatorApiTransport;

  constructor(transport: OperatorApiTransport) {
    this.#transport = transport;
  }

  async listAudit(options: AuditQuery = {}): Promise<AuditPage> {
    const params = new URLSearchParams();
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.cursor !== undefined) params.set("cursor", options.cursor);
    if (options.correlationId !== undefined) params.set("correlation_id", options.correlationId);
    if (options.mode !== undefined) params.set("mode", options.mode);
    if (options.tier !== undefined) params.set("tier", options.tier);
    if (options.action !== undefined) params.set("action", options.action);
    if (options.outcome !== undefined) params.set("outcome", options.outcome);
    if (options.vertical !== undefined) params.set("vertical", options.vertical);
    if (options.window !== undefined) params.set("window", options.window);
    if (options.fromSeq !== undefined) params.set("from_seq", String(options.fromSeq));
    if (options.throughSeq !== undefined) params.set("through_seq", String(options.throughSeq));
    if (options.includeSummary === true) params.set("summary", "true");
    const payload = await this.#transport.getJson<unknown>("/audit", params);
    const { decodeAuditPage } = await import("./api-operations");
    return decodeAuditPage(payload);
  }

  async listAgentActivity(limit = 200): Promise<AgentOperationalActivityPage> {
    const params = new URLSearchParams({ limit: String(limit) });
    const payload = await this.#transport.getJson<unknown>("/agents/activity", params);
    const { decodeAgentOperationalActivityPage } = await import("./agent-operational-activity");
    return decodeAgentOperationalActivityPage(payload);
  }

  async listIncidents(options: IncidentQuery = {}): Promise<IncidentPage> {
    const params = new URLSearchParams();
    if (options.status !== undefined) params.set("status", options.status);
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.cursor !== undefined) params.set("cursor", options.cursor);
    if (options.search !== undefined) params.set("q", options.search);
    if (options.vertical !== undefined) params.set("vertical", options.vertical);
    if (options.severity !== undefined) params.set("severity", options.severity);
    if (options.correlationId !== undefined) params.set("correlation_id", options.correlationId);
    const payload = await this.#transport.getJson<unknown>("/incidents", params);
    const { decodeIncidentPage } = await import("./api-operations");
    return decodeIncidentPage(payload);
  }

  async intervene(
    body: IncidentInterventionBody,
    idempotencyKey: string,
  ): Promise<IncidentInterventionReceipt> {
    const raw = await this.#transport.postJson<unknown>(
      `/incidents/${encodeURIComponent(body.correlation_id)}/interventions`,
      { ...body },
      idempotencyKey,
    );
    const receipt = raw as Partial<IncidentInterventionReceipt>;
    if (
      typeof receipt.request_id !== "string"
      || (receipt.correlation_id !== null && typeof receipt.correlation_id !== "string")
      || typeof receipt.dispatch_status !== "string"
      || typeof receipt.accepted_at !== "string"
      || receipt.durably_queued !== true
    ) {
      throw new Error("incident intervention receipt is malformed");
    }
    return receipt as IncidentInterventionReceipt;
  }

  async rca(correlationId: string): Promise<RcaView> {
    const params = new URLSearchParams();
    params.set("correlation", correlationId);
    const payload = await this.#transport.getJson<unknown>("/rca", params);
    const { decodeRcaView } = await import("./api-operations");
    return decodeRcaView(payload);
  }

  async listHilQueue(options: { limit?: number; query?: string } = {}): Promise<HilQueuePage> {
    const params = new URLSearchParams();
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.query !== undefined) params.set("q", options.query);
    const payload = await this.#transport.getJson<unknown>("/hil-queue", params);
    const { decodeHilQueuePage } = await import("./api-operations");
    return decodeHilQueuePage(payload);
  }
}
