import { describe, expect, it } from "vitest";
import type { Release } from "./api";
import { editionOverviewPath, editionReleasePath, editionStage, filterEditionReleases } from "./operational-edition";

function release(id: string, state: Release["state"], channels: string[], label = ""): Release {
  return {
    id, state, channels, label, manifest: "{}",
    digest: "a".repeat(64), signed_payload_sha256: "b".repeat(64),
    signature: null, signature_status: "unsigned", published_at: null, recalled_at: null,
  };
}

describe("operational Edition catalog projection", () => {
  const releases = [
    release("0.5.1", "published", ["DEV", "RELEASE"], "Lite Observe"),
    release("0.5.3", "published", ["DEV", "RELEASE_CANDIDATE"], "Standard SRE"),
    release("0.5.2", "draft", [], "Standard SRE"),
    release("0.5.4", "recalled", [], "Full Enterprise"),
  ];
  it("uses only supplied live catalog releases and sorts by semantic version", () => {
    expect(filterEditionReleases(releases, "", "all").map((item) => item.id)).toEqual([
      "0.5.4", "0.5.3", "0.5.2", "0.5.1",
    ]);
    expect(filterEditionReleases(releases, "", "RELEASE").map((item) => item.id)).toEqual(["0.5.1"]);
    expect(filterEditionReleases(releases, "", "draft").map((item) => item.id)).toEqual(["0.5.2"]);
    expect(filterEditionReleases(releases, "  full  ", "all").map((item) => item.id)).toEqual(["0.5.4"]);
    expect(filterEditionReleases(releases, "missing", "all")).toEqual([]);
    expect(releases.map((item) => item.id)).toEqual(["0.5.1", "0.5.3", "0.5.2", "0.5.4"]);
  });

  it("labels channel eligibility, not deployment success, and distinguishes blocked releases", () => {
    expect(releases.map((item) => editionStage(item))).toEqual(["RELEASE", "RC", "DRAFT", "RECALLED"]);
    expect(editionStage(releases[0]!, true)).toBe("BLOCKED");
    expect(editionStage(release("0.5.5", "published", ["custom-pilot"]))).toBe("custom-pilot");
    expect(editionStage(release("0.5.6", "published", []))).toBe("UNASSIGNED");
  });

  it("links straight to full topology and preserves the version on return", () => {
    expect(editionReleasePath("0.5.1")).toBe("#/edition/releases/0.5.1");
    expect(editionOverviewPath("0.5.1")).toBe("#/edition/selected/0.5.1");
  });
});
