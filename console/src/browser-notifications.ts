import type { LiveStageEvent } from "./hooks/use-live-stream";
import { routeHref } from "./router";

const STORAGE_PREFIX = "fdai:console:browser-notifications:v1";
const DELIVERY_PREFIX = "fdai:console:browser-notification-delivery:v1";
const SAFE_EVENT_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const SAFE_CORRELATION_ID = /^[\x21-\x7E]{1,256}$/;
const DELIVERY_DEDUP_MS = 5 * 60_000;
const DELIVERY_RATE_WINDOW_MS = 60_000;
const DELIVERY_RATE_LIMIT = 5;
const DELIVERY_LEDGER_LIMIT = 32;
export const CONSOLE_WEB_NOTIFICATION_CHANNEL_ID = "console-web";
export const BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE =
  "fdai.console-web-notification.acknowledged";
export const BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_QUERY = "fdai_notification_ack";
const FAILURE_OUTCOMES: ReadonlySet<string> = new Set([
  "failed",
  "failure",
  "rollback",
  "rolled_back",
  "timed_out",
]);

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem" | "removeItem">;
type DeliveryStorage = StorageReader & StorageWriter;

interface BrowserAlertDeliveryEntry {
  readonly tag: string;
  readonly claimedAt: number;
  readonly deliveredAt: number | null;
  readonly acknowledgedAt: number | null;
}

export type BrowserAlertKind = "approval" | "denied" | "failed";

export interface BrowserAlert {
  readonly kind: BrowserAlertKind;
  readonly tag: string;
  readonly path: string;
}

export interface BrowserNotificationEnvironment {
  readonly secureContext: boolean;
  readonly notificationApi: boolean;
  readonly serviceWorkerApi: boolean;
}

export type BrowserAlertClaim = "claimed" | "duplicate" | "rate-limited" | "unavailable";

export interface BrowserAlertDeliveryReceipt {
  readonly channelId: typeof CONSOLE_WEB_NOTIFICATION_CHANNEL_ID;
  readonly tag: string;
  readonly deliveredAt: number;
  readonly acknowledgedAt: number | null;
}

export interface BrowserAlertAcknowledgement {
  readonly tag: string;
  readonly acknowledgedAt: number;
}

export function browserNotificationPreferenceKey(principalId: string | null | undefined): string {
  return `${STORAGE_PREFIX}:${principalId?.trim() || "local"}`;
}

export function browserNotificationDeliveryKey(principalId: string | null | undefined): string {
  return `${DELIVERY_PREFIX}:${principalId?.trim() || "local"}`;
}

export function readBrowserNotificationPreference(
  principalId?: string | null,
  storage: StorageReader | null = browserStorage(),
): boolean {
  if (storage === null) return false;
  try {
    return storage.getItem(browserNotificationPreferenceKey(principalId)) === "enabled";
  } catch {
    return false;
  }
}

