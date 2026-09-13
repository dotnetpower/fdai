/**
 * Operator API client - the real data source behind `--source=api`.
 *
 * Talks to the independent Operator Service (three GET routes: /kpi, /hil-queue,
 * /audit). This is the same read-only
 * surface the console SPA uses; the CLI just renders it differently. No mutating
 * calls - the console never executes an action.
 */

import { safeDisplayLine, safeDisplayText } from "../display-text.js";

/** KPI dashboard aggregate (mirrors DashboardKpi.to_dict). */
export interface KpiPayload {
  event_count: number;
  shadow_share: number;
  enforce_share: number;
  hil_pending: number;
  by_action_kind: Record<string, number>;
  by_outcome: Record<string, number>;
  by_tier: Record<string, number>;
  last_recorded_at: string | null;
  audit_sample?: {
    from_seq: number | null;
    through_seq: number | null;
    row_count: number;
    limit: number;
  } | null;
}

/** One pending HIL item (mirrors HilQueueItem.to_dict). */
export interface HilItemPayload {
  idempotency_key: string;
  event_id: string;
  action_kind: string;
  reason: string;
  requested_at: string;
  correlation_id: string | null;
}

export interface HilQueuePayload {
  items: HilItemPayload[];
  total: number;
  detail_level?: string;
}

/** One audit row (mirrors AuditItem.to_dict; entry kept opaque). */
export interface AuditItemPayload {
  seq: number;
  event_id: string;
  actor: string;
  action_kind: string;
  mode: string;
  recorded_at: string;
}

export interface ReadModelSnapshot {
  kpi: KpiPayload | null;
  hil: HilQueuePayload | null;
  audit: AuditItemPayload[] | null;
}

export interface ChatHistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatReply {
  answer: string;
  model: string;
  latency_ms?: number;
  verification?: Record<string, unknown>;
}

export const DEFAULT_CHAT_TIMEOUT_MS = 135_000;
const MAX_API_RESPONSE_CHARS = 512 * 1024;
const MAX_ERROR_RESPONSE_CHARS = 16 * 1024;
const MAX_COLLECTION_ITEMS = 512;
const MAX_CHAT_ANSWER_CODE_POINTS = 256 * 1024;

export interface OperatorApiRequestOptions {
  authorization?: string;
}

export class OperatorApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "OperatorApiError";
  }
}

function requestHeaders(
  accept: string,
  authorization?: string,
): Record<string, string> {
  return authorization ? { accept, authorization } : { accept };
}

async function getJson<T>(
  url: string,
  decode: (payload: unknown) => T,
  options: OperatorApiRequestOptions = {},
): Promise<T> {
  const res = await fetch(url, {
    headers: requestHeaders("application/json", options.authorization),
    redirect: "error",
  });
  if (!res.ok) {
    throw await responseError(res, url);
  }
  return decode(await responseJson(res, url));
}

async function responseError(res: Response, url: string): Promise<OperatorApiError> {
  let detail = "";
  try {
    const raw = await boundedResponseText(res, MAX_ERROR_RESPONSE_CHARS);
    const body = JSON.parse(raw) as unknown;
    if (isRecord(body) && typeof body.detail === "string") {
      detail = safeDisplayLine(body.detail, 500);
    }
  } catch {
    // Status and statusText remain actionable when the body is not JSON.
  }
  const suffix = detail ? `: ${detail.replace(/\s+/g, " ").slice(0, 500)}` : "";
  const statusText = res.statusText ? ` ${res.statusText}` : "";
  return new OperatorApiError(
    `Operator API ${url} -> ${res.status}${statusText}${suffix}`,
    res.status,
  );
}

const norm = (baseUrl: string): string => baseUrl.replace(/\/$/, "");

/** Delegate one conversational turn to the shared Operator API coordinator. */
export async function askChat(
  baseUrl: string,
  prompt: string,
  options: {
    viewContext?: Record<string, unknown>;
    history?: readonly ChatHistoryTurn[];
    sessionId?: string;
    timeoutMs?: number;
    authorization?: string;
    signal?: AbortSignal;
  } = {},
): Promise<ChatReply> {
  const url = `${norm(baseUrl)}/chat`;
  const timeoutSignal = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_CHAT_TIMEOUT_MS);
  const res = await fetch(url, {
    method: "POST",
    headers: {
      ...requestHeaders("application/json", options.authorization),
      "content-type": "application/json",
    },
    signal: options.signal
      ? AbortSignal.any([options.signal, timeoutSignal])
      : timeoutSignal,
    redirect: "error",
    body: JSON.stringify({
      prompt,
      view_context: options.viewContext ?? {},
      history: options.history ?? [],
      session_id: options.sessionId,
    }),
  });
  if (!res.ok) {
    throw await responseError(res, url);
  }
  return decodeChatReply(await responseJson(res, url), url);
}

