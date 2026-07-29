import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { InvestigationActivity } from "./backend";
import { upsertEvidenceBranch, upsertInvestigationActivity } from "./investigation-timeline";
import type { EvidenceBranch } from "./backend";

function activity(
  activityId: string,
  status: InvestigationActivity["status"],
): InvestigationActivity {
  return {
    activityId,
    kind: "health.querying",
    status,
    label: `Activity ${activityId}`,
    completed: status === "completed" ? 1 : 0,
    total: 1,
  };
}

describe("upsertInvestigationActivity", () => {
  it("appends new activities and updates an existing row in place", () => {
    const first = upsertInvestigationActivity([], activity("scope", "completed"));
    const second = upsertInvestigationActivity(first, activity("health", "running"));
    const completed = upsertInvestigationActivity(second, activity("health", "completed"));

    expect(completed.map((item) => item.activityId)).toEqual(["scope", "health"]);
    expect(completed[1]?.status).toBe("completed");
  });

  it.each([
    ["completed", "running"],
    ["failed", "pending"],
    ["unavailable", "completed"],
    ["running", "pending"],
  ] as const)("ignores status regression from %s to %s", (current, incoming) => {
    const existing = activity("health", current);
    const updated = upsertInvestigationActivity(
      [existing],
      { ...activity("health", incoming), label: "stale frame" },
    );

    expect(updated).toEqual([existing]);
  });

  it("freezes a terminal row when a duplicate terminal frame arrives", () => {
    const existing = activity("health", "completed");
    const updated = upsertInvestigationActivity(
      [existing],
      { ...activity("health", "completed"), detail: "late replacement" },
    );

    expect(updated).toEqual([existing]);
  });
});

function branch(status: EvidenceBranch["status"]): EvidenceBranch {
  return {
    branchId: "request:tool",
    kind: "tool",
    parentBranchId: null,
    status,
    summary: status,
    startedAt: "2026-07-27T01:00:00Z",
    evidenceRefs: [],
  };
}

describe("upsertEvidenceBranch", () => {
  it("advances running branches once and keeps terminal state immutable", () => {
    const running = upsertEvidenceBranch([], branch("running"));
    const completed = upsertEvidenceBranch(running, branch("completed"));
    const stale = upsertEvidenceBranch(completed, branch("running"));

    expect(completed[0]?.status).toBe("completed");
    expect(stale).toBe(completed);
  });

  it("keeps execution evidence folded and branch summaries accessible on narrow screens", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./investigation-timeline.tsx", import.meta.url)),
      "utf8",
    );
    const styles = readFileSync(
      fileURLToPath(new URL("../styles.css", import.meta.url)),
      "utf8",
    );
    const presenter = readFileSync(
      fileURLToPath(new URL("./command-deck-presenters.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).toContain(
      '<details class="deck-investigation-activity-disclosure" open={running}>',
    );
    expect(component).toContain('aria-label={t("deck.investigation.branches")}');
    expect(component).toContain('class="deck-investigation-pill"');
    expect(component).toContain('class="deck-investigation-elapsed muted"');
    expect(component).toContain("deck-branch-badge");
    expect(component).toContain('t("deck.investigation.sourceSummary"');
    expect(styles).toContain("@keyframes deck-investigation-rise");
    expect(presenter).toContain('turn.source === "investigation"');
    expect(presenter).toContain('class="deck-progress-note" role="status"');
    expect(styles).toContain(".deck-progress-note {");
    expect(styles).toMatch(
      /\.deck-investigation-list::before\s*\{[^}]*background:\s*var\(--border\)/,
    );
    expect(styles).toMatch(
      /\.deck-investigation-item\s*\{[^}]*border:\s*0;[^}]*background:\s*transparent/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.deck-investigation\.is-running/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.deck-branch-item\s*\{[^}]*opacity:\s*1/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.deck-branch-item\s*\{[^}]*grid-template-columns:\s*42px minmax\(0, 1fr\)/,
    );
  });
});
