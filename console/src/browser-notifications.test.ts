import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { LiveStageEvent } from "./hooks/use-live-stream";
import { consoleDataMode } from "./console-data-mode";
import {
  acknowledgeBrowserAlertDelivery,
  acknowledgeBrowserAlertDeliveryForClaim,
  BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
  BROWSER_NOTIFICATION_DELIVERY_CHANGED_EVENT,
  browserAlertDeliveryStatusForStorageKey,
  browserAlertNotificationData,
  browserAlertForLiveEvent,
  BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT,
  CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
  decodeBrowserAlertAcknowledgement,
  decodeBrowserAlertAcknowledgementFragment,
  isBrowserNotificationPreferenceStorageKey,
  isBrowserNotificationDeliveryChange,
  isBrowserNotificationPreferenceChange,
  browserNotificationPreferenceKey,
  browserNotificationsSupported,
  browserNotificationTargetPath,
  browserNotificationWorkerPaths,
  claimBrowserAlertDelivery,
  readBrowserAlertAcknowledgementToken,
  readBrowserAlertDeliveryStatus,
  readLatestBrowserAlertReceipt,
  readBrowserNotificationPreference,
  recordBrowserAlertDelivered,
  releaseBrowserAlertDelivery,
  requireBrowserNotificationPreferenceWrite,
  withBrowserNotificationDeadline,
  writeBrowserNotificationPreference,
} from "./browser-notifications";

const ACKNOWLEDGEMENT_TOKEN = "a".repeat(32);

beforeEach(() => {
  vi.stubGlobal("navigator", {
    locks: {
      request: async (_name: string, callback: () => unknown) => callback(),
    },
  });
});

function indexedStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => { values.delete(key); },
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function event(overrides: Partial<LiveStageEvent> = {}): LiveStageEvent {
  return {
    event_id: "event-1",
    correlation_id: "correlation-1",
    stage: "gate",
    phase: "done",
    source: "runtime-observed",
    ts: "2026-07-23T00:00:00Z",
    detail: { gate_decision: "hil" },
    ...overrides,
  };
}

function acknowledgementToken(
  storage: Pick<Storage, "getItem">,
  principalId: string,
  tag: string,
): string {
  const token = readBrowserAlertAcknowledgementToken(tag, principalId, storage);
  if (token === null) throw new Error("test claim did not record an acknowledgement token");
  return token;
}

