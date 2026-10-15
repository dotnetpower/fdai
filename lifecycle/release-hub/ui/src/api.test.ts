import { afterEach, describe, expect, it, vi } from "vitest";
import { actionsFor, artifacts, requestCatalog, type Release } from "./api";

afterEach(() => vi.unstubAllGlobals());
describe("release action boundaries", () => {
  const base = { id: "1.0.0" } as Release;
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
});
