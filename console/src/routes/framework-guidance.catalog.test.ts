import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { decodeFrameworkGuidance, verifyFrameworkGuidanceDigest, type FrameworkGuidance, type GuidanceFramework } from "./framework-guidance.model";
import { guidanceMissingKoreanFields } from "./wara-guidance.model";

test("all WAF59, MCSB86 and CAF15 packaged guides match authoritative assessment source pins and Console digest verification", async () => {
  const indexUrl = new URL("../../../packages/service-contracts/src/fdai_service_contracts/data/framework-guidance.json", import.meta.url);
  const manifest = JSON.parse(readFileSync(indexUrl, "utf8")) as {
    shards: { file: string; digest: string; entry_count: number }[];
  };
  const entries = manifest.shards.flatMap((shard) => {
    expect(shard.file).toMatch(/^framework-guidance-\d{2}\.json$/);
    const bytes = readFileSync(new URL(shard.file, indexUrl));
    expect(`sha256:${createHash("sha256").update(bytes).digest("hex")}`).toBe(shard.digest);
    const data = JSON.parse(bytes.toString("utf8")) as { entries: FrameworkGuidance[] };
    expect(data.entries).toHaveLength(shard.entry_count);
    return data.entries;
  });
  expect(entries).toHaveLength(160);
  expect(new Set(entries.map((entry) => `${entry.framework_id}:${entry.control_id}`)).size).toBe(160);
  for (const [framework, count] of Object.entries({ "azure-waf": 59, "azure-mcsb": 86, "azure-caf": 15 })) {
    const authority = JSON.parse(readFileSync(new URL(`../../../rule-catalog/framework-assessments/generated/${framework}.json`, import.meta.url), "utf8")) as {
      source_revision_digest: string;
      expected_control_count: number;
      controls: { control_id: string; specification_digest: string }[];
    };
    expect(authority.expected_control_count).toBe(count);
    const guides = entries.filter((entry) => entry.framework_id === framework);
    expect(guides).toHaveLength(count);
    expect(new Set(guides.map((entry) => entry.control_id))).toEqual(new Set(authority.controls.map((control) => control.control_id)));
    for (const guide of guides) {
      const control = authority.controls.find((item) => item.control_id === guide.control_id)!;
      const decoded = decodeFrameworkGuidance(guide, {
        framework_id: framework as GuidanceFramework, control_id: control.control_id,
        source_revision: authority.source_revision_digest, source_digest: control.specification_digest,
      });
      await expect(verifyFrameworkGuidanceDigest(decoded), `${framework}:${control.control_id}`).resolves.toBeUndefined();
      expect(guidanceMissingKoreanFields(decoded!), `${framework}:${control.control_id}`).toBe(0);
    }
  }
});
