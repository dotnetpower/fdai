import { afterEach, describe, expect, it, vi } from "vitest";
import { requestDeploymentRequests, type DeploymentRequestPage } from "./api";
import { nextRequestOffset } from "./deployment-requests";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const record = {
  request_id: "a".repeat(64), subscription_id: "00000000-0000-0000-0000-000000000000",
  release_id: "1.6.0", channel: "DEV", region: "eastus", source_commit: "b".repeat(40),
  catalog_digest: "c".repeat(64), recorded_at: "2026-10-25T12:00:00Z",
  status: "requested", trust: "self-reported",
};
const page = { requests: [record], limit: 25, offset: 25, has_more: true };

describe("operator deployment requests", () => {
  it("follows has_more beyond the old offset ceiling and stops at the retained end", async () => {
    const later = { ...page, offset: 10000 } as DeploymentRequestPage;
    expect(nextRequestOffset(later)).toBe(10025);
    expect(nextRequestOffset({ ...later, offset: 99950 })).toBe(99975);
    expect(nextRequestOffset({ ...later, offset: 99975, has_more: false })).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ...page, offset: 10025 }),
    }));
    await expect(requestDeploymentRequests("", 10025)).resolves.toMatchObject({ offset: 10025 });
  });
  it("requests the exact subscription page without a write or automatic retry", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => page });
    vi.stubGlobal("fetch", fetch);
    await expect(requestDeploymentRequests(record.subscription_id, 25)).resolves.toEqual(page);
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toBe(`/v1/deployment-requests?limit=25&offset=25&subscription_id=${record.subscription_id}`);
    expect(fetch.mock.calls[0]?.[1]).not.toHaveProperty("method");
  });
  it("keeps unavailable operator access distinct from an empty list", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ error: "authentication_required" }) });
    vi.stubGlobal("fetch", fetch);
    await expect(requestDeploymentRequests()).rejects.toThrow("operator access");
    expect(fetch).toHaveBeenCalledOnce();
  });
  it.each([
    { ...page, offset: 0 }, { ...page, requests: [{ ...record, trust: "verified" }] },
    { ...page, requests: [{ ...record, status: "deployed" }] },
    { ...page, requests: [{ ...record, recorded_at: "invalid" }] },
    { ...page, requests: [null] }, { ...page, has_more: "yes" },
  ])("rejects misleading or malformed server state", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
    await expect(requestDeploymentRequests("", 25)).rejects.toThrow("Invalid deployment request page");
  });
  it("accepts an explicitly empty page", async () => {
    const empty = { requests: [], limit: 25, offset: 0, has_more: false };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => empty }));
    await expect(requestDeploymentRequests()).resolves.toEqual(empty);
  });
});
