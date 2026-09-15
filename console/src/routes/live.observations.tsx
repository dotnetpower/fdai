import type {
  AgentOperationalActivityV13Message,
  AgentOperationalActivityMessage,
} from "../agent-operational-activity";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import { useContentUpdatePulse } from "../hooks/use-content-update-pulse";
import { t as appT } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTime } from "../time-format";
import { t } from "./i18n/live";
import { LiveDetailShell } from "./live.detail-shell";

export const LIVE_OBSERVATION_LIMIT = 500;

export type LiveObservationLoadState = "loading" | "ready" | "unavailable" | "error";
export type LiveObservationPresentation =
  | "loading"
  | "items"
  | "waiting"
  | "unavailable"
  | "error"
  | "empty";

export function liveObservationPresentation(
  loadState: LiveObservationLoadState,
  streamStatus: LiveConnectionStatus,
  itemCount: number,
): LiveObservationPresentation {
  if (itemCount > 0) return "items";
  if (loadState === "loading") return "loading";
  if (loadState === "error") return "error";
  if (loadState === "unavailable") {
    return streamStatus === "open" ? "waiting" : "unavailable";
  }
  return "empty";
}

export function mergeLiveObservations(
  current: readonly AgentOperationalActivityMessage[],
  incoming: readonly AgentOperationalActivityMessage[],
  limit = LIVE_OBSERVATION_LIMIT,
  pinnedActivityId: string | null = null,
): readonly AgentOperationalActivityMessage[] {
  if (!Number.isInteger(limit) || limit < 1) {
    throw new Error("Live observation limit MUST be a positive integer");
  }
  const activityKey = (item: AgentOperationalActivityMessage) =>
    item.activity_instance_id ?? item.activity_id;
  const byActivity = new Map(current.map((item) => [activityKey(item), item]));
  incoming.forEach((item) => {
    const key = activityKey(item);
    const previous = byActivity.get(key);
    const incomingAt = Date.parse(item.observed_at);
    const previousAt = previous ? Date.parse(previous.observed_at) : Number.NEGATIVE_INFINITY;
    if (
      !previous ||
      incomingAt > previousAt ||
      incomingAt === previousAt && lifecycleRank(item) >= lifecycleRank(previous)
    ) {
      byActivity.set(
        key,
        isV13(item) && item.started_at === null && previous?.started_at
          ? { ...item, started_at: previous.started_at }
          : item,
      );
    }
  });
  const ordered = [...byActivity.values()]
    .sort((left, right) => Date.parse(right.observed_at) - Date.parse(left.observed_at));
  const visible = ordered.slice(0, limit);
  if (
    pinnedActivityId === null
    || visible.some((item) => activityKey(item) === pinnedActivityId)
  ) {
    return visible;
  }
  const pinned = byActivity.get(pinnedActivityId);
  if (!pinned) return visible;
  return [...visible.slice(0, Math.max(0, limit - 1)), pinned]
    .sort((left, right) => Date.parse(right.observed_at) - Date.parse(left.observed_at));
}

function activityLabel(item: AgentOperationalActivityMessage): string {
  if (isV13(item)) {
    return t(`live.observations.summary.${item.summary_key}`);
  }
  if (item.observation_domain) {
    return appT(`agentActivity.observationDomain.${item.observation_domain}`);
  }
  return appT(`agentActivity.log.lane.${item.kind}`);
}

/** Return the operator-facing observation title without exposing a machine identifier. */
export function activityTitle(item: AgentOperationalActivityMessage): string {
  if (item.observation_domain) {
    return t("live.observations.observationTitle", {
      domain: appT(`agentActivity.observationDomain.${item.observation_domain}`),
    });
  }
  return activityLabel(item);
}

function activityContext(item: AgentOperationalActivityMessage): string {
  if (isV13(item)) {
    return t(`live.observations.scope.${item.scope_class}`);
  }
  return item.source;
}

export function activityResultLabel(item: AgentOperationalActivityMessage): string {
  if (!isV13(item)) {
    return item.evidence_count > 0
      ? t("live.observations.result.measured", {
          count: item.evidence_count.toLocaleString(),
          unit: t("live.observations.unit.evidence-items"),
        })
      : t("live.observations.result.not-recorded");
  }
  if (item.result_state !== "measured") {
    return t(`live.observations.result.${item.result_state}`);
  }
  return t("live.observations.result.measured", {
    count: item.result_count.toLocaleString(),
    unit: t(`live.observations.unit.${item.result_unit}`),
  });
}

