import { describe, expect, test } from "vitest";
import type { LiveStageEvent } from "./hooks/use-live-stream";
import {
  acknowledgeBrowserAlertDelivery,
  BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
  browserAlertDeliveryStatusForStorageKey,
  browserAlertNotificationData,
  browserAlertForLiveEvent,
  CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
  decodeBrowserAlertAcknowledgement,
  browserNotificationPreferenceKey,
  browserNotificationsSupported,
  browserNotificationTargetPath,
  browserNotificationWorkerPaths,
  claimBrowserAlertDelivery,
  readBrowserAlertDeliveryStatus,
  readLatestBrowserAlertReceipt,
  readBrowserNotificationPreference,
  recordBrowserAlertDelivered,
  releaseBrowserAlertDelivery,
  requireBrowserNotificationPreferenceWrite,
  trustedBrowserAlertAcknowledgement,
  writeBrowserNotificationPreference,
} from "./browser-notifications";

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
    expect(browserAlertForLiveEvent(event({ source: "replay" }))).toBeNull();
    expect(browserAlertForLiveEvent(event({ source: "synthetic-dev" }))).toBeNull();
    expect(browserAlertForLiveEvent(event({ source: "unknown" }))).toBeNull();
    expect(browserAlertForLiveEvent(event({ source: undefined }))).toBeNull();
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
    expect(browserAlertNotificationData(browserAlertForLiveEvent(event())!, "/")).toEqual({
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      path: "/incidents?status=all&correlation=correlation-1",
    });
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
    })).toBe(true);
    expect(browserNotificationsSupported({
      secureContext: false,
      notificationApi: true,
      serviceWorkerApi: true,
    })).toBe(false);
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
    releaseBrowserAlertDelivery("fdai:event-1", "principal-a", storage);
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
      "principal-a",
      now + 1,
      storage,
    )).toBeNull();

    expect(recordBrowserAlertDelivered(
      "fdai:event-1",
      "principal-a",
      now + 2,
      storage,
    )).toEqual({
      channelId: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      deliveredAt: now + 2,
      acknowledgedAt: null,
    });
    expect(acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
      "principal-a",
      now + 3,
      storage,
    )).toEqual({
      channelId: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      deliveredAt: now + 2,
      acknowledgedAt: now + 3,
    });
    expect(readLatestBrowserAlertReceipt("principal-a", now + 4, storage)?.acknowledgedAt)
      .toBe(now + 3);
    expect(readLatestBrowserAlertReceipt("principal-b", now + 4, storage)).toBeNull();
  });

  test("accepts only bounded Console web acknowledgement messages", () => {
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
    })).toEqual({
      tag: "fdai:event-1",
    });
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: "teams",
      tag: "fdai:event-1",
    })).toBeNull();
    expect(decodeBrowserAlertAcknowledgement({
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "unsafe tag",
    })).toBeNull();
  });

  test("accepts only trusted browser messages and mints the acknowledgement time locally", () => {
    const payload = {
      type: BROWSER_NOTIFICATION_ACKNOWLEDGEMENT_TYPE,
      channel_id: CONSOLE_WEB_NOTIFICATION_CHANNEL_ID,
      tag: "fdai:event-1",
      acknowledged_at: 1,
    };
    expect(trustedBrowserAlertAcknowledgement(payload, false, 1_800_000_000_000)).toBeNull();
    expect(trustedBrowserAlertAcknowledgement(payload, true, 1_800_000_000_000)).toEqual({
      tag: "fdai:event-1",
      acknowledgedAt: 1_800_000_000_000,
    });
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
    recordBrowserAlertDelivered("fdai:event-1", "principal-a", now + 1, storage);
    acknowledgeBrowserAlertDelivery("fdai:event-1", "principal-a", now + 2, storage);

    const stored = JSON.parse(values.get(key) ?? "[]") as readonly Record<string, unknown>[];
    expect(stored).toEqual([expect.objectContaining({
      tag: "fdai:event-1",
      at: now,
      claimedAt: now,
      deliveredAt: now + 1,
      acknowledgedAt: now + 2,
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
      "principal-a",
      now + 1,
      storage,
    )).not.toBeNull();

    const delayedClick = now + 6 * 60_000;
    expect(acknowledgeBrowserAlertDelivery(
      "fdai:event-1",
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
    recordBrowserAlertDelivered("fdai:event-old", "principal-a", now + 1, storage);
    claimBrowserAlertDelivery("fdai:event-new", "principal-a", now + 2, storage);
    recordBrowserAlertDelivered("fdai:event-new", "principal-a", now + 3, storage);

    acknowledgeBrowserAlertDelivery("fdai:event-old", "principal-a", now + 4, storage);
    expect(readBrowserAlertDeliveryStatus("principal-a", now + 4, storage)).toBe("delivered");

    acknowledgeBrowserAlertDelivery("fdai:event-new", "principal-a", now + 5, storage);
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
    recordBrowserAlertDelivered("fdai:event-1", "principal-a", now + 1, storage);

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
});
