import { useEffect, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { useTransientFlag } from "../hooks/use-transient-flag";
import { t } from "../i18n";
import type {
  EvidenceBranch,
  EvidenceBranchStatus,
  InvestigationActivity,
  InvestigationExecutionEvidence,
} from "./backend";
import { formatJsonValue } from "./json-code-block";
import { inventoryExecutionDisplay } from "./inventory-execution-display";

export function upsertEvidenceBranch(
  branches: readonly EvidenceBranch[],
  incoming: EvidenceBranch,
): readonly EvidenceBranch[] {
  const index = branches.findIndex((branch) => branch.branchId === incoming.branchId);
  if (index < 0) return [...branches, incoming];
  const existing = branches[index];
  if (existing && !canAdvanceBranch(existing.status, incoming.status)) return branches;
  return branches.map((branch, branchIndex) => branchIndex === index ? incoming : branch);
}

function canAdvanceBranch(current: EvidenceBranchStatus, incoming: EvidenceBranchStatus): boolean {
  if (!["pending", "running"].includes(current)) return false;
  return current !== "running" || incoming !== "pending";
}

export function upsertInvestigationActivity(
  activities: readonly InvestigationActivity[],
  incoming: InvestigationActivity,
): readonly InvestigationActivity[] {
  const index = activities.findIndex((item) => item.activityId === incoming.activityId);
  if (index < 0) return [...activities, incoming];
  const existing = activities[index];
  if (existing && !canAdvanceActivity(existing.status, incoming.status)) return activities;
  return activities.map((item, itemIndex) => itemIndex === index ? incoming : item);
}

export function unrepresentedEvidenceBranches(
  branches: readonly EvidenceBranch[],
  activities: readonly InvestigationActivity[],
): readonly EvidenceBranch[] {
  const representedBranchIds = new Set(
    activities
      .filter((activity) => activity.execution !== undefined && activity.branchId)
      .map((activity) => activity.branchId),
  );
  return branches.filter((branch) => !representedBranchIds.has(branch.branchId));
}

function canAdvanceActivity(
  current: InvestigationActivity["status"],
  incoming: InvestigationActivity["status"],
): boolean {
  if (current === "completed" || current === "unavailable" || current === "failed") {
    return false;
  }
  return current !== "running" || incoming !== "pending";
}

function statusMark(status: InvestigationActivity["status"]): string {
  if (status === "completed") return "\u2713";
  if (status === "unavailable") return "!";
  if (status === "failed") return "\u00d7";
  return "";
}

function statusLabel(status: InvestigationActivity["status"] | "partial"): string {
  return t(`deck.investigation.${status}`);
}

function branchStatusMark(status: EvidenceBranchStatus): string {
  if (status === "completed") return "\u2713";
  if (status === "failed" || status === "timed_out" || status === "cancelled") return "\u00d7";
  if (status === "unavailable") return "!";
  return "";
}

function branchStatusLabel(status: EvidenceBranchStatus): string {
  return t(`deck.investigation.${status}`);
}

function branchKindBadge(kind: EvidenceBranch["kind"]): string {
  if (kind === "public_web") return "WEB";
  if (kind === "operational") return "OPS";
  return kind.toUpperCase();
}

function formatDuration(durationMs: number): string {
  return durationMs < 1000
    ? `${Math.round(durationMs)} ms`
    : `${(durationMs / 1000).toFixed(1)} s`;
}

function terminalDuration(
  branches: readonly EvidenceBranch[],
  activities: readonly InvestigationActivity[],
): number {
  return Math.max(
    0,
    ...branches.map((branch) => branch.durationMs ?? 0),
    ...activities.map((activity) => activity.execution?.durationMs ?? 0),
  );
}

export function investigationTone(
  activities: readonly InvestigationActivity[],
  branches: readonly EvidenceBranch[],
): "completed" | "partial" | "unavailable" | "failed" {
  const statuses = [
    ...activities.map((activity) => activity.status),
    ...branches.map((branch) => branch.status),
  ];
  if (statuses.some((status) => ["failed", "timed_out", "cancelled"].includes(status))) {
    return "failed";
  }
  if (statuses.every((status) => status === "completed")) return "completed";
  return statuses.some((status) => status === "completed") ? "partial" : "unavailable";
}

function useInvestigationElapsed(running: boolean, finalDurationMs: number): number {
  const [elapsedMs, setElapsedMs] = useState(finalDurationMs);
  useEffect(() => {
    if (!running) {
      setElapsedMs(finalDurationMs);
      return;
    }
    const startedAt = performance.now();
    setElapsedMs(0);
    const timer = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAt);
    }, 100);
    return () => window.clearInterval(timer);
  }, [finalDurationMs, running]);
  return elapsedMs;
}