export function writeBrowserNotificationPreference(
  enabled: boolean,
  principalId?: string | null,
  storage: StorageWriter | null = browserStorage(),
): boolean {
  if (storage === null) return false;
  try {
    const key = browserNotificationPreferenceKey(principalId);
    if (enabled) storage.setItem(key, "enabled");
    else storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function claimBrowserAlertDelivery(
  tag: string,
  principalId?: string | null,
  now = Date.now(),
  storage: DeliveryStorage | null = browserStorage(),
): BrowserAlertClaim {
  if (storage === null || !isSafeNotificationTag(tag) || !isSafeTimestamp(now)) {
    return "unavailable";
  }
  const key = browserNotificationDeliveryKey(principalId);
  try {
    const entries = readDeliveryEntries(storage.getItem(key)).filter(
      (entry) => entry.claimedAt <= now && entry.claimedAt > now - DELIVERY_DEDUP_MS,
    );
    if (entries.some((entry) => entry.tag === tag)) return "duplicate";
    if (
      entries.filter((entry) => entry.claimedAt > now - DELIVERY_RATE_WINDOW_MS).length
      >= DELIVERY_RATE_LIMIT
    ) {
      return "rate-limited";
    }
    const next = [
      ...entries,
      { tag, claimedAt: now, deliveredAt: null, acknowledgedAt: null },
    ].slice(-DELIVERY_LEDGER_LIMIT);
    storage.setItem(key, JSON.stringify(next));
    return "claimed";
  } catch {
    return "unavailable";
  }
}

export function releaseBrowserAlertDelivery(
  tag: string,
  principalId?: string | null,
  storage: DeliveryStorage | null = browserStorage(),
): void {
  if (storage === null) return;
  const key = browserNotificationDeliveryKey(principalId);
  try {
    const entries = readDeliveryEntries(storage.getItem(key)).filter((entry) => entry.tag !== tag);
    storage.setItem(key, JSON.stringify(entries));
  } catch {
    // A failed release expires through the bounded deduplication window.
  }
}

export function recordBrowserAlertDelivered(
  tag: string,
  principalId?: string | null,
  now = Date.now(),
  storage: DeliveryStorage | null = browserStorage(),
): BrowserAlertDeliveryReceipt | null {
  return updateBrowserAlertReceipt(tag, principalId, now, "delivered", storage);
}

export function acknowledgeBrowserAlertDelivery(
  tag: string,
  principalId?: string | null,
  now = Date.now(),
  storage: DeliveryStorage | null = browserStorage(),
): BrowserAlertDeliveryReceipt | null {
  return updateBrowserAlertReceipt(tag, principalId, now, "acknowledged", storage);
}

export function readLatestBrowserAlertReceipt(
  principalId?: string | null,
  now = Date.now(),
  storage: StorageReader | null = browserStorage(),
): BrowserAlertDeliveryReceipt | null {
  if (storage === null) return null;
  try {
    const entries = readDeliveryEntries(
      storage.getItem(browserNotificationDeliveryKey(principalId)),
    )
      .filter(
        (entry) =>
          entry.claimedAt <= now
          && entry.claimedAt > now - DELIVERY_DEDUP_MS
          && entry.deliveredAt !== null
          && entry.deliveredAt <= now
          && (entry.acknowledgedAt === null || entry.acknowledgedAt <= now),
      )
      .sort((left, right) => right.claimedAt - left.claimedAt);
    const latest = entries[0];
    return latest === undefined || latest.deliveredAt === null ? null : deliveryReceipt(latest);
  } catch {
    return null;
  }
}

export function decodeBrowserAlertAcknowledgement(
  value: unknown,
): BrowserAlertAcknowledgement | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (
    candidate["type"] !== BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE
    || candidate["channel_id"] !== CONSOLE_WEB_NOTIFICATION_CHANNEL_ID
    || !isSafeNotificationTag(candidate["tag"])
    || !isSafeTimestamp(candidate["acknowledged_at"])
  ) {
    return null;
  }
  return {
    tag: candidate["tag"],
    acknowledgedAt: candidate["acknowledged_at"],
  };
}

export function browserAlertNotificationData(
  alert: BrowserAlert,
  baseUrl: string,
): {
  readonly channel_id: typeof CONSOLE_WEB_NOTIFICATION_CHANNEL_ID;
  readonly tag: string;
  readonly path: string;
} {
  return {
    channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
    tag: alert.tag,
    path: browserNotificationTargetPath(alert.path, baseUrl),
  };
}

export function browserNotificationsSupported(
  environment: BrowserNotificationEnvironment = currentEnvironment(),
): boolean {
  return environment.secureContext
    && environment.notificationApi
    && environment.serviceWorkerApi;
}

export function browserNotificationWorkerPaths(baseUrl: string): {
  readonly scriptUrl: string;
  readonly scope: string;
} {
  if (!baseUrl.startsWith("/") || baseUrl.startsWith("//") || baseUrl.includes("..")) {
    throw new Error("Console base URL must be a same-origin absolute path.");
  }
  const scope = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  return { scriptUrl: `${scope}notification-sw.js`, scope };
}

export function browserNotificationTargetPath(path: string, baseUrl: string): string {
  const { scope } = browserNotificationWorkerPaths(baseUrl);
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Notification target must be a same-origin absolute path.");
  }
  return scope === "/" ? path : `${scope.slice(0, -1)}${path}`;
}

