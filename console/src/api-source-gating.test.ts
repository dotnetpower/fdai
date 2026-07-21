import { afterEach, describe, expect, test, vi } from "vitest";

import { ReadApiClient, ReadApiError } from "./api";
import type { AuthContext } from "./auth";
import { observeUnauthorizedApiResponses } from "./auth-response";
import type { ConsoleConfig } from "./config";

const config: ConsoleConfig = {
  readApiBaseUrl: "http://127.0.0.1:8010",
  ingestionApiBaseUrl: "http://127.0.0.1:8011",
  msalClientId: "",
  msalTenantId: "",
  msalApiScope: "",
  authTokenTimeoutMs: 10_000,
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

afterEach(() => vi.unstubAllGlobals());

describe("read source gating", () => {
  test("does not fetch a route whose authoritative source is unavailable", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({
      surface: "read-data-sources",
      sources: [{
        key: "operational-state",
        source: "empty-local-memory",
        routes: ["/kpi"],
        availability: "unavailable",
        configured: true,
        reachable: true,
        authoritative: false,
        durable: false,
        synthetic: false,
        reason: "Authoritative state is not connected.",
        last_observed_at: null,
      }],
    }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new ReadApiClient(config, auth);

    await expect(client.dashboardMetrics()).rejects.toEqual(
      expect.objectContaining<Partial<ReadApiError>>({
        status: 503,
        message: "Authoritative state is not connected.",
      }),
    );
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://127.0.0.1:8010/system/data-sources",
    );
  });

  test("does not fetch a descendant of an unavailable source route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({
      surface: "read-data-sources",
      sources: [{
        key: "process-state",
        source: "not-configured",
        routes: ["/views/process"],
        availability: "unavailable",
        configured: false,
        reachable: null,
        authoritative: false,
        durable: null,
        synthetic: false,
        reason: "Process state is not connected.",
        last_observed_at: null,
      }],
    }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new ReadApiClient(config, auth);

    await expect(client.panel("/views/process/run-1/events")).rejects.toEqual(
      expect.objectContaining<Partial<ReadApiError>>({
        status: 503,
        message: "Process state is not connected.",
      }),
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  test("reports unauthorized requests and retries a failed source manifest", async () => {
    const onUnauthorized = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(
        { error: { status: 401, message: "Authorization header missing" } },
        { status: 401 },
      ))
      .mockResolvedValueOnce(Response.json({
        surface: "read-data-sources",
        sources: [],
      }));
    vi.stubGlobal("fetch", fetchMock);
      const stopObserving = observeUnauthorizedApiResponses(
        [config.readApiBaseUrl],
        onUnauthorized,
      );
    const client = new ReadApiClient(config, auth, { onUnauthorized });

      try {
        await expect(client.dataSources()).rejects.toEqual(
          expect.objectContaining({ status: 401 }),
        );
        await expect(client.dataSources()).resolves.toEqual({
          surface: "read-data-sources",
          sources: [],
        });
        expect(onUnauthorized).toHaveBeenCalledOnce();
        expect(fetchMock).toHaveBeenCalledTimes(2);
      } finally {
        stopObserving();
      }
  });
});