function CopyIcon({ copied }: { readonly copied: boolean }) {
  return copied ? (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 8.5 6.5 12 13 4.5" />
    </svg>
  ) : (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5" />
    </svg>
  );
}

function TerminalIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true">
      <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="1.5" stroke="currentColor" />
      <path d="m4.25 6 2 2-2 2M8.25 10h3.25" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  );
}

interface ObjectSetQuerySummary {
  readonly objectType?: string;
  readonly filters: readonly string[];
  readonly limit?: number;
  readonly asOf?: string;
  readonly purpose?: string;
}

interface QueryResultSummary {
  readonly status?: string;
  readonly evidenceCount?: number;
  readonly returnedRows?: number;
  readonly totalRows?: number;
  readonly complete?: boolean;
}

export function objectSetQuerySummary(
  command: string,
  operation: string | undefined,
): ObjectSetQuerySummary | undefined {
  try {
    const parsed = JSON.parse(command) as unknown;
    const root = jsonRecord(parsed);
    if (operation !== "object_set_materialization" && root?.capability !== "query.object_set") {
      return undefined;
    }
    const argumentsRecord = jsonRecord(root?.arguments) ?? root;
    const definition = jsonRecord(argumentsRecord?.definition);
    if (!definition) return undefined;
    const selector = jsonRecord(definition.selector);
    const predicates = Array.isArray(definition.predicates) ? definition.predicates : [];
    const filters = predicates.flatMap((item) => {
      const predicate = jsonRecord(item);
      if (!predicate || typeof predicate.property !== "string" ||
          typeof predicate.operator !== "string") return [];
      const operand = predicate.operator === "in" ? predicate.values : predicate.equals;
      return [`${predicate.property} ${predicate.operator} ${readableOperand(operand)}`];
    });
    return {
      ...(selector && typeof selector.name === "string" ? { objectType: selector.name } : {}),
      filters,
      ...(typeof definition.limit === "number" && Number.isSafeInteger(definition.limit)
        ? { limit: definition.limit }
        : {}),
      ...(typeof definition.as_of === "string" ? { asOf: definition.as_of } : {}),
      ...(typeof definition.purpose === "string" ? { purpose: definition.purpose } : {}),
    };
  } catch {
    return undefined;
  }
}

export function queryResultSummary(output: string | undefined): QueryResultSummary | undefined {
  if (output === undefined) return undefined;
  try {
    const parsed = JSON.parse(output) as unknown;
    const root = Array.isArray(parsed) ? jsonRecord(parsed[0]) : jsonRecord(parsed);
    if (!root) return undefined;
    const result = jsonRecord(root.result) ?? root;
    const returnedRows = safeCount(root.returned_rows) ?? safeCount(result.returned_rows) ??
      (Array.isArray(result.rows) ? result.rows.length : undefined);
    const totalRows = safeCount(root.total_rows) ?? safeCount(result.total_rows);
    const complete = typeof root.complete === "boolean" ? root.complete
      : typeof root.source_complete === "boolean" ? root.source_complete
      : typeof result.complete === "boolean" ? result.complete
      : typeof result.source_complete === "boolean" ? result.source_complete
      : undefined;
    const summary: QueryResultSummary = {
      ...(typeof root.status === "string" ? { status: root.status } : {}),
      ...(Array.isArray(root.evidence_refs) ? { evidenceCount: root.evidence_refs.length } : {}),
      ...(returnedRows !== undefined ? { returnedRows } : {}),
      ...(totalRows !== undefined ? { totalRows } : {}),
      ...(complete !== undefined ? { complete } : {}),
    };
    return Object.keys(summary).length > 0 ? summary : undefined;
  } catch {
    return undefined;
  }
}

function jsonRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function readableOperand(value: unknown): string {
  if (Array.isArray(value)) return value.map(readableOperand).join(", ");
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return t("deck.trajectory.notRecorded");
}

function safeCount(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : undefined;
}

function executionTargetValue(value: string): string {
  const key = `deck.investigation.executionValue.${value}`;
  const translated = t(key);
  return translated === key ? value : translated;
}

