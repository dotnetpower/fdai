import type { BrowserAlert } from "./browser-notifications";
import { routeHref } from "./router";

export interface CurrentFinding {
  readonly finding_id: string;
  readonly revision?: number;
  readonly notification_version: number;
  readonly notification_reason: "opened" | "escalated" | "recovered";
  readonly notification_changed_at: string;
  readonly resource_ref: string;
  readonly resource_kind: string;
  readonly signal: string;
  readonly severity: "low" | "medium" | "high" | "critical";
  readonly status: "active" | "resolved";
  readonly observation: string;
  readonly observation_key?: string;
  readonly observation_digest?: string;
  readonly first_seen_at?: string;
  readonly occurred_at: string;
  readonly recorded_at?: string;
  readonly current_state?: string;
  readonly evidence_complete: boolean;
  readonly evidence_state: string;
  readonly recovery_closed?: boolean | null;
  readonly assessed_by?: string | null;
  readonly evidence_gaps: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly publication?: string;
}

interface FindingPage {
  readonly items: readonly CurrentFinding[];
  readonly next_cursor: string | null;
  readonly total_count: number;
}

const ID = /^[a-f0-9]{64}$/;

export function decodeFindingPage(value: unknown): FindingPage {
  if (typeof value !== "object" || value === null) throw new Error("Invalid Finding page");
  const page = value as Record<string, unknown>;
  if (page.source !== "runtime-observed" || !Array.isArray(page.items)
      || !Number.isSafeInteger(page.total_count) || Number(page.total_count) < 0
      || !(page.next_cursor === null || (typeof page.next_cursor === "string" && ID.test(page.next_cursor)))) {
    throw new Error("Finding page is not an authoritative bounded projection");
  }
  const items = page.items.map((item: unknown): CurrentFinding => {
    if (typeof item !== "object" || item === null) throw new Error("Invalid Finding record");
    const row = item as Record<string, unknown>;
    if (typeof row.finding_id !== "string" || !ID.test(row.finding_id)
        || !Number.isSafeInteger(row.notification_version) || Number(row.notification_version) < 1
        || !["opened", "escalated", "recovered"].includes(String(row.notification_reason))
        || !["active", "resolved"].includes(String(row.status))
        || !["low", "medium", "high", "critical"].includes(String(row.severity))
        || row.execution_authority !== false || row.cause_claim_supported !== false
        || typeof row.evidence_complete !== "boolean"
        || !Array.isArray(row.evidence_refs) || !row.evidence_refs.every((entry) => typeof entry === "string")
        || !Array.isArray(row.evidence_gaps) || !row.evidence_gaps.every((entry) => typeof entry === "string")) {
      throw new Error("Invalid Finding identity, lifecycle, or evidence");
    }
    for (const field of ["resource_ref", "resource_kind", "signal", "observation", "evidence_state"]) {
      if (typeof row[field] !== "string" || String(row[field]).length > 2048) {
        throw new Error("Invalid Finding presentation data");
      }
    }
    for (const field of ["occurred_at", "notification_changed_at"]) {
      if (typeof row[field] !== "string" || !Number.isFinite(Date.parse(String(row[field])))) {
        throw new Error("Invalid Finding observation time");
      }
    }
    const optionalText = (key: string): string | undefined => {
      const candidate = row[key];
      return typeof candidate === "string" && candidate.trim().length > 0 && candidate.length <= 512
        ? candidate.trim()
        : undefined;
    };
    const optionalTimestamp = (key: string): string | undefined => {
      const candidate = optionalText(key);
      return candidate !== undefined && Number.isFinite(Date.parse(candidate))
        ? candidate
        : undefined;
    };
    const revision = Number.isSafeInteger(row.revision) && Number(row.revision) >= 1
      ? Number(row.revision)
      : undefined;
    const recoveryClosed = typeof row.recovery_closed === "boolean"
      ? row.recovery_closed
      : row.recovery_closed === null
        ? null
        : undefined;
    const assessedBy = optionalText("assessed_by") ?? (row.assessed_by === null ? null : undefined);
    const observationKey = optionalText("observation_key");
    const observationDigest = optionalText("observation_digest");
    const firstSeenAt = optionalTimestamp("first_seen_at");
    const recordedAt = optionalTimestamp("recorded_at");
    const currentState = optionalText("current_state");
    const publication = optionalText("publication");
    return {
      finding_id: row.finding_id,
      ...(revision !== undefined ? { revision } : {}),
      notification_version: Number(row.notification_version),
      notification_reason: row.notification_reason as CurrentFinding["notification_reason"],
      notification_changed_at: String(row.notification_changed_at),
      resource_ref: String(row.resource_ref),
      resource_kind: String(row.resource_kind),
      signal: String(row.signal),
      severity: row.severity as CurrentFinding["severity"],
      status: row.status as CurrentFinding["status"],
      observation: String(row.observation),
      ...(observationKey !== undefined ? { observation_key: observationKey } : {}),
      ...(observationDigest !== undefined ? { observation_digest: observationDigest } : {}),
      ...(firstSeenAt !== undefined ? { first_seen_at: firstSeenAt } : {}),
      occurred_at: String(row.occurred_at),
      ...(recordedAt !== undefined ? { recorded_at: recordedAt } : {}),
      ...(currentState !== undefined ? { current_state: currentState } : {}),
      evidence_complete: row.evidence_complete,
      evidence_state: String(row.evidence_state),
      ...(recoveryClosed !== undefined ? { recovery_closed: recoveryClosed } : {}),
      ...(assessedBy !== undefined ? { assessed_by: assessedBy } : {}),
      evidence_refs: row.evidence_refs,
      evidence_gaps: row.evidence_gaps,
      ...(publication !== undefined ? { publication } : {}),
    };
  });
  return { items, next_cursor: page.next_cursor as string | null, total_count: Number(page.total_count) };
}

