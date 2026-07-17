import {
  decodeAuditPage,
  decodeHilQueuePage,
  decodeIncidentPage,
  decodeRcaView,
} from "./api-operations";
import type { ReadApiTransport } from "./api-transport";
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
}

export interface IncidentQuery {
  readonly status?: IncidentStatusFilter;
  readonly limit?: number;
  readonly cursor?: string;
  readonly vertical?: string;
  readonly correlationId?: string;
}

export class OperationsApiClient {
  readonly #transport: ReadApiTransport;

  constructor(transport: ReadApiTransport) {
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
    return decodeAuditPage(await this.#transport.getJson<unknown>("/audit", params));
  }

  async listIncidents(options: IncidentQuery = {}): Promise<IncidentPage> {
    const params = new URLSearchParams();
    if (options.status !== undefined) params.set("status", options.status);
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.cursor !== undefined) params.set("cursor", options.cursor);
    if (options.vertical !== undefined) params.set("vertical", options.vertical);
    if (options.correlationId !== undefined) params.set("correlation_id", options.correlationId);
    return decodeIncidentPage(await this.#transport.getJson<unknown>("/incidents", params));
  }

  async rca(correlationId: string): Promise<RcaView> {
    const params = new URLSearchParams();
    params.set("correlation", correlationId);
    return decodeRcaView(await this.#transport.getJson<unknown>("/rca", params));
  }

  async listHilQueue(options: { limit?: number; query?: string } = {}): Promise<HilQueuePage> {
    const params = new URLSearchParams();
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.query !== undefined) params.set("q", options.query);
    return decodeHilQueuePage(await this.#transport.getJson<unknown>("/hil-queue", params));
  }
}
