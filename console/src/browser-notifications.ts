import type { LiveStageEvent } from "./hooks/use-live-stream";
import { routeHref } from "./router";

const STORAGE_PREFIX = "fdai:console:browser-notifications:v1";
const DELIVERY_PREFIX = "fdai:console:browser-notification-delivery:v1";
const SAFE_EVENT_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const SAFE_CORRELATION_ID = /^[\x21-\x7E]{1,256}$/;
const SAFE_ACKNOWLEDGEMENT_TOKEN = /^[a-f0-9]{32}$/;
const DELIVERY_DEDUP_MS = 5 * 60_000;
const DELIVERY_RECEIPT_RETENTION_MS = 7 * 24 * 60 * 60_000;
const DELIVERY_RATE_WINDOW_MS = 60_000;
const DELIVERY_RATE_LIMIT = 5;
const DELIVERY_LEDGER_LIMIT = 32;
export const BROWSER_NOTIFICATION_WORKER_TIMEOUT_MS = 10_000;
export const BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT =
  "fdai:console-web-notification-preference-changed";
export const CONSOLE_WEB_NOTIFICATION_CHANNEL_ID = "console-web";
export const BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE =
  "fdai.console-web-notification.acknowledged";
const BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_FRAGMENT = "fdai-notification-ack";
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
  readonly acknowledgementToken: string | null;
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
  readonly lockManagerApi: boolean;
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
  readonly acknowledgementToken: string;
  readonly acknowledgedAt: number;
}

export interface BrowserAlertAcknowledgementMessage {
  readonly tag: string;
  readonly acknowledgementToken: string;
}

export type BrowserAlertDeliveryStatus = "ready" | "delivered" | "acknowledged";

export function browserNotificationPreferenceKey(principalId: string | null | undefined): string {
  return `${STORAGE_PREFIX}:${principalId?.trim() || "local"}`;
}

export function isBrowserNotificationPreferenceStorageKey(
  key: string | null,
  principalId?: string | null,
): boolean {
  return key === null || key === browserNotificationPreferenceKey(principalId);
}

export function isBrowserNotificationPreferenceChange(
  detail: unknown,
  principalId?: string | null,
): boolean {
  return detail === browserNotificationPreferenceKey(principalId);
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
    publishBrowserNotificationPreferenceChange(key);
    return true;
  } catch {
    return false;
  }
}

export function requireBrowserNotificationPreferenceWrite(
  enabled: boolean,
  principalId?: string | null,
  storage: StorageWriter | null = browserStorage(),
): void {
  if (!writeBrowserNotificationPreference(enabled, principalId, storage)) {
    throw new Error("Console web notification preference storage is unavailable.");
  }
}

export function claimBrowserAlertDelivery(
  tag: string,
  principalId?: string | null,
  now = Date.now(),
  storage: DeliveryStorage | null = browserStorage(),
  tokenFactory: () => string | null = createBrowserAcknowledgementToken,
): BrowserAlertClaim {
  if (storage === null || !isSafeNotificationTag(tag) || !isSafeTimestamp(now)) {
    return "unavailable";
  }
  const key = browserNotificationDeliveryKey(principalId);
  try {
    const acknowledgementToken = tokenFactory();
    if (!isSafeAcknowledgementToken(acknowledgementToken)) return "unavailable";
    const entries = readDeliveryEntries(storage.getItem(key)).filter(
      (entry) =>
        entry.claimedAt <= now
        && entry.claimedAt > now - DELIVERY_RECEIPT_RETENTION_MS,
    );
    if (
      entries.some(
        (entry) => entry.tag === tag && entry.claimedAt > now - DELIVERY_DEDUP_MS,
      )
    ) {
      return "duplicate";
    }
    if (
      entries.filter((entry) => entry.claimedAt > now - DELIVERY_RATE_WINDOW_MS).length
      >= DELIVERY_RATE_LIMIT
    ) {
      return "rate-limited";
    }
    const next = [
      ...entries.filter((entry) => entry.tag !== tag),
      {
        tag,
        acknowledgementToken,
        claimedAt: now,
        deliveredAt: null,
        acknowledgedAt: null,
      },
    ].slice(-DELIVERY_LEDGER_LIMIT);
    writeDeliveryEntries(storage, key, next);
    return "claimed";
  } catch {
    return "unavailable";
  }
}

