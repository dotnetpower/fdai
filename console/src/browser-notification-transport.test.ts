import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";

const TOKEN = "a".repeat(32);
const data = {
  channel_id: "console-web",
  tag: "fdai:event-1",
  acknowledgement_token: TOKEN,
  path: "/audit?correlation=event-1&data=live",
};

class TestNotification {
  static permission: NotificationPermission = "granted";
  static outcome: "show" | "error" | "silent" = "show";
  static instances: TestNotification[] = [];
  onshow: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclick: (() => void) | null = null;
  close = vi.fn();

  constructor(readonly title: string, readonly options: NotificationOptions) {
    TestNotification.instances.push(this);
    setTimeout(() => {
      if (TestNotification.outcome === "show") this.onshow?.();
      if (TestNotification.outcome === "error") this.onerror?.();
    }, 0);
  }
}

describe("Console notification receiver", () => {
  const stored = new Map<string, string>();
  const assign = vi.fn();
  const focus = vi.fn();
  const register = vi.fn();
  const showNotification = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    stored.clear();
    assign.mockReset();
    focus.mockReset();
    register.mockReset();
    showNotification.mockReset();
    TestNotification.permission = "granted";
    TestNotification.outcome = "show";
    TestNotification.instances = [];
    vi.stubGlobal("Notification", TestNotification);
    vi.stubGlobal("window", {
      setTimeout,
      clearTimeout,
      focus,
      location: { origin: "http://localhost:5273", assign },
      sessionStorage: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => { stored.set(key, value); },
        removeItem: (key: string) => { stored.delete(key); },
      },
    });
    vi.stubGlobal("navigator", {
      serviceWorker: {
        register,
        ready: Promise.resolve({ showNotification }),
      },
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("keeps the existing service-worker receiver without a connection notification", async () => {
    register.mockResolvedValue({});
    showNotification.mockResolvedValue(undefined);
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    const receiver = await prepareBrowserNotificationTransport("/");
    expect(receiver.kind).toBe("service-worker");
    await receiver.show("FDAI", { data });
    expect(register).toHaveBeenCalledWith("/notification-sw.js", {
      scope: "/", updateViaCache: "none",
    });
    expect(showNotification).toHaveBeenCalledOnce();
    expect(TestNotification.instances).toHaveLength(0);
  });

  it("requires a real show event after a bounded worker timeout before session readiness", async () => {
    register.mockReturnValue(new Promise(() => {}));
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    let ready = false;
    const pending = prepareBrowserNotificationTransport("/", true).then((receiver) => {
      ready = true;
      return receiver;
    });
    await vi.advanceTimersByTimeAsync(9999);
    expect(ready).toBe(false);
    expect(stored.size).toBe(0);
    await vi.runAllTimersAsync();
    expect((await pending).kind).toBe("session");
    expect(ready).toBe(true);
    expect(TestNotification.instances).toHaveLength(1);
    expect(TestNotification.instances[0]?.options.data).toBeUndefined();
    expect([...stored.values()]).toEqual(["verified"]);
  });

  it.each(["error", "silent"] as const)("never enables a failed or unobserved native display: %s", async (outcome) => {
    register.mockRejectedValue(new Error("worker unavailable"));
    TestNotification.outcome = outcome;
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    const failed = expect(prepareBrowserNotificationTransport("/", true))
      .rejects.toThrow("No verified Console web notification receiver");
    await vi.runAllTimersAsync();
    await failed;
    expect(stored.size).toBe(0);
    expect(TestNotification.instances[0]?.close).toHaveBeenCalled();
  });

  it("does not probe or enable an unverified receiver during automatic restoration", async () => {
    register.mockRejectedValue(new Error("worker unavailable"));
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    await expect(prepareBrowserNotificationTransport("/")).rejects.toThrow("worker unavailable");
    expect(TestNotification.instances).toHaveLength(0);
  });

  it("restores verified session capability without another connection notification", async () => {
    register.mockRejectedValue(new Error("worker unavailable"));
    const module = await import("./browser-notification-transport");
    const pending = module.prepareBrowserNotificationTransport("/", true);
    await vi.runAllTimersAsync();
    await pending;
    vi.resetModules();
    register.mockClear();
    const restored = await import("./browser-notification-transport");
    expect((await restored.prepareBrowserNotificationTransport("/")).kind).toBe("session");
    expect(TestNotification.instances).toHaveLength(1);
    expect(register).not.toHaveBeenCalled();
    TestNotification.permission = "denied";
    await expect(restored.prepareBrowserNotificationTransport("/")).rejects.toThrow("permission");
  });

  it("waits for native display and retains the token-bound Audit click path", async () => {
    register.mockRejectedValue(new Error("worker unavailable"));
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    const pending = prepareBrowserNotificationTransport("/", true);
    await vi.runAllTimersAsync();
    const receiver = await pending;
    const display = receiver.show("FDAI operation failed", { body: "Review evidence", data });
    expect(assign).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(TestNotification.instances).toHaveLength(2));
    await vi.runAllTimersAsync();
    await display;
    TestNotification.instances[1]?.onclick?.();
    expect(focus).toHaveBeenCalledOnce();
    const target = new URL(assign.mock.calls[0]![0]);
    expect(target.pathname).toBe("/audit");
    expect(target.searchParams.get("correlation")).toBe("event-1");
    expect(target.hash).toContain(`token=${TOKEN}`);
    expect(target.hash).toContain("tag=fdai%3Aevent-1");
  });

  it("preserves closed route, deployment scope, and claim validation", async () => {
    const { sessionNotificationClickTarget } = await import("./browser-notification-transport");
    expect(sessionNotificationClickTarget({ ...data, path: "/fdai/audit" }, "/fdai/"))
      .toContain("http://localhost:5273/fdai/audit#fdai-notification-ack");
    for (const invalid of [
      { ...data, path: "//example.com/audit" },
      { ...data, path: "/settings" },
      { ...data, path: "/audit" },
      { ...data, path: "/fdai/audit", acknowledgement_token: "bad" },
      { ...data, path: "/fdai/audit", channel_id: "other" },
    ]) {
      expect(() => sessionNotificationClickTarget(invalid, "/fdai/")).toThrow();
    }
  });

  it("invalidates session readiness after a real notification display failure", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    register.mockRejectedValue(new Error("worker unavailable"));
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    const pending = prepareBrowserNotificationTransport("/", true);
    await vi.runAllTimersAsync();
    const receiver = await pending;
    TestNotification.outcome = "error";
    const failed = expect(receiver.show("FDAI", { data })).rejects.toThrow("display failed");
    await vi.waitFor(() => expect(TestNotification.instances).toHaveLength(2));
    await vi.runAllTimersAsync();
    await failed;
    expect(warning).toHaveBeenCalledWith("console_web_notification_session_failed", {
      reason: "Console web session notification display failed.",
    });
    expect(stored.size).toBe(0);
    await expect(prepareBrowserNotificationTransport("/")).rejects.toThrow("worker unavailable");
    expect(TestNotification.instances).toHaveLength(2);
  });

  it("uses a bounded stable display tag without changing the original event or claim", async () => {
    register.mockRejectedValue(new Error("worker unavailable"));
    const { prepareBrowserNotificationTransport } = await import("./browser-notification-transport");
    const pending = prepareBrowserNotificationTransport("/", true);
    await vi.runAllTimersAsync();
    const receiver = await pending;
    const original = `fdai:${"a".repeat(128)}`;
    const payload = { ...data, tag: original };
    const display = receiver.show("FDAI", { tag: original, data: payload });
    await vi.waitFor(() => expect(TestNotification.instances).toHaveLength(2));
    await vi.runAllTimersAsync();
    await display;
    const first = TestNotification.instances[1]?.options;
    expect(first?.tag).toMatch(/^[a-f0-9]{32}$/);
    expect(first?.tag).toBe(createHash("sha256").update(original).digest("hex").slice(0, 32));
    expect(first?.data).toEqual(payload);
    const repeated = receiver.show("FDAI", { tag: original, data: payload });
    await vi.waitFor(() => expect(TestNotification.instances).toHaveLength(3));
    await vi.runAllTimersAsync();
    await repeated;
    expect(TestNotification.instances[2]?.options.tag).toBe(first?.tag);
  });
});
