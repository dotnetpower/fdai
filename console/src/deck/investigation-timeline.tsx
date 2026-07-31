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

function statusLabel(status: InvestigationActivity["status"]): string {
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
  return durationMs < 1000 ? `${durationMs} ms` : `${(durationMs / 1000).toFixed(1)} s`;
}

function terminalDuration(branches: readonly EvidenceBranch[]): number {
  return Math.max(0, ...branches.map((branch) => branch.durationMs ?? 0));
}

function terminalTone(
  activities: readonly InvestigationActivity[],
  branches: readonly EvidenceBranch[],
): "completed" | "unavailable" | "failed" {
  const statuses = [
    ...activities.map((activity) => activity.status),
    ...branches.map((branch) => branch.status),
  ];
  if (statuses.some((status) => ["failed", "timed_out", "cancelled"].includes(status))) {
    return "failed";
  }
  return statuses.some((status) => status !== "completed") ? "unavailable" : "completed";
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
  const outputLabel = evidence.inputKind === "query"
    ? t("deck.investigation.queryResult")
    : t("deck.investigation.outputLogs");
  const hasTimestamps = evidence.startedAt || evidence.completedAt || evidence.durationMs !== undefined;
  return (
    <section class="deck-investigation-execution" aria-label={t("deck.investigation.executionEvidence")}>
      <header class="deck-investigation-command-head">
        {agent ? <><strong>{agent}</strong><span aria-hidden="true">-</span></> : null}
        <span>{evidence.tool}</span>
        <span class="deck-investigation-redacted">{t("deck.investigation.redacted")}</span>
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
      <pre class="deck-investigation-command"><code>{evidence.command}</code></pre>
      <div class="deck-investigation-result">
        <span class={`deck-investigation-result-status is-${status}`}>
          {statusLabel(status)}
        </span>
        {evidence.exitCode !== undefined ? (
          <span>{t("deck.investigation.exitCode", { code: evidence.exitCode })}</span>
        ) : null}
        {authority ? <span>{authority}</span> : null}
      </div>
      {evidence.output !== undefined ? (
        <details class="deck-investigation-disclosure">
          <summary>
            <span>{outputLabel}</span>
            {evidence.outputTruncated ? (
              <span class="muted">{t("deck.investigation.truncated")}</span>
            ) : null}
          </summary>
          <pre class="deck-investigation-output"><code>{evidence.output}</code></pre>
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

export function InvestigationTimeline({
  activities,
  branches,
  running,
}: {
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly running: boolean;
}) {
  const finalDurationMs = terminalDuration(branches);
  const elapsedMs = useInvestigationElapsed(running, finalDurationMs);
  const tone = terminalTone(activities, branches);
  const visibleBranches = unrepresentedEvidenceBranches(branches, activities);
  const summary = branches.length > 0
    ? t("deck.investigation.sourceSummary", { count: branches.length })
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
              <span class={`deck-branch-badge is-${branch.kind}`} aria-hidden="true">
                {branchKindBadge(branch.kind)}
              </span>
              <span class="deck-investigation-copy">
                <strong>{t(`deck.investigation.kind.${branch.kind}`)}</strong>
                <small>{branch.summary}</small>
              </span>
              <span class={`deck-branch-status is-${branch.status}`}>
                <span class="deck-investigation-state" aria-hidden="true">
                  {branchStatusMark(branch.status)}
                </span>
                <span class="deck-investigation-meta muted">
                  {branch.durationMs !== undefined
                    ? formatDuration(branch.durationMs)
                    : branchStatusLabel(branch.status)}
                </span>
              </span>
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
            {activities.map((activity) => {
              const progress = activity.completed !== null && activity.total !== null
                ? `${activity.completed}/${activity.total}`
                : null;
              return (
                <li
                  key={activity.activityId}
                  class={`deck-investigation-item is-${activity.status}`}
                >
                  <div class={`deck-investigation-summary${activity.execution ? " has-kind-badge" : ""}`}>
                    <span class="deck-investigation-state" aria-hidden="true">
                      {statusMark(activity.status)}
                    </span>
                    {activity.execution ? (
                      <span
                        class={`deck-investigation-kind-badge ${activity.execution.inputKind === "query" ? "is-query" : "is-tool"}`}
                        aria-hidden="true"
                      >
                        {activity.execution.inputKind === "query" ? "QUERY" : "TOOL"}
                      </span>
                    ) : null}
                    <span class="deck-investigation-copy">
                      <strong>{activity.label}</strong>
                      {activity.detail ? <small>{activity.detail}</small> : null}
                    </span>
                    <span class="deck-investigation-meta muted">
                      {progress ?? statusLabel(activity.status)}
                    </span>
                  </div>
                  {activity.execution ? (
                    <ExecutionEvidence
                      evidence={activity.execution}
                      status={activity.status}
                      {...(activity.agent ? { agent: activity.agent } : {})}
                      {...(activity.authority ? { authority: activity.authority } : {})}
                    />
                  ) : null}
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}
    </div>
  );

  if (!running) {
    return (
      <section
        class={`deck-investigation is-settled is-${tone}`}
        aria-label={t("deck.investigation.label")}
      >
        <header class="deck-investigation-head">
          <span class="deck-investigation-phase" aria-hidden="true">01</span>
          <span class="deck-investigation-state" aria-hidden="true">
            {tone === "completed" ? "\u2713" : tone === "failed" ? "\u00d7" : "!"}
          </span>
          <strong>{t("deck.investigation.title")}</strong>
          <span class="muted">{summary}</span>
          <span class={`deck-investigation-badge is-${tone}`}>
            {statusLabel(tone)}
          </span>
          {finalDurationMs > 0 ? (
            <span class="deck-investigation-meta muted">{formatDuration(finalDurationMs)}</span>
          ) : null}
        </header>
        {body}
      </section>
    );
  }

  return (
    <section
      class="deck-investigation is-running"
      aria-label={t("deck.investigation.label")}
    >
      <header class="deck-investigation-head">
        <span class="deck-investigation-phase" aria-hidden="true">01</span>
        <span class="deck-investigation-spinner" aria-hidden="true" />
        <strong>{t("deck.investigation.title")}</strong>
        <span class="muted">{summary}</span>
        <span class="deck-investigation-elapsed muted" aria-hidden="true">
          {(elapsedMs / 1000).toFixed(1)}s
        </span>
      </header>
      {body}
    </section>
  );
}
