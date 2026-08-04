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
  const copyCommand = () => {
    void navigator.clipboard?.writeText(evidence.command).then(showCopied, () => undefined);
  };
  const copyLabel = evidence.inputKind === "query"
    ? t("deck.investigation.copyQuery")
    : t("deck.investigation.copyCommand");
  const outputLabel = evidence.inputKind === "query" || providerUsesTerminal(evidence)
    ? t("deck.investigation.queryResult")
    : t("deck.investigation.outputLogs");
  const inventoryDisplay = evidence.inputKind === "query"
    ? inventoryExecutionDisplay(evidence.command)
    : undefined;
  const formattedCommand = formatJsonValue(inventoryDisplay?.iql ?? evidence.command);
  const formattedOutput = evidence.output === undefined
    ? undefined
    : formatJsonValue(evidence.output);
  const hasTimestamps = evidence.startedAt || evidence.completedAt || evidence.durationMs !== undefined;
  const kindLabel = executionKindLabel(evidence, inventoryDisplay !== undefined);
  const safetyLabel = evidence.inputKind === "query"
    ? t("deck.investigation.readOnly")
    : authority ?? t("deck.investigation.redacted");
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
      {evidence.inputKind === "query" ? (
        <details class="deck-investigation-disclosure deck-investigation-command-disclosure" open={status === "running"}>
          <summary>{kindLabel}</summary>
          <pre class="deck-investigation-command">
            <code data-format={formattedCommand.isJson ? "json" : "text"}>
              {formattedCommand.text}
            </code>
          </pre>
        </details>
      ) : (
        <pre class="deck-investigation-command">
          <code data-format={formattedCommand.isJson ? "json" : "text"}>
            <span class="deck-investigation-prompt" aria-hidden="true">$ </span>
            {formattedCommand.text}
          </code>
        </pre>
      )}
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
        <details class="deck-investigation-disclosure" open={status === "running"}>
          <summary>
            <span>{outputLabel}</span>
            {evidence.outputTruncated ? (
              <span class="muted">{t("deck.investigation.truncated")}</span>
            ) : null}
          </summary>
          <pre class="deck-investigation-output">
            <code data-format={formattedOutput.isJson ? "json" : "text"}>
              {formattedOutput.text}
            </code>
          </pre>
        </details>
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
    <div class={`deck-investigation-summary${activity.execution ? " has-kind-badge" : ""}`}>
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
      ) : null}
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
}: {
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly running: boolean;
  readonly showStartNote: boolean;
}) {
  const finalDurationMs = terminalDuration(branches, activities);
  const elapsedMs = useInvestigationElapsed(running, finalDurationMs);
  const tone = investigationTone(activities, branches);
  const visibleBranches = unrepresentedEvidenceBranches(branches, activities);
  const callCount = activities.length + visibleBranches.length;
  const completedCallCount = activities.filter((activity) =>
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
  const allObservedCallsSettled = callCount > 0 && completedCallCount === callCount;
  const phaseTitle = t(running
    ? "deck.investigation.runningTitle"
    : tone === "completed"
      ? "deck.investigation.completedTitle"
      : "deck.investigation.title");
  const callSummary = running
    ? t("deck.investigation.callProgress", {
        current: Math.min(callCount, completedCallCount + 1),
        total: callCount,
      })
    : t(callCount === 1
      ? "deck.investigation.callCompletedOne"
      : "deck.investigation.callsCompletedMany", { count: callCount });
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
        <details class="deck-investigation-activity-disclosure" open>
          <summary>
            {t("deck.investigation.executionDetails", { count: activities.length })}
          </summary>
          <ol class="deck-investigation-list">
            {activities.map((activity, index) => {
              return (
                <li
                  key={activity.activityId}
                  class={`deck-investigation-item is-${activity.status}`}
                >
                  {activity.execution ? (
                    <details
                      class="deck-investigation-item-disclosure"
                      open={activity.status === "running" ||
                        (running && index === activities.length - 1)}
                    >
                      <summary><ActivitySummary activity={activity} /></summary>
                      <ExecutionEvidence
                        evidence={activity.execution}
                        status={activity.status}
                        {...(activity.agent ? { agent: activity.agent } : {})}
                        {...(activity.authority ? { authority: activity.authority } : {})}
                      />
                    </details>
                  ) : <ActivitySummary activity={activity} />}
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}
    </div>
  );

  return (
    <>
      {showStartNote && startCopy ? (
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
      <section
        class={`deck-investigation ${running ? "is-running" : `is-settled is-${tone}`}`}
        aria-label={t("deck.investigation.label")}
      >
        <header class="deck-investigation-head">
          {running ? (
            <span class="deck-investigation-spinner" aria-hidden="true" />
          ) : (
            <span class="deck-investigation-state" aria-hidden="true">
              <span class="deck-marker-glyph">
                {tone === "completed" ? "\u2713" : tone === "failed" ? "\u00d7" : tone === "partial" ? "~" : "!"}
              </span>
            </span>
          )}
          <span class="deck-investigation-session-copy">
            <strong>{phaseTitle}</strong>
            <small>{callSummary} · {formatDuration(running ? elapsedMs : finalDurationMs)}</small>
          </span>
          <span class="deck-investigation-session-summary muted">{summary}</span>
          <span class={`deck-investigation-badge is-${running ? "running" : tone}`}>
            {statusLabel(running ? "running" : tone)}
          </span>
        </header>
        {body}
        {running && allObservedCallsSettled ? <InvestigationNextSkeleton /> : null}
      </section>
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