export function releaseBrowserAlertDelivery(
  tag: string,
  acknowledgementToken: string,
  principalId?: string | null,
  storage: DeliveryStorage | null = browserStorage(),
): void {
  if (storage === null || !isSafeAcknowledgementToken(acknowledgementToken)) return;
  const key = browserNotificationDeliveryKey(principalId);
  try {
    const entries = readDeliveryEntries(storage.getItem(key)).filter(
      (entry) =>
        entry.tag !== tag
        || entry.acknowledgementToken !== acknowledgementToken,
    );
    writeDeliveryEntries(storage, key, entries);
  } catch {
    // A failed release expires through the bounded deduplication window.
  }
}

export function recordBrowserAlertDelivered(
  tag: string,
  acknowledgementToken: string,
  principalId?: string | null,
  now = Date.now(),
  storage: DeliveryStorage | null = browserStorage(),
): BrowserAlertDeliveryReceipt | null {
  return updateBrowserAlertReceipt(
    tag,
    principalId,
    now,
    "delivered",
    storage,
    acknowledgementToken,
  );
}

export function readBrowserAlertAcknowledgementToken(
  tag: string,
  principalId?: string | null,
  storage: StorageReader | null = browserStorage(),
): string | null {
  if (storage === null || !isSafeNotificationTag(tag)) return null;
  try {
    return readDeliveryEntries(storage.getItem(browserNotificationDeliveryKey(principalId)))
      .find((entry) => entry.tag === tag)
      ?.acknowledgementToken ?? null;
  } catch {
    return null;
  }
}

export function acknowledgeBrowserAlertDelivery(
  tag: string,
  acknowledgementToken: string,
  principalId?: string | null,
  now = Date.now(),
  storage: DeliveryStorage | null = browserStorage(),
): BrowserAlertDeliveryReceipt | null {
  return updateBrowserAlertReceipt(
    tag,
    principalId,
    now,
    "acknowledged",
    storage,
    acknowledgementToken,
  );
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
          && entry.claimedAt > now - DELIVERY_RECEIPT_RETENTION_MS
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

export function readBrowserAlertDeliveryStatus(
  principalId?: string | null,
  now = Date.now(),
  storage: StorageReader | null = browserStorage(),
): BrowserAlertDeliveryStatus {
  const receipt = readLatestBrowserAlertReceipt(principalId, now, storage);
  if (receipt === null) return "ready";
  return receipt.acknowledgedAt === null ? "delivered" : "acknowledged";
}

export function browserAlertDeliveryStatusForStorageKey(
  key: string | null,
  principalId?: string | null,
  now = Date.now(),
  storage: StorageReader | null = browserStorage(),
): BrowserAlertDeliveryStatus | null {
  if (key !== browserNotificationDeliveryKey(principalId)) return null;
  return readBrowserAlertDeliveryStatus(principalId, now, storage);
}

export function decodeBrowserAlertAcknowledgement(
  value: unknown,
): BrowserAlertAcknowledgementMessage | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (
    candidate["type"] !== BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE
    || candidate["channel_id"] !== CONSOLE_WEB_NOTIFICATION_CHANNEL_ID
    || !isSafeNotificationTag(candidate["tag"])
    || !isSafeAcknowledgementToken(candidate["acknowledgement_token"])
  ) {
    return null;
  }
  return {
    tag: candidate["tag"],
    acknowledgementToken: candidate["acknowledgement_token"],
  };
}

export function trustedBrowserAlertAcknowledgement(
  value: unknown,
  isTrusted: boolean,
  now = Date.now(),
): BrowserAlertAcknowledgement | null {
  if (!isTrusted || !isSafeTimestamp(now)) return null;
  const message = decodeBrowserAlertAcknowledgement(value);
  return message === null ? null : { ...message, acknowledgedAt: now };
}

