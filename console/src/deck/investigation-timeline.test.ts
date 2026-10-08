import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { InvestigationActivity } from "./backend";
import {
  investigationTone,
  objectSetQuerySummary,
  queryResultSummary,
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

describe("objectSetQuerySummary", () => {
  it("projects readable ObjectSet facts from exact query JSON", () => {
    expect(objectSetQuerySummary(JSON.stringify({
      capability: "query.object_set",
      arguments: {
        definition: {
          selector: { kind: "object_type", name: "Resource" },
          predicates: [{ property: "name", operator: "equals", equals: "resource-example" }],
          limit: 2,
          as_of: "2026-08-21T00:33:34Z",
          purpose: "operations-review",
        },
      },
    }), "object_set_materialization")).toEqual({
      objectType: "Resource",
      filters: ["name equals resource-example"],
      limit: 2,
      asOf: "2026-08-21T00:33:34Z",
      purpose: "operations-review",
    });
  });

  it("does not reinterpret another operation or malformed JSON", () => {
    expect(objectSetQuerySummary("{}", "metric_series")).toBeUndefined();
    expect(objectSetQuerySummary("not-json", "object_set_materialization")).toBeUndefined();
  });

  it("recovers legacy ObjectSet scope only from the exact capability field", () => {
    expect(objectSetQuerySummary(JSON.stringify({
      capability: "query.object_set",
      arguments: { definition: { selector: { name: "Resource" }, limit: 2 } },
    }), undefined)).toEqual({ objectType: "Resource", filters: [], limit: 2 });
    expect(objectSetQuerySummary(JSON.stringify({
      capability: "query.metric_series",
      arguments: { definition: { selector: { name: "Resource" }, limit: 2 } },
    }), undefined)).toBeUndefined();
  });
});

describe("queryResultSummary", () => {
  it("projects exact status, evidence, row counts, and completeness", () => {
    expect(queryResultSummary(JSON.stringify({
      status: "completed",
      evidence_refs: ["evidence:1", "evidence:2"],
      result: { rows: [{ name: "resource-example" }], source_complete: true },
    }))).toEqual({
      status: "completed",
      evidenceCount: 2,
      returnedRows: 1,
      complete: true,
    });
    expect(queryResultSummary(JSON.stringify([{
      returned_rows: 20,
      total_rows: 42,
    }]))).toEqual({ returnedRows: 20, totalRows: 42 });
  });

  it("does not invent a summary from malformed or empty output", () => {
    expect(queryResultSummary("not-json")).toBeUndefined();
    expect(queryResultSummary("{}")) .toBeUndefined();
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
    const sharedStyles = readFileSync(
      fileURLToPath(new URL("../../../ui/calm-slate-primitives.css", import.meta.url)),
      "utf8",
    );
    const conversationLayer = readFileSync(
      fileURLToPath(new URL("../../../ui/calm-slate-deck-conversation.css", import.meta.url)),
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
    const roles = readFileSync(
      fileURLToPath(new URL("./investigation-roles.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).toContain('key={running ? "running" : "settled"}');
    expect(component).toContain('class={`deck-investigation ${running ? "is-running" : `is-settled is-${tone}`}`}');
    expect(component).toContain("open={running}");
    expect(component).toContain("answerSettled ? (");
    expect(component).toContain("is-answer-settled");
    expect(component).toContain('key="answer-settled"');
    expect(component).not.toMatch(/key="answer-settled"[\s\S]*?class=\{`deck-investigation[^>]*\sopen(?:\s|>)/);
    expect(component).toMatch(/key="answer-settled"[\s\S]*?open=\{tone !== "completed"\}/);
    expect(component).toContain("<summary class={headClass}>{head}</summary>");
    expect(component).toContain("`deck-investigation-head cs-work-summary${");
    expect(component).toContain("{body}");
    // Turn-wide timing sits on the lead panel; the settled budget telemetry replaces it there.
    expect(component).toContain("const detailText = answerSettled && lead");
    expect(component).toContain("? limits ? undefined : telemetrySummary");
    expect(component).toContain("{limits ? <TurnBudgetLimits budget={limits} /> : null}");
    expect(component).toContain('<span class="deck-investigation-session-summary muted">{detailText}</span>');
    expect(styles).toContain(".deck-investigation > summary.deck-investigation-head { cursor: pointer; }");
    expect(styles).toContain(".deck-investigation.is-answer-settled .deck-investigation-head");
    expect(component).not.toContain("deck-investigation-activity-disclosure");
    expect(styles).toContain(".deck-investigation-head::-webkit-details-marker { display: none; }");
    expect(component).toContain('class="deck-investigation-readonly cs-work-summary-safety"');
    expect(component).toContain('t("deck.investigation.readOnly")');
    expect(component).toContain('class="deck-investigation-item-disclosure"');
    // A read opens only while its panel runs; a stopped read stays folded with its outcome.
    expect(component).toContain(
      'open={running && (activity.status === "running" || index === activities.length - 1)}',
    );
    expect(presenter).toContain("showStartNote={investigationFlowStart}");
    expect(presenter).toContain("answerSettled={investigationAnswerSettled}");
    expect(presenter).toContain("trajectory && !turn.streaming && !isActivity && !isProgressMessage");
    expect(view).toContain("investigationFlowHasTerminalAnswer(");
    expect(component).toContain("showStartNote && !answerSettled && !stopped && startCopy");
    expect(presenter).toContain("const isInvestigationFinalAnswer = isDeck && investigationFlowEnd");
    expect(presenter).toContain("!isInvestigationFlow || investigationFlowStart");
    expect(presenter).not.toContain("investigationFlowStart || isInvestigationFinalAnswer");
    expect(presenter).toContain("!isInvestigationFlow || isInvestigationFinalAnswer");
    // The derived start note is one quiet lead line on the layer's plan role, not a numbered card.
    expect(component).toContain('<p class="deck-start-note cs-deck-plan-lead" role="status">');
    expect(component).not.toContain("deck-progress-note");
    expect(component).toContain('class="deck-marker-glyph"');
    expect(component).toContain("<InvestigationNextSkeleton />");
    expect(component).toContain('class="deck-investigation-output-block"');
    expect(component).not.toContain("deck-investigation-command-disclosure");
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
    expect(presenter).toContain(
      "isDeck && (!isInvestigationFlow || isInvestigationFinalAnswer) ? (",
    );
    expect(component).toContain('"deck.investigation.sourceSummaryOne"');
    expect(component).toContain('"deck.investigation.eventCompletedOne"');
    expect(component).toContain('"deck.investigation.eventsCompletedMany"');
    expect(component).toContain("<ActivityObservation activity={activity} status={status} />");
    expect(component).toContain('activity.detail ?? t("deck.trajectory.coverageGap")');
    expect(component).toContain('t("deck.investigation.lifecycleEvent")');
    expect(component).toContain('t("deck.investigation.noExternalExecution")');
    expect(component).toContain('"deck.investigation.readOnly"');
    expect(component).toContain("deck-branch-badge");
    expect(component).toContain('"is-query" : "is-tool"');
    expect(component).toContain('activity.kind === "model_call" ? "MODEL" : "EVENT"');
    expect(component).toContain("executionKindLabel(activity.execution");
    expect(component).toContain('evidence.tool.includes("Azure Resource Graph")');
    expect(component).toContain('evidence.tool === "Azure CLI"');
    expect(component).not.toContain('t("deck.investigation.providerExecution")');
    expect(component).toContain('t("deck.investigation.copyIql")');
    expect(component).toContain('t("deck.investigation.copyQuery")');
    expect(component).toContain('class="deck-investigation-provenance"');
    expect(component).toContain('class="deck-investigation-provenance-unavailable"');
    expect(component).toContain('t("deck.investigation.provenanceNotRecorded")');
    expect(component).toContain('t("deck.investigation.internalQueryEndpoint")');
    expect(component).toContain('class="deck-investigation-query-summary"');
    expect(component).toContain('class="deck-investigation-result-summary"');
    expect(component).toContain('"deck.investigation.verifiedQueryInput"');
    expect(component).toContain("formatJsonValue(inventoryDisplay?.iql ?? evidence.command)");
    expect(component).toContain('data-format={formattedOutput.isJson ? "json" : "text"}');
    expect(styles).toContain("@keyframes deck-investigation-rise");
    expect(presenter).toContain('turn.source === "investigation"');
    // A workflow milestone is one quiet progress line; its label stays for assistive technology.
    expect(presenter).toContain("<MilestoneLine text={turn.text}");
    expect(presenter).not.toContain('"deck.investigation.startingWork"');
    expect(roles).toContain('<p class="deck-milestone cs-deck-milestone" role="status">');
    expect(roles).toContain('<span class="cs-deck-milestone-label">{t("deck.investigation.progressUpdate")}</span>');
    expect(presenter).toContain("is-investigation-flow");
    expect(presenter).toContain('isActivity ? " deck-turn-activity"');
    expect(styles).not.toContain(".deck-progress-note");
    expect(styles).toContain(".deck-turn.is-investigation-flow > .deck-start-note {");
    expect(styles).toContain(".deck-turn.is-investigation-flow::before");
    expect(styles).toContain(".deck-marker-glyph {");
    expect(conversationLayer).toContain(".cs-run-axis {");
    expect(conversationLayer).toMatch(/\.cs-run-bar \{[^}]*width: max\(3px, calc\(var\(--cs-run-width, 0\) \* 1%\)\);/s);
    expect(styles).not.toContain(".deck-execution-");
    // The pending turn renders the conversation layer's live grounding trace.
    expect(retrieval).toContain('<header class="deck-turn-head cs-deck-turn-head">');
    expect(retrieval).not.toContain("cs-deck-agent-source");
    expect(retrieval).toContain('<span class="cs-grounding-authority">{t("deck.retrieval.readOnly")}</span>');
    expect(retrieval).toContain("sources.slice(Math.max(0, shown - VISIBLE), shown)");
    expect(retrieval).not.toContain("translateY(${-rolled * CARD_PITCH_PX}px)");
    expect(retrieval).toContain('class="cs-grounding-panel cs-deck-enter"');
    expect(retrieval).toContain('<header class="cs-grounding-head">');
    expect(retrieval).toContain('class={`cs-grounding-stage ${stage.done ? "is-done" : "is-active"}`}');
    expect(retrieval).toContain('<span class="cs-grounding-spinner" />');
    expect(retrieval).toContain('<li key={`${source.kind}-${source.label}-${index}`} class="cs-grounding-source">');
    expect(retrieval).toContain('<div class="cs-deck-answer-skeleton" aria-hidden="true">');
    expect(sharedStyles).toMatch(
      /\.cs-grounding-stage\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*20px minmax\(0, 1fr\) auto 14px;/s,
    );
    expect(conversationLayer).toMatch(
      /\.cs-deck-conversation \.cs-grounding-stages > \.cs-grounding-stage \{[^}]*grid-template-columns: 20px minmax\(0, 1fr\) auto;/s,
    );
    expect(sharedStyles).toMatch(/\.cs-grounding-head\s*\{[^}]*display:\s*flex;/s);
    expect(conversationLayer).toMatch(
      /\.cs-grounding-source-list \{[^}]*--cs-grounding-source-row: 30px;/s,
    );
    expect(styles).not.toMatch(/\.deck-rt(-(?!turn)[a-z-]+)?[\s.{:,]/);
    expect(view).toContain("showPreparingAnswer");
    expect(view).toContain("pending && retrievalProgress === null && !finalAnswerPresent");
    expect(view).toContain("index === activeOperatorIndex");
    expect(view).toContain('class="deck-composer-inner cs-deck-composer-grid"');
    expect(view).toContain('class={`deck-transcript-inner');
    expect(styles).toContain("overflow-anchor: none;");
    expect(styles).toContain("padding: 24px 42px 32px;");
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
    expect(reply).toContain('<details\n          class="deck-llm-escalation cs-deck-disclosure"');
    expect(reply).toContain('<span class="cs-run-chevron" aria-hidden="true" />');
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
    expect(conversationLayer).toContain(".cs-run-chevron {");
    expect(styles).toContain(".deck-overlay-mode-workspace .deck-header {");
    expect(styles).toContain(".deck-overlay-mode-workspace .deck-transcript-tools {");
    expect(styles).toContain(".deck-trajectory-goal-status.is-skipped");
    expect(trajectory).toContain('<span class="cs-run-record-glyph" aria-hidden="true"><i /><i /><i /></span>');
    expect(styles).toMatch(
      /\.deck-trajectory-question strong\s*\{[^}]*overflow-wrap:\s*anywhere;[^}]*white-space:\s*normal;/,
    );
    expect(styles).toMatch(
      /\.deck-body\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
    expect(styles).toMatch(
      /\.deck-body\.has-conversations\.has-digest\s*\{[^}]*grid-template-columns:\s*210px minmax\(0, 1fr\) 280px/,
    );
    // Commands and outputs use the shared code tokens, like every other deck code surface.
    expect(styles).toMatch(
      /\.deck-investigation-command,[\s\S]*?\.deck-investigation-output\s*\{[^}]*color:\s*var\(--cs-code-text\);[^}]*background:\s*var\(--cs-code-bg\);/,
    );
    expect(styles).toContain(
      "scrollbar-color: color-mix(in srgb, var(--cs-code-text) 30%, transparent) var(--cs-code-bg);",
    );
    expect(styles).toMatch(
      /\.deck-investigation-execution\.is-event-only\s*\{[^}]*background:\s*var\(--bg-elevated\);[^}]*box-shadow:\s*none;/s,
    );
    expect(styles).toContain(".deck-investigation-event-summary {");
    expect(styles).toContain(".deck-investigation-command::-webkit-scrollbar-thumb,");
    expect(styles).toContain(".deck-investigation-item-disclosure > summary::after");
    expect(styles).toContain("--font-sans:");
    expect(styles).toContain("--font-mono:");
    expect(styles).toContain(".deck-investigation-list::before");
    expect(styles).toContain("--deck-investigation-rail-x: 9px;");
    expect(styles).toMatch(/\.deck-investigation-summary > \.deck-investigation-state \{[^}]*left: -33px;[^}]*top: 22px;[^}]*transform: translateY\(-50%\);/s);
    expect(styles).toContain(".deck-branch-list::before");
    expect(styles).toMatch(
      /@container deck-transcript \(max-width: 620px\)[\s\S]*?\.deck-table tbody tr/,
    );
    expect(styles).toMatch(/\.deck-investigation-summary\s*\{[^}]*min-height:\s*44px/);
    // Readable floor: investigation labels and meta stay at 12px, and the kind is a quiet label.
    expect(styles).toMatch(
      /\.deck-investigation-kind-badge\s*\{[^}]*min-width:\s*46px;[^}]*color:\s*var\(--cs-deck-meta-text\);[^}]*font-size:\s*12px/,
    );
    expect(styles).toMatch(
      /\.deck-investigation-copy small,[\s\S]*?\.deck-investigation-meta\s*\{[^}]*font-size:\s*12px/,
    );
    expect(styles).toMatch(
      /\.deck-investigation-copy-command\s*\{[^}]*width:\s*32px;[^}]*height:\s*32px/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.deck-investigation-copy-command\s*\{[^}]*width:\s*44px;[^}]*height:\s*44px/,
    );
    expect(styles).toContain(".deck-investigation-copy-command:focus-visible {");
    expect(styles).toContain(".deck-investigation-item-disclosure > summary:focus-visible {");
    expect(conversationLayer).toContain(":is(.cs-run-event-summary, .cs-model-trace-lane-summary):focus-visible {");
    expect(conversationLayer).toMatch(
      /\.cs-run-facts \{[^}]*grid-template-columns: repeat\(auto-fill, minmax\(150px, 1fr\)\);/s,
    );
    expect(conversationLayer).toMatch(
      /@container deck-transcript \(max-width: 620px\)[\s\S]*?\.cs-run-event-kind,[\s\S]*?\.cs-run-axis,[\s\S]*?\{ display: none; \}/,
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
