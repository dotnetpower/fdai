import { describe, expect, it } from "vitest";
import {
  safeParseReleaseManifest,
  schemaCompatibility,
  syncManifestReleaseVersion,
  type Catalog,
  type Release,
} from "./api";
import {
  buildConnectorGeometry,
  buildReleaseLineageGraph,
  buildReleaseStagePipeline,
  buildReleaseTopologyGraph,
  compareSemVer,
  computeLineageSummary,
  nextSuggestedSemVer,
  parseSemVerTuple,
  resolveReleaseNodeStatus,
} from "./release-lineage";

function makeRelease(
  id: string,
  options?: {
    state?: "draft" | "published" | "recalled";
    channels?: string[];
    stencilId?: string;
    commit?: string;
    capabilities?: Record<string, string>;
  },
): Release {
  const stencilId = options?.stencilId ?? "standard-sre";
  const manifest = JSON.stringify({
    product: "FDAI",
    source_commit: (options?.commit ?? "a1b2c3d4").padEnd(40, "0"),
    capability_maximums: options?.capabilities ?? {},
    stencil: {
      stencil_id: stencilId,
      stencil_digest: "f".repeat(64),
      topology_profile:
        stencilId === "lite-observe-alert"
          ? "lite-observe-alert"
          : stencilId === "full-enterprise"
            ? "full-enterprise"
            : "standard-sre",
      azure_rbac_posture:
        stencilId === "lite-observe-alert" ? "read-only-observation" : "governed-execution",
      enabled_workloads: ["core-control-plane", "operator-service"],
      enabled_panel_ids: ["audit", "dashboard", "settings-general"],
    },
  });
  return {
    id,
    label: `${stencilId} release ${id}`,
    manifest,
    digest: "a".repeat(64),
    signed_payload_sha256: "b".repeat(64),
    signature: options?.state === "draft" ? null : "sig",
    signature_status: options?.state === "draft" ? "unsigned" : "development-key-verified",
    state: options?.state ?? "published",
    channels: options?.channels ?? ["DEV"],
    published_at: options?.state === "draft" ? null : "2026-11-01T00:00:00Z",
    recalled_at: options?.state === "recalled" ? "2026-11-02T00:00:00Z" : null,
  };
}

