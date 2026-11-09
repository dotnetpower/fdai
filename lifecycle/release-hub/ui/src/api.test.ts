import { afterEach, describe, expect, it, vi } from "vitest";
import { actionsFor, artifacts, catalogChangeObserved, catalogRecovery, CatalogRequestError, isCustomChannel, parseReleaseManifest, releaseStateIndex, releaseTitle, requestCatalog, requestCatalogExport, requestEntraLogout, requestStencilCatalog, requestStencilCompose, schemaCompatibility, type Catalog, type Release, type StencilComposePayload } from "./api";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function stencilCatalog(panel: Record<string, unknown>) {
  return {
    presets: [],
    panels: [panel],
    workloads: [],
    locked_workloads: [],
    scheduled_jobs: [],
    locked_scheduled_jobs: [],
    loops: [],
    locked_loops: [],
    addons: [],
    locked_addons: [],
    locked_panels: [],
  };
}

const VALID_PANEL = {
  id: "detection-readiness",
  path: "/detection-coverage",
  group: "operations",
  label: "Detection coverage",
  label_ko: "감지 커버리지",
  locked: false,
  required_workloads: [],
  required_loops: [],
  required_addons: [],
  feature_ids: [],
};

describe("release action boundaries", () => {
  const base = { id: "1.0.0" } as Release;
  const catalog = (revision = 3) => ({
    revision,
    updated_at: "2026-10-15T13:00:00Z",
    expires_at: "2026-10-16T13:00:00Z",
    expired: false,
    key_id: "development",
    mode: "local-development",
    releases: [],
    channels: {},
    events: [],
  });
  it("keeps the custom namespace exact, bounded and separate from signed bundle channels", () => {
    for (const name of ["custom-pilot", "custom-a1", `custom-${"a".repeat(57)}`]) {
      expect(isCustomChannel(name)).toBe(true);
    }
    for (const name of ["DEV", "development", "custom-", "custom-Pilot", "custom-a--b", "custom-a\n", `custom-${"a".repeat(58)}`]) {
      expect(isCustomChannel(name)).toBe(false);
    }
  });
  it("transmits the independently reviewed destination confirmation without retry", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => catalog() });
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
  it("indexes release states once for repeated channel membership lookups", () => {
    let reads = 0;
    const releases = ["1.0.0", "1.1.0"].map((id) => ({
      ...base,
      id,
      get state() {
        reads += 1;
        return id === "1.0.0" ? "recalled" as const : "published" as const;
      },
    }));
    const states = releaseStateIndex(releases);
    for (let index = 0; index < 100; index += 1) {
      expect(states.get("1.0.0")).toBe("recalled");
      expect(states.get("1.1.0")).toBe("published");
    }
    expect(reads).toBe(2);
  });
  it("preserves full artifact and evidence digests", () => {
    const digest = `sha256:${"a".repeat(64)}`;
    expect(artifacts(parseReleaseManifest(JSON.stringify({ services: { core: { image_digest: digest, sbom_sha256: "b".repeat(64) } } }))))
      .toEqual([{ component: "core", digest, sbom: "b".repeat(64) }]);
  });
  it.each(["example-web", "example-worker", "fdai"])("renders %s without application branches", (product) => {
    const digest = `sha256:${"a".repeat(64)}`;
    const raw = JSON.stringify({ product, workloads: { frontend: { image_digest: digest } } });
    const manifest = parseReleaseManifest(raw);
    expect(releaseTitle({ ...base, manifest: raw }, manifest)).toBe(`${product} 1.0.0`);
    expect(schemaCompatibility(manifest)).toBe("Not declared (stateless package)");
    expect(artifacts(manifest)).toEqual([{ component: "frontend", digest, sbom: "Not declared" }]);
  });
  it("does not invent a product for a legacy manifest", () => {
    const raw = JSON.stringify({ schema: { target: 6, tolerates: { minimum: 5, maximum: 7 } } });
    const manifest = parseReleaseManifest(raw);
    expect(releaseTitle({ ...base, manifest: raw }, manifest)).toBe("Release 1.0.0");
    expect(schemaCompatibility(manifest)).toBe("5 - 7 (target 6)");
  });
  it("parses one detail manifest once for all derived views", () => {
    const parse = vi.spyOn(JSON, "parse");
    const raw = JSON.stringify({
      product: "example-web",
      schema: { target: 0, tolerates: { minimum: 0, maximum: 0 } },
      workloads: { frontend: { image_digest: `sha256:${"a".repeat(64)}` } },
    });
    const manifest = parseReleaseManifest(raw);
    releaseTitle({ ...base, manifest: raw }, manifest);
    schemaCompatibility(manifest);
    artifacts(manifest);
    expect(parse).toHaveBeenCalledTimes(1);
  });
  it("surfaces server denial without success-shaped defaults", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ error: "Catalog changed." }) }));
    await expect(requestCatalog()).rejects.toThrow("Catalog changed.");
  });
  it("does not claim sign-out succeeded on a rejected or still-authenticated response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 503, json: async () => ({ error: "Not ready" }),
    }));
    await expect(requestEntraLogout()).rejects.toThrow("sign-out was rejected");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ authenticated: true, session: { principal: "operator" } }),
    }));
    await expect(requestEntraLogout()).rejects.toThrow("not confirmed");
  });
  it("downloads exact export bytes through the authenticated fetch path", async () => {
    const raw = '{"revision":4,"snapshot":"exact bytes"}\n';
    const fetch = vi.fn().mockResolvedValue(new Response(raw, {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetch);
    expect(await (await requestCatalogExport()).text()).toBe(raw);
    expect(fetch).toHaveBeenCalledWith("/v1/catalog/export", expect.objectContaining({ cache: "no-store" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("denied", { status: 401 })));
    await expect(requestCatalogExport()).rejects.toThrow("export unavailable");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>sign in</html>", { status: 200 })));
    await expect(requestCatalogExport()).rejects.toThrow("unexpected content type");
  });
  it("rejects incomplete Stencil catalog and compose responses before using nested fields", async () => {
    const payload: StencilComposePayload = {
      stencil_id: "lite-observe-alert", title: "Lite", title_ko: "경량",
      description: "", description_ko: "", topology_profile: "lite-observe-alert",
      requested_panel_ids: [], requested_workloads: [], requested_scheduled_jobs: [],
      requested_loops: [], requested_addons: [], auto_resolve_dependencies: true,
      release_version: "1.0.0", source_commit: "auto",
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ presets: [], panels: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ stencil: {}, footprint: {}, release_manifest: {} }) });
    vi.stubGlobal("fetch", fetch);
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
    await expect(requestStencilCompose(payload)).rejects.toThrow("Invalid Stencil composition payload");
  });
  it.each([
    ["invalid id", { ...VALID_PANEL, id: "Detection_Readiness" }],
    ["unknown group", { ...VALID_PANEL, group: "other" }],
    ["invalid path", { ...VALID_PANEL, path: "/Detection-Coverage" }],
    ["blank English label", { ...VALID_PANEL, label: " " }],
    ["control character in Korean label", { ...VALID_PANEL, label_ko: "감지\n커버리지" }],
  ])("rejects %s in Stencil panel descriptors", async (_label, panel) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => stencilCatalog(panel),
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it("preserves a specific promotion rejection while advising a fresh review", () => {
    expect(catalogRecovery(new CatalogRequestError("Promotion stage blocked (promotion_canary_unhealthy).", 409)))
      .toContain("Healthy canary observations are insufficient");
  });
  it("attributes a capability recall only to its matching readback event", () => {
    const change = { revision: 3, confirmation: "isolated-executor", reason: "Defect found" };
    const readBack: Catalog = {
      ...catalog(4), events: [{
        revision: 4, release_id: "isolated-executor", action: "recall_capability",
        reason: "Defect found", channel: null, occurred_at: "2026-10-15T13:00:00Z",
      }],
    };
    expect(catalogChangeObserved(readBack, "recall_capability", "isolated-executor", change)).toBe(true);
    expect(catalogChangeObserved(readBack, "lift_capability", "isolated-executor", change)).toBe(false);
    expect(catalogChangeObserved(readBack, "recall_capability", "other", change)).toBe(false);
  });
  it("uses a stable status error when a failed response is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => { throw new SyntaxError("Unexpected token"); },
    }));
    await expect(requestCatalog()).rejects.toThrow("Request failed (502).");
  });
  it("rejects blank server errors and malformed successful catalogs", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ error: "   " }),
    }));
    await expect(requestCatalog()).rejects.toThrow("Request failed (409).");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ revision: 3 }),
    }));
    await expect(requestCatalog()).rejects.toThrow("invalid catalog");
  });
  it("rejects malformed catalog dates, channel members, releases, and events before rendering", async () => {
    const invalidCatalogs = [
      { ...catalog(), expires_at: "invalid" },
      { ...catalog(), channels: { DEV: null } },
      { ...catalog(), releases: [{ id: "1.0.0" }] },
      { ...catalog(), events: [{ revision: 1, action: "publish" }] },
    ];
    const fetch = vi.fn().mockImplementation((_path: string) => Promise.resolve({
      ok: true, status: 200, json: async () => invalidCatalogs.shift(),
    }));
    vi.stubGlobal("fetch", fetch);
    for (let index = 0; index < 4; index += 1) {
      await expect(requestCatalog()).rejects.toThrow("invalid catalog");
    }
    expect(fetch).toHaveBeenCalledTimes(4);
  });
  it("reports invalid JSON separately from a valid catalog", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => { throw new SyntaxError("Unexpected token"); },
    }));
    await expect(requestCatalog()).rejects.toThrow("Release Hub returned invalid JSON.");
  });
  it("does not retry an ambiguous failed write", async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError("Network unavailable"));
    vi.stubGlobal("fetch", fetch);
    await expect(requestCatalog("/v1/releases/1.0.0/recall", { revision: 1, confirmation: "1.0.0", reason: "withdraw" })).rejects.toThrow();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("posts only the reviewed freshness confirmation under a bounded signal", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => catalog() });
    vi.stubGlobal("fetch", fetch);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const body = { revision: 2, confirmation: "renew 2", reason: "Reviewed current eligibility" };
    expect(await requestCatalog("/v1/catalog/renew", body)).toEqual(catalog());
    expect(timeout).toHaveBeenCalledWith(10_000);
    expect(fetch).toHaveBeenCalledOnce();
    const call = fetch.mock.calls[0];
    if (!call) throw new Error("Expected a renewal request.");
    expect(call[0]).toBe("/v1/catalog/renew");
    expect(call[1]).toMatchObject({ method: "POST", body: JSON.stringify(body) });
    expect(call[1].signal).toBeInstanceOf(AbortSignal);
  });
  it("fails closed when artifact evidence has no digest", () => {
    const manifest = JSON.stringify({ services: { core: { sbom_sha256: "b".repeat(64) } } });
    expect(() => artifacts(parseReleaseManifest(manifest))).toThrow("Artifact core has no digest.");
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
