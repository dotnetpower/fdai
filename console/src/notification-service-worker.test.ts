import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, test, vi } from "vitest";

interface WorkerContext {
  readonly handlers: Map<string, (event: unknown) => void>;
  readonly clients: WorkerClients;
  safeTarget?: (path: unknown) => URL | null;
}

interface WindowClientStub {
  readonly url: string;
  readonly focus: () => Promise<unknown>;
  readonly navigate: (url: string) => Promise<WindowClientStub | null>;
  readonly postMessage?: (value: unknown) => void;
}

interface WorkerClients {
  readonly matchAll: () => Promise<readonly WindowClientStub[]>;
  readonly openWindow: (url: string) => Promise<WindowClientStub | null>;
}

function loadWorker(
  scope = "https://console.example.com/",
  clients: WorkerClients = {
    matchAll: async () => [],
    openWindow: async () => null,
  },
): WorkerContext {
  const handlers = new Map<string, (event: unknown) => void>();
  const context: WorkerContext & Record<string, unknown> = {
    handlers,
    clients,
    URL,
    self: {
      location: { origin: "https://console.example.com" },
      registration: { scope },
      clients,
      addEventListener: (name: string, handler: (event: unknown) => void) => {
        handlers.set(name, handler);
      },
    },
  };
  const source = readFileSync(new URL("../public/notification-sw.js", import.meta.url), "utf8");
  runInNewContext(source, context);
  return context;
}

async function clickNotification(
  context: WorkerContext,
  path: string,
  tag = "fdai:event-1",
  channelId = "console-web",
): Promise<void> {
  let pending: Promise<unknown> | undefined;
  const close = vi.fn();
  context.handlers.get("notificationclick")?.({
    notification: { data: { path, tag, channel_id: channelId }, close },
    waitUntil: (value: Promise<unknown>) => {
      pending = value;
    },
  });
  expect(close).toHaveBeenCalledOnce();
  expect(pending).toBeDefined();
  await pending;
}

describe("notification service worker boundary", () => {
  test("registers lifecycle and click handlers", () => {
    const context = loadWorker();
    expect([...context.handlers.keys()].sort()).toEqual(["activate", "install", "notificationclick"]);
  });

  test("opens only the scoped Incident route", () => {
    const root = loadWorker();
    expect(root.safeTarget?.("/incidents?status=all")?.href).toBe(
      "https://console.example.com/incidents?status=all",
    );
    expect(root.safeTarget?.("/approvals")).toBeNull();
    expect(root.safeTarget?.("//attacker.example/incidents")).toBeNull();

    const nested = loadWorker("https://console.example.com/fdai/");
    expect(nested.safeTarget?.("/fdai/incidents?status=all")?.pathname).toBe("/fdai/incidents");
    expect(nested.safeTarget?.("/incidents?status=all")).toBeNull();
  });

  test("focuses the client returned by navigation", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget =
      "https://console.example.com/incidents?status=all&fdai_notification_ack=fdai%3Aevent-1";
    const navigatedFocus = vi.fn(async () => undefined);
    const navigated: WindowClientStub = {
      url: acknowledgedTarget,
      focus: navigatedFocus,
      navigate: async () => null,
    };
    const originalFocus = vi.fn(async () => undefined);
    const navigate = vi.fn(async () => navigated);
    const original: WindowClientStub = {
      url: "https://console.example.com/",
      focus: originalFocus,
      navigate,
    };
    const openWindow = vi.fn(async () => null);
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [original],
      openWindow,
    });

    await clickNotification(context, "/incidents?status=all");

    expect(navigate).toHaveBeenCalledWith(acknowledgedTarget);
    expect(navigatedFocus).toHaveBeenCalledOnce();
    expect(originalFocus).not.toHaveBeenCalled();
    expect(openWindow).not.toHaveBeenCalled();
  });

  test("opens the target when focusing an exact client fails", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget =
      "https://console.example.com/incidents?status=all&fdai_notification_ack=fdai%3Aevent-1";
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => {
        throw new Error("focus unavailable");
      }),
      navigate: async () => null,
    };
    const openWindow = vi.fn(async () => null);
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow,
    });

    await clickNotification(context, "/incidents?status=all");

    expect(exact.focus).toHaveBeenCalledOnce();
    expect(openWindow).toHaveBeenCalledWith(acknowledgedTarget);
  });

  test("reports acknowledgement to an already open exact Console target", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const postMessage = vi.fn();
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
      postMessage,
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(context, "/incidents?status=all");

    expect(postMessage).toHaveBeenCalledOnce();
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: "fdai.console-web-notification.acknowledged",
      channel_id: "console-web",
      tag: "fdai:event-1",
    }));
    expect(postMessage.mock.calls[0]?.[0]).not.toHaveProperty("acknowledged_at");
  });

  test("does not record an acknowledgement for an invalid notification tag", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const postMessage = vi.fn();
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
      postMessage,
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(context, "/incidents?status=all", "unsafe tag");

    expect(postMessage).not.toHaveBeenCalled();
  });

  test("does not record an acknowledgement for another notification channel", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const postMessage = vi.fn();
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
      postMessage,
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(context, "/incidents?status=all", "fdai:event-1", "teams");

    expect(postMessage).not.toHaveBeenCalled();
  });

  test("reuses the focused exact window when acknowledgement messaging fails", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget =
      "https://console.example.com/incidents?status=all&fdai_notification_ack=fdai%3Aevent-1";
    const navigated: WindowClientStub = {
      url: acknowledgedTarget,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
    };
    const navigate = vi.fn(async () => navigated);
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate,
      postMessage: () => { throw new Error("detached client"); },
    };
    const openWindow = vi.fn(async () => null);
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow,
    });

    await clickNotification(context, "/incidents?status=all");

    expect(navigate).toHaveBeenCalledWith(acknowledgedTarget);
    expect(navigated.focus).toHaveBeenCalledOnce();
    expect(openWindow).not.toHaveBeenCalled();
  });
});