export function activityDurationLabel(durationMs: number | null): string {
  if (durationMs === null) return t("live.observations.duration.notRecorded");
  if (durationMs < 1_000) {
    return t("live.observations.duration.milliseconds", {
      count: durationMs.toLocaleString(),
    });
  }
  if (durationMs < 60_000) {
    return t("live.observations.duration.seconds", {
      count: (durationMs / 1_000).toLocaleString(undefined, {
        maximumFractionDigits: 1,
      }),
    });
  }
  return t("live.observations.duration.minutes", {
    count: (durationMs / 60_000).toLocaleString(undefined, {
      maximumFractionDigits: 1,
    }),
  });
}

function isV13(
  item: AgentOperationalActivityMessage,
): item is AgentOperationalActivityV13Message {
  return item.schema_version === "1.3.0";
}

function lifecycleRank(item: AgentOperationalActivityMessage): number {
  const ranks = {
    started: 0,
    superseded: 1,
    degraded: 2,
    failed: 3,
    completed: 4,
  } as const;
  return ranks[item.status];
}

/** Pulse changed source facts, not timestamps, elapsed time, or card selection. */
export function liveObservationUpdateKey(item: AgentOperationalActivityMessage): string {
  return [
    item.activity_instance_id ?? item.activity_id,
    item.status,
    item.freshness,
    item.owner_agent,
    item.observation_domain,
    item.reason_codes.join(","),
    isV13(item)
      ? [item.summary_key, item.scope_class, item.result_state, item.result_count, item.result_unit].join(":")
      : item.evidence_count,
  ].join("|");
}

