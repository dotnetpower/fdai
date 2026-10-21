import { afterEach, describe, expect, it, vi } from "vitest";
import { actionsFor, artifacts, releaseTitle, requestCatalog, schemaCompatibility, type Release } from "./api";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("release action boundaries", () => {
  const base = { id: "1.0.0", manifest: JSON.stringify({ schema_version: "fdai.runtime-release.v3" }) } as Release;
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
  it("separates nginx acceptance from FDAI services and database compatibility", () => {
    const manifest = JSON.stringify({
      schema_version: "fdai.nginx-acceptance-release.v1",
      workloads: { nginx: { image_digest: `sha256:${"a".repeat(64)}` } },
    });
    const release = { ...base, manifest, state: "published" } as Release;
    expect(actionsFor(release)).toEqual(["recall"]);
    expect(releaseTitle(release)).toBe("nginx acceptance 1.0.0");
    expect(schemaCompatibility(manifest)).toBe("Not applicable (nginx acceptance; no database)");
    expect(artifacts(manifest)).toEqual([{
      component: "nginx", digest: `sha256:${"a".repeat(64)}`,
      sbom: "Not declared for acceptance workload",
    }]);
  });
  it("preserves runtime schema information and FDAI labels", () => {
    expect(releaseTitle(base)).toBe("FDAI 1.0.0");
    expect(schemaCompatibility(JSON.stringify({
      schema: { target: 15, tolerates: { minimum: 12, maximum: 16 } },
    }))).toBe("12 - 16 (target 15)");
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
