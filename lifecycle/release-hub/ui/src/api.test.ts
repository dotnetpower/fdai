import { afterEach, describe, expect, it, vi } from "vitest";
import { actionsFor, artifacts, isCustomChannel, releaseTitle, requestCatalog, schemaCompatibility, type Release } from "./api";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("release action boundaries", () => {
  const base = { id: "1.0.0" } as Release;
  it("keeps the custom namespace exact, bounded and separate from signed bundle channels", () => {
    for (const name of ["custom-pilot", "custom-a1", `custom-${"a".repeat(57)}`]) {
      expect(isCustomChannel(name)).toBe(true);
    }
    for (const name of ["DEV", "development", "custom-", "custom-Pilot", "custom-a--b", "custom-a\n", `custom-${"a".repeat(58)}`]) {
      expect(isCustomChannel(name)).toBe(false);
    }
  });
  it("transmits the independently reviewed destination confirmation without retry", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 3 }) });
    vi.stubGlobal("fetch", fetch);
    const body = { revision: 2, confirmation: "1.0.0", reason: "Reviewed destination",
      channel: "custom-pilot", channel_confirmation: "custom-pilot" };
    await requestCatalog("/v1/releases/1.0.0/contribute", body);
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ body: JSON.stringify(body), method: "POST" });
  });
  it("never offers publication or contribution for a recalled release", () => {
    expect(actionsFor({ ...base, state: "recalled" })).toEqual([]);
    expect(actionsFor({ ...base, state: "draft" })).toEqual(["publish"]);
    expect(actionsFor({ ...base, state: "published" })).toEqual(["contribute", "recall"]);
  });
  it("preserves full artifact and evidence digests", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    expect(artifacts(JSON.stringify({ services: { core: { image_digest: digest, sbom_sha256: "b".repeat(64) } } })))
      .toEqual([{ component: "core", digest, sbom: "b".repeat(64) }]);
  });
  it.each(["example-web", "example-worker", "fdai"])("renders %s without application branches", (product) => {
    const digest = `sha256:${"a".repeat(64)}`;
    const manifest = JSON.stringify({ product, workloads: { frontend: { image_digest: digest } } });
    expect(releaseTitle({ ...base, manifest })).toBe(`${product} 1.0.0`);
    expect(schemaCompatibility(manifest)).toBe("Not declared (stateless package)");
    expect(artifacts(manifest)).toEqual([{ component: "frontend", digest, sbom: "Not declared" }]);
  });
  it("does not invent a product for a legacy manifest", () => {
    const manifest = JSON.stringify({ schema: { target: 6, tolerates: { minimum: 5, maximum: 7 } } });
    expect(releaseTitle({ ...base, manifest })).toBe("Release 1.0.0");
    expect(schemaCompatibility(manifest)).toBe("5 - 7 (target 6)");
  });
  it("surfaces server denial without success-shaped defaults", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ error: "Catalog changed." }) }));
    await expect(requestCatalog()).rejects.toThrow("Catalog changed.");
  });
  it("does not retry an ambiguous failed write", async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError("Network unavailable"));
    vi.stubGlobal("fetch", fetch);
    await expect(requestCatalog("/v1/releases/1.0.0/recall", { revision: 1, confirmation: "1.0.0", reason: "withdraw" })).rejects.toThrow();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("posts only the reviewed freshness confirmation under a bounded signal", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ revision: 3 }) });
    vi.stubGlobal("fetch", fetch);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = { revision: 2, confirmation: "renew 2", reason: "Reviewed current eligibility" };
    expect(await requestCatalog("/v1/catalog/renew", body)).toEqual({ revision: 3 });
    expect(timeout).toHaveBeenCalledWith(10_000);
    expect(fetch).toHaveBeenCalledOnce();
    const call = fetch.mock.calls[0];
    if (!call) throw new Error("Expected a renewal request.");
    expect(call[0]).toBe("/v1/catalog/renew");
    expect(call[1]).toMatchObject({ method: "POST", body: JSON.stringify(body) });
    expect(call[1].signal).toBeInstanceOf(AbortSignal);
  });
  it("never retries a renewal after its request is aborted", async () => {
    const controller = new AbortController();
    vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    const fetch = vi.fn((_path: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Timed out", "TimeoutError")));
    }));
    vi.stubGlobal("fetch", fetch);
    const request = requestCatalog("/v1/catalog/renew", { revision: 2, confirmation: "renew 2", reason: "Review" });
    const result = expect(request).rejects.toThrow("Timed out");
    controller.abort();
    await result;
    expect(fetch).toHaveBeenCalledOnce();
  });
});
