import { describe, expect, it } from "vitest";
import type { AnswerVerification } from "./backend-types";
import { parsePresentationArtifact } from "./presentation-artifact";

const ref = "subscription-health:test@2026-08-05T00:00:00Z";
const verification: AnswerVerification = {
  status: "verified",
  authority: "server_subscription_health",
  checks_completed: 1,
  checks_total: 1,
  evidence_refs: [ref],
  reason_code: "subscription_health_grounded",
};

function artifact(): Record<string, unknown> {
  return {
    schema_version: 1,
    layout: "stack",
    evidence_refs: [ref],
    blocks: [
      {
        slot_id: "overview",
        kind: "summary",
        title: "Azure scope health",
        emphasis: "primary",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          items: [{ label: "Resources checked", value: "454", tone: "neutral" }],
        },
      },
      {
        slot_id: "coverage",
        kind: "coverage",
        title: "Metric observation coverage",
        emphasis: "secondary",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          items: [
            { label: "Checked", value: 11, tone: "positive" },
            { label: "Unavailable", value: 5, tone: "warning" },
            { label: "Unsupported", value: 413, tone: "neutral" },
          ],
        },
      },
    ],
  };
}

describe("presentation artifact boundary", () => {
  it("accepts bounded blocks whose refs are verified", () => {
    const parsed = parsePresentationArtifact(artifact(), verification);

    expect(parsed?.blocks.map((block) => block.slotId)).toEqual(["overview", "coverage"]);
    expect(parsed?.blocks[1]?.kind).toBe("coverage");
  });

  it("rejects refs outside terminal verification", () => {
    const raw = artifact();
    raw.evidence_refs = ["subscription-health:other@2026-08-05T00:00:00Z"];

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });

  it("rejects duplicate slots and unknown blocks", () => {
    const duplicate = artifact();
    const blocks = duplicate.blocks as Record<string, unknown>[];
    blocks[1] = { ...blocks[1], slot_id: "overview" };
    expect(parsePresentationArtifact(duplicate, verification)).toBeUndefined();

    const unknown = artifact();
    (unknown.blocks as Record<string, unknown>[])[0]!.kind = "html";
    expect(parsePresentationArtifact(unknown, verification)).toBeUndefined();
  });

  it("rejects oversized rows and unsafe text", () => {
    const raw = artifact();
    const blocks = raw.blocks as Record<string, unknown>[];
    blocks[0]!.title = "x".repeat(513);
    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();

    const control = artifact();
    (control.blocks as Record<string, unknown>[])[0]!.title = "bad\u0000title";
    expect(parsePresentationArtifact(control, verification)).toBeUndefined();
  });

  it("keeps partial verified facts renderable under unverified status", () => {
    const parsed = parsePresentationArtifact(artifact(), {
      ...verification,
      status: "unverified",
      checks_completed: 0,
      reason_code: "subscription_health_partial",
    });

    expect(parsed).toBeDefined();
  });

  it("rejects duplicate item labels used as renderer keys", () => {
    const raw = artifact();
    const blocks = raw.blocks as Record<string, unknown>[];
    const data = blocks[1]!.data as { items: Record<string, unknown>[] };
    data.items[1]!.label = "Checked";

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });
});
