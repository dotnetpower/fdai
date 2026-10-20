import { afterEach, describe, expect, test, vi } from "vitest";

import type { AccountInfo } from "@azure/msal-browser";

import {
  clearMsalActiveAccount,
  initAuth,
  interactiveLoginRequest,
  restoreMsalActiveAccount,
} from "./auth";
import type { ConsoleConfig } from "./config";

function config(overrides: Partial<ConsoleConfig> = {}): ConsoleConfig {
  return {
    operatorApiBaseUrl: "http://127.0.0.1:8000",
    ingestionApiBaseUrl: "http://127.0.0.1:8010",
    msalClientId: "",
    msalTenantId: "",
    msalApiScope: "",
    authTokenTimeoutMs: 10_000,
    operatorApiRequestTimeoutMs: 30_000,
    devMode: false,
    localAzureCliAuth: true,
    localLoginPrompt: false,
    workflowCatalogRepo: "",
    workflowCatalogBranch: "main",
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function account(id: string): AccountInfo {
  return {
    environment: "login.microsoftonline.com",
    homeAccountId: `home-${id}`,
    idTokenClaims: {},
    localAccountId: `local-${id}`,
    name: id,
    tenantId: "tenant",
    username: `${id}@example.com`,
  };
}

describe("MSAL active account restoration", () => {
  test("persists the redirect-selected account over an older active account", () => {
    const admin = account("admin");
    const reader = account("reader");
    const setActiveAccount = vi.fn();
    const client = {
      getActiveAccount: () => admin,
      getAllAccounts: () => [admin, reader],
      setActiveAccount,
    };

    expect(restoreMsalActiveAccount(client, reader)).toBe(reader);
    expect(setActiveAccount).toHaveBeenCalledWith(reader);
  });

  test("restores the matching cached active account instead of array order", () => {
    const admin = account("admin");
    const reader = account("reader");
    const setActiveAccount = vi.fn();
    const client = {
      getActiveAccount: () => ({ ...reader }),
      getAllAccounts: () => [admin, reader],
      setActiveAccount,
    };

    expect(restoreMsalActiveAccount(client, null)).toBe(reader);
    expect(setActiveAccount).toHaveBeenCalledWith(reader);
  });

  test("uses the only cached account when no active selection exists", () => {
    const reader = account("reader");
    const setActiveAccount = vi.fn();
    const client = {
      getActiveAccount: () => null,
      getAllAccounts: () => [reader],
      setActiveAccount,
    };

    expect(restoreMsalActiveAccount(client, null)).toBe(reader);
    expect(setActiveAccount).toHaveBeenCalledWith(reader);
  });

  test("requires selection instead of choosing the first of multiple accounts", () => {
    const admin = account("admin");
    const reader = account("reader");
    const setActiveAccount = vi.fn();
    const client = {
      getActiveAccount: () => null,
      getAllAccounts: () => [admin, reader],
      setActiveAccount,
    };

    expect(restoreMsalActiveAccount(client, null)).toBeNull();
    expect(setActiveAccount).toHaveBeenCalledWith(null);
  });

  test("does not restore an active account that is absent from the cache", () => {
    const admin = account("admin");
    const reader = account("reader");
    const setActiveAccount = vi.fn();
    const client = {
      getActiveAccount: () => account("removed"),
      getAllAccounts: () => [admin, reader],
      setActiveAccount,
    };

    expect(restoreMsalActiveAccount(client, null)).toBeNull();
    expect(setActiveAccount).toHaveBeenCalledWith(null);
  });

  test("clears the active account before sign-out redirect", () => {
    const setActiveAccount = vi.fn();

    clearMsalActiveAccount({
      getActiveAccount: () => account("reader"),
      getAllAccounts: () => [account("reader")],
      setActiveAccount,
    });

    expect(setActiveAccount).toHaveBeenCalledWith(null);
  });
});

describe("local Azure CLI auth", () => {
  test("projects the local profile with a process-local bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          oid: "cli-user",
          username: "operator@example.com",
          name: "Example Operator",
          roles: ["Contributor"],
          source: "azure-cli",
        }),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "x-fdai-local-session": "local-session-token",
          },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const auth = await initAuth(config());

    expect(auth.localAzureCli).toBe(true);
    expect(auth.account?.homeAccountId).toBe("cli-user");
    expect(auth.account?.username).toBe("operator@example.com");
    expect(auth.account?.idTokenClaims?.roles).toEqual(["Contributor"]);
    expect(await auth.getAuthorizationHeader()).toBe("Bearer local-session-token");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/local-auth/me",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  describe("interactive login request", () => {
    test("uses the current username for ordinary authentication recovery", () => {
      expect(interactiveLoginRequest("api://fdai/access", {
        username: "operator@example.com",
      })).toEqual({
        scopes: ["api://fdai/access"],
        loginHint: "operator@example.com",
      });
    });

    test("opens the account picker without retaining the current login hint", () => {
      expect(interactiveLoginRequest(
        "api://fdai/access",
        { username: "operator@example.com" },
        { selectAccount: true },
      )).toEqual({
        scopes: ["api://fdai/access"],
        prompt: "select_account",
      });
    });

    test("requires a fresh provider login for Slack approval handoff", () => {
      expect(interactiveLoginRequest(
        "api://fdai/access",
        { username: "operator@example.com" },
        { reauthenticate: true },
      )).toEqual({ scopes: ["api://fdai/access"], prompt: "login" });
    });
  });

  test("rejects ambiguous anonymous and CLI modes", async () => {
    await expect(initAuth(config({ devMode: true }))).rejects.toThrow("MUST NOT both");
  });

  test("rejects a malformed local profile", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          { source: "azure-cli" },
          { headers: { "x-fdai-local-session": "local-session-token" } },
        ),
      ),
    );

    await expect(initAuth(config())).rejects.toThrow("invalid profile");
  });

  test("rejects a profile response without a local session token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          oid: "cli-user",
          username: "operator@example.com",
          name: null,
          roles: ["Contributor"],
          source: "azure-cli",
        }),
      ),
    );

    await expect(initAuth(config())).rejects.toThrow("no local session token");
  });

  test("keeps immediate anonymous bypass when the local prompt is disabled", async () => {
    const auth = await initAuth(config({
      devMode: true,
      localAzureCliAuth: false,
      localLoginPrompt: false,
    }));

    expect(auth.devMode).toBe(true);
    expect(auth.interactiveSignIn).toBe(false);
    expect(auth.account).toBeNull();
  });
});
