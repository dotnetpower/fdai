import { describe, expect, it } from "vitest";
import {
  computeLiveApolloBlueprint,
  groupPanelsByDomain,
  isValidStencilBuilderInput,
  normalizeShortCommitSeed,
} from "./stencil-builder";
import type { StencilCatalogResponse, StencilPanelDescriptor } from "./api";

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

    const expanded = normalizeShortCommitSeed("4fbb8096cd");
    expect(expanded).toMatch(/^[0-9a-f]{40}$/);
    expect(expanded.startsWith("4fbb8096cd")).toBe(true);
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

    const docBp = computeLiveApolloBlueprint(catalog, {
      stencilId: "custom-docs",
      topologyProfile: "full-enterprise",
      selectedPanels: ["live", "documents"],
      selectedWorkloads: [],
      selectedLoops: [],
      selectedJobs: [],
      autoResolve: true,
    });
    expect(docBp.includesClamav).toBe(true);
    expect(docBp.workloadReasons["document-ingestion-api"]).toContain("menu:documents");
    expect(docBp.releaseLabels).toContain("clamav:included");
  });
});
