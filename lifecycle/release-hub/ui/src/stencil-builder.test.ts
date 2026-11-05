import { describe, expect, it, vi } from "vitest";
import {
  canQuickCreatePresetVersion,
  computeLiveApolloBlueprint,
  dispatchBuilderRelease,
  groupPanelsByDomain,
  isAddonSelectionLocked,
  isValidStencilBuilderInput,
  resolvedDerivedSourceCommit,
  restoreRegisteredStencil,
  toggleRequestedItem,
} from "./stencil-builder";
import {
  artifacts,
  computeApolloReleaseDiff,
  evaluateApolloPromotionReadiness,
  extractReleaseStencil,
  type Release,
  type StencilCatalogResponse,
  type StencilPanelDescriptor,
} from "./api";

const samplePanels: StencilPanelDescriptor[] = [
  {
    id: "dashboard",
    group: "overview",
    label: "Overview dashboard",
    label_ko: "종합 대시보드",
    locked: true,
    required_workloads: [],
    required_loops: [],
    required_addons: [],
    feature_ids: ["F01.1"],
  },
  {
    id: "live",
    group: "operations",
    label: "Live operations",
    label_ko: "실시간 리소스",
    locked: false,
    required_workloads: [],
    required_loops: ["inventory-reconciliation"],
    required_addons: [],
    feature_ids: ["F02.1"],
  },
];

