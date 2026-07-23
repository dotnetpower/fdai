import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, test } from "vitest";

interface WorkerContext {
  readonly handlers: Map<string, (event: unknown) => void>;
  safeTarget?: (path: unknown) => URL | null;
}

function loadWorker(scope = "https://console.example.com/"): WorkerContext {
  const handlers = new Map<string, (event: unknown) => void>();
  const context: WorkerContext & Record<string, unknown> = {
    handlers,
    URL,
    self: {
      location: { origin: "https://console.example.com" },
      registration: { scope },
      clients: {},
      addEventListener: (name: string, handler: (event: unknown) => void) => {
        handlers.set(name, handler);
      },
    },
  };
  const source = readFileSync(new URL("../public/notification-sw.js", import.meta.url), "utf8");
  runInNewContext(source, context);
  return context;
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
});