/** Render one source-read activity using the same visual slots as control-loop work. */
export function LiveObservationCard({
  item,
  selected,
  onSelect,
}: {
  readonly item: AgentOperationalActivityMessage;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  const contentUpdated = useContentUpdatePulse(liveObservationUpdateKey(item));
  return (
    <button
      type="button"
      class={`live-observation-item live-work-card${contentUpdated ? " is-content-updated" : ""}`}
      data-status={item.status}
      data-selected={selected ? "1" : "0"}
      aria-expanded={selected}
      aria-haspopup="dialog"
      aria-controls="live-observation-detail-panel"
      aria-label={t("live.observations.cardLabel", {
        activity: activityTitle(item),
      })}
      onClick={onSelect}
    >
      <span class="live-tile-top">
        <span class="live-activity-kind">{t("live.observations.kindBadge")}</span>
        <span class={`live-observation-status is-${item.status}`}>
          {t(`live.observations.status.${item.status}`)}
        </span>
      </span>
      <strong class="live-tile-action">{activityTitle(item)}</strong>
      <span class="live-tile-target">
        {activityContext(item)} · {item.owner_agent}
      </span>
      <span class="live-tile-reason">{activityResultLabel(item)}</span>
      {item.reason_codes.length > 0 ? (
        <span class="live-observation-reason">
          {t("live.observations.reasonRecorded", {
            count: item.reason_codes.length,
          })}
        </span>
      ) : null}
      <span class="live-observation-meta">
        <span>{t(`live.observations.freshness.${item.freshness}`)}</span>
        <span>{activityDurationLabel(item.duration_ms)}</span>
        <time dateTime={item.observed_at}>{formatConsoleTime(item.observed_at)}</time>
      </span>
    </button>
  );
}

export function LiveObservationDetailPanel({
  item,
  onClose,
}: {
  readonly item: AgentOperationalActivityMessage;
  readonly onClose: () => void;
}) {
  const notObserved = t("live.control.notObserved");
  return (
    <LiveDetailShell
      panelId="live-observation-detail-panel"
      titleId="live-observation-detail-title"
      heading={activityTitle(item)}
      closeLabel={t("live.detail.close")}
      onClose={onClose}
    >
      <p class="live-detail-boundary">
        <strong>{t("live.observations.detail.boundaryTitle")}</strong>
        <span>{t("live.observations.detail.readOnly")}</span>
      </p>
      <section class="live-detail-section" aria-labelledby="live-observation-summary-heading">
        <h3 id="live-observation-summary-heading">
          {t("live.observations.detail.summaryHeading")}
        </h3>
        <dl class="live-detail-list">
          <dt>{t("live.observations.detail.summary")}</dt>
          <dd>{activityTitle(item)}</dd>
          <dt>{t("live.observations.detail.status")}</dt>
          <dd>{t(`live.observations.status.${item.status}`)}</dd>
          {isV13(item) ? (
            <>
              <dt>{t("live.observations.detail.scope")}</dt>
              <dd>{t(`live.observations.scope.${item.scope_class}`)}</dd>
            </>
          ) : null}
          <dt>{t("live.observations.detail.domain")}</dt>
          <dd>
            {item.observation_domain
              ? appT(`agentActivity.observationDomain.${item.observation_domain}`)
              : notObserved}
          </dd>
          <dt>{t("live.observations.detail.owner")}</dt>
          <dd>{item.owner_agent}</dd>
        </dl>
      </section>
      <section class="live-detail-section" aria-labelledby="live-observation-result-heading">
        <h3 id="live-observation-result-heading">
          {t("live.observations.detail.resultHeading")}
        </h3>
        <dl class="live-detail-list">
          <dt>{t("live.observations.detail.result")}</dt>
          <dd>{activityResultLabel(item)}</dd>
          {isV13(item) && item.target_count !== null ? (
            <>
              <dt>{t("live.observations.detail.targetCount")}</dt>
              <dd>{item.target_count.toLocaleString()}</dd>
            </>
          ) : null}
          <dt>{t("live.observations.detail.source")}</dt>
          <dd><code>{item.source}</code></dd>
          {item.reason_codes.length > 0 ? (
            <>
              <dt>{t("live.observations.detail.reasonCodes")}</dt>
              <dd>{item.reason_codes.join(", ")}</dd>
            </>
          ) : null}
        </dl>
      </section>
      <section class="live-detail-section" aria-labelledby="live-observation-timing-heading">
        <h3 id="live-observation-timing-heading">
          {t("live.observations.detail.timingHeading")}
        </h3>
        <dl class="live-detail-list">
          <dt>{t("live.observations.detail.freshness")}</dt>
          <dd>{t(`live.observations.freshness.${item.freshness}`)}</dd>
          <dt>{t("live.observations.detail.duration")}</dt>
          <dd>{activityDurationLabel(item.duration_ms)}</dd>
          <dt>{t("live.observations.detail.observedAt")}</dt>
          <dd><time dateTime={item.observed_at}>{formatConsoleTime(item.observed_at)}</time></dd>
          {isV13(item) ? (
            <>
              <dt>{t("live.observations.detail.sourceCutoff")}</dt>
              <dd>
                {item.source_cutoff
                  ? <time dateTime={item.source_cutoff}>{formatConsoleTime(item.source_cutoff)}</time>
                  : notObserved}
              </dd>
              <dt>{t("live.observations.detail.startedAt")}</dt>
              <dd>
                {item.started_at
                  ? <time dateTime={item.started_at}>{formatConsoleTime(item.started_at)}</time>
                  : notObserved}
              </dd>
              <dt>{t("live.observations.detail.completedAt")}</dt>
              <dd>
                {item.completed_at
                  ? <time dateTime={item.completed_at}>{formatConsoleTime(item.completed_at)}</time>
                  : notObserved}
              </dd>
            </>
          ) : null}
        </dl>
      </section>
      <details class="live-detail-technical">
        <summary>{t("live.observations.detail.technicalHeading")}</summary>
        <dl class="live-detail-list">
          {isV13(item) ? (
            <>
              <dt>{t("live.observations.detail.instanceId")}</dt>
              <dd><code>{item.activity_instance_id}</code></dd>
            </>
          ) : null}
          <dt>{t("live.observations.detail.activityId")}</dt>
          <dd><code>{item.activity_id}</code></dd>
          <dt>{t("live.observations.detail.kind")}</dt>
          <dd>{appT(`agentActivity.log.lane.${item.kind}`)}</dd>
          <dt>{t("live.observations.detail.producer")}</dt>
          <dd><code>{item.producer}</code></dd>
          <dt>{t("live.observations.detail.correlationId")}</dt>
          <dd>{item.correlation_id ? <code>{item.correlation_id}</code> : notObserved}</dd>
        </dl>
      </details>
      <section class="live-detail-section" aria-labelledby="live-observation-authority-heading">
        <h3 id="live-observation-authority-heading">
          {t("live.observations.detail.authorityHeading")}
        </h3>
        <dl class="live-detail-list">
          <dt>{t("live.observations.detail.authority")}</dt>
          <dd>{t("live.scope.readOnly")}</dd>
        </dl>
      </section>
      <div class="live-detail-actions">
        <a class="btn" href={routeHref("agent-activity")}>
          {t("live.observations.openActivity")}
        </a>
      </div>
    </LiveDetailShell>
  );
}
