import { Tooltip } from "../components/tooltip";
import { useTransientFlag } from "../hooks/use-transient-flag";
import { t } from "../i18n";
import type { InvestigationActivity, InvestigationExecutionEvidence } from "./backend";

export function upsertInvestigationActivity(
  activities: readonly InvestigationActivity[],
  incoming: InvestigationActivity,
): readonly InvestigationActivity[] {
  const index = activities.findIndex((item) => item.activityId === incoming.activityId);
  if (index < 0) return [...activities, incoming];
  return activities.map((item, itemIndex) => itemIndex === index ? incoming : item);
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

function formatDuration(durationMs: number): string {
  return durationMs < 1000 ? `${durationMs} ms` : `${(durationMs / 1000).toFixed(1)} s`;
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
  const hasTimestamps = evidence.startedAt || evidence.completedAt || evidence.durationMs !== undefined;
  return (
    <section class="deck-investigation-execution" aria-label={t("deck.investigation.executionEvidence")}>
      <header class="deck-investigation-command-head">
        {agent ? <><strong>{agent}</strong><span aria-hidden="true">-</span></> : null}
        <span>{evidence.tool}</span>
        <span class="deck-investigation-redacted">{t("deck.investigation.redacted")}</span>
        <Tooltip content={copied ? t("deck.tooltip.copied") : t("deck.investigation.copyCommand")}>
          <button
            type="button"
            class="deck-investigation-copy-command"
            onClick={copyCommand}
            aria-label={t("deck.investigation.copyCommand")}
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
            <span>{t("deck.investigation.outputLogs")}</span>
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
  running,
}: {
  readonly activities: readonly InvestigationActivity[];
  readonly running: boolean;
}) {
  return (
    <section class="deck-investigation" aria-label={t("deck.investigation.label")}>
      <header class="deck-investigation-head">
        <strong>{t("deck.investigation.title")}</strong>
        <span class="muted">
          {running ? t("deck.investigation.running") : t("deck.investigation.finished")}
        </span>
      </header>
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
              <div class="deck-investigation-summary">
                <span class="deck-investigation-state" aria-hidden="true">
                  {statusMark(activity.status)}
                </span>
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
    </section>
  );
}