function ExecutionEvidence({
  evidence,
  status,
  authority,
  agent,
}: {
  readonly evidence: InvestigationExecutionEvidence;
  readonly status: InvestigationActivity["status"];
  readonly authority?: string;
  readonly agent?: string;
}) {
  const [copied, showCopied] = useTransientFlag(1200);
  const inventoryDisplay = evidence.inputKind === "query"
    ? inventoryExecutionDisplay(evidence.command)
    : undefined;
  const copyCommand = () => {
    void navigator.clipboard?.writeText(evidence.command).then(showCopied, () => undefined);
  };
  const copyLabel = inventoryDisplay
    ? t("deck.investigation.copyIql")
    : evidence.inputKind === "query" ? t("deck.investigation.copyQuery")
    : t("deck.investigation.copyCommand");
  const outputLabel = evidence.inputKind === "query" || providerUsesTerminal(evidence)
    ? t("deck.investigation.queryResult")
    : t("deck.investigation.outputLogs");
  const formattedCommand = formatJsonValue(inventoryDisplay?.iql ?? evidence.command);
  const formattedOutput = evidence.output === undefined
    ? undefined
    : formatJsonValue(evidence.output);
  const hasTimestamps = evidence.startedAt || evidence.completedAt || evidence.durationMs !== undefined;
  const kindLabel = executionKindLabel(evidence, inventoryDisplay !== undefined);
  const safetyLabel = evidence.inputKind === "query"
    ? t("deck.investigation.readOnly")
    : authority ?? t("deck.investigation.redacted");
  const querySummary = objectSetQuerySummary(evidence.command, evidence.target?.operation);
  const resultSummary = evidence.inputKind === "query"
    ? queryResultSummary(evidence.output)
    : undefined;
  return (
    <section class="deck-investigation-execution" aria-label={t("deck.investigation.executionEvidence")}>
      <header class="deck-investigation-command-head">
        {agent ? <><strong>{agent}</strong><span aria-hidden="true">-</span></> : null}
        <span class="deck-investigation-command-kind">{kindLabel}</span>
        <span class="deck-investigation-command-safety">{safetyLabel}</span>
        <span class="deck-investigation-command-tool">{evidence.tool}</span>
        <Tooltip content={copied ? t("deck.tooltip.copied") : copyLabel}>
          <button
            type="button"
            class="deck-investigation-copy-command"
            onClick={copyCommand}
            aria-label={copyLabel}
          >
            <CopyIcon copied={copied} />
          </button>
        </Tooltip>
      </header>
      {evidence.target ? (
        <dl class="deck-investigation-provenance">
          <div>
            <dt>{t("deck.investigation.executionInterface")}</dt>
            <dd>{executionTargetValue(evidence.target.interfaceKind)}</dd>
          </div>
          <div>
            <dt>{t("deck.investigation.service")}</dt>
            <dd>{executionTargetValue(evidence.target.service)}</dd>
          </div>
          <div>
            <dt>{t("deck.investigation.component")}</dt>
            <dd><code>{evidence.target.component}</code></dd>
          </div>
          <div>
            <dt>{t("deck.investigation.operation")}</dt>
            <dd>{executionTargetValue(evidence.target.operation)}</dd>
          </div>
          {evidence.target.sourceKind ? (
            <div>
              <dt>{t("deck.investigation.dataSource")}</dt>
              <dd>{executionTargetValue(evidence.target.sourceKind)}</dd>
            </div>
          ) : null}
          {evidence.target.transport ? (
            <div>
              <dt>{t("deck.investigation.transport")}</dt>
              <dd>{executionTargetValue(evidence.target.transport)}</dd>
            </div>
          ) : null}
          <div>
            <dt>{t("deck.investigation.endpoint")}</dt>
            <dd>{evidence.target.endpoint
              ? <code>{`${evidence.target.endpoint.method} ${evidence.target.endpoint.path}`}</code>
              : evidence.target.interfaceKind === "internal_query"
              ? t("deck.investigation.internalQueryEndpoint")
              : t("deck.trajectory.notRecorded")}</dd>
          </div>
        </dl>
      ) : evidence.inputKind === "query" ? (
        <p class="deck-investigation-provenance-unavailable">
          <strong>{t("deck.investigation.executionProvenance")}</strong>
          <span>{t("deck.investigation.provenanceNotRecorded")}</span>
        </p>
      ) : null}
      {querySummary ? (
        <section class="deck-investigation-query-summary">
          <strong>{t("deck.investigation.querySummary")}</strong>
          <dl>
            {querySummary.objectType ? (
              <div><dt>{t("deck.investigation.objectType")}</dt><dd><code>{querySummary.objectType}</code></dd></div>
            ) : null}
            {querySummary.filters.length > 0 ? (
              <div><dt>{t("deck.investigation.filters")}</dt><dd>{querySummary.filters.join("; ")}</dd></div>
            ) : null}
            {querySummary.limit !== undefined ? (
              <div><dt>{t("deck.investigation.limit")}</dt><dd>{querySummary.limit}</dd></div>
            ) : null}
            {querySummary.asOf ? (
              <div><dt>{t("deck.investigation.asOf")}</dt><dd><time>{querySummary.asOf}</time></dd></div>
            ) : null}
            {querySummary.purpose ? (
              <div><dt>{t("deck.investigation.purpose")}</dt><dd>{querySummary.purpose}</dd></div>
            ) : null}
          </dl>
        </section>
      ) : null}
      <div class="deck-investigation-input-label">
        {t(evidence.inputKind === "query"
          ? "deck.investigation.verifiedQueryInput"
          : "deck.investigation.commandInput")}
      </div>
      <pre class="deck-investigation-command">
        <code data-format={formattedCommand.isJson ? "json" : "text"}>
          {evidence.inputKind === "command" ? (
            <span class="deck-investigation-prompt" aria-hidden="true">$ </span>
          ) : null}
          {formattedCommand.text}
        </code>
      </pre>
      <div class="deck-investigation-result">
        <span class={`deck-investigation-result-status is-${status}`}>
          {statusLabel(status)}
        </span>
        {evidence.exitCode !== undefined ? (
          <span>{t("deck.investigation.exitCode", { code: evidence.exitCode })}</span>
        ) : null}
        {authority ? <span>{authority}</span> : null}
      </div>
      {formattedOutput !== undefined ? (
        <div class="deck-investigation-output-block">
          <div class="deck-investigation-output-label">
            <span>{outputLabel}</span>
            {evidence.outputTruncated ? (
              <span class="muted">{t("deck.investigation.truncated")}</span>
            ) : null}
          </div>
          {resultSummary ? (
            <dl class="deck-investigation-result-summary">
              {resultSummary.status ? (
                <div><dt>{t("deck.investigation.outcome")}</dt><dd>{resultSummary.status}</dd></div>
              ) : null}
              {resultSummary.evidenceCount !== undefined ? (
                <div><dt>{t("deck.investigation.evidenceReferences")}</dt><dd>{resultSummary.evidenceCount}</dd></div>
              ) : null}
              {resultSummary.returnedRows !== undefined ? (
                <div><dt>{t("deck.investigation.returnedRows")}</dt><dd>{resultSummary.returnedRows}</dd></div>
              ) : null}
              {resultSummary.totalRows !== undefined ? (
                <div><dt>{t("deck.investigation.totalRows")}</dt><dd>{resultSummary.totalRows}</dd></div>
              ) : null}
              {resultSummary.complete !== undefined ? (
                <div><dt>{t("deck.investigation.completeness")}</dt><dd>{t(resultSummary.complete
                  ? "deck.investigation.complete"
                  : "deck.investigation.incomplete")}</dd></div>
              ) : null}
            </dl>
          ) : null}
          <pre class="deck-investigation-output">
            <code data-format={formattedOutput.isJson ? "json" : "text"}>
              {formattedOutput.text}
            </code>
          </pre>
        </div>
      ) : null}
      {hasTimestamps ? (
        <details class="deck-investigation-disclosure">
          <summary>{t("deck.investigation.timestamps")}</summary>
          <dl class="deck-investigation-timestamps">
            {evidence.startedAt ? (
              <><dt>{t("deck.investigation.startedAt")}</dt><dd>{evidence.startedAt}</dd></>
            ) : null}
            {evidence.completedAt ? (
              <><dt>{t("deck.investigation.completedAt")}</dt><dd>{evidence.completedAt}</dd></>
            ) : null}
            {evidence.durationMs !== undefined ? (
              <><dt>{t("deck.investigation.duration")}</dt><dd>{formatDuration(evidence.durationMs)}</dd></>
            ) : null}
          </dl>
        </details>
      ) : null}
    </section>
  );
}

