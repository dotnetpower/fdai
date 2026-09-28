import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { EvidenceBranch } from "./backend-types";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { workProgressPresentation } from "./conversation-trajectory-presentation";
import { parseTrajectoryDetail } from "./trajectory-detail";

// The adaptive investigation study and these contract checks read the same synthetic fixtures.
const FIXTURES = fileURLToPath(new URL("../../../mocks/ui/fixtures/adaptive/", import.meta.url));
const scenarios = readdirSync(FIXTURES)
  .filter((name) => name.endsWith(".json") && name !== "index.json")
  .map((name) => ({ name, fixture: JSON.parse(readFileSync(`${FIXTURES}${name}`, "utf8")) }));

function waveDepth(branch: EvidenceBranch, byId: ReadonlyMap<string, EvidenceBranch>): number {
  let depth = 1;
  let parent = branch.parentBranchId;
  while (parent) {
    depth += 1;
    parent = byId.get(parent)?.parentBranchId ?? null;
  }
  return depth;
}

describe("adaptive investigation fixtures", () => {
  it("covers every scenario the study offers", () => {
    const index = JSON.parse(readFileSync(`${FIXTURES}index.json`, "utf8"));
    expect(index.scenarios.map((item: { file: string }) => item.file).sort())
      .toEqual(scenarios.map((item) => item.name).sort());
    expect(scenarios.length).toBeGreaterThanOrEqual(8);
  });

  it.each(scenarios)("$name parses without losing evidence and keeps its invariants", ({ fixture }) => {
    const raw = fixture.trajectory_detail;
    const parsed = parseTrajectoryDetail(raw);
    expect(parsed).toBeDefined();
    if (!parsed) return;
    expect(parsed.activities).toHaveLength(raw.activities.length);
    expect(parsed.branches).toHaveLength(raw.branches.length);
    expect(parsed.milestones).toHaveLength(raw.milestones.length);
    expect(parsed.work_progress_shape?.density).toBe("procedural");
    expect(parsed.turn_budget).toBeDefined();
    expect(parsed.context_receipts?.length).toBeGreaterThan(0);

    const byId = new Map(parsed.branches.map((branch) => [branch.branchId, branch]));
    for (const branch of parsed.branches) {
      if (branch.parentBranchId) expect(byId.has(branch.parentBranchId)).toBe(true);
    }
    const waves = Math.max(...parsed.branches.map((branch) => waveDepth(branch, byId)));
    expect(waves).toBe(parsed.work_progress_shape?.waves);
    for (const activity of parsed.activities) {
      if (activity.branchId) expect(byId.has(activity.branchId)).toBe(true);
      // Execution authority is never granted: every activity reads, and evidence stays redacted.
      expect(activity.authority).toBe("read");
      if (activity.execution) expect(activity.execution.redacted).toBe(true);
    }
    // Milestones state workflow facts only; operational claims belong to confirmed segments.
    for (const milestone of parsed.milestones) {
      expect(milestone.text).not.toMatch(/\b(match|matches|drift|verified|healthy|mismatch)\b/i);
    }

    const trajectory = {
      question: { id: "q", role: "operator", text: fixture.question, at: "10:41:00" },
      answer: { id: "a", role: "deck", text: fixture.answer.lead, terminal: true, at: "10:41:05" },
      observedTurns: [],
      activities: parsed.activities,
      branches: parsed.branches,
      milestones: parsed.milestones,
      workProgressShape: parsed.work_progress_shape,
    } as ConversationTrajectory;
    expect(workProgressPresentation(trajectory)).toBe("timeline");
  });

  it("never turns a finding into a draft unless it is a separate request", () => {
    for (const { fixture } of scenarios) {
      const kinds = fixture.affordances.map((item: { kind: string }) => item.kind);
      expect(kinds.every((kind: string) => kind === "draft_remediation")).toBe(true);
      expect(JSON.stringify(fixture.trajectory_detail)).not.toMatch(/action_draft|"draft"/);
    }
  });
});