export async function fetchKpi(
  baseUrl: string,
  options: OperatorApiRequestOptions = {},
): Promise<KpiPayload> {
  return getJson(`${norm(baseUrl)}/kpi`, decodeKpi, options);
}

export async function fetchHilItems(
  baseUrl: string,
  options: OperatorApiRequestOptions = {},
): Promise<HilQueuePayload> {
  return getJson(
    `${norm(baseUrl)}/hil-queue`,
    decodeHilQueue,
    options,
  );
}

export async function fetchAuditItems(
  baseUrl: string,
  limit = 8,
  options: OperatorApiRequestOptions = {},
): Promise<AuditItemPayload[]> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 500) {
    throw new Error("audit limit must be an integer from 1 through 500");
  }
  const page = await getJson(
    `${norm(baseUrl)}/audit?limit=${limit}`,
    decodeAuditPage,
    options,
  );
  return page.items;
}

async function responseJson(response: Response, url: string): Promise<unknown> {
  const raw = await boundedResponseText(response, MAX_API_RESPONSE_CHARS);
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    throw new Error(`Operator API ${url} returned invalid JSON`);
  }
}

async function boundedResponseText(response: Response, maximum: number): Promise<string> {
  const declared = response.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > maximum) {
    throw new Error("Operator API response exceeds the size limit");
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let raw = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > maximum) {
        await reader.cancel("Operator API response exceeds the size limit").catch(() => {});
        throw new Error("Operator API response exceeds the size limit");
      }
      raw += decoder.decode(value, { stream: true });
    }
    raw += decoder.decode();
    return raw;
  } finally {
    reader.releaseLock();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`Operator API returned invalid ${label}`);
  return value;
}

function text(
  value: unknown,
  label: string,
  maximum = 4096,
  nullable = false,
): string | null {
  if (nullable && value === null) return null;
  if (typeof value !== "string") throw new Error(`Operator API returned invalid ${label}`);
  if ([...value].length > maximum) throw new Error(`Operator API returned invalid ${label}`);
  const normalized = safeDisplayLine(value, maximum);
  if (normalized.length === 0) throw new Error(`Operator API returned invalid ${label}`);
  return normalized;
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new Error(`Operator API returned invalid ${label}`);
  }
  return value as number;
}

function ratio(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error(`Operator API returned invalid ${label}`);
  }
  return value;
}

function countRecord(value: unknown, label: string): Record<string, number> {
  const payload = record(value, label);
  const entries = Object.entries(payload);
  if (entries.length > 128) throw new Error(`Operator API returned invalid ${label}`);
  const result: Record<string, number> = {};
  for (const [key, count] of entries) {
    if ([...key].length > 256) throw new Error(`Operator API returned invalid ${label}`);
    const normalized = safeDisplayLine(key, 256);
    if (normalized.length === 0 || Object.hasOwn(result, normalized)) {
      throw new Error(`Operator API returned invalid ${label}`);
    }
    result[normalized] = integer(count, label);
  }
  return result;
}

function decodeKpi(value: unknown): KpiPayload {
  const payload = record(value, "KPI response");
  return {
    event_count: integer(payload.event_count, "KPI event_count"),
    shadow_share: ratio(payload.shadow_share, "KPI shadow_share"),
    enforce_share: ratio(payload.enforce_share, "KPI enforce_share"),
    hil_pending: integer(payload.hil_pending, "KPI hil_pending"),
    by_action_kind: countRecord(payload.by_action_kind, "KPI by_action_kind"),
    by_outcome: countRecord(payload.by_outcome, "KPI by_outcome"),
    by_tier: countRecord(payload.by_tier, "KPI by_tier"),
    last_recorded_at: text(payload.last_recorded_at, "KPI last_recorded_at", 128, true),
  };
}