export async function loadCurrentFindings(client: {
  panel(path: string, params?: Record<string, string>): Promise<unknown>;
}): Promise<readonly CurrentFinding[]> {
  const found = new Map<string, CurrentFinding>();
  const cursors = new Set<string>();
  const deadline = Date.now() + 30_000;
  let cursor: string | null = null;
  let expected: number | null = null;
  do {
    if (Date.now() > deadline || cursors.size >= 200) {
      throw new Error("Finding pagination exceeded its bounded collection deadline");
    }
    const params: Record<string, string> = { limit: "200" };
    if (cursor !== null) params.cursor = cursor;
    const page = decodeFindingPage(await client.panel("/findings", params));
    expected ??= page.total_count;
    if (expected !== page.total_count) throw new Error("Finding collection changed during pagination");
    for (const finding of page.items) {
      if (found.has(finding.finding_id)) throw new Error("Duplicate Finding across pages");
      found.set(finding.finding_id, finding);
    }
    cursor = page.next_cursor;
    if (cursor !== null) {
      if (cursors.has(cursor) || page.items.length === 0) throw new Error("Finding cursor made no progress");
      cursors.add(cursor);
    }
  } while (cursor !== null);
  if (found.size !== expected) throw new Error("Finding projection is incomplete");
  return [...found.values()].sort((a, b) =>
    Date.parse(b.notification_changed_at) - Date.parse(a.notification_changed_at));
}

export function findingHref(finding: CurrentFinding): string {
  return routeHref("detection-readiness", { params: { finding: finding.finding_id, data: "live" } });
}

export function findingBrowserAlert(finding: CurrentFinding): BrowserAlert {
  return {
    kind: "finding",
    tag: `fdai:finding:${finding.finding_id}:${finding.notification_version}`,
    path: findingHref(finding),
  };
}

function seenKey(finding: CurrentFinding, principalId?: string | null): string {
  return `fdai:console:finding-seen:v1:${principalId?.trim() || "local"}:${finding.finding_id}`;
}

export function findingWasSeen(finding: CurrentFinding, principalId?: string | null): boolean {
  return readFindingVersion(finding, principalId) >= finding.notification_version;
}

export function findingNeedsAttention(finding: CurrentFinding, principalId?: string | null): boolean {
  const seen = readFindingVersion(finding, principalId);
  if (seen < 0 && -seen > finding.notification_version) return false;
  return seen < finding.notification_version
    && (finding.status === "active" || finding.notification_reason === "opened" || seen !== 0);
}

function readFindingVersion(finding: CurrentFinding, principalId?: string | null): number {
  const raw = localStorage.getItem(seenKey(finding, principalId));
  if (raw === null) return 0;
  const version = Number(raw);
  if (!Number.isSafeInteger(version)) throw new Error("Finding notification history is invalid");
  return version;
}

export function markFindingPending(finding: CurrentFinding, principalId?: string | null): void {
  if (Math.abs(readFindingVersion(finding, principalId)) >= finding.notification_version) return;
  localStorage.setItem(seenKey(finding, principalId), String(-finding.notification_version));
}

export function rememberFinding(finding: CurrentFinding, principalId?: string | null): void {
  if (Math.abs(readFindingVersion(finding, principalId)) > finding.notification_version) return;
  localStorage.setItem(seenKey(finding, principalId), String(finding.notification_version));
}