function ActivityObservation({
  activity,
}: {
  readonly activity: InvestigationActivity;
}) {
  return (
    <section
      class="deck-investigation-execution is-event-only"
      aria-label={t("deck.investigation.observedEvent")}
    >
      <header class="deck-investigation-command-head">
        <span class="deck-investigation-command-kind">
          {t("deck.investigation.lifecycle")}
        </span>
        <span class="deck-investigation-command-safety">
          {t("deck.investigation.observed")}
        </span>
      </header>
      <p class="deck-investigation-event-summary">
        {activity.detail ?? t("deck.trajectory.coverageGap")}
      </p>
      <dl class="deck-investigation-event-facts">
        <div>
          <dt>{t("deck.investigation.eventType")}</dt>
          <dd>{t("deck.investigation.lifecycleEvent")}</dd>
        </div>
        <div><dt>{t("deck.investigation.stage")}</dt><dd><code>{activity.kind}</code></dd></div>
        <div><dt>{t("deck.investigation.outcome")}</dt><dd>{statusLabel(activity.status)}</dd></div>
        {activity.agent ? (
          <div><dt>{t("deck.trajectory.agent")}</dt><dd>{activity.agent}</dd></div>
        ) : null}
        {activity.authority ? (
          <div><dt>{t("deck.trajectory.authority")}</dt><dd>{activity.authority}</dd></div>
        ) : null}
        {activity.observedAt ? (
          <div><dt>{t("deck.investigation.observedAt")}</dt><dd>{activity.observedAt}</dd></div>
        ) : null}
      </dl>
      <p class="deck-investigation-no-execution">
        {t("deck.investigation.noExternalExecution")}
      </p>
    </section>
  );
}

