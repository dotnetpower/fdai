import { describe, expect, test } from "vitest";
import type { LiveStageEvent } from "./hooks/use-live-stream";
import {
  browserAlertForLiveEvent,
  browserNotificationPreferenceKey,
  browserNotificationsSupported,
  browserNotificationTargetPath,
  browserNotificationWorkerPaths,
  claimBrowserAlertDelivery,
  readBrowserNotificationPreference,
  releaseBrowserAlertDelivery,
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

  test("rejects replay and malformed identifiers without exposing raw detail", () => {
    expect(browserAlertForLiveEvent(event({ source: "replay" }))).toBeNull();
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
});
