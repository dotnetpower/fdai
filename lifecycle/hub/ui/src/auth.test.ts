import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const account = { homeAccountId: "a", username: "operator" };
const client = {
  initialize: vi.fn(async () => undefined),
  handleRedirectPromise: vi.fn(async () => null),
  getAllAccounts: vi.fn(() => [account]),
  setActiveAccount: vi.fn(),
  acquireTokenSilent: vi.fn(),
  acquireTokenRedirect: vi.fn(async () => undefined),
};

vi.mock("@azure/msal-browser", () => {
  class InteractionRequiredAuthError extends Error {}
  class BrowserAuthError extends Error {
    constructor(public errorCode: string) { super(errorCode); }
  }
  return {
    InteractionRequiredAuthError,
    BrowserAuthError,
    PublicClientApplication: vi.fn(function () { return client; }),
  };
});

async function authorize(): Promise<string> {
  const { initializeAuth, authenticatedFetch } = await import("./auth");
  expect(await initializeAuth({} as HTMLElement)).toBe(true);
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockResolvedValueOnce(new Response("{}"));
  await authenticatedFetch("/v1/x");
  const headers = fetchMock.mock.calls.at(-1)?.[1]?.headers as Headers;
  return headers.get("Authorization") ?? "";
}

describe("access token renewal", () => {
  const store = new Map<string, string>();

  beforeEach(() => {
    vi.resetModules();
    store.clear();
    vi.stubGlobal("window", { location: { origin: "https://hub.example" } });
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      profile: "remote-development", clientId: "c", authority: "https://login.example/t",
      scope: "api://x/.default", origin: "https://hub.example",
    }))));
    client.acquireTokenSilent.mockReset();
    client.acquireTokenRedirect.mockClear();
  });

  afterEach(() => vi.unstubAllGlobals());

  test("uses the silently acquired token", async () => {
    client.acquireTokenSilent.mockResolvedValue({ accessToken: "tok" });
    expect(await authorize()).toBe("Bearer tok");
    expect(client.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  test("renews by redirect when the framed renewal times out", async () => {
    const { BrowserAuthError } = await import("@azure/msal-browser");
    client.acquireTokenSilent.mockRejectedValue(
      new (BrowserAuthError as unknown as new (code: string) => Error)("monitor_window_timeout"),
    );
    const outcome = await Promise.race([
      authorize(), new Promise((resolve) => setTimeout(() => resolve("pending"), 50)),
    ]);
    expect(outcome).toBe("pending");
    expect(client.acquireTokenRedirect).toHaveBeenCalledTimes(1);
  });

  test("does not loop redirects", async () => {
    const { InteractionRequiredAuthError } = await import("@azure/msal-browser");
    client.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError("login_required"));
    store.set("fdai.hub.auth.redirect-at", String(Date.now()));
    await expect(authorize()).rejects.toThrow("login_required");
    expect(client.acquireTokenRedirect).not.toHaveBeenCalled();
  });

  test("propagates unrelated failures", async () => {
    client.acquireTokenSilent.mockRejectedValue(new Error("network"));
    await expect(authorize()).rejects.toThrow("network");
    expect(client.acquireTokenRedirect).not.toHaveBeenCalled();
  });
});