function ActivitySummary({
  activity,
}: {
  readonly activity: InvestigationActivity;
}) {
  const progress = activity.completed !== null && activity.total !== null
    ? `${activity.completed}/${activity.total}`
    : null;
  const meta = activity.execution?.durationMs !== undefined
    ? formatDuration(activity.execution.durationMs)
    : progress ?? statusLabel(activity.status);
  const inventoryDisplay = activity.execution?.inputKind === "query"
    ? inventoryExecutionDisplay(activity.execution.command)
    : undefined;
  const kindLabel = activity.execution
    ? executionKindLabel(activity.execution, inventoryDisplay !== undefined)
    : "";
  const terminalActivity = activity.execution
    ? providerUsesTerminal(activity.execution)
    : false;
  return (
    <div class="deck-investigation-summary has-kind-badge">
      <span class="deck-investigation-state" aria-hidden="true">
        <span class="deck-marker-glyph">{statusMark(activity.status)}</span>
      </span>
      {activity.execution ? (
        <span
          class={`deck-investigation-kind-badge ${activity.execution.inputKind === "query" ? "is-query" : "is-tool"}${terminalActivity ? " is-terminal" : ""}`}
          aria-hidden={terminalActivity ? undefined : "true"}
          aria-label={terminalActivity ? kindLabel : undefined}
        >
          {terminalActivity ? <TerminalIcon /> : kindLabel}
        </span>
      ) : (
        <span class="deck-investigation-kind-badge is-event" aria-hidden="true">
          EVENT
        </span>
      )}
      <span class="deck-investigation-copy">
        <span class="deck-investigation-title-line">
          <strong>{activity.label}</strong>
          {activity.status === "running" || activity.status === "pending" ? (
            <em>{statusLabel(activity.status)}</em>
          ) : null}
        </span>
        {activity.detail ? <small>{activity.detail}</small> : null}
      </span>
      <span class="deck-investigation-meta muted">
        {meta}
      </span>
    </div>
  );
}

function executionKindLabel(
  evidence: InvestigationExecutionEvidence,
  inventoryQuery: boolean,
): string {
  if (inventoryQuery) return "IQL";
  if (evidence.inputKind === "query") return "QUERY";
  if (evidence.tool.includes("Azure Resource Graph")) return "ARG";
  if (evidence.tool === "Azure CLI") return "AZ CLI";
  return "TOOL";
}

function providerUsesTerminal(evidence: InvestigationExecutionEvidence): boolean {
  return evidence.inputKind === "command" && (
    evidence.tool === "Azure CLI" || evidence.tool.includes("Azure Resource Graph")
  );
}