describe("browser notification boundary", () => {
  test("classifies only approval, denial, and failure outcomes", () => {
    expect(browserAlertForLiveEvent(event())?.kind).toBe("approval");
    expect(browserAlertForLiveEvent(event({ detail: { gate_decision: "deny" } }))?.kind).toBe("denied");
    expect(browserAlertForLiveEvent(event({ stage: "execute", phase: "failed", error: "secret" }))?.kind)
      .toBe("failed");
    expect(browserAlertForLiveEvent(event({ stage: "audit", detail: { outcome: "rolled_back" } }))?.kind)
      .toBe("failed");
    expect(browserAlertForLiveEvent(event({ stage: "audit", detail: { outcome: "succeeded" } }))).toBeNull();
  });

  test("accepts only runtime-observed events with safe identifiers", () => {
    const { source: _source, ...missingSource } = event();
    expect(browserAlertForLiveEvent(event({ source: "replay" }))).toBeNull();
    expect(browserAlertForLiveEvent(event({ source: "synthetic-dev" }))).toBeNull();
    expect(browserAlertForLiveEvent(event({ source: "unknown" }))).toBeNull();
    expect(browserAlertForLiveEvent(missingSource)).toBeNull();
    expect(browserAlertForLiveEvent(event({ event_id: "event id" }))).toBeNull();
    expect(browserAlertForLiveEvent(event({ correlation_id: "line\nbreak" }))).toBeNull();
    const alert = browserAlertForLiveEvent(event({ error: "credential=value" }));
    expect(JSON.stringify(alert)).not.toContain("credential");
  });

  test("opens correlated audit evidence without assuming an Incident exists", () => {
    expect(browserAlertForLiveEvent(event())).toEqual({
      kind: "approval",
      tag: "fdai:event-1",
      path: "/audit?correlation=correlation-1&data=live",
    });
    expect(browserNotificationWorkerPaths("/fdai")).toEqual({
      scriptUrl: "/fdai/notification-sw.js",
      scope: "/fdai/",
    });
    expect(() => browserNotificationWorkerPaths("//example.com/")).toThrow();
    expect(() => browserNotificationWorkerPaths("/../escape/")).toThrow();
    expect(browserNotificationTargetPath("/incidents?status=all", "/")).toBe(
      "/incidents?status=all",
    );
    expect(browserNotificationTargetPath("/incidents?status=all", "/fdai/")).toBe(
      "/fdai/incidents?status=all",
    );
    expect(() => browserNotificationTargetPath("//example.com", "/")).toThrow();
    expect(browserAlertNotificationData(
      browserAlertForLiveEvent(event())!,
      "/",
      ACKNOWLEDGEMENT_TOKEN,
    )).toEqual({
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      acknowledgement_token: ACKNOWLEDGEMENT_TOKEN,
      path: "/audit?correlation=correlation-1&data=live",
    });
    expect(() => browserAlertNotificationData(
      browserAlertForLiveEvent(event())!,
      "/",
      "predictable",
    )).toThrow(/token is invalid/);
  });

  test("keeps runtime alert evidence live even when the tab prefers Sample", () => {
    const alert = browserAlertForLiveEvent(event({ correlation_id: "corr/one&two" }));
    const target = new URL(alert!.path, "https://console.example.com");
    expect(target.pathname).toBe("/audit");
    expect(target.searchParams.get("correlation")).toBe("corr/one&two");
    expect(target.searchParams.get("data")).toBe("live");
    expect(consoleDataMode("audit", target.searchParams, "sample")).toBe("live");
    expect(browserAlertNotificationData(alert!, "/fdai/", ACKNOWLEDGEMENT_TOKEN).path)
      .toBe("/fdai/audit?correlation=corr%2Fone%26two&data=live");
  });

  test("scopes opt-in storage to the browser principal", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    expect(browserNotificationPreferenceKey("principal-a")).not.toBe(
      browserNotificationPreferenceKey("principal-b"),
    );
    expect(writeBrowserNotificationPreference(true, "principal-a", storage)).toBe(true);
    expect(readBrowserNotificationPreference("principal-a", storage)).toBe(true);
    expect(readBrowserNotificationPreference("principal-b", storage)).toBe(false);
    expect(writeBrowserNotificationPreference(false, "principal-a", storage)).toBe(true);
    expect(readBrowserNotificationPreference("principal-a", storage)).toBe(false);
    expect(isBrowserNotificationPreferenceStorageKey(
      browserNotificationPreferenceKey("principal-a"),
      "principal-a",
    )).toBe(true);
    expect(isBrowserNotificationPreferenceStorageKey(
      browserNotificationPreferenceKey("principal-b"),
      "principal-a",
    )).toBe(false);
    expect(isBrowserNotificationPreferenceStorageKey(null, "principal-a")).toBe(true);
    expect(isBrowserNotificationPreferenceChange(
      browserNotificationPreferenceKey("principal-a"),
      "principal-a",
    )).toBe(true);
    expect(isBrowserNotificationPreferenceChange(
      browserNotificationPreferenceKey("principal-b"),
      "principal-a",
    )).toBe(false);
    expect(BROWSER_NOTIFICATION_PREFERENCE_CHANGED_EVENT).toContain("preference-changed");
  });

  test("fails explicit preference changes when browser storage is unavailable", () => {
    expect(() => requireBrowserNotificationPreferenceWrite(true, "principal-a", null))
      .toThrow(/storage is unavailable/);
    expect(() => requireBrowserNotificationPreferenceWrite(true, "principal-a", {
      setItem: () => { throw new Error("quota"); },
      removeItem: () => { throw new Error("quota"); },
    })).toThrow(/storage is unavailable/);
  });

  test("requires every secure browser capability", () => {
    expect(browserNotificationsSupported({
      secureContext: true,
      notificationApi: true,
      serviceWorkerApi: true,
      lockManagerApi: true,
    })).toBe(true);
    expect(browserNotificationsSupported({
      secureContext: false,
      notificationApi: true,
      serviceWorkerApi: true,
      lockManagerApi: true,
    })).toBe(false);
    expect(browserNotificationsSupported({
      secureContext: true,
      notificationApi: true,
      serviceWorkerApi: true,
      lockManagerApi: false,
    })).toBe(false);
  });

  test("bounds service worker registration and readiness waits", async () => {
    vi.useFakeTimers();
    const pending = withBrowserNotificationDeadline(
      new Promise<never>(() => undefined),
      10,
    );
    const timedOut = expect(pending).rejects.toThrow(/service worker timed out/);
    await vi.advanceTimersByTimeAsync(10);
    await timedOut;
    await expect(withBrowserNotificationDeadline(Promise.resolve("ready"), 0))
      .rejects.toThrow(/timeout MUST be positive/);
  });

  test("deduplicates across tabs and limits burst delivery", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage))
      .toBe("claimed");
    expect(await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now + 1, storage))
      .toBe("duplicate");
    for (let index = 2; index <= 5; index += 1) {
      expect(await claimBrowserAlertDelivery(
        `fdai:event-${index}`,
        "principal-a",
        now + index,
        storage,
      ))
        .toBe("claimed");
    }
    expect(await claimBrowserAlertDelivery(
      "fdai:event-6",
      "principal-a",
      now + 6,
      storage,
    ))
      .toBe("rate-limited");
    expect(await claimBrowserAlertDelivery(
      "fdai:event-6",
      "principal-b",
      now + 6,
      storage,
    )).toBe("claimed");
    expect(await claimBrowserAlertDelivery(
      "fdai:event-6",
      "principal-a",
      now + 60_001,
      storage,
    )).toBe("claimed");
  });

  test("contains acknowledgement token generation failures", async () => {
    const storage = {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    };
    expect(await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      1_800_000_000_000,
      storage,
      () => { throw new Error("entropy unavailable"); },
    )).toBe("unavailable");
  });

  test("serializes every delivery ledger mutation under one browser lock", async () => {
    const lockNames: string[] = [];
    vi.stubGlobal("navigator", {
      locks: {
        request: async (name: string, callback: () => unknown) => {
          lockNames.push(name);
          return callback();
        },
      },
    });
    const storage = indexedStorage();
    const now = 1_800_000_000_000;

    await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now,
      storage,
      () => ACKNOWLEDGEMENT_TOKEN,
    );
    await recordBrowserAlertDelivered(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      "principal-a",
      now + 1,
      storage,
    );
    await acknowledgeBrowserAlertDeliveryForClaim(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      now + 2,
      storage,
    );
    await releaseBrowserAlertDelivery(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      "principal-a",
      storage,
    );

    expect(lockNames).toHaveLength(4);
    expect(new Set(lockNames).size).toBe(1);
    expect(lockNames[0]).toContain("notification-delivery-ledger");
  });

  test("fails closed when the delivery ledger lock is unavailable", async () => {
    vi.stubGlobal("navigator", {});
    const storage = indexedStorage();

    expect(await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      1_800_000_000_000,
      storage,
    )).toBe("unavailable");
    expect(storage.length).toBe(0);
  });

  test("recovers malformed delivery storage and releases failed sends", async () => {
    const values = new Map<string, string>([[
      "fdai:console:browser-notification-delivery:v1:principal-a",
      "not-json",
    ]]);
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage))
      .toBe("claimed");
    await releaseBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      storage,
    );
    expect(await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now + 1,
      storage,
    )).toBe("claimed");
    expect(await claimBrowserAlertDelivery("fdai:event-2", "principal-a", now, null))
      .toBe("unavailable");
  });

  test("records Console web delivery and user acknowledgement separately", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage))
      .toBe("claimed");
    expect(readLatestBrowserAlertReceipt("principal-a", now + 1, storage)).toBeNull();
    expect(await acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 1,
      storage,
    )).toEqual({
      channelId: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      deliveredAt: now + 1,
      acknowledgedAt: now + 1,
    });

    expect(await recordBrowserAlertDelivered(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 2,
      storage,
    )).toEqual({
      channelId: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      deliveredAt: now + 1,
      acknowledgedAt: now + 1,
    });
    expect(await acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 3,
      storage,
    )).toEqual({
      channelId: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      deliveredAt: now + 1,
      acknowledgedAt: now + 1,
    });
    expect(readLatestBrowserAlertReceipt("principal-a", now + 4, storage)?.acknowledgedAt)
      .toBe(now + 1);
    expect(readLatestBrowserAlertReceipt("principal-b", now + 4, storage)).toBeNull();
  });

  test("accepts only bounded Console web acknowledgement messages", () => {
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      acknowledgement_token: ACKNOWLEDGEMENT_TOKEN,
    })).toEqual({
      tag: "fdai:event-1",
      acknowledgementToken: ACKNOWLEDGEMENT_TOKEN,
    });
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: "teams",
      tag: "fdai:event-1",
      acknowledgement_token: ACKNOWLEDGEMENT_TOKEN,
    })).toBeNull();
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "unsafe tag",
      acknowledgement_token: ACKNOWLEDGEMENT_TOKEN,
    })).toBeNull();
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      acknowledgement_token: "predictable",
    })).toBeNull();
  });

  test("accepts only the closed acknowledgement fragment shape", () => {
    const encodedTag = encodeURIComponent("fdai:event-1");
    expect(decodeBrowserAlertAcknowledgementFragment(
      `#fdai-notification-ack?tag=${encodedTag}&token=${ACKNOWLEDGEMENT_TOKEN}`,
    )).toEqual({
      tag: "fdai:event-1",
      acknowledgementToken: ACKNOWLEDGEMENT_TOKEN,
    });
    expect(decodeBrowserAlertAcknowledgementFragment(
      `#other?tag=${encodedTag}&token=${ACKNOWLEDGEMENT_TOKEN}`,
    )).toBeNull();
    expect(decodeBrowserAlertAcknowledgementFragment(
      `#fdai-notification-ack?tag=${encodedTag}&token=${ACKNOWLEDGEMENT_TOKEN}&extra=1`,
    )).toBeNull();
    expect(decodeBrowserAlertAcknowledgementFragment(
      `#fdai-notification-ack?tag=${encodedTag}&tag=${encodedTag}&token=${ACKNOWLEDGEMENT_TOKEN}`,
    )).toBeNull();
  });

  test("acknowledges the originating principal after the active account changes", async () => {
    const storage = indexedStorage();
    const now = 1_800_000_000_000;
    await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now,
      storage,
      () => ACKNOWLEDGEMENT_TOKEN,
    );
    await recordBrowserAlertDelivered(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      "principal-a",
      now + 1,
      storage,
    );

    expect((await acknowledgeBrowserAlertDeliveryForClaim(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      now + 2,
      storage,
    ))?.acknowledgedAt).toBe(now + 2);
    expect(readLatestBrowserAlertReceipt("principal-a", now + 3, storage)?.acknowledgedAt)
      .toBe(now + 2);
    expect(readLatestBrowserAlertReceipt("principal-b", now + 3, storage)).toBeNull();
  });

  test("rejects an ambiguous claim token across principal ledgers", async () => {
    const storage = indexedStorage();
    const now = 1_800_000_000_000;
    for (const principalId of ["principal-a", "principal-b"]) {
      await claimBrowserAlertDelivery(
        "fdai:event-1",
        principalId,
        now,
        storage,
        () => ACKNOWLEDGEMENT_TOKEN,
      );
      await recordBrowserAlertDelivered(
        "fdai:event-1",
        ACKNOWLEDGEMENT_TOKEN,
        principalId,
        now + 1,
        storage,
      );
    }

    expect(await acknowledgeBrowserAlertDeliveryForClaim(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      now + 2,
      storage,
    )).toBeNull();
  });

  test("keeps legacy claims deduplicated without upgrading them to delivery evidence", async () => {
    const now = 1_800_000_000_000;
    const values = new Map<string, string>([[
      "fdai:console:browser-notification-delivery:v1:principal-a",
      JSON.stringify([{ tag: "fdai:event-1", at: now }]),
    ]]);
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };

    expect(await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now + 1,
      storage,
    ))
      .toBe("duplicate");
    expect(readLatestBrowserAlertReceipt("principal-a", now + 1, storage)).toBeNull();
  });

  test("keeps the legacy timestamp alias across every receipt write", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const key = "fdai:console:browser-notification-delivery:v1:principal-a";
    const now = 1_800_000_000_000;
    expect(await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage))
      .toBe("claimed");
    await recordBrowserAlertDelivered(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 1,
      storage,
    );
    await acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 2,
      storage,
    );

    const stored = JSON.parse(values.get(key) ?? "[]") as readonly Record<string, unknown>[];
    expect(stored).toEqual([expect.objectContaining({
      tag: "fdai:event-1",
      at: now,
      claimedAt: now,
      deliveredAt: now + 1,
      acknowledgedAt: now + 2,
      acknowledgementToken: expect.stringMatching(/^[a-f0-9]{32}$/),
    })]);
  });

  test("retains delivery evidence after the five-minute duplicate window", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage))
      .toBe("claimed");
    expect(await recordBrowserAlertDelivered(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 1,
      storage,
    )).not.toBeNull();

    const delayedClick = now + 6 * 60_000;
    expect((await acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      delayedClick,
      storage,
    ))?.acknowledgedAt).toBe(delayedClick);
    expect(readLatestBrowserAlertReceipt("principal-a", delayedClick, storage)?.tag)
      .toBe("fdai:event-1");
  });

  test("derives status from the latest delivery instead of an older acknowledgement", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    await claimBrowserAlertDelivery("fdai:event-old", "principal-a", now, storage);
    await recordBrowserAlertDelivered(
      "fdai:event-old",
      acknowledgementToken(storage, "principal-a", "fdai:event-old"),
      "principal-a",
      now + 1,
      storage,
    );
    await claimBrowserAlertDelivery("fdai:event-new", "principal-a", now + 2, storage);
    await recordBrowserAlertDelivered(
      "fdai:event-new",
      acknowledgementToken(storage, "principal-a", "fdai:event-new"),
      "principal-a",
      now + 3,
      storage,
    );

    await acknowledgeBrowserAlertDelivery(
      "fdai:event-old",
      acknowledgementToken(storage, "principal-a", "fdai:event-old"),
      "principal-a",
      now + 4,
      storage,
    );
    expect(readBrowserAlertDeliveryStatus("principal-a", now + 4, storage)).toBe("delivered");

    await acknowledgeBrowserAlertDelivery(
      "fdai:event-new",
      acknowledgementToken(storage, "principal-a", "fdai:event-new"),
      "principal-a",
      now + 5,
      storage,
    );
    expect(readBrowserAlertDeliveryStatus("principal-a", now + 5, storage)).toBe("acknowledged");
  });

  test("retains the latest delivery status across preference changes", async () => {
    const storage = indexedStorage();
    const now = 1_800_000_000_000;
    await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now,
      storage,
      () => ACKNOWLEDGEMENT_TOKEN,
    );
    await recordBrowserAlertDelivered(
      "fdai:event-1",
      ACKNOWLEDGEMENT_TOKEN,
      "principal-a",
      now + 1,
      storage,
    );

    writeBrowserNotificationPreference(false, "principal-a", storage);
    writeBrowserNotificationPreference(true, "principal-a", storage);

    expect(readBrowserAlertDeliveryStatus("principal-a", now + 2, storage)).toBe("delivered");
  });

  test("synchronizes only the current principal delivery ledger key", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    await claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage);
    await recordBrowserAlertDelivered(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 1,
      storage,
    );

    expect(browserAlertDeliveryStatusForStorageKey(
      "fdai:console:browser-notification-delivery:v1:principal-a",
      "principal-a",
      now + 2,
      storage,
    )).toBe("delivered");
    expect(browserAlertDeliveryStatusForStorageKey(
      "fdai:console:browser-notification-delivery:v1:principal-b",
      "principal-a",
      now + 2,
      storage,
    )).toBeNull();
    expect(browserAlertDeliveryStatusForStorageKey(null, "principal-a", now + 2, storage))
      .toBeNull();
    expect(isBrowserNotificationDeliveryChange(
      "fdai:console:browser-notification-delivery:v1:principal-a",
      "principal-a",
    )).toBe(true);
    expect(isBrowserNotificationDeliveryChange(
      "fdai:console:browser-notification-delivery:v1:principal-b",
      "principal-a",
    )).toBe(false);
    expect(BROWSER_NOTIFICATION_DELIVERY_CHANGED_EVENT).toContain("delivery-changed");
  });

  test("stale callbacks cannot mutate a replacement claim with the same tag", async () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    const oldToken = "a".repeat(32);
    const newToken = "b".repeat(32);
    expect(await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now,
      storage,
      () => oldToken,
    )).toBe("claimed");
    expect(await claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now + 6 * 60_000,
      storage,
      () => newToken,
    )).toBe("claimed");

    expect(await recordBrowserAlertDelivered(
      "fdai:event-1",
      oldToken,
      "principal-a",
      now + 6 * 60_000 + 1,
      storage,
    )).toBeNull();
    await releaseBrowserAlertDelivery("fdai:event-1", oldToken, "principal-a", storage);
    expect(readBrowserAlertAcknowledgementToken("fdai:event-1", "principal-a", storage))
      .toBe(newToken);
    expect((await recordBrowserAlertDelivered(
      "fdai:event-1",
      newToken,
      "principal-a",
      now + 6 * 60_000 + 2,
      storage,
    ))?.deliveredAt).toBe(now + 6 * 60_000 + 2);
  });
});
