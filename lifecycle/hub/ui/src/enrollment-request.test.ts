import { afterEach, describe, expect, it, vi } from "vitest";
import { hubApi, HubApiError } from "./api";

vi.mock("./auth", () => ({
  authenticatedFetch: (path: string, init?: RequestInit) => fetch(path, init),
}));

const signed = { signed_payload: "e30=", proof: "cHJvb2Y=" };
const file = (value: unknown) => new File([JSON.stringify(value)], "request.json");

afterEach(() => vi.unstubAllGlobals());

describe("operator enrollment submission", () => {
  it("submits only the signed bytes to the exact installation request route", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      enrollment: "pending", installation_key_id: "installation-test",
    }), { status: 202 }));
    vi.stubGlobal("fetch", fetcher);

    await hubApi.requestEnrollment("nginx-dev", file(signed));

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/v1/enrollments/nginx-dev/requests", {
      method: "POST", body: JSON.stringify(signed),
      headers: { "content-type": "application/json" },
      signal: expect.any(AbortSignal),
    });
  });

  it.each([
    { signed_payload: "e30=" },
    { ...signed, private_key: "not-allowed" },
    { ...signed, proof: "" },
    { ...signed, proof: "not base64" },
    null,
    [],
  ])("rejects malformed or extra fields without sending them", async value => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await expect(hubApi.requestEnrollment("nginx-dev", file(value))).rejects.toThrow("only base64");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects invalid JSON, empty and oversized files before a network request", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    for (const input of [
      new File(["{"], "invalid.json"),
      new File([], "empty.json"),
      new File([" ".repeat(64 * 1024 + 1)], "large.json"),
    ]) {
      await expect(hubApi.requestEnrollment("nginx-dev", input)).rejects.toThrow();
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects path-changing installation IDs", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await expect(hubApi.requestEnrollment("../other", file(signed))).rejects.toThrow("valid installation ID");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("surfaces stale proof or binding denial without automatic retries", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: "enrollment_proof_stale",
    }), { status: 403 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(hubApi.requestEnrollment("nginx-dev", file(signed))).rejects.toBeInstanceOf(HubApiError);
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