function decodeHilQueue(value: unknown): HilQueuePayload {
  const payload = record(value, "approval queue response");
  const items = payload.items;
  if (!Array.isArray(items) || items.length > MAX_COLLECTION_ITEMS) {
    throw new Error("Operator API returned invalid approval queue items");
  }
  const detailLevel = text(payload.detail_level, "approval queue detail_level", 32);
  if (detailLevel !== "full" && detailLevel !== "count_only") {
    throw new Error("Operator API returned invalid approval queue detail_level");
  }
  const total = integer(payload.total, "approval queue total");
  if (total < items.length || (detailLevel === "count_only" && items.length !== 0)) {
    throw new Error("Operator API returned inconsistent approval queue response");
  }
  return {
    items: items.map((item) => decodeHilItem(item)),
    total,
    detail_level: detailLevel,
  };
}

function decodeHilItem(value: unknown): HilItemPayload {
  const item = record(value, "approval queue item");
  return {
    idempotency_key: text(item.idempotency_key, "approval idempotency_key", 1024)!,
    event_id: text(item.event_id, "approval event_id", 1024)!,
    action_kind: text(item.action_kind, "approval action_kind", 256)!,
    reason: text(item.reason, "approval reason", 4096)!,
    requested_at: text(item.requested_at, "approval requested_at", 128)!,
    correlation_id: text(item.correlation_id, "approval correlation_id", 1024, true),
  };
}

function decodeAuditPage(value: unknown): { items: AuditItemPayload[] } {
  const payload = record(value, "audit response");
  if (!Array.isArray(payload.items) || payload.items.length > MAX_COLLECTION_ITEMS) {
    throw new Error("Operator API returned invalid audit items");
  }
  return { items: payload.items.map((item) => decodeAuditItem(item)) };
}

function decodeAuditItem(value: unknown): AuditItemPayload {
  const item = record(value, "audit item");
  return {
    seq: integer(item.seq, "audit seq"),
    event_id: text(item.event_id, "audit event_id", 1024)!,
    actor: text(item.actor, "audit actor", 256)!,
    action_kind: text(item.action_kind, "audit action_kind", 256)!,
    mode: text(item.mode, "audit mode", 64)!,
    recorded_at: text(item.recorded_at, "audit recorded_at", 128)!,
  };
}

function decodeChatReply(value: unknown, url: string): ChatReply {
  const payload = record(value, "chat response");
  if (typeof payload.answer !== "string" || typeof payload.model !== "string") {
    throw new Error(`Operator API ${url} returned an invalid chat response`);
  }
  if (
    payload.latency_ms !== undefined &&
    (typeof payload.latency_ms !== "number" ||
      !Number.isFinite(payload.latency_ms) ||
      payload.latency_ms < 0)
  ) {
    throw new Error(`Operator API ${url} returned an invalid chat response`);
  }
  if (payload.verification !== undefined && !isRecord(payload.verification)) {
    throw new Error(`Operator API ${url} returned an invalid chat response`);
  }
  if (
    [...payload.answer].length > MAX_CHAT_ANSWER_CODE_POINTS ||
    [...payload.model].length > 256
  ) {
    throw new Error(`Operator API ${url} returned an invalid chat response`);
  }
  const answer = safeDisplayText(payload.answer);
  const model = safeDisplayLine(payload.model, 256);
  if (answer.trim().length === 0 || model.length === 0) {
    throw new Error(`Operator API ${url} returned an invalid chat response`);
  }
  return {
    answer,
    model,
    ...(payload.latency_ms === undefined ? {} : { latency_ms: payload.latency_ms }),
    ...(payload.verification === undefined ? {} : { verification: payload.verification }),
  };
}

/** Fetch the whole console snapshot in parallel. */
export async function fetchSnapshot(
  baseUrl: string,
  options: OperatorApiRequestOptions = {},
): Promise<ReadModelSnapshot> {
  const [kpi, hil, audit] = await Promise.all([
    optionalProjection(() => fetchKpi(baseUrl, options)),
    optionalProjection(() => fetchHilItems(baseUrl, options)),
    optionalProjection(() => fetchAuditItems(baseUrl, 8, options)),
  ]);
  return { kpi, hil, audit };
}

async function optionalProjection<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (
      error instanceof OperatorApiError &&
      (error.status === 404 || error.status === 501 || error.status === 503)
    ) {
      return null;
    }
    throw error;
  }
}