export function InvestigationTimeline({
  activities,
  branches,
  running,
  showStartNote,
  answerSettled,
}: {
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly running: boolean;
  readonly showStartNote: boolean;
  readonly answerSettled: boolean;
}) {
  const finalDurationMs = terminalDuration(branches, activities);
  const elapsedMs = useInvestigationElapsed(running, finalDurationMs);
  const tone = investigationTone(activities, branches);
  const visibleBranches = unrepresentedEvidenceBranches(branches, activities);
  const eventCount = activities.length + visibleBranches.length;
  const completedEventCount = activities.filter((activity) =>
    ["completed", "unavailable", "failed"].includes(activity.status),
  ).length + visibleBranches.filter((branch) =>
    !["pending", "running"].includes(branch.status),
  ).length;
  const firstActivity = activities[0];
  const startCopy = firstActivity?.execution
    ? t(firstActivity.execution.inputKind === "query"
      ? "deck.investigation.startingQuery"
      : "deck.investigation.startingCommand", { tool: firstActivity.execution.tool })
    : visibleBranches[0]?.summary ?? firstActivity?.label;
  const allObservedEventsSettled = eventCount > 0 && completedEventCount === eventCount;
  const phaseTitle = t(running
    ? "deck.investigation.runningTitle"
    : tone === "completed"
      ? "deck.investigation.completedTitle"
      : "deck.investigation.title");
  const eventSummary = running
    ? t("deck.investigation.eventProgress", {
        current: Math.min(eventCount, completedEventCount + 1),
        total: eventCount,
      })
    : t(eventCount === 1
      ? "deck.investigation.eventCompletedOne"
      : "deck.investigation.eventsCompletedMany", { count: eventCount });
  const summary = branches.length > 0
    ? t(branches.length === 1
      ? "deck.investigation.sourceSummaryOne"
      : "deck.investigation.sourceSummaryMany", { count: branches.length })
    : t("deck.investigation.executionDetails", { count: activities.length });
  const body = (
    <div class="deck-investigation-body">
      {visibleBranches.length > 0 ? (
        <ol class="deck-branch-list" aria-label={t("deck.investigation.branches")}>
          {visibleBranches.map((branch, index) => (
            <li
              key={branch.branchId}
              class={`deck-branch-item is-${branch.status}`}
              style={{ animationDelay: `${index * 55}ms` }}
            >
              <details
                class="deck-branch-disclosure"
                open={branch.status === "running" || branch.status === "pending"}
              >
                <summary class="deck-branch-summary">
                  <span class="deck-branch-step" aria-hidden="true">
                    {String(index + 2).padStart(2, "0")}
                  </span>
                  <span class={`deck-branch-badge is-${branch.kind}`} aria-hidden="true">
                    {branchKindBadge(branch.kind)}
                  </span>
                  <span class="deck-investigation-copy">
                    <strong>{t(`deck.investigation.kind.${branch.kind}`)}</strong>
                    <small>{branch.summary}</small>
                  </span>
                  <span class={`deck-branch-status is-${branch.status}`}>
                    <span class="deck-investigation-state" aria-hidden="true">
                      <span class="deck-marker-glyph">{branchStatusMark(branch.status)}</span>
                    </span>
                    <span class="deck-investigation-meta muted">
                      {branch.durationMs !== undefined
                        ? formatDuration(branch.durationMs)
                        : branchStatusLabel(branch.status)}
                    </span>
                  </span>
                </summary>
                <div class="deck-branch-detail">
                  <dl>
                    <div>
                      <dt>{t("deck.investigation.status")}</dt>
                      <dd>{branchStatusLabel(branch.status)}</dd>
                    </div>
                    <div>
                      <dt>{t("deck.investigation.startedAt")}</dt>
                      <dd>{branch.startedAt}</dd>
                    </div>
                    {branch.completedAt ? (
                      <div>
                        <dt>{t("deck.investigation.completedAt")}</dt>
                        <dd>{branch.completedAt}</dd>
                      </div>
                    ) : null}
                    {branch.durationMs !== undefined ? (
                      <div>
                        <dt>{t("deck.investigation.duration")}</dt>
                        <dd>{formatDuration(branch.durationMs)}</dd>
                      </div>
                    ) : null}
                  </dl>
                  {branch.evidenceRefs.length > 0 ? (
                    <div class="deck-branch-evidence">
                      <strong>{t("deck.investigation.evidenceReferences")}</strong>
                      <ul>
                        {branch.evidenceRefs.map((reference) => (
                          <li key={reference}><code>{reference}</code></li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p class="deck-branch-empty-evidence">
                      <span aria-hidden="true">!</span>
                      {t("deck.investigation.noEvidenceReferences")}
                    </p>
                  )}
                </div>
              </details>
            </li>
          ))}
        </ol>
      ) : null}
      {activities.length > 0 ? (
        <ol class="deck-investigation-list">
          {activities.map((activity, index) => (
              <li
                key={activity.activityId}
                class={`deck-investigation-item is-${activity.status}`}
              >
                <details
                  class="deck-investigation-item-disclosure"
                  open={activity.status === "running" ||
                    (running && index === activities.length - 1)}
                >
                  <summary><ActivitySummary activity={activity} /></summary>
                  {activity.execution ? (
                    <ExecutionEvidence
                      evidence={activity.execution}
                      status={activity.status}
                      {...(activity.agent ? { agent: activity.agent } : {})}
                      {...(activity.authority ? { authority: activity.authority } : {})}
                    />
                  ) : <ActivityObservation activity={activity} />}
                </details>
              </li>
          ))}
        </ol>
      ) : null}
    </div>
  );

  const head = (
    <>
      {running ? (
        <span class="deck-investigation-spinner" aria-hidden="true" />
      ) : (
        <span class="deck-investigation-state cs-work-summary-mark" aria-hidden="true">
          <span class="deck-marker-glyph">
            {tone === "completed" ? "\u2713" : tone === "failed" ? "\u00d7" : tone === "partial" ? "~" : "!"}
          </span>
        </span>
      )}
      <span class="deck-investigation-session-copy cs-work-summary-copy">
        <strong class="cs-work-summary-title">{phaseTitle}</strong>
        <small class="cs-work-summary-meta">{eventSummary} · {formatDuration(running ? elapsedMs : finalDurationMs)}</small>
      </span>
      {!answerSettled ? (
        <span class="deck-investigation-session-summary muted">{summary}</span>
      ) : null}
      <span class="deck-investigation-readonly cs-work-summary-safety">
        {t("deck.investigation.readOnly")}
      </span>
      <span class={`deck-investigation-badge cs-work-summary-badge is-${running ? "running" : tone}`}>
        {statusLabel(running ? "running" : tone)}
      </span>
    </>
  );

  return (
    <>
      {showStartNote && !answerSettled && startCopy ? (
        <div class="deck-progress-note deck-progress-note-derived" role="status">
          <span class="deck-progress-note-mark" aria-hidden="true">
            <span class="deck-marker-glyph">01</span>
          </span>
          <div class="deck-progress-note-body">
            <strong>{t("deck.investigation.startingWork")}</strong>
            <p>{startCopy}</p>
          </div>
        </div>
      ) : null}
      {answerSettled ? (
        <details
          key="answer-settled"
          class={`deck-investigation is-settled is-${tone} is-answer-settled`}
          // A single observed read adds nothing the answer does not already state, but a
          // multi-step investigation is the only place its per-step provenance is visible.
          open={eventCount > 1}
          aria-label={t("deck.investigation.label")}
        >
          <summary class="deck-investigation-head cs-work-summary">{head}</summary>
          {body}
        </details>
      ) : (
        <details
          key={running ? "running" : "settled"}
          class={`deck-investigation ${running ? "is-running" : `is-settled is-${tone}`}`}
          open={running}
          aria-label={t("deck.investigation.label")}
        >
          <summary class="deck-investigation-head cs-work-summary">{head}</summary>
          {body}
          {running && allObservedEventsSettled ? <InvestigationNextSkeleton /> : null}
        </details>
      )}
    </>
  );
}

function InvestigationNextSkeleton() {
  return (
    <div class="deck-next-skeleton" aria-hidden="true">
      <span class="deck-next-skeleton-mark" />
      <div class="deck-next-skeleton-stack">
        <div class="deck-next-skeleton-card">
          <span class="deck-next-skeleton-line is-label" />
          <span class="deck-next-skeleton-line" />
        </div>
        <div class="deck-next-skeleton-session">
          <span class="deck-next-skeleton-dot" />
          <span class="deck-next-skeleton-line" />
          <span class="deck-next-skeleton-pill" />
        </div>
      </div>
    </div>
  );
}
