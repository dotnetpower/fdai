export interface ConsoleInboxItem {
  readonly inbox_id: string;
  readonly category: string;
  readonly severity: "info" | "warn" | "error" | "critical";
  readonly title: string;
  readonly body: string;
  readonly correlation_id: string;
  readonly recorded_at: string;
}

const ID = /^[a-f0-9]{32}$/;
const SEVERITIES = ["info", "warn", "error", "critical"];
const STORAGE_KEY = "fdai:console:inbox-seen:v1";

function text(row: Record<string, unknown>, key: string, max: number, required = true): string {
  const value = row[key];
  if (typeof value !== "string" || value.length > max || (required && value.trim() === "")) {
    throw new Error(`Invalid Console inbox ${key}`);
  }
  return value;
}

export function decodeConsoleInbox(value: unknown): readonly ConsoleInboxItem[] {
  if (typeof value !== "object" || value === null) throw new Error("Invalid Console inbox page");
  const page = value as Record<string, unknown>;
  if (page.source !== "runtime-observed" || page.execution_authority !== false
      || !Array.isArray(page.items) || !Number.isSafeInteger(page.total_count)) {
    throw new Error("Console inbox is not an authoritative bounded projection");
  }
  const seen = new Set<string>();
  return page.items.map((item: unknown): ConsoleInboxItem => {
    if (typeof item !== "object" || item === null) throw new Error("Invalid Console inbox record");
    const row = item as Record<string, unknown>;
    const id = text(row, "inbox_id", 32);
    const severity = text(row, "severity", 16);
    const recordedAt = text(row, "recorded_at", 64);
    if (!ID.test(id) || seen.has(id) || !SEVERITIES.includes(severity)
        || row.execution_authority !== false || Number.isNaN(Date.parse(recordedAt))) {
      throw new Error("Invalid Console inbox identity, severity, or authority");
    }
    seen.add(id);
    return {
      inbox_id: id,
      category: text(row, "category", 128),
      severity: severity as ConsoleInboxItem["severity"],
      title: text(row, "title", 300),
      body: text(row, "body", 4000, false),
      correlation_id: text(row, "correlation_id", 256),
      recorded_at: recordedAt,
    };
  });
}

export async function loadConsoleInbox(client: {
  panel(path: string, params?: Record<string, string>): Promise<unknown>;
}): Promise<readonly ConsoleInboxItem[]> {
  return decodeConsoleInbox(await client.panel("/notifications/inbox", { limit: "100" }));
}

type InboxStorage = Pick<Storage, "getItem" | "setItem">;

function defaultStorage(): InboxStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The unread marker is a per-browser convenience; it grants and hides nothing. */
export function inboxLastSeen(storage: InboxStorage | null = defaultStorage()): number {
  try {
    const raw = storage?.getItem(STORAGE_KEY) ?? null;
    const parsed = raw === null ? 0 : Number(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  } catch {
    return 0;
  }
}

export function markInboxSeen(
  items: readonly ConsoleInboxItem[],
  storage: InboxStorage | null = defaultStorage(),
): void {
  const newest = items.reduce((max, item) => Math.max(max, Date.parse(item.recorded_at)), 0);
  if (newest === 0) return;
  try {
    storage?.setItem(STORAGE_KEY, String(newest));
  } catch {
    // An unavailable store only means the unread count is not remembered.
  }
}

export function unseenInboxItems(
  items: readonly ConsoleInboxItem[],
  storage: InboxStorage | null = defaultStorage(),
): readonly ConsoleInboxItem[] {
  const since = inboxLastSeen(storage);
  return items.filter((item) => Date.parse(item.recorded_at) > since);
}
