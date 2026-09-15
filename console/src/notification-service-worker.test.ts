import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, test, vi } from "vitest";

const ACKNOWLEDGEMENT_TOKEN = "a".repeat(32);
const ACKNOWLEDGEMENT_SUFFIX =
  `#fdai-notification-ack?tag=fdai%3Aevent-1&token=${ACKNOWLEDGEMENT_TOKEN}`;

interface WorkerContext {
  readonly handlers: Map<string, (event: unknown) => void>;
  readonly clients: WorkerClients;
  safeTarget?: (path: unknown) => URL | null;
}

interface WindowClientStub {
  readonly url: string;
  readonly focus: () => Promise<unknown>;
  readonly navigate: (url: string) => Promise<WindowClientStub | null>;
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
    URLSearchParams,
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
  acknowledgementToken = ACKNOWLEDGEMENT_TOKEN,
): Promise<void> {
  let pending: Promise<unknown> | undefined;
  const close = vi.fn();
  context.handlers.get("notificationclick")?.({
    notification: {
      data: {
        path,
        tag,
        channel_id: channelId,
        acknowledgement_token: acknowledgementToken,
      },
      close,
    },
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

  test("opens only scoped Audit and legacy Incident routes", () => {
    const root = loadWorker();
    expect(root.safeTarget?.("/incidents?status=all")?.href).toBe(
      "https://console.example.com/incidents?status=all",
    );
    expect(root.safeTarget?.("/approvals")).toBeNull();
    expect(root.safeTarget?.("//attacker.example/incidents")).toBeNull();
    expect(root.safeTarget?.("/audit?correlation=corr-1")?.pathname).toBe("/audit");
    expect(root.safeTarget?.("//attacker.example/audit")).toBeNull();
    expect(root.safeTarget?.("/audit/other")).toBeNull();

    const nested = loadWorker("https://console.example.com/fdai/");
    expect(nested.safeTarget?.("/fdai/incidents?status=all")?.pathname).toBe("/fdai/incidents");
    expect(nested.safeTarget?.("/incidents?status=all")).toBeNull();
    expect(nested.safeTarget?.("/fdai/audit?correlation=corr-1")?.pathname).toBe("/fdai/audit");
    expect(nested.safeTarget?.("/audit?correlation=corr-1")).toBeNull();
  });

  test("opens correlated audit evidence with the click acknowledgement", async () => {
    const openWindow = vi.fn(async () => null);
    const context = loadWorker("https://console.example.com/fdai/", {
      matchAll: async () => [],
      openWindow,
    });

    await clickNotification(context, "/fdai/audit?correlation=corr-1");

    expect(openWindow).toHaveBeenCalledWith(
      `https://console.example.com/fdai/audit?correlation=corr-1${ACKNOWLEDGEMENT_SUFFIX}`,
    );
  });

  test("focuses the client returned by navigation", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget = `${target}${ACKNOWLEDGEMENT_SUFFIX}`;
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

  test("never navigates an uncontrolled same-origin window outside the Console scope", async () => {
    const target = "https://console.example.com/fdai/incidents?status=all";
    const acknowledgedTarget = `${target}${ACKNOWLEDGEMENT_SUFFIX}`;
    const unrelatedNavigate = vi.fn(async () => null);
    const unrelated: WindowClientStub = {
      url: "https://console.example.com/other-app",
      focus: vi.fn(async () => undefined),
      navigate: unrelatedNavigate,
    };
    const navigated: WindowClientStub = {
      url: acknowledgedTarget,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
    };
    const scopedNavigate = vi.fn(async () => navigated);
    const scoped: WindowClientStub = {
      url: "https://console.example.com/fdai/overview",
      focus: vi.fn(async () => undefined),
      navigate: scopedNavigate,
    };
    const context = loadWorker("https://console.example.com/fdai/", {
      matchAll: async () => [unrelated, scoped],
      openWindow: async () => null,
    });

    await clickNotification(context, "/fdai/incidents?status=all");

    expect(unrelatedNavigate).not.toHaveBeenCalled();
    expect(scopedNavigate).toHaveBeenCalledWith(acknowledgedTarget);
  });

  test("opens the target when exact-client navigation returns no client", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget = `${target}${ACKNOWLEDGEMENT_SUFFIX}`;
    const navigate = vi.fn(async () => null);
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate,
    };
    const openWindow = vi.fn(async () => null);
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow,
    });

    await clickNotification(context, "/incidents?status=all");

    expect(navigate).toHaveBeenCalledWith(acknowledgedTarget);
    expect(exact.focus).not.toHaveBeenCalled();
    expect(openWindow).toHaveBeenCalledWith(acknowledgedTarget);
  });

  test("navigates an exact Console target through the acknowledgement fragment", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget = `${target}${ACKNOWLEDGEMENT_SUFFIX}`;
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
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(context, "/incidents?status=all");

    expect(navigate).toHaveBeenCalledWith(acknowledgedTarget);
    expect(navigated.focus).toHaveBeenCalledOnce();
  });

  test("does not add acknowledgement data for an invalid notification tag", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const navigated: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
    };
    const navigate = vi.fn(async () => navigated);
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate,
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(context, "/incidents?status=all", "unsafe tag");

    expect(navigate).toHaveBeenCalledWith(target);
  });

  test("does not add acknowledgement data for another notification channel", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const navigated: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
    };
    const navigate = vi.fn(async () => navigated);
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate,
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(context, "/incidents?status=all", "fdai:event-1", "teams");

    expect(navigate).toHaveBeenCalledWith(target);
  });

  test("does not add acknowledgement data with an invalid claim token", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const navigated: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate: async () => null,
    };
    const navigate = vi.fn(async () => navigated);
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate,
    };
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow: async () => null,
    });

    await clickNotification(
      context,
      "/incidents?status=all",
      "fdai:event-1",
      "console-web",
      "predictable",
    );

    expect(navigate).toHaveBeenCalledWith(target);
  });

  test("opens the acknowledgement target when exact-client navigation fails", async () => {
    const target = "https://console.example.com/incidents?status=all";
    const acknowledgedTarget = `${target}${ACKNOWLEDGEMENT_SUFFIX}`;
    const navigate = vi.fn(async () => {
      throw new Error("detached client");
    });
    const exact: WindowClientStub = {
      url: target,
      focus: vi.fn(async () => undefined),
      navigate,
    };
    const openWindow = vi.fn(async () => null);
    const context = loadWorker("https://console.example.com/", {
      matchAll: async () => [exact],
      openWindow,
    });

    await clickNotification(context, "/incidents?status=all");
    expect(navigate).toHaveBeenCalledWith(acknowledgedTarget);
    expect(navigate).toHaveBeenCalledWith(acknowledgedTarget);
    expect(openWindow).toHaveBeenCalledWith(acknowledgedTarget);
  });
});
