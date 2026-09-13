import { afterEach, describe, expect, it, vi } from "vitest";

import { createOperatorApiSession } from "../src/operator-api-session.js";

afterEach(() => vi.unstubAllGlobals());

describe("createOperatorApiSession", () => {
  it("keeps remote APIs outside the loopback bootstrap flow", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(createOperatorApiSession("https://example.com")).resolves.toEqual({
      authMode: "none",
      roles: [],
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("continues without credentials when local auth is not registered", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 404 })));

    await expect(createOperatorApiSession("http://127.0.0.1:8010/")).resolves.toEqual({
      authMode: "none",
      roles: [],
    });
  });

  it("returns an in-memory bearer from the loopback local auth profile", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ source: "azure-cli", roles: ["Contributor"] }), {
        status: 200,
        headers: { "X-FDAI-Local-Session": "opaque-session" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const session = await createOperatorApiSession("http://localhost:8010");
    expect(session.authMode).toBe("local-azure-cli");
    expect(session.authorization).toBe("Bearer opaque-session");
    expect(session.roles).toEqual(["Contributor"]);
    expect(JSON.stringify(session)).not.toContain("opaque-session");
    expect(Object.isFrozen(session)).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8010/local-auth/me", {
      headers: { accept: "application/json" },
      redirect: "error",
    });
  });

  it("rejects bootstrap redirects instead of following them", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(null, {
        status: 302,
        headers: { location: "https://example.com/auth" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(createOperatorApiSession("http://127.0.0.1:8010")).rejects.toThrow(
      "bootstrap failed (302)",
    );
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects malformed session headers without exposing their value", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ roles: [] }), {
          status: 200,
          headers: { "X-FDAI-Local-Session": "bad token" },
        }),
      ),
    );

    await expect(createOperatorApiSession("http://[::1]:8010")).rejects.toThrow(
      "invalid local session token",
    );
  });
});
