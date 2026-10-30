import { createHash } from "node:crypto";
import type { FrameworkGuidance, GuidanceFramework } from "./framework-guidance.model";
import { fixtureGuidance } from "./wara-guidance.fixture";

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([key, item]) => [key, sorted(item)]));
  }
  return value;
}

export function signFrameworkFixture(value: Omit<FrameworkGuidance, "content_digest">): FrameworkGuidance {
  const { content_digest: _previous, ...material } = value as FrameworkGuidance;
  const canonical = JSON.stringify(sorted(material)).replace(/[\u007f-\uffff]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return { ...material, content_digest: `sha256:${createHash("sha256").update(canonical).digest("hex")}` };
}

export function fixtureFrameworkGuidance(framework_id: GuidanceFramework = "azure-waf", control_id = "RE:01"): FrameworkGuidance {
  const { recommendation_id: _id, lifecycle: _lifecycle, reference_image: _image, content_digest: _digest, ...presentation } = fixtureGuidance();
  return signFrameworkFixture({
    ...presentation, framework_id, control_id,
    source_revision: `sha256:${"b".repeat(64)}`, source_digest: `sha256:${"c".repeat(64)}`,
    sources: [{ label: { en: "Microsoft Learn", ko: "Microsoft Learn" }, url: "https://learn.microsoft.com/azure/well-architected/", kind: "learn" }],
  });
}
