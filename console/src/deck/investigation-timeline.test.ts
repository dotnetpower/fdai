import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { InvestigationActivity } from "./backend";
import {
  investigationTone,
  unrepresentedEvidenceBranches,
  upsertEvidenceBranch,
  upsertInvestigationActivity,
} from "./investigation-timeline";
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

  it("removes a source row when the linked execution step already represents it", () => {
    const linkedActivity = {
      ...activity("inventory", "completed"),
      branchId: "request:tool",
      execution: {
        tool: "query_inventory",
        command: "query_inventory --scope <server-owned>",
        redacted: true as const,
      },
    };

    expect(unrepresentedEvidenceBranches([branch("completed")], [linkedActivity])).toEqual([]);
    expect(unrepresentedEvidenceBranches([branch("completed")], [activity("health", "completed")]))
      .toHaveLength(1);
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
    const retrieval = readFileSync(
      fileURLToPath(new URL("./retrieval-trace.tsx", import.meta.url)),
      "utf8",
    );
    const view = readFileSync(
      fileURLToPath(new URL("./command-deck-view.tsx", import.meta.url)),
      "utf8",
    );
    const reply = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );
    const richContent = readFileSync(
      fileURLToPath(new URL("./rich-content.tsx", import.meta.url)),
      "utf8",
    );
    const trajectory = readFileSync(
      fileURLToPath(new URL("./conversation-trajectory-view.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).toContain('<details class="deck-investigation-activity-disclosure" open>');
    expect(component).toContain('class="deck-investigation-item-disclosure"');
    expect(component).toContain('open={activity.status === "running" ||');
    expect(presenter).toContain("showStartNote={investigationFlowStart}");
    expect(component).toContain('class="deck-progress-note deck-progress-note-derived"');
    expect(component).toContain('class="deck-marker-glyph"');
    expect(component).toContain("<InvestigationNextSkeleton />");
    expect(component).toContain('open={status === "running"}');
    expect(component).toContain('aria-label={t("deck.investigation.branches")}');
    expect(component).toContain('class="deck-branch-disclosure"');
    expect(component).toContain('class="deck-branch-step"');
    expect(component).toContain('t("deck.investigation.evidenceReferences")');
    expect(component).toContain("branch.evidenceRefs.map");
    expect(component).toContain('running ? "is-running" : `is-settled is-${tone}`');
    expect(component).toContain('is-${running ? "running" : tone}');
    expect(component).toContain('"deck.investigation.startingQuery"');
    expect(component).toContain('"deck.investigation.startingCommand"');
    expect(presenter).toContain("!isInvestigationFlow || investigationFlowStart");
    expect(presenter).toContain("!isInvestigationFlow ? (");
    expect(component).toContain('"deck.investigation.sourceSummaryOne"');
    expect(component).toContain('"deck.investigation.callCompletedOne"');
    expect(component).toContain('"deck.investigation.callsCompletedMany"');
    expect(component).toContain('"deck.investigation.readOnly"');
    expect(component).toContain("deck-branch-badge");
    expect(component).toContain('"is-query" : "is-tool"');
    expect(component).toContain("executionKindLabel(activity.execution");
    expect(component).toContain('evidence.tool.includes("Azure Resource Graph")');
    expect(component).toContain('evidence.tool === "Azure CLI"');
    expect(component).not.toContain('t("deck.investigation.providerExecution")');
    expect(component).toContain('t("deck.investigation.copyQuery")');
    expect(component).toContain("formatJsonValue(inventoryDisplay?.iql ?? evidence.command)");
    expect(component).toContain('data-format={formattedOutput.isJson ? "json" : "text"}');
    expect(styles).toContain("@keyframes deck-investigation-rise");
    expect(presenter).toContain('turn.source === "investigation"');
    expect(presenter).toContain('class="deck-progress-note" role="status"');
    expect(presenter).toContain('class="deck-progress-note-body"');
    expect(presenter).toContain('"deck.investigation.startingWork"');
    expect(presenter).toContain("is-investigation-flow");
    expect(presenter).toContain('isActivity ? " deck-turn-activity"');
    expect(styles).toContain(".deck-progress-note {");
    expect(styles).toContain(".deck-turn.is-investigation-flow::before");
    expect(styles).toContain(".deck-marker-glyph {");
    expect(styles).toContain(".deck-progress-note-mark > .deck-marker-glyph");
    expect(styles).toMatch(/\.deck-progress-note-mark\s*\{[^}]*color:\s*var\(--accent\);/);
    expect(styles).toContain(".deck-execution-axis {");
    expect(styles).toContain("repeating-linear-gradient(to right");
    expect(retrieval).toContain('class="deck-turn-head deck-rt-agent-head"');
    expect(retrieval).toContain('class="deck-turn-source"');
    expect(retrieval).toContain('<details class="deck-rt-sources">');
    expect(view).toContain("showPreparingAnswer");
    expect(view).toContain("inFlight && !finalAnswerPresent");
    expect(view).toContain("index === activeOperatorIndex");
    expect(view).toContain('class="deck-composer-inner"');
    expect(view).toContain('class="deck-transcript-inner"');
    expect(styles).toContain("overflow-anchor: none;");
    expect(styles).toContain("padding: 16px 42px 88px;");
    expect(styles).toContain(".deck-table-wrap { max-height: none; overflow: visible; }");
    expect(richContent).toContain("streaming ? parseStreamingAnswer(text) : parseAnswer(text)");
    expect(richContent).toContain("{rows.map((row, r) => (");
    expect(richContent).toContain('<th key={i} scope="col">');
    expect(richContent).toContain('class="deck-table-cell-label" aria-hidden="true"');
    expect(richContent).not.toContain("tableRowsForDisplay");
    expect(styles).toContain(".deck-table-cell-label {");
    expect(styles).toContain("grid-template-columns: minmax(88px, 36%) minmax(0, 1fr);");
    expect(styles).toContain(".deck-composer-inner {");
    expect(styles).toContain(".deck-transcript-inner {");
    expect(reply).toContain('<details\n          class="deck-llm-escalation"');
    expect(reply).toContain('class="deck-llm-escalation-chevron"');
    expect(trajectory).toContain("<IntentGraphPhase");
    expect(trajectory).toContain('class="deck-trajectory-goals"');
    expect(trajectory).toContain('t("deck.trajectory.runRecord")');
    expect(trajectory).toContain('class="deck-trajectory-signals"');
    expect(trajectory).toContain("useState(false)");
    expect(trajectory).toContain("trajectory.question.text");
    expect(trajectory).not.toContain('if (presentation.workProgress === "none") return null;');
    expect(trajectory).not.toContain('if (presentation.workProgress === "compact")');
    expect(trajectory).toContain("open={open}");
    expect(trajectory).toContain("function phaseMark(");
    expect(trajectory).toContain('class="deck-trajectory-records"');
    expect(trajectory).toContain('t("deck.trajectory.checks")');
    expect(styles).toContain(".deck-trajectory-results {");
    expect(styles).toContain(".deck-trajectory-signals {");
    expect(styles).toContain(".deck-execution-chevron {");
    expect(styles).toContain(".deck-overlay-mode-workspace .deck-header {");
    expect(styles).toContain(".deck-overlay-mode-workspace .deck-transcript-tools {");
    expect(styles).toContain(".deck-trajectory-goal-status.is-skipped");
    expect(styles).toContain(".deck-trajectory-title-copy");
    expect(styles).toMatch(
      /\.deck-trajectory-question strong\s*\{[^}]*overflow-wrap:\s*anywhere;[^}]*white-space:\s*normal;/,
    );
    expect(styles).toMatch(
      /\.deck-body\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    expect(styles).toMatch(
      /\.deck-body\.has-conversations\.has-digest\s*\{[^}]*grid-template-columns:\s*210px minmax\(0, 1fr\) 280px/,
    );
    expect(styles).toMatch(
      /\.deck-investigation-command,[\s\S]*?\.deck-investigation-output\s*\{[^}]*background:\s*#1f2428/,
    );
    expect(styles).toContain("scrollbar-color: #68737e #1f2428;");
    expect(styles).toContain(".deck-investigation-command::-webkit-scrollbar-thumb,");
    expect(styles).toContain(".deck-investigation-item-disclosure > summary::after");
    expect(styles).toContain("--font-sans:");
    expect(styles).toContain("--font-mono:");
    expect(styles).toContain(".deck-investigation-list::before");
    expect(styles).toContain(".deck-branch-list::before");
    expect(styles).toMatch(
      /@container deck-transcript \(max-width: 620px\)[\s\S]*?\.deck-table tbody tr/,
    );
    expect(styles).toMatch(/\.deck-investigation-summary\s*\{[^}]*min-height:\s*44px/);
    expect(styles).toMatch(
      /\.deck-investigation-kind-badge\s*\{[^}]*min-width:\s*46px;[^}]*font-size:\s*11px/,
    );
    expect(styles).toMatch(
      /\.deck-investigation-copy small,[\s\S]*?\.deck-investigation-meta\s*\{[^}]*font-size:\s*11px/,
    );
    expect(styles).toMatch(
      /\.deck-investigation-copy-command\s*\{[^}]*width:\s*32px;[^}]*height:\s*32px/,
    );
    expect(styles).toContain(".deck-investigation-copy-command:focus-visible {");
    expect(styles).toContain(".deck-investigation-item-disclosure > summary:focus-visible {");
    expect(styles).toContain(".deck-execution-timeline > ol > li > details > summary:focus-visible {");
    expect(styles).toMatch(
      /@container deck-transcript \(max-width: 820px\)[\s\S]*?\.deck-execution-facts\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
    );
    expect(styles).toMatch(
      /@container deck-transcript \(max-width: 620px\)[\s\S]*?\.deck-execution-label\s*\{[^}]*white-space:\s*normal/,
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

describe("investigationTone", () => {
  it("keeps mixed successful and unavailable evidence visibly partial", () => {
    expect(investigationTone([], [branch("completed"), branch("unavailable")]))
      .toBe("partial");
  });

  it("distinguishes all unavailable, all completed, and failed evidence", () => {
    expect(investigationTone([], [branch("unavailable")])).toBe("unavailable");
    expect(investigationTone([], [branch("completed")])).toBe("completed");
    expect(investigationTone([], [branch("completed"), branch("failed")])).toBe("failed");
  });
});
