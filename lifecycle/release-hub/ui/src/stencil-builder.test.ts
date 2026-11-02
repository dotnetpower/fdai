import { describe, expect, it } from "vitest";
import { groupPanelsByDomain, isValidStencilBuilderInput } from "./stencil-builder";
import type { StencilPanelDescriptor } from "./api";

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

  it("validates Stencil ID, SemVer release version, and 40-char hex source commit (C10)", () => {
    const valid = {
      stencilId: "lite-observe-alert",
      releaseVersion: "1.7.0",
      sourceCommit: "a".repeat(40),
    };
    expect(isValidStencilBuilderInput(valid)).toBe(true);
    expect(isValidStencilBuilderInput({ ...valid, stencilId: "Bad_ID" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, releaseVersion: "v1.7" })).toBe(false);
    expect(isValidStencilBuilderInput({ ...valid, sourceCommit: "abc" })).toBe(false);
  });
});
