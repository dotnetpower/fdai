import { describe, expect, it } from "vitest";
import type { Catalog, Release } from "./api";
import {
  buildReleaseLineageGraph,
  buildReleaseStagePipeline,
  compareSemVer,
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
  });
});
