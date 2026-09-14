import { afterEach, describe, expect, test, vi } from "vitest";
import type { LiveStageEvent } from "./hooks/use-live-stream";
import {
  acknowledgeBrowserAlertDelivery,
  BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
  browserAlertDeliveryStatusForStorageKey,
  browserAlertNotificationData,
  browserAlertForLiveEvent,
  CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
  decodeBrowserAlertAcknowledgement,
  decodeBrowserAlertAcknowledgementFragment,
  isBrowserNotificationPreferenceStorageKey,
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
  trustedBrowserAlertAcknowledgement,
  withBrowserNotificationDeadline,
  writeBrowserNotificationPreference,
} from "./browser-notifications";

const ACKNOWLEDGEMENT_TOKEN = "a".repeat(32);

afterEach(() => vi.useRealTimers());

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

  test("creates a bounded same-origin incident route and replacement tag", () => {
    expect(browserAlertForLiveEvent(event())).toEqual({
      kind: "approval",
      tag: "fdai:event-1",
      path: "/incidents?status=all&correlation=correlation-1",
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
      path: "/incidents?status=all&correlation=correlation-1",
    });
    expect(() => browserAlertNotificationData(
      browserAlertForLiveEvent(event())!,
      "/",
      "predictable",
    )).toThrow(/token is invalid/);
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

  test("deduplicates across tabs and limits burst delivery", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage)).toBe("claimed");
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now + 1, storage)).toBe("duplicate");
    for (let index = 2; index <= 5; index += 1) {
      expect(claimBrowserAlertDelivery(`fdai:event-${index}`, "principal-a", now + index, storage))
        .toBe("claimed");
    }
    expect(claimBrowserAlertDelivery("fdai:event-6", "principal-a", now + 6, storage))
      .toBe("rate-limited");
    expect(claimBrowserAlertDelivery("fdai:event-6", "principal-b", now + 6, storage)).toBe("claimed");
    expect(claimBrowserAlertDelivery("fdai:event-6", "principal-a", now + 60_001, storage)).toBe("claimed");
  });

  test("contains acknowledgement token generation failures", () => {
    const storage = {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    };
    expect(claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      1_800_000_000_000,
      storage,
      () => { throw new Error("entropy unavailable"); },
    )).toBe("unavailable");
  });

  test("recovers malformed delivery storage and releases failed sends", () => {
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
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage)).toBe("claimed");
    releaseBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      storage,
    );
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now + 1, storage)).toBe("claimed");
    expect(claimBrowserAlertDelivery("fdai:event-2", "principal-a", now, null)).toBe("unavailable");
  });

  test("records Console web delivery and user acknowledgement separately", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage)).toBe("claimed");
    expect(readLatestBrowserAlertReceipt("principal-a", now + 1, storage)).toBeNull();
    expect(acknowledgeBrowserAlertDelivery(
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

    expect(recordBrowserAlertDelivered(
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
    expect(acknowledgeBrowserAlertDelivery(
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

  test("accepts only trusted browser messages and mints the acknowledgement time locally", () => {
    const payload = {
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      acknowledgement_token: ACKNOWLEDGEMENT_TOKEN,
      acknowledged_at: 1,
    };
    expect(trustedBrowserAlertAcknowledgement(payload, false, 1_800_000_000_000)).toBeNull();
    expect(trustedBrowserAlertAcknowledgement(payload, true, 1_800_000_000_000)).toEqual({
      tag: "fdai:event-1",
      acknowledgementToken: ACKNOWLEDGEMENT_TOKEN,
      acknowledgedAt: 1_800_000_000_000,
    });
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

  test("keeps legacy claims deduplicated without upgrading them to delivery evidence", () => {
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

    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now + 1, storage))
      .toBe("duplicate");
    expect(readLatestBrowserAlertReceipt("principal-a", now + 1, storage)).toBeNull();
  });

  test("keeps the legacy timestamp alias across every receipt write", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const key = "fdai:console:browser-notification-delivery:v1:principal-a";
    const now = 1_800_000_000_000;
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage)).toBe("claimed");
    recordBrowserAlertDelivered(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 1,
      storage,
    );
    acknowledgeBrowserAlertDelivery(
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

  test("retains delivery evidence after the five-minute duplicate window", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    expect(claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage)).toBe("claimed");
    expect(recordBrowserAlertDelivered(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      now + 1,
      storage,
    )).not.toBeNull();

    const delayedClick = now + 6 * 60_000;
    expect(acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
      acknowledgementToken(storage, "principal-a", "fdai:event-1"),
      "principal-a",
      delayedClick,
      storage,
    )?.acknowledgedAt).toBe(delayedClick);
    expect(readLatestBrowserAlertReceipt("principal-a", delayedClick, storage)?.tag)
      .toBe("fdai:event-1");
  });

  test("derives status from the latest delivery instead of an older acknowledgement", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    claimBrowserAlertDelivery("fdai:event-old", "principal-a", now, storage);
    recordBrowserAlertDelivered(
      "fdai:event-old",
      acknowledgementToken(storage, "principal-a", "fdai:event-old"),
      "principal-a",
      now + 1,
      storage,
    );
    claimBrowserAlertDelivery("fdai:event-new", "principal-a", now + 2, storage);
    recordBrowserAlertDelivered(
      "fdai:event-new",
      acknowledgementToken(storage, "principal-a", "fdai:event-new"),
      "principal-a",
      now + 3,
      storage,
    );

    acknowledgeBrowserAlertDelivery(
      "fdai:event-old",
      acknowledgementToken(storage, "principal-a", "fdai:event-old"),
      "principal-a",
      now + 4,
      storage,
    );
    expect(readBrowserAlertDeliveryStatus("principal-a", now + 4, storage)).toBe("delivered");

    acknowledgeBrowserAlertDelivery(
      "fdai:event-new",
      acknowledgementToken(storage, "principal-a", "fdai:event-new"),
      "principal-a",
      now + 5,
      storage,
    );
    expect(readBrowserAlertDeliveryStatus("principal-a", now + 5, storage)).toBe("acknowledged");
  });

  test("synchronizes only the current principal delivery ledger key", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    claimBrowserAlertDelivery("fdai:event-1", "principal-a", now, storage);
    recordBrowserAlertDelivered(
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
  });

  test("stale callbacks cannot mutate a replacement claim with the same tag", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const now = 1_800_000_000_000;
    const oldToken = "a".repeat(32);
    const newToken = "b".repeat(32);
    expect(claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now,
      storage,
      () => oldToken,
    )).toBe("claimed");
    expect(claimBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now + 6 * 60_000,
      storage,
      () => newToken,
    )).toBe("claimed");

    expect(recordBrowserAlertDelivered(
      "fdai:event-1",
      oldToken,
      "principal-a",
      now + 6 * 60_000 + 1,
      storage,
    )).toBeNull();
    releaseBrowserAlertDelivery("fdai:event-1", oldToken, "principal-a", storage);
    expect(readBrowserAlertAcknowledgementToken("fdai:event-1", "principal-a", storage))
      .toBe(newToken);
    expect(recordBrowserAlertDelivered(
      "fdai:event-1",
      newToken,
      "principal-a",
      now + 6 * 60_000 + 2,
      storage,
    )?.deliveredAt).toBe(now + 6 * 60_000 + 2);
  });
});
