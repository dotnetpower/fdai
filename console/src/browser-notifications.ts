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

export function browserNotificationPreferenceKey(principalId: string | null | undefined): string {
  return `${STORAGE_PREFIX}:${principalId?.trim() || "local"}`;
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
  if (storage === null) return "unavailable";
  const key = `${DELIVERY_PREFIX}:${principalId?.trim() || "local"}`;
  try {
    const entries = readDeliveryEntries(storage.getItem(key)).filter(
      (entry) => entry.at <= now && entry.at > now - DELIVERY_DEDUP_MS,
    );
    if (entries.some((entry) => entry.tag === tag)) return "duplicate";
    if (entries.filter((entry) => entry.at > now - DELIVERY_RATE_WINDOW_MS).length >= DELIVERY_RATE_LIMIT) {
      return "rate-limited";
    }
    const next = [...entries, { tag, at: now }].slice(-DELIVERY_LEDGER_LIMIT);
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
  const key = `${DELIVERY_PREFIX}:${principalId?.trim() || "local"}`;
  try {
    const entries = readDeliveryEntries(storage.getItem(key)).filter((entry) => entry.tag !== tag);
    storage.setItem(key, JSON.stringify(entries));
  } catch {
    // A failed release expires through the bounded deduplication window.
  }
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

function readDeliveryEntries(value: string | null): readonly { readonly tag: string; readonly at: number }[] {
  if (value === null) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((entry) => {
      if (typeof entry !== "object" || entry === null || Array.isArray(entry)) return [];
      const candidate = entry as Record<string, unknown>;
      return typeof candidate.tag === "string"
        && SAFE_EVENT_ID.test(candidate.tag.replace(/^fdai:/, ""))
        && typeof candidate.at === "number"
        && Number.isSafeInteger(candidate.at)
        ? [{ tag: candidate.tag, at: candidate.at }]
        : [];
    });
  } catch {
    return [];
  }
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
