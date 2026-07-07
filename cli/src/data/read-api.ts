/**
 * Read-API client - the real data source behind `--source=api`.
 *
 * Talks to the running console read API (three GET routes: /kpi, /hil-queue,
 * /audit; see `src/fdai/delivery/read_api/main.py`). This is the same read-only
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

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`read API ${url} -> ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

const norm = (baseUrl: string): string => baseUrl.replace(/\/$/, "");

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
