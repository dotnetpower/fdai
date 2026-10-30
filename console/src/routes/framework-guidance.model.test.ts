import { describe, expect, test } from "vitest";
import { decodeFrameworkGuidance, verifyFrameworkGuidanceDigest } from "./framework-guidance.model";
import { fixtureFrameworkGuidance, signFrameworkFixture } from "./framework-guidance.fixture";

describe("shared framework guidance boundary", () => {
  test.each(["azure-waf", "azure-mcsb", "azure-caf"] as const)("validates exact %s source identity and ASCII canonical bilingual digest", async (framework) => {
    const guide = fixtureFrameworkGuidance(framework);
    const decoded = decodeFrameworkGuidance(guide, guide);
    expect(decoded).toEqual(guide);
    await expect(verifyFrameworkGuidanceDigest(decoded)).resolves.toBeUndefined();
  });

  test("distinguishes an absent guide from invalid or unrelated content", () => {
    const guide = fixtureFrameworkGuidance();
    expect(decodeFrameworkGuidance(undefined, guide)).toBeNull();
    expect(decodeFrameworkGuidance(null, guide)).toBeNull();
    for (const change of [
      { schema_version: "2.0.0" }, { framework_id: "azure-caf" }, { control_id: "RE:02" },
      { source_revision: "another-revision" }, { source_digest: `sha256:${"d".repeat(64)}` },
      { recommendation_id: "not-a-framework-id" }, { lifecycle: "active" }, { reference_image: null },
    ]) expect(() => decodeFrameworkGuidance({ ...guide, ...change }, guide)).toThrow(/framework guidance/);
    expect(() => decodeFrameworkGuidance(guide, { ...guide, source_digest: undefined })).toThrow(/does not match/);
  });

  test.each(["javascript:alert(1)", "https://example.com/guide", "https://learn.microsoft.com@evil.example/guide", "https://learn.microsoft.com/guide?token=example"])(
    "rejects an unapproved source URL %s", (url) => {
      const guide = fixtureFrameworkGuidance();
      expect(() => decodeFrameworkGuidance({ ...guide, sources: [{ ...guide.sources[0], url }] }, guide)).toThrow(/approved source/);
    },
  );

  test("requires bounded technical sections and a valid connected diagram", () => {
    const guide = fixtureFrameworkGuidance();
    for (const change of [
      { implementation_steps: [] }, { configuration: { before: [], after: [] } }, { cautions: [] },
      { diagram: { ...guide.diagram, edges: [{ from: "unknown", to: "other", label: { en: "link" }, style: "solid" }] } },
      { sources: [{ ...guide.sources[0], kind: "aprl" }] },
    ]) expect(() => decodeFrameworkGuidance({ ...guide, ...change }, guide)).toThrow(/framework guidance/);
  });

  test("withholds tampered display content even when its source identity matches", async () => {
    const guide = fixtureFrameworkGuidance();
    const changed = decodeFrameworkGuidance({ ...guide, summary: { en: "Changed", ko: "변경됨" } }, guide);
    await expect(verifyFrameworkGuidanceDigest(changed)).rejects.toThrow(/content_digest/);
    await expect(verifyFrameworkGuidanceDigest(signFrameworkFixture({ ...guide, summary: { en: "Changed", ko: "변경됨" } }))).resolves.toBeUndefined();
  });
});