describe("stencil-builder helpers", () => {
  it("groups Console panels by stable domain order", () => {
    const grouped = groupPanelsByDomain(samplePanels);
    expect([...grouped.keys()]).toEqual([
      "overview",
      "operations",
      "agents",
      "governance",
      "knowledge",
      "evidence",
      "labs",
      "settings",
    ]);
    expect(grouped.get("overview")?.map((p) => p.id)).toEqual(["dashboard"]);
    expect(grouped.get("operations")?.map((p) => p.id)).toEqual(["live"]);
  });

  it("validates Stencil ID, SemVer release version, and auto/derived/40-char hex source commit (C10)", () => {
    const valid = {
      stencilId: "lite-observe-alert",
      releaseVersion: "1.7.0",
      sourceCommit: "a".repeat(40),
    };
    expect(isValidStencilBuilderInput(valid)).toBe(true);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: "auto" })).toBe(true);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: "derived" })).toBe(true);
    expect(isValidStencilBuilderInput({ ...valid, stencilId: "Bad_ID" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, releaseVersion: "v1.7" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: "abc" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: "4fbb8096cd" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: "release-tag" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: " " + "A".repeat(40) + " " })).toBe(true);
  });

  it("blocks both prepared registration and one-click dispatch when mutations are disabled", async () => {
    const draft = { id: "1.7.0", label: "test", manifest: "{}" };
    const prepare = vi.fn();
    const quickCreate = vi.fn().mockResolvedValue(undefined);
    let disabled = true;
    const currentGuard = () => disabled;

    expect(await dispatchBuilderRelease(draft, currentGuard, prepare)).toBe(false);
    expect(await dispatchBuilderRelease(draft, currentGuard, prepare, quickCreate)).toBe(false);
    expect(prepare).not.toHaveBeenCalled();
    expect(quickCreate).not.toHaveBeenCalled();

    // Re-check at dispatch time: a read-only preview may finish after the parent disables writes.
    disabled = false;
    const preview = { ...draft };
    disabled = true;
    expect(await dispatchBuilderRelease(preview, currentGuard, prepare, quickCreate)).toBe(false);
    expect(quickCreate).not.toHaveBeenCalled();

    disabled = false;
    expect(await dispatchBuilderRelease(draft, currentGuard, prepare)).toBe(true);
    expect(await dispatchBuilderRelease(draft, currentGuard, prepare, quickCreate)).toBe(true);
    expect(prepare).toHaveBeenCalledExactlyOnceWith(draft);
    expect(quickCreate).toHaveBeenCalledExactlyOnceWith(draft);
  });

  it("shows only the compose response's actual derived commit, never a locally padded preview", () => {
    expect(resolvedDerivedSourceCommit(null)).toBeNull();
    const result = { release_manifest: { source_commit: "f".repeat(40) } };
    expect(resolvedDerivedSourceCommit(result)).toBe("f".repeat(40));
    expect(resolvedDerivedSourceCommit({
      release_manifest: { source_commit: "short-sha" },
    })).toBeNull();
  });

  it("offers optional add-ons while locking core and showing dependency closure reasons", () => {
    const catalog: StencilCatalogResponse = {
      presets: [],
      panels: [
        samplePanels[0]!,
        {
          id: "policy", group: "governance", label: "Policy", label_ko: "정책",
          locked: false, required_workloads: [], required_loops: [],
          required_addons: ["policy-administration"], feature_ids: [],
        },
      ],
      workloads: ["core-control-plane"], locked_workloads: ["core-control-plane"],
      scheduled_jobs: [], locked_scheduled_jobs: [], loops: [], locked_loops: [],
      addons: ["notifications", "policy-administration", "enterprise-identity-governance"],
      locked_addons: ["notifications"], locked_panels: ["dashboard"],
    };
    const options = {
      stencilId: "policy", topologyProfile: "standard-sre",
      selectedPanels: ["policy"], selectedWorkloads: [], selectedLoops: [],
      selectedJobs: [], selectedAddons: [], autoResolve: true,
    };
    const required = computeLiveApolloBlueprint(catalog, options);
    expect(required.effectiveAddons).toEqual([
      "enterprise-identity-governance", "notifications", "policy-administration",
    ]);
    expect(required.addonReasons["policy-administration"]).toContain("menu:policy");
    expect(required.addonReasons["enterprise-identity-governance"]).toContain("addon:policy-administration");
    expect(isAddonSelectionLocked("notifications", catalog, required, true)).toBe(true);
    expect(isAddonSelectionLocked("policy-administration", catalog, required, true)).toBe(true);
    expect(isAddonSelectionLocked("enterprise-identity-governance", catalog, required, true)).toBe(true);

    const withoutMenu = computeLiveApolloBlueprint(catalog, { ...options, selectedPanels: [] });
    expect(withoutMenu.effectiveAddons).toEqual(["notifications"]);
    expect(isAddonSelectionLocked("policy-administration", catalog, withoutMenu, true)).toBe(false);
    const selectedAddons = toggleRequestedItem([], "policy-administration", catalog.locked_addons);
    const manuallySelected = computeLiveApolloBlueprint(catalog, {
      ...options, selectedPanels: [], selectedAddons,
    });
    expect(manuallySelected.effectiveAddons).toContain("policy-administration");
    expect(isAddonSelectionLocked("policy-administration", catalog, manuallySelected, true)).toBe(false);
    expect(isAddonSelectionLocked("enterprise-identity-governance", catalog, manuallySelected, true)).toBe(true);
    expect(toggleRequestedItem(selectedAddons, "policy-administration", catalog.locked_addons)).toEqual([]);
    expect(toggleRequestedItem([], "notifications", catalog.locked_addons)).toEqual([]);

    const manualDependencies = computeLiveApolloBlueprint(catalog, { ...options, autoResolve: false });
    expect(manualDependencies.addonReasons["policy-administration"]).toContain("menu:policy");
    expect(isAddonSelectionLocked("policy-administration", catalog, manualDependencies, false)).toBe(false);
  });

  it("keeps explicit selections separate from dependency-closed preview after deselection", () => {
    const catalog: StencilCatalogResponse = {
      presets: [],
      panels: [
        samplePanels[0]!,
        {
          id: "documents", group: "knowledge", label: "Documents", label_ko: "문서",
          locked: false, required_workloads: ["document-ingestion-api", "document-processing-worker"],
          required_loops: ["document-ingestion"], required_addons: [], feature_ids: [],
        },
      ],
      workloads: ["core-control-plane", "document-ingestion-api", "document-processing-worker"],
      locked_workloads: ["core-control-plane"],
      scheduled_jobs: [], locked_scheduled_jobs: [],
      loops: ["document-ingestion"], locked_loops: [],
      addons: [], locked_addons: [], locked_panels: ["dashboard"],
    };
    const requestedPanels = toggleRequestedItem([], "documents", catalog.locked_panels);
    const preview = computeLiveApolloBlueprint(catalog, {
      stencilId: "custom-docs", topologyProfile: "lite-observe-alert",
      selectedPanels: requestedPanels, selectedWorkloads: [], selectedLoops: [],
      selectedJobs: [], autoResolve: true,
    });

    expect(preview.effectiveWorkloads).toContain("document-ingestion-api");
    expect(preview.effectiveLoops).toContain("document-ingestion");
    // Composition must not replace the explicit selections with preview.effective*.
    const afterRemoval = computeLiveApolloBlueprint(catalog, {
      stencilId: "custom-docs", topologyProfile: "lite-observe-alert",
      selectedPanels: toggleRequestedItem(requestedPanels, "documents", catalog.locked_panels),
      selectedWorkloads: [], selectedLoops: [], selectedJobs: [], autoResolve: true,
    });
    expect(afterRemoval.effectivePanels).toEqual(["dashboard"]);
    expect(afterRemoval.effectiveWorkloads).toEqual(["core-control-plane"]);
    expect(afterRemoval.effectiveLoops).toEqual([]);
  });

  it("only previews the privileged executor role when its governed-execution add-on is present", () => {
    const catalog: StencilCatalogResponse = {
      presets: [], panels: [], workloads: ["core-control-plane", "isolated-executor"],
      locked_workloads: ["core-control-plane"], scheduled_jobs: [], locked_scheduled_jobs: [],
      loops: ["remediation-execution"], locked_loops: [],
      addons: ["governed-execution"], locked_addons: [], locked_panels: [],
    };
    const options = {
      stencilId: "custom-executor", topologyProfile: "standard-sre" as const,
      selectedPanels: [], selectedWorkloads: ["isolated-executor"],
      selectedLoops: ["remediation-execution"], selectedJobs: [], autoResolve: false,
    };
    const withoutAddon = computeLiveApolloBlueprint(catalog, {
      ...options, selectedAddons: [],
    });
    expect(withoutAddon.rbacPosture).toBe("governed-execution");
    expect(withoutAddon.requiredAzureRoles).not.toContain("Scoped Executor Action Role (privileged mutation)");
    const withAddon = computeLiveApolloBlueprint(catalog, {
      ...options, selectedAddons: ["governed-execution"],
    });
    expect(withAddon.requiredAzureRoles).toContain("Scoped Executor Action Role (privileged mutation)");
  });

  it("restores registered add-ons and source rather than retaining the preceding preset", () => {
    const catalog: StencilCatalogResponse = {
      presets: [], panels: [], workloads: [], locked_workloads: [],
      scheduled_jobs: ["analyzer"], locked_scheduled_jobs: ["analyzer"],
      loops: ["inventory"], locked_loops: ["inventory"],
      addons: ["notifications", "policy-administration"], locked_addons: ["notifications"],
      locked_panels: [], detected_source_commit: "b".repeat(40),
    };
    const release = {
      id: "1.2.0",
      manifest: JSON.stringify({
        source_commit: "A".repeat(40),
        stencil: {
          stencil_id: "enterprise", stencil_digest: "sha256:" + "1".repeat(64),
          topology_profile: "full-enterprise", enabled_workloads: ["core-control-plane"],
          enabled_panel_ids: ["dashboard"], enabled_loops: ["inventory"],
          enabled_scheduled_jobs: ["analyzer"],
          feature_flags: { enabled_addons: ["notifications", "policy-administration"] },
        },
      }),
    } as Release;
    expect(restoreRegisteredStencil(release, catalog)).toMatchObject({
      addons: ["notifications", "policy-administration"],
      sourceMode: "release:1.2.0",
      sourceCommit: "a".repeat(40),
      customCommitInput: "a".repeat(40),
    });
    const legacy = { ...release, manifest: JSON.stringify({
      stencil: {
        stencil_id: "legacy", stencil_digest: "sha256:" + "2".repeat(64),
        topology_profile: "lite-observe-alert", enabled_workloads: [], enabled_panel_ids: [],
      },
    }) };
    expect(restoreRegisteredStencil(legacy, catalog)).toMatchObject({
      addons: ["notifications"], loops: ["inventory"], jobs: ["analyzer"],
      sourceMode: "auto", sourceCommit: "auto",
    });
  });

  it("does not silently replace invalid or already registered preset one-click versions", () => {
    const existing = [{ id: "0.5.0" }, { id: "0.5.1" }];
    expect(canQuickCreatePresetVersion("not-a-version", existing)).toBe(false);
    expect(canQuickCreatePresetVersion("0.5.1", existing)).toBe(false);
    expect(canQuickCreatePresetVersion("0.5.2", existing)).toBe(true);
    expect(canQuickCreatePresetVersion(" 0.5.2 ", existing)).toBe(true);
    expect(canQuickCreatePresetVersion("1.0.0" + "x".repeat(65), existing)).toBe(false);
  });

  it("computes live Apollo blueprint, dependency reasons, and release labels in 0ms", () => {
    const catalog: StencilCatalogResponse = {
      presets: [],
      panels: [
        ...samplePanels,
        {
          id: "documents",
          group: "knowledge",
          label: "Documents",
          label_ko: "문서 수집",
          locked: false,
          required_workloads: ["document-ingestion-api", "document-processing-worker"],
          required_loops: ["document-ingestion"],
          required_addons: [],
          feature_ids: ["F11.1"],
        },
      ],
      workloads: [
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
      ],
      locked_workloads: ["core-control-plane", "operator-service"],
      scheduled_jobs: ["analyzer", "inventory", "canary"],
      locked_scheduled_jobs: ["analyzer", "inventory"],
      loops: [
        "anomaly-analyzer",
        "document-ingestion",
        "inventory-reconciliation",
        "notification-dispatch",
        "saga-audit",
      ],
      locked_loops: [
        "anomaly-analyzer",
        "inventory-reconciliation",
        "notification-dispatch",
        "saga-audit",
      ],
      addons: ["notifications", "read-only-console"],
      locked_addons: ["notifications", "read-only-console"],
      locked_panels: ["dashboard"],
    };

    const liteBp = computeLiveApolloBlueprint(catalog, {
      stencilId: "lite-observe-alert",
      topologyProfile: "lite-observe-alert",
      selectedPanels: ["live"],
      selectedWorkloads: [],
      selectedLoops: [],
      selectedJobs: [],
      autoResolve: true,
    });
    expect(liteBp.effectiveWorkloads).toEqual(["core-control-plane", "operator-service"]);
    expect(liteBp.includesClamav).toBe(false);
    expect(liteBp.releaseLabels).toContain("clamav:omitted");
    expect(liteBp.releaseLabels).toContain("rbac:read-only-observation");
    expect(liteBp.disabledPanels).toEqual(["documents"]);
    expect(liteBp.panelFeatureFlags).toEqual({
      dashboard: true,
      documents: false,
      live: true,
    });
    expect(liteBp.loopFeatureFlags["document-ingestion"]).toBe(false);
    expect(liteBp.runtimeEnvFlags.FDAI_STENCIL_ENFORCE_INACTIVE_MENUS).toBe("1");
    expect(liteBp.runtimeEnvFlags.FDAI_STENCIL_DISABLED_PANELS).toBe("documents");
    expect(liteBp.runtimeEnvFlags.FDAI_STENCIL_ENABLED_WORKLOADS).toBe(
      "core-control-plane,operator-service",
    );
    expect(liteBp.runtimeEnvFlags.FDAI_STENCIL_DISABLED_WORKLOADS).toBe(
      "document-ingestion-api,document-processing-worker,isolated-executor",
    );
    expect(liteBp.workloadFeatureFlags["document-ingestion-api"]).toBe(false);
    expect(liteBp.jobFeatureFlags.canary).toBe(false);
    expect(liteBp.addonFeatureFlags.notifications).toBe(true);

    const docBp = computeLiveApolloBlueprint(catalog, {
      stencilId: "custom-docs",
      topologyProfile: "lite-observe-alert",
      selectedPanels: ["live", "documents"],
      selectedWorkloads: [],
      selectedLoops: [],
      selectedJobs: [],
      autoResolve: true,
    });
    expect(docBp.includesClamav).toBe(true);
    expect(docBp.effectiveTopologyProfile).toBe("full-enterprise");
    expect(docBp.workloadReasons["document-ingestion-api"]).toContain("menu:documents");
    expect(docBp.releaseLabels).toContain("clamav:included");
    expect(docBp.releaseLabels).toContain("profile:full-enterprise");
  });

  it("extracts Stencil metadata and component artifacts from application-release.v2 manifests", () => {
    const manifestObj = {
      schema_version: "fdai.application-release.v2",
      product: "fdai",
      release_version: "1.7.0",
      source_commit: "a".repeat(40),
      platform_tag: "linux-x86_64",
      components: {
        "core-control-plane": { image_digest: "sha256:" + "1".repeat(64) },
        "operator-service": { image_digest: "sha256:" + "2".repeat(64) },
        pgvector: { image_digest: "sha256:" + "3".repeat(64) },
      },
      stencil: {
        stencil_id: "lite-observe-alert",
        stencil_digest: "sha256:" + "9".repeat(64),
        topology_profile: "lite-observe-alert" as const,
        azure_rbac_posture: "read-only-observation",
        enabled_workloads: ["core-control-plane", "operator-service"],
        enabled_panel_ids: ["audit", "dashboard", "live", "settings-general"],
        release_labels: ["stencil:lite-observe-alert", "rbac:read-only-observation"],
      },
    };
    const extracted = extractReleaseStencil(manifestObj);
    expect(extracted?.stencil_id).toBe("lite-observe-alert");
    expect(extracted?.enabled_workloads).toEqual(["core-control-plane", "operator-service"]);

    const artList = artifacts(manifestObj);
    expect(artList.map((a) => a.component)).toEqual([
      "core-control-plane",
      "operator-service",
      "pgvector",
    ]);

    const liteRel: Release = {
      id: "1.7.0",
      label: "lite",
      manifest: JSON.stringify(manifestObj),
      digest: "sha256:" + "a".repeat(64),
      signed_payload_sha256: "b".repeat(64),
      signature: "sig",
      signature_status: "verified",
      state: "published",
      channels: ["DEV"],
      published_at: "2026-11-02T00:00:00Z",
      recalled_at: null,
    };
    const readiness = evaluateApolloPromotionReadiness({
      release: liteRel,
      manifest: manifestObj,
      events: [
        {
          revision: 1,
          release_id: "isolated-executor",
          action: "recall_capability",
          reason: "test",
          channel: null,
          occurred_at: "2026-11-02T00:00:00Z",
        },
      ],
      sourceChannel: "DEV",
      targetChannel: "RELEASE_CANDIDATE",
    });
    expect(readiness.allowed).toBe(true);

    const stdManifest = {
      ...manifestObj,
      release_version: "1.8.0",
      stencil: {
        ...manifestObj.stencil,
        stencil_id: "standard-sre",
        azure_rbac_posture: "governed-execution",
        enabled_workloads: ["core-control-plane", "operator-service", "isolated-executor"],
        enabled_panel_ids: ["audit", "dashboard", "live", "remediation", "settings-general"],
      },
    };
    const stdRel: Release = {
      ...liteRel,
      id: "1.8.0",
      manifest: JSON.stringify(stdManifest),
    };
    const diff = computeApolloReleaseDiff(liteRel, stdRel);
    expect(diff.addedWorkloads).toEqual(["isolated-executor"]);
    expect(diff.addedPanels).toEqual(["remediation"]);
    expect(diff.addedPanelCount).toBe(1);
    expect(diff.rbacChanged).toBe(true);
    expect(diff.featureFlagEnforcementChanged).toBe(false);

    const recalledPanelReadiness = evaluateApolloPromotionReadiness({
      release: liteRel,
      manifest: manifestObj,
      events: [
        {
          revision: 2,
          release_id: "panel:live",
          action: "recall_capability",
          reason: "recall live menu",
          channel: null,
          occurred_at: "2026-11-02T00:00:00Z",
        },
      ],
      sourceChannel: "DEV",
      targetChannel: "RELEASE_CANDIDATE",
    });
    expect(recalledPanelReadiness.allowed).toBe(false);
    expect(recalledPanelReadiness.gates.some((g) => g.id === "stencil-feature-flags" && g.passed)).toBe(
      true,
    );
  });
});