export function browserAlertForLiveEvent(event: LiveStageEvent): BrowserAlert | null {
  if (event.source === "replay") return null;
  if (!SAFE_EVENT_ID.test(event.event_id) || !SAFE_CORRELATION_ID.test(event.correlation_id)) {
    return null;
  }

  const detail = event.detail ?? {};
  const decision = normalizedDetail(detail, event.stage === "audit" ? "decision" : "gate_decision");
  const outcome = normalizedDetail(detail, "outcome");
  let kind: BrowserAlertKind | null = null;

  if (event.phase === "failed") kind = "failed";
  else if (event.stage === "gate" && event.phase === "done" && decision === "hil") kind = "approval";
  else if (event.stage === "gate" && event.phase === "done" && decision === "deny") kind = "denied";
  else if (event.stage === "audit" && event.phase === "done" && FAILURE_OUTCOMES.has(outcome)) kind = "failed";
  if (kind === null) return null;

  return {
    kind,
    tag: `fdai:${event.event_id}`,
    path: routeHref("incidents", {
      params: { status: "all", correlation: event.correlation_id },
    }),
  };
}

function normalizedDetail(detail: Record<string, unknown>, key: string): string {
  const value = detail[key];
  return typeof value === "string" && value.length <= 64 ? value.trim().toLowerCase() : "";
}

function updateBrowserAlertReceipt(
  tag: string,
  principalId: string | null | undefined,
  now: number,
  transition: "delivered" | "acknowledged",
  storage: DeliveryStorage | null,
): BrowserAlertDeliveryReceipt | null {
  if (storage === null || !isSafeNotificationTag(tag) || !isSafeTimestamp(now)) return null;
  const key = browserNotificationDeliveryKey(principalId);
  try {
    const entries = readDeliveryEntries(storage.getItem(key));
    const current = entries.find((entry) => entry.tag === tag);
    if (
      current === undefined
      || current.claimedAt > now
      || (current.deliveredAt !== null && current.deliveredAt > now)
      || (current.acknowledgedAt !== null && current.acknowledgedAt > now)
    ) {
      return null;
    }
    if (transition === "acknowledged" && current.deliveredAt === null) return null;
    const updated: BrowserAlertDeliveryEntry = {
      ...current,
      deliveredAt: current.deliveredAt ?? now,
      acknowledgedAt: transition === "acknowledged"
        ? current.acknowledgedAt ?? now
        : current.acknowledgedAt,
    };
    storage.setItem(
      key,
      JSON.stringify(entries.map((entry) => entry.tag === tag ? updated : entry)),
    );
    return deliveryReceipt(updated);
  } catch {
    return null;
  }
}

function deliveryReceipt(entry: BrowserAlertDeliveryEntry): BrowserAlertDeliveryReceipt {
  if (entry.deliveredAt === null) {
    throw new Error("browser alert delivery receipt requires deliveredAt");
  }
  return {
    channelId: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
    tag: entry.tag,
    deliveredAt: entry.deliveredAt,
    acknowledgedAt: entry.acknowledgedAt,
  };
}

function readDeliveryEntries(value: string | null): readonly BrowserAlertDeliveryEntry[] {
  if (value === null) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((entry) => {
      if (typeof entry !== "object" || entry === null || Array.isArray(entry)) return [];
      const candidate = entry as Record<string, unknown>;
      const claimedAt = isSafeTimestamp(candidate["claimedAt"])
        ? candidate["claimedAt"]
        : candidate["at"];
      if (!isSafeNotificationTag(candidate["tag"]) || !isSafeTimestamp(claimedAt)) return [];
      const deliveredAt = optionalTimestamp(candidate["deliveredAt"]);
      const acknowledgedAt = optionalTimestamp(candidate["acknowledgedAt"]);
      if (
        deliveredAt === undefined
        || acknowledgedAt === undefined
        || (deliveredAt !== null && deliveredAt < claimedAt)
        || (acknowledgedAt !== null && (deliveredAt === null || acknowledgedAt < deliveredAt))
      ) {
        return [];
      }
      return [{
        tag: candidate["tag"],
        claimedAt,
        deliveredAt,
        acknowledgedAt,
      }];
    });
  } catch {
    return [];
  }
}

function optionalTimestamp(value: unknown): number | null | undefined {
  if (value === undefined || value === null) return null;
  return isSafeTimestamp(value) ? value : undefined;
}

function isSafeTimestamp(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isSafeNotificationTag(value: unknown): value is string {
  return typeof value === "string"
    && value.startsWith("fdai:")
    && SAFE_EVENT_ID.test(value.slice("fdai:".length));
}

function currentEnvironment(): BrowserNotificationEnvironment {
  return {
    secureContext: typeof window !== "undefined" && window.isSecureContext,
    notificationApi: typeof Notification !== "undefined",
    serviceWorkerApi: typeof navigator !== "undefined" && "serviceWorker" in navigator,
  };
}

function browserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
