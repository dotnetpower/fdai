import { afterEach, describe, expect, test, vi } from "vitest";
import { OperatorApiClient } from "./api";
import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";

const config: ConsoleConfig = {
  operatorApiBaseUrl: "http://127.0.0.1:8010",
  ingestionApiBaseUrl: "http://127.0.0.1:8011",
  msalClientId: "",
  msalTenantId: "",
  msalApiScope: "",
  authTokenTimeoutMs: 10_000,
  operatorApiRequestTimeoutMs: 30_000,
  devMode: true,
  localAzureCliAuth: false,
  localLoginPrompt: false,
  workflowCatalogRepo: "",
  workflowCatalogBranch: "main",
};

const auth: AuthContext = {
  devMode: true,
  account: null,
  async getAuthorizationHeader() { return null; },
  async signIn() {},
  async signOut() {},
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function installFetch() {
  return vi.fn(async (input: string | URL | Request) => {
    const path = new URL(String(input)).pathname;
    if (path === "/system/data-sources") {
      return Response.json({ surface: "read-data-sources", sources: [] });
    }
    if (path === "/models/settings") return Response.json({ revision: 1 });
    return Response.json({ error: { message: "not found" } }, { status: 404 });
  });
}

describe("Models projection cache", () => {
  test("coalesces and briefly reuses successful reads", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T00:00:00Z"));
    const fetchMock = installFetch();
    vi.stubGlobal("fetch", fetchMock);
    const client = new OperatorApiClient(config, auth);

    const first = client.modelSettings();
    const overlapping = client.modelSettings();

    expect(overlapping).toBe(first);
    await expect(first).resolves.toEqual({ revision: 1 });
    await expect(client.modelSettings()).resolves.toEqual({ revision: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    vi.advanceTimersByTime(60_001);
    await expect(client.modelSettings()).resolves.toEqual({ revision: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  test("bypasses or evicts cached reads when requested", async () => {
    const fetchMock = installFetch();
    vi.stubGlobal("fetch", fetchMock);
    const client = new OperatorApiClient(config, auth);

    await client.modelSettings();
    await client.modelSettings({ force: true });
    await client.modelSettings({ refreshCatalog: true });
    client.invalidateModelSettings();
    await client.modelSettings();

    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(String(fetchMock.mock.calls[3]?.[0])).toContain("refresh_catalog=1");
  });

  test("does not cache a failed read", async () => {
    const fetchMock = installFetch()
      .mockRejectedValueOnce(new Error("temporary network failure"));
    vi.stubGlobal("fetch", fetchMock);
    const client = new OperatorApiClient(config, auth);

    await expect(client.modelSettings()).rejects.toThrow("temporary network failure");
    await expect(client.modelSettings()).resolves.toEqual({ revision: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  test("summary reads do not wait for an in-flight provider catalog", async () => {
    let finish!: (value: Response) => void;
    const fullResponse = new Promise<Response>((resolve) => { finish = resolve; });
    const fallback = installFetch();
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = new URL(String(input));
      if (url.pathname !== "/models/settings") return fallback(input);
      return url.searchParams.get("view") === "summary"
        ? Promise.resolve(Response.json({ view: "summary" }))
        : fullResponse;
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new OperatorApiClient(config, auth);
    const full = client.modelSettings();
    const summary = client.modelSettings({ includeCatalog: false });
    await expect(summary).resolves.toEqual({ view: "summary" });
    expect(client.modelSettings({ includeCatalog: false })).toBe(summary);
    expect(client.modelSettings()).toBe(full);
    finish(Response.json({ view: "full" }));
    await expect(full).resolves.toEqual({ view: "full" });
    expect(fetchMock.mock.calls.filter(([input]) =>
      new URL(String(input)).pathname === "/models/settings"
    )).toHaveLength(2);
  });

  test("invalidates both views without letting an old response reenter the cache", async () => {
    let finish!: (value: Response) => void;
    const oldResponse = new Promise<Response>((resolve) => { finish = resolve; });
    const fallback = installFetch();
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      if (new URL(String(input)).pathname !== "/models/settings") return fallback(input);
      calls += 1;
      return calls === 1 ? oldResponse : Promise.resolve(Response.json({ revision: calls }));
    }));
    const client = new OperatorApiClient(config, auth);
    const old = client.modelSettings();
    await client.modelSettings({ includeCatalog: false });
    client.invalidateModelSettings();
    finish(Response.json({ revision: 1 }));
    await old;
    await expect(client.modelSettings()).resolves.toEqual({ revision: 3 });
    await expect(client.modelSettings({ includeCatalog: false })).resolves.toEqual({ revision: 4 });
  });
});
