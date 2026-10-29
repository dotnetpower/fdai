import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { decodeWaraGuidance, verifyWaraGuidanceDigest } from "./wara-guidance.model";

test("the complete installed public corpus passes the Console renderer boundary with exact source identities", async () => {
  const framework = JSON.parse(readFileSync(new URL("../../../rule-catalog/collected/wara-aprl/azure-wara.json", import.meta.url), "utf8")) as {
    areas: { resolved_ref: string; controls: { id: string; wara: { source_digest: string; state: string } }[] }[];
  };
  const indexUrl = new URL("../../../packages/service-contracts/src/fdai_service_contracts/data/wara-guidance.json", import.meta.url);
  const index = JSON.parse(readFileSync(indexUrl, "utf8")) as {
    shards: { path: string; count: number }[];
  };
  const entries = index.shards.flatMap((shard) => {
    expect(shard.path).toMatch(/^wara-guidance-\d{2}\.json$/);
    const data = JSON.parse(readFileSync(new URL(shard.path, indexUrl), "utf8")) as { entries: { recommendation_id: string; lifecycle: string }[] };
    expect(data.entries).toHaveLength(shard.count);
    return data.entries;
  });
  const identities = new Map(framework.areas.flatMap((area) => area.controls.map((control) => [
    control.id, { id: control.id, source_revision: area.resolved_ref, source_digest: control.wara.source_digest, lifecycle: control.wara.state.toLowerCase() },
  ] as const)));
  expect(entries).toHaveLength(456);
  expect(new Set(entries.map((entry) => entry.recommendation_id))).toEqual(new Set(identities.keys()));
  expect(entries.filter((entry) => entry.lifecycle === "active")).toHaveLength(393);
  expect(entries.filter((entry) => entry.lifecycle === "disabled")).toHaveLength(63);
  for (const entry of entries) {
    const identity = identities.get(entry.recommendation_id);
    expect(identity, entry.recommendation_id).toBeDefined();
    const guidance = decodeWaraGuidance(entry, identity!);
    await expect(verifyWaraGuidanceDigest(guidance), entry.recommendation_id).resolves.toBeUndefined();
  }
});
