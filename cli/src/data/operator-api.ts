/**
 * Operator API client - the real data source behind `--source=api`.
 *
 * Talks to the running console Operator API (three GET routes: /kpi, /hil-queue,
 * /audit; see `src/fdai/delivery/operator_api/main.py`). This is the same read-only
 * surface the console SPA uses; the CLI just renders it differently. No mutating
 * calls - the console never executes an action.
 */

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
  kpi: KpiPayload;
  hil: HilItemPayload[];
  audit: AuditItemPayload[];
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

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) {
    throw await responseError(res, url);
  }
  return (await res.json()) as T;
}

async function responseError(res: Response, url: string): Promise<Error> {
  let detail = "";
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // Status and statusText remain actionable when the body is not JSON.
  }
  const suffix = detail ? `: ${detail.replace(/\s+/g, " ").slice(0, 500)}` : "";
  const statusText = res.statusText ? ` ${res.statusText}` : "";
  return new Error(`Operator API ${url} -> ${res.status}${statusText}${suffix}`);
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
  } = {},
): Promise<ChatReply> {
  const url = `${norm(baseUrl)}/chat`;
  const res = await fetch(url, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_CHAT_TIMEOUT_MS),
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
  const payload = (await res.json()) as Partial<ChatReply>;
  if (typeof payload.answer !== "string" || typeof payload.model !== "string") {
    throw new Error(`Operator API ${url} returned an invalid chat response`);
  }
  return payload as ChatReply;
}

export async function fetchKpi(baseUrl: string): Promise<KpiPayload> {
  return getJson<KpiPayload>(`${norm(baseUrl)}/kpi`);
}

export async function fetchHilItems(baseUrl: string): Promise<HilItemPayload[]> {
  const page = await getJson<{ items: HilItemPayload[] }>(
    `${norm(baseUrl)}/hil-queue`,
  );
  return page.items;
}

export async function fetchAuditItems(
  baseUrl: string,
  limit = 8,
): Promise<AuditItemPayload[]> {
  const page = await getJson<{ items: AuditItemPayload[] }>(
    `${norm(baseUrl)}/audit?limit=${limit}`,
  );
  return page.items;
}

/** Fetch the whole console snapshot in parallel. */
export async function fetchSnapshot(baseUrl: string): Promise<ReadModelSnapshot> {
  const [kpi, hil, audit] = await Promise.all([
    fetchKpi(baseUrl),
    fetchHilItems(baseUrl),
    fetchAuditItems(baseUrl),
  ]);
  return { kpi, hil, audit };
}
