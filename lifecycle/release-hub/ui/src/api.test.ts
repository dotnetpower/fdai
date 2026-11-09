import { afterEach, describe, expect, it, vi } from "vitest";
import { actionsFor, artifacts, catalogChangeObserved, catalogRecovery, CatalogRequestError, isCustomChannel, parseReleaseManifest, releaseStateIndex, releaseTitle, requestCatalog, requestCatalogExport, requestEntraLogout, requestStencilCatalog, requestStencilCompose, schemaCompatibility, type Catalog, type Release, type StencilComposePayload } from "./api";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function stencilCatalog(
  panel: Record<string, unknown>,
  additionalPanels: Record<string, unknown>[] = [],
  presets: Record<string, unknown>[] = [],
) {
  return {
    presets,
    panels: [panel, ...additionalPanels],
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

const VALID_STENCIL = {
  schema_version: "fdai.stencil-definition.v1",
  stencil_id: "lite-observe-alert",
  title: "Lite",
  title_ko: "경량",
  description: "Lite profile",
  description_ko: "경량 프로필",
  topology_profile: "lite-observe-alert",
  enabled_workloads: [],
  enabled_scheduled_jobs: [],
  enabled_loops: [],
  enabled_addons: [],
  enabled_panel_ids: ["detection-readiness"],
  authority_granted: false,
};

const VALID_FEATURE_FLAGS = {
  schema_version: "fdai.stencil-feature-flags.v1",
  stencil_id: "lite-observe-alert",
  stencil_digest: `sha256:${"a".repeat(64)}`,
  feature_flags_digest: `sha256:${"b".repeat(64)}`,
  enforcement_mode: "fail-closed",
  enabled_panel_ids: ["detection-readiness"],
  disabled_panel_ids: ["labs"],
  enabled_loops: [],
  disabled_loops: [],
  enabled_workloads: [],
  disabled_workloads: [],
  enabled_scheduled_jobs: [],
  disabled_scheduled_jobs: [],
  enabled_addons: [],
  disabled_addons: [],
  panel_flags: { "detection-readiness": true, labs: false },
  loop_flags: {},
  workload_flags: {},
  scheduled_job_flags: {},
  addon_flags: {},
  runtime_env: { FDAI_STENCIL_ID: "lite-observe-alert" },
};

const VALID_FOOTPRINT = {
  stencil_id: "lite-observe-alert",
  stencil_digest: `sha256:${"a".repeat(64)}`,
  topology_profile: "lite-observe-alert",
  azure_rbac_posture: "read-only-observation",
  console_build_command: "npm run build",
  includes_clamav_sidecar: false,
  includes_privileged_executor: false,
  workload_count: 0,
  total_workloads: 0,
  scheduled_job_count: 0,
  enabled_panel_count: 1,
  total_panel_count: 1,
  omitted_panel_count: 0,
  omitted_workloads: [],
  omitted_scheduled_jobs: [],
  omitted_loops: [],
  disabled_panel_ids: [],
  disabled_loops: [],
  active_navigation_groups: ["operations"],
  enabled_feature_ids: [],
  required_azure_roles: [],
  terraform_flags: {
    enable_document_ingestion_workloads: false,
    enable_isolated_executor: false,
    product_profile_mode: "observation-first",
  },
  feature_flags: VALID_FEATURE_FLAGS,
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
  it.each([
    ["duplicate panel ids", { ...VALID_PANEL, path: "/other-path" }],
    ["duplicate panel paths", { ...VALID_PANEL, id: "other-panel" }],
  ])("rejects %s", async (_label, duplicate) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => stencilCatalog(VALID_PANEL, [duplicate]),
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    ["unknown locked panel", stencilCatalog(VALID_PANEL), ["missing-panel"]],
    [
      "unknown preset panel",
      stencilCatalog(VALID_PANEL, [], [{
        stencil: { ...VALID_STENCIL, enabled_panel_ids: ["missing-panel"] },
        footprint: VALID_FOOTPRINT,
      }]),
      [],
    ],
    [
      "duplicate preset panel",
      stencilCatalog(VALID_PANEL, [], [{
        stencil: {
          ...VALID_STENCIL,
          enabled_panel_ids: ["detection-readiness", "detection-readiness"],
        },
        footprint: VALID_FOOTPRINT,
      }]),
      [],
    ],
  ])("rejects %s references", async (_label, payload, lockedPanels) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...payload, locked_panels: lockedPanels }),
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    ["duplicate workloads", { ...stencilCatalog(VALID_PANEL), workloads: ["core", "core"] }],
    [
      "unknown locked workload",
      { ...stencilCatalog(VALID_PANEL), locked_workloads: ["missing-workload"] },
    ],
    [
      "unknown panel dependency",
      stencilCatalog({ ...VALID_PANEL, required_loops: ["missing-loop"] }),
    ],
    [
      "unknown preset workload",
      stencilCatalog(VALID_PANEL, [], [{
        stencil: { ...VALID_STENCIL, enabled_workloads: ["missing-workload"] },
        footprint: VALID_FOOTPRINT,
      }]),
    ],
  ])("rejects %s in Stencil runtime axes", async (_label, payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    [
      "unknown axis descriptor",
      {
        ...stencilCatalog(VALID_PANEL),
        workloads_catalog: [{
          id: "missing",
          label: "Missing",
          label_ko: "누락",
          summary: "Missing workload",
          summary_ko: "누락된 워크로드",
          agents: [],
          locked: false,
        }],
      },
    ],
    [
      "axis descriptor lock mismatch",
      {
        ...stencilCatalog(VALID_PANEL),
        workloads: ["core"],
        locked_workloads: ["core"],
        workloads_catalog: [{
          id: "core",
          label: "Core",
          label_ko: "Core",
          summary: "Core service",
          summary_ko: "Core 서비스",
          agents: [],
          locked: false,
        }],
      },
    ],
    [
      "blank axis descriptor label",
      {
        ...stencilCatalog(VALID_PANEL),
        workloads: ["core"],
        workloads_catalog: [{
          id: "core",
          label: " ",
          label_ko: "Core",
          summary: "Core service",
          summary_ko: "Core 서비스",
          agents: [],
          locked: false,
        }],
      },
    ],
  ])("rejects %s", async (_label, payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    ["unknown schema", { ...VALID_STENCIL, schema_version: "unknown" }],
    ["invalid Stencil id", { ...VALID_STENCIL, stencil_id: "Lite_Profile" }],
    ["blank title", { ...VALID_STENCIL, title: " " }],
    ["control character in description", { ...VALID_STENCIL, description: "Bad\nprofile" }],
    ["unknown topology", { ...VALID_STENCIL, topology_profile: "other" }],
  ])("rejects %s in Stencil definitions", async (_label, stencil) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => stencilCatalog(VALID_PANEL, [], [{
        stencil,
        footprint: VALID_FOOTPRINT,
      }]),
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    ["invalid digest", { ...VALID_FOOTPRINT, stencil_digest: "sha256:bad" }],
    ["negative count", { ...VALID_FOOTPRINT, workload_count: -1 }],
    ["fractional count", { ...VALID_FOOTPRINT, total_panel_count: 1.5 }],
    [
      "missing executor boundary",
      { ...VALID_FOOTPRINT, includes_privileged_executor: undefined },
    ],
    [
      "invalid Terraform flag",
      {
        ...VALID_FOOTPRINT,
        terraform_flags: {
          ...VALID_FOOTPRINT.terraform_flags,
          enable_isolated_executor: "false",
        },
      },
    ],
  ])("rejects %s in Stencil footprints", async (_label, footprint) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => stencilCatalog(VALID_PANEL, [], [{
        stencil: VALID_STENCIL,
        footprint,
      }]),
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    [
      "non-fail-closed enforcement",
      { ...VALID_FEATURE_FLAGS, enforcement_mode: "allow" },
    ],
    [
      "overlapping panel lists",
      {
        ...VALID_FEATURE_FLAGS,
        disabled_panel_ids: ["detection-readiness"],
        panel_flags: { "detection-readiness": true },
      },
    ],
    [
      "contradictory panel flag",
      {
        ...VALID_FEATURE_FLAGS,
        panel_flags: { "detection-readiness": false, labs: false },
      },
    ],
    [
      "unscoped runtime env",
      { ...VALID_FEATURE_FLAGS, runtime_env: { AZURE_CLIENT_SECRET: "not-allowed" } },
    ],
  ])("rejects %s in Stencil feature flags", async (_label, featureFlags) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => stencilCatalog(VALID_PANEL, [], [{
        stencil: VALID_STENCIL,
        footprint: { ...VALID_FOOTPRINT, feature_flags: featureFlags },
      }]),
    }));
    await expect(requestStencilCatalog()).rejects.toThrow("Invalid Stencil catalog payload");
  });
  it.each([
    [
      "Stencil identity mismatch",
      VALID_STENCIL,
      { ...VALID_FOOTPRINT, stencil_id: "other-stencil" },
    ],
    [
      "enabled panel count mismatch",
      VALID_STENCIL,
      { ...VALID_FOOTPRINT, enabled_panel_count: 0 },
    ],
    [
      "feature flag panel mismatch",
      VALID_STENCIL,
      {
        ...VALID_FOOTPRINT,
        feature_flags: {
          ...VALID_FEATURE_FLAGS,
          enabled_panel_ids: [],
          panel_flags: { labs: false },
        },
      },
    ],
  ])("rejects %s between Stencil and footprint", async (_label, stencil, footprint) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => stencilCatalog(VALID_PANEL, [], [{ stencil, footprint }]),
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
