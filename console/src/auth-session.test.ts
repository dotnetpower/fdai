import { afterEach, describe, expect, test, vi } from "vitest";

import {
  AUTH_SESSION_REFRESH_INTERVAL_MS,
  type AuthSessionHost,
  installAuthSessionKeeper,
  msalCacheLocationForOrigin,
} from "./auth-session";

afterEach(() => vi.restoreAllMocks());

function sessionHost() {
  const windowListeners = new Map<string, () => void>();
  const documentListeners = new Map<string, () => void>();
  let interval: (() => void) | undefined;
  const host: AuthSessionHost = {
    setInterval(callback, intervalMs) {
      expect(intervalMs).toBe(AUTH_SESSION_REFRESH_INTERVAL_MS);
      interval = callback;
      return "interval";
    },
    clearInterval: vi.fn(),
    addWindowListener(type, listener) {
      windowListeners.set(type, listener);
    },
    removeWindowListener: vi.fn(),
    addDocumentListener(type, listener) {
      documentListeners.set(type, listener);
    },
    removeDocumentListener: vi.fn(),
    isVisible: () => true,
  };
  return {
    host,
    triggerInterval: () => interval?.(),
    triggerWindow: (type: "focus" | "online") => windowListeners.get(type)?.(),
    triggerVisible: () => documentListeners.get("visibilitychange")?.(),
  };
}

async function settleRefresh(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("MSAL cache policy", () => {
  test.each([
    "http://localhost:5273",
    "http://127.0.0.1:5273",
    "http://[::1]:5273",
  ])("uses durable cache only for loopback origin %s", (origin) => {
    expect(msalCacheLocationForOrigin(origin)).toBe("localStorage");
  });

  test("keeps deployed origins in session storage", () => {
    expect(msalCacheLocationForOrigin("https://console.example.com")).toBe("sessionStorage");
  });
});

describe("auth session keeper", () => {
  test("refreshes on startup, interval, and browser resume signals", async () => {
    const refresh = vi.fn(async () => undefined);
    const fixture = sessionHost();
    const stop = installAuthSessionKeeper(refresh, fixture.host);

    await vi.waitFor(() => expect(refresh).toHaveBeenCalledWith("startup"));
    await settleRefresh();
    fixture.triggerInterval();
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
    await settleRefresh();
    fixture.triggerWindow("focus");
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(3));
    await settleRefresh();
    fixture.triggerWindow("online");
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(4));
    await settleRefresh();
    fixture.triggerVisible();
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(5));

    stop();
    fixture.triggerInterval();
    expect(refresh).toHaveBeenCalledTimes(5);
  });

  test("coalesces overlapping refresh triggers", async () => {
    let release: (() => void) | undefined;
    const refresh = vi.fn(() => new Promise<void>((resolve) => {
      release = resolve;
    }));
    const fixture = sessionHost();
    const stop = installAuthSessionKeeper(refresh, fixture.host);

    fixture.triggerWindow("focus");
    fixture.triggerWindow("online");
    expect(refresh).toHaveBeenCalledTimes(1);

    release?.();
  await settleRefresh();
  fixture.triggerWindow("focus");
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
    stop();
  });
});
