/**
 * Unit tests for the surface-neutral view-model builders.
 *
 * These are the "same content" layer: given data, assert the compiled block IR
 * has the right shape and wording, independent of any renderer.
 */

import { describe, expect, it } from "vitest";

import { buildBriefing } from "../src/view-model/build-briefing.js";
import { buildFromReadModel } from "../src/view-model/build-from-readmodel.js";
import { sampleBriefing } from "../src/data/sample-briefing.js";
import type { ReadModelSnapshot } from "../src/data/read-api.js";
import type { Block } from "../src/view-model/blocks.js";

const types = (blocks: readonly Block[]) => blocks.map((b) => b.type);

describe("buildBriefing (sample source)", () => {
  it("needs-me mode emits decision cards and a prompt", () => {
    const blocks = buildBriefing(sampleBriefing("needs-me"));
    expect(types(blocks)).toContain("decisionCard");
    expect(types(blocks)[0]).toBe("header");
    expect(types(blocks).at(-1)).toBe("prompt");
    const cards = blocks.filter((b) => b.type === "decisionCard");
    expect(cards).toHaveLength(3);
  });

  it("all-clear mode emits no decision cards but a suggestion list", () => {
    const blocks = buildBriefing(sampleBriefing("all-clear"));
    expect(types(blocks)).not.toContain("decisionCard");
    expect(types(blocks)).toContain("list");
  });

  it("always leads with a header and a bar chart", () => {
    const blocks = buildBriefing(sampleBriefing("needs-me"));
    expect(types(blocks)).toContain("barChart");
    expect(blocks[0].type).toBe("header");
  });
});

const SNAPSHOT: ReadModelSnapshot = {
  kpi: {
    event_count: 9,
    shadow_share: 1,
    enforce_share: 0,
    hil_pending: 1,
    by_action_kind: { "control_loop.abstain": 2 },
    by_outcome: { abstained_t0: 2, shadow_pr_opened: 5 },
    by_tier: { t0: 6, t1: 2, t2: 1 },
    last_recorded_at: "2026-07-06T10:55:00+00:00",
  },
  hil: [
    {
      idempotency_key: "hil-dev-0001",
      event_id: "00000000-0000-0000-0000-000000000010",
      action_kind: "restrict-network-access",
      reason: "blast-radius exceeds executor cap",
      requested_at: "2026-07-06T10:10:00+00:00",
      correlation_id: "corr-dev-0001",
    },
  ],
  audit: [
    {
      seq: 9,
      event_id: "00000000-0000-0000-0000-000000000009",
      actor: "fdai.core.control_loop",
      action_kind: "root-cause-reasoning",
      mode: "shadow",
      recorded_at: "2026-07-06T10:55:00+00:00",
    },
  ],
};

describe("buildFromReadModel (live source)", () => {
  it("renders trust tiers from by_tier, ordered T0/T1/T2", () => {
    const blocks = buildFromReadModel(SNAPSHOT, "live");
    const bars = blocks.find(
      (b) => b.type === "statBars" && b.title === "Trust tiers:",
    );
    expect(bars).toBeDefined();
    if (bars && bars.type === "statBars") {
      expect(bars.rows.map((r) => r.tone)).toEqual(["t0", "t1", "t2"]);
      expect(bars.rows[0].pct).toBe(67); // 6/9
    }
  });

  it("maps a HIL item into a decision card with inferred risk", () => {
    const blocks = buildFromReadModel(SNAPSHOT, "live");
    const card = blocks.find((b) => b.type === "decisionCard");
    expect(card).toBeDefined();
    if (card && card.type === "decisionCard") {
      expect(card.actionType).toBe("restrict-network-access");
      expect(card.risk).toBe("HIGH"); // "network" -> HIGH heuristic
      expect(card.reference).toBe("hil-dev-0001");
    }
  });

  it("shows all-clear text when the HIL queue is empty", () => {
    const empty: ReadModelSnapshot = { ...SNAPSHOT, hil: [] };
    const blocks = buildFromReadModel(empty, "live");
    expect(blocks.some((b) => b.type === "decisionCard")).toBe(false);
    const narr = blocks.filter((b) => b.type === "narration");
    expect(narr.some((b) => b.type === "narration" && /Nothing/.test(b.text))).toBe(
      true,
    );
  });
});