describe("release lineage LR graph", () => {
  it("parses and compares SemVer versions deterministically", () => {
    expect(parseSemVerTuple("v1.8.2-rc.1")).toEqual([1, 8, 2, "rc.1"]);
    expect(compareSemVer("1.7.0", "1.8.0")).toBeLessThan(0);
    expect(compareSemVer("1.10.0", "1.9.0")).toBeGreaterThan(0);
    expect(compareSemVer("1.8.0-rc.1", "1.8.0")).toBeLessThan(0);
  });

  it("assigns Complete, Running, and Recalled statuses accurately", () => {
    const rProd = makeRelease("1.7.0", { channels: ["DEV", "RELEASE_CANDIDATE", "RELEASE"] });
    const rRc = makeRelease("1.8.0", { channels: ["DEV", "RELEASE_CANDIDATE"] });
    const rDraft = makeRelease("1.9.0", { state: "draft", channels: [] });
    const rRecalled = makeRelease("1.8.1", { state: "recalled", channels: ["DEV"] });
    const catalog: Catalog = {
      revision: 5,
      updated_at: "2026-11-03T00:00:00Z",
      expires_at: "2026-11-04T00:00:00Z",
      expired: false,
      key_id: "dev",
      mode: "local-development",
      releases: [rProd, rRc, rDraft, rRecalled],
      channels: {
        DEV: ["1.7.0", "1.8.0"],
        RELEASE_CANDIDATE: ["1.7.0", "1.8.0"],
        RELEASE: ["1.7.0"],
      },
      events: [],
    };

    expect(resolveReleaseNodeStatus(rProd, catalog)).toBe("complete");
    expect(resolveReleaseNodeStatus(rRc, catalog)).toBe("running");
    expect(resolveReleaseNodeStatus(rDraft, catalog)).toBe("running");
    expect(resolveReleaseNodeStatus(rRecalled, catalog)).toBe("recalled");
    expect(resolveReleaseNodeStatus(rProd, catalog, "1.7.0")).toBe("running");
  });

  it("connects all release versions left-to-right (LR) with increasing x coordinates and recall-lifting edges", () => {
    const r1 = makeRelease("1.7.0", {
      stencilId: "lite-observe-alert",
      channels: ["DEV", "RELEASE_CANDIDATE", "RELEASE"],
    });
    const r2 = makeRelease("1.8.0", {
      stencilId: "standard-sre",
      state: "recalled",
      channels: ["DEV"],
    });
    const r3 = makeRelease("1.9.0", {
      stencilId: "standard-sre",
      channels: ["DEV", "RELEASE_CANDIDATE", "RELEASE"],
    });
    const r4 = makeRelease("1.10.0", {
      stencilId: "full-enterprise",
      channels: ["DEV", "RELEASE_CANDIDATE"],
    });
    const catalog: Catalog = {
      revision: 8,
      updated_at: "2026-11-03T00:00:00Z",
      expires_at: "2026-11-04T00:00:00Z",
      expired: false,
      key_id: "dev",
      mode: "local-development",
      releases: [r4, r2, r1, r3],
      channels: {
        DEV: ["1.7.0", "1.9.0", "1.10.0"],
        RELEASE_CANDIDATE: ["1.7.0", "1.9.0", "1.10.0"],
        RELEASE: ["1.7.0", "1.9.0"],
      },
      events: [
        {
          revision: 6,
          release_id: "isolated-executor",
          action: "recall_capability",
          reason: "defect",
          channel: null,
          occurred_at: "2026-11-02T00:00:00Z",
        },
        {
          revision: 7,
          release_id: "isolated-executor",
          action: "lift_capability",
          reason: "patched in 1.9.0",
          channel: "1.9.0",
          occurred_at: "2026-11-02T02:00:00Z",
        },
      ],
    };

    const graph = buildReleaseLineageGraph(catalog, {
      buildingDraft: { id: "1.11.0", stencilId: "full-enterprise", label: "building draft" },
    });

    expect(graph.nodes.map((n) => n.id)).toEqual(["1.7.0", "1.8.0", "1.9.0", "1.10.0", "1.11.0"]);
    for (let i = 0; i < graph.nodes.length - 1; i++) {
      expect(graph.nodes[i]!.x).toBeLessThan(graph.nodes[i + 1]!.x);
    }
    for (const edge of graph.edges) {
      expect(edge.startX).toBeLessThan(edge.endX);
    }
    const draftNode = graph.nodes.find((n) => n.id === "1.11.0");
    expect(draftNode?.status).toBe("running");
  });

  it("builds a 5-stage LR pipeline for an individual release", () => {
    const rRc = makeRelease("1.10.0", { channels: ["DEV", "RELEASE_CANDIDATE"] });
    const catalog: Catalog = {
      revision: 4,
      updated_at: "2026-11-03T00:00:00Z",
      expires_at: "2026-11-04T00:00:00Z",
      expired: false,
      key_id: "dev",
      mode: "local-development",
      releases: [rRc],
      channels: { DEV: ["1.10.0"], RELEASE_CANDIDATE: ["1.10.0"], RELEASE: [] },
      events: [],
    };

    const stageGraph = buildReleaseStagePipeline(rRc, catalog);
    expect(stageGraph.nodes).toHaveLength(5);
    expect(stageGraph.edges).toHaveLength(4);
    expect(stageGraph.nodes[0]!.status).toBe("complete");
    expect(stageGraph.nodes[1]!.status).toBe("complete");
    expect(stageGraph.nodes[2]!.status).toBe("complete");
    expect(stageGraph.nodes[3]!.status).toBe("complete");
    expect(stageGraph.nodes[4]!.status).toBe("running");
    expect(stageGraph.nodes[2]!.badgeTextKo).toBe("소속 기록");
    expect(stageGraph.nodes[3]!.subtitle).toContain("RC member");
    expect(stageGraph.nodes[4]!.badgeTextKo).toBe("다음 단계 검토");
  });

  it("shows only manifest-declared workloads and never treats channel membership as runtime health", () => {
    const recorded = makeRelease("1.10.0", { channels: ["DEV", "RELEASE"] });
    const catalog: Catalog = {
      revision: 4, updated_at: "2026-11-03T00:00:00Z", expires_at: "2026-11-04T00:00:00Z",
      expired: false, key_id: "dev", mode: "local-development", releases: [recorded],
      channels: { DEV: [recorded.id], RELEASE_CANDIDATE: [], RELEASE: [recorded.id] }, events: [],
    };
    const declared = buildReleaseTopologyGraph(recorded, catalog).nodes.filter((node) => node.id.startsWith("workload-"));
    expect(declared.map((node) => node.title)).toEqual(["core-control-plane", "operator-service"]);
    expect(declared.every((node) => node.badgeTextKo === "선언됨 · RELEASE"
      && node.subtitle.includes("digest not declared"))).toBe(true);

    const withoutDeclaration = { ...recorded, manifest: "{}" };
    expect(buildReleaseTopologyGraph(withoutDeclaration, catalog).nodes).toHaveLength(5);
    expect(buildReleaseStagePipeline(withoutDeclaration, catalog).nodes[0]?.status).toBe("pending");
  });

  it("draws horizontal and smoothstep orthogonal connectors that enter arrowheads horizontally", () => {
    const straight = buildConnectorGeometry({ startX: 192, startY: 65, endX: 248, endY: 65 });
    expect(straight.pathD).toBe("M 199 65 L 245 65");
    expect(straight.arrowD).toContain("L 245.5 65");

    const branched = buildConnectorGeometry({ startX: 192, startY: 65, endX: 248, endY: 195 });
    expect(branched.pathD).toContain("Q ");
    expect(branched.pathD.endsWith("L 245 195")).toBe(true);
    expect(branched.arrowD).toContain("L 245.5 195");
  });

  it("defaults to 0.5.0 and increments only patch (0.5.1, 0.5.2) unless minor/major is explicitly requested", () => {
    expect(nextSuggestedSemVer([])).toBe("0.5.0");
    expect(nextSuggestedSemVer([{ id: "0.3.0" }, { id: "0.4.0" }])).toBe("0.5.0");
    expect(nextSuggestedSemVer([{ id: "0.4.0" }, { id: "0.5.0" }])).toBe("0.5.1");
    expect(nextSuggestedSemVer([{ id: "0.5.0" }, { id: "0.5.1" }])).toBe("0.5.2");
    expect(nextSuggestedSemVer([{ id: "0.5.0" }, { id: "0.5.2" }], "minor")).toBe("0.6.0");
    expect(nextSuggestedSemVer([{ id: "0.5.0" }, { id: "0.5.2" }], "major")).toBe("1.0.0");
    expect(nextSuggestedSemVer([{ id: "0.5.1-rc.1" }])).toBe("0.5.1");
    expect(nextSuggestedSemVer([{ id: "0.5.1" }, { id: "0.5.1-rc.1" }])).toBe("0.5.2");
  });

  it("strips build metadata and compares numeric pre-release identifiers per SemVer 2.0.0", () => {
    expect(parseSemVerTuple("v0.5.1-rc.2+20261104")).toEqual([0, 5, 1, "rc.2"]);
    expect(compareSemVer("0.5.1-rc.2", "0.5.1-rc.10")).toBeLessThan(0);
    expect(compareSemVer("0.5.1-1", "0.5.1-alpha")).toBeLessThan(0);
  });

  it("computes lineage summary, handles empty catalogs, and synchronizes manifest versions safely", () => {
    const emptyCatalog: Catalog = {
      revision: 0,
      updated_at: "2026-11-04T00:00:00Z",
      expires_at: "2026-11-05T00:00:00Z",
      expired: false,
      key_id: "dev",
      mode: "local-development",
      releases: [],
      channels: {},
      events: [],
    };
    const emptyGraph = buildReleaseLineageGraph(emptyCatalog);
    expect(emptyGraph.width).toBeGreaterThanOrEqual(220);
    expect(emptyGraph.height).toBeGreaterThanOrEqual(134);
    expect(computeLineageSummary(emptyGraph)).toEqual({
      total: 0,
      complete: 0,
      running: 0,
      recalled: 0,
      editionTracks: [],
      recallLifts: 0,
    });

    const synced = syncManifestReleaseVersion(
      JSON.stringify({
        release_version: "0.5.0",
        configuration_schema: { release_version: "0.5.0" },
      }),
      "0.5.1",
    );
    expect(JSON.parse(synced)).toEqual({
      release_version: "0.5.1",
      configuration_schema: { release_version: "0.5.1" },
    });
    expect(safeParseReleaseManifest("invalid-json")).toEqual({});
    expect(schemaCompatibility({}, "ko")).toContain("선언되지 않음");
  });
});
