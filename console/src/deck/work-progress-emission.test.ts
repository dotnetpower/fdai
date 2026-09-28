import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { ConversationTrajectory } from "./conversation-trajectory";
import { workProgressPresentation } from "./conversation-trajectory-presentation";
import { parseTrajectoryDetail } from "./trajectory-detail";

// The Operator projection test pins this golden to its real output, so a server change that the
// Console can't parse losslessly fails here.
const GOLDEN = fileURLToPath(new URL(
  "../../../services/operator-service/tests/fixtures/semantic_work_progress_trajectory.json",
  import.meta.url,
));
const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));
const raw = golden.trajectory_detail;

describe("server-emitted work progress", () => {
  it("keeps the pin, turn budget, and context receipts unchanged", () => {
    const parsed = parseTrajectoryDetail(raw);

    expect(parsed).toBeDefined();
    expect(parsed?.work_progress_shape).toEqual(raw.work_progress_shape);
    expect(parsed?.turn_budget).toEqual(raw.turn_budget);
    expect(parsed?.context_receipts).toEqual(raw.context_receipts);
    expect(parsed?.activities).toHaveLength(raw.activities.length);
    expect(parsed?.omitted).toEqual(raw.omitted);
    expect(parsed?.truncated_outputs).toBe(raw.truncated_outputs);
  });

  it("drops only a malformed server field and keeps the evidence", () => {
    const parsed = parseTrajectoryDetail({
      ...raw,
      turn_budget: { ...raw.turn_budget, complete: "yes" },
    });

    expect(parsed?.turn_budget).toBeUndefined();
    expect(parsed?.work_progress_shape).toEqual(raw.work_progress_shape);
    expect(parsed?.context_receipts).toEqual(raw.context_receipts);
    expect(parsed?.activities).toHaveLength(raw.activities.length);
  });

  it("presents a procedural pin as a timeline", () => {
    const parsed = parseTrajectoryDetail(raw);
    if (!parsed) throw new Error("golden trajectory detail must parse");
    const trajectory = {
      question: { id: "q", role: "operator", text: "", at: "10:41:00" },
      answer: { id: "a", role: "deck", text: "", terminal: true, at: "10:41:06" },
      observedTurns: [],
      activities: parsed.activities,
      branches: parsed.branches,
      milestones: parsed.milestones,
      workProgressShape: parsed.work_progress_shape,
    } as ConversationTrajectory;

    expect(workProgressPresentation(trajectory)).toBe("timeline");
  });
});
