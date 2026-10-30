import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { expect, test } from "vitest";
import { decodeWaraGuidance, guidanceMissingKoreanFields, guidanceText, verifyWaraGuidanceDigest } from "./wara-guidance.model";

function assertKoreanReaderText(value: unknown, path: string): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertKoreanReaderText(item, `${path}[${index}]`));
  } else if (typeof value === "object" && value !== null) {
    if ("en" in value) {
      expect("ko" in value && typeof value.ko === "string" && value.ko.trim().length > 0, path).toBe(true);
      if ("ko" in value && typeof value.ko === "string" && typeof value.en === "string") {
        expect(guidanceText({ en: value.en, ko: value.ko }, "ko"), path).toBe(value.ko);
      }
    } else {
      for (const [key, child] of Object.entries(value)) {
        if (key !== "sources") assertKoreanReaderText(child, `${path}.${key}`);
      }
    }
  }
}

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
    assertKoreanReaderText(guidance, entry.recommendation_id);
    expect(guidanceMissingKoreanFields(guidance!), entry.recommendation_id).toBe(0);
    if (guidance!.reference_image) {
      const image = guidance!.reference_image;
      const bytes = readFileSync(new URL(`../../public/wara-guidance-assets/${image.asset_id}.png`, import.meta.url));
      expect(bytes.byteLength).toBeLessThanOrEqual(2 * 1024 * 1024);
      expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
      expect(`sha256:${createHash("sha256").update(bytes).digest("hex")}`).toBe(image.digest);
    }
  }
});