export function decodeBrowserAlertAcknowledgementFragment(
  hash: string,
): BrowserAlertAcknowledgementMessage | null {
  const prefix = `#${BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_FRAGMENT}?`;
  if (!hash.startsWith(prefix)) return null;
  const params = new URLSearchParams(hash.slice(prefix.length));
  if (
    [...params.keys()].some((key) => key !== "tag" && key !== "token")
    || params.getAll("tag").length !== 1
    || params.getAll("token").length !== 1
  ) {
    return null;
  }
  return decodeBrowserAlertAcknowledgement({
    type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
    channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
    tag: params.get("tag"),
    acknowledgement_token: params.get("token"),
  });
}

export function browserAlertNotificationData(
  alert: BrowserAlert,
  baseUrl: string,
  acknowledgementToken: string,
): {
  readonly channel_id: typeof CONSOLE_WEB_NOTIFICATION_CHANNEL_ID;
  readonly tag: string;
  readonly acknowledgement_token: string;
  readonly path: string;
} {
  if (!isSafeAcknowledgementToken(acknowledgementToken)) {
    throw new Error("Console web acknowledgement token is invalid.");
  }
  return {
    channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
    tag: alert.tag,
    acknowledgement_token: acknowledgementToken,
    path: browserNotificationTargetPath(alert.path, baseUrl),
  };
}

export function browserNotificationsSupported(
  environment: BrowserNotificationEnvironment = currentEnvironment(),
): boolean {
  return environment.secureContext
    && environment.notificationApi
    && environment.serviceWorkerApi
    && environment.lockManagerApi;
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

export function withBrowserNotificationDeadline<T>(
  operation: Promise<T>,
  timeoutMs = BROWSER_NOTIFICATION_WORKER_TIMEOUT_MS,
): Promise<T> {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    return Promise.reject(new Error("Browser notification timeout MUST be positive."));
  }
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error("Browser notification service worker timed out.")),
      timeoutMs,
    );
    operation.then(
      (value) => {
        clearTimeout(timeout);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

export function browserNotificationTargetPath(path: string, baseUrl: string): string {
  const { scope } = browserNotificationWorkerPaths(baseUrl);
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Notification target must be a same-origin absolute path.");
  }
  return scope === "/" ? path : `${scope.slice(0, -1)}${path}`;
}

export function browserAlertForLiveEvent(event: LiveStageEvent): BrowserAlert | null {
  if (event.source !== "runtime-observed") return null;
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
  acknowledgementToken: string | null = null,
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
      || current.acknowledgementToken !== acknowledgementToken
    ) {
      return null;
    }
    const updated: BrowserAlertDeliveryEntry = {
      ...current,
      deliveredAt: current.deliveredAt ?? now,
      acknowledgedAt: transition === "acknowledged"
        ? current.acknowledgedAt ?? now
        : current.acknowledgedAt,
    };
    writeDeliveryEntries(
      storage,
      key,
      entries.map((entry) => entry.tag === tag ? updated : entry),
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
        acknowledgementToken: isSafeAcknowledgementToken(candidate["acknowledgementToken"])
          ? candidate["acknowledgementToken"]
          : null,
        claimedAt,
        deliveredAt,
        acknowledgedAt,
      }];
    });
  } catch {
    return [];
  }
}

function writeDeliveryEntries(
  storage: StorageWriter,
  key: string,
  entries: readonly BrowserAlertDeliveryEntry[],
): void {
  storage.setItem(
    key,
    JSON.stringify(entries.map((entry) => ({
      ...entry,
      at: entry.claimedAt,
    }))),
  );
}

function createBrowserAcknowledgementToken(): string | null {
  if (
    typeof globalThis.crypto === "undefined"
    || typeof globalThis.crypto.getRandomValues !== "function"
  ) {
    return null;
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isSafeAcknowledgementToken(value: unknown): value is string {
  return typeof value === "string" && SAFE_ACKNOWLEDGEMENT_TOKEN.test(value);
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
    lockManagerApi: typeof navigator !== "undefined"
      && "locks" in navigator
      && typeof navigator.locks.request === "function",
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

function publishBrowserNotificationPreferenceChange(key: string): void {
  if (typeof window === "undefined" || typeof CustomEvent === "undefined") return;
  window.dispatchEvent(new CustomEvent(
    BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
    { detail: key },
  ));
}
