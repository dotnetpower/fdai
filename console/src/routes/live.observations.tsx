import type {
  AgentOperationalActivityV13Message,
  AgentOperationalActivityMessage,
} from "../agent-operational-activity";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import {
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
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
      byActivity.set(key, item);
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

function activityContext(item: AgentOperationalActivityMessage): string {
  if (item.observation_domain) {
    return appT(`agentActivity.observationDomain.${item.observation_domain}`);
  }
  if (isV13(item)) {
    return t(`live.observations.scope.${item.scope_class}`);
  }
  return item.owner_agent;
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

export function LiveObservations({
  items,
  loadState,
  streamStatus,
  streamSource,
  error,
  selectedActivityId,
  onSelect,
}: {
  readonly items: readonly AgentOperationalActivityMessage[];
  readonly loadState: LiveObservationLoadState;
  readonly streamStatus: LiveConnectionStatus;
  readonly streamSource: ObservationSource;
  readonly error: string | null;
  readonly selectedActivityId: string | null;
  readonly onSelect: (activityId: string | null) => void;
}) {
  const visible = items;
  const active = items.filter((item) => item.status === "started").length;
  const degraded = items.filter(
    (item) => item.status === "degraded" || item.status === "failed",
  ).length;
  const presentation = liveObservationPresentation(
    loadState,
    streamStatus,
    visible.length,
  );

  return (
    <section class="live-observations" aria-labelledby="live-observations-title">
      <div class="live-observations-toolbar">
        <div class="live-observations-identity">
          <strong id="live-observations-title">{t("live.observations.title")}</strong>
          <small>{t("live.observations.note")}</small>
        </div>
        <div class="live-observations-summary">
          <span>{t("live.observations.active", { count: active })}</span>
          <span>{t("live.observations.degraded", { count: degraded })}</span>
          <span>{t("live.observations.retained", { count: items.length })}</span>
          <span>
            {streamStatus === "open"
              ? observationSourceLabel(streamSource)
              : t(`live.status.${streamStatus}`)}
          </span>
          <a href={routeHref("agent-activity")}>{t("live.observations.openActivity")}</a>
        </div>
      </div>
      {presentation === "loading" ? (
        <div class="live-observation-grid" role="status" aria-busy="true">
          <span class="sr-only">{t("live.observations.loading")}</span>
          {Array.from({ length: 4 }, (_, index) => (
            <span key={index} class="live-observation-skeleton skeleton-shimmer" aria-hidden="true" />
          ))}
        </div>
      ) : presentation === "error" ? (
        <div class="live-observation-state is-error" role="alert">
          {t("live.observations.error", { error: error ?? t("live.control.notObserved") })}
        </div>
      ) : presentation === "waiting" ? (
        <div class="live-observation-state" role="status">
          {t("live.observations.waiting")}
        </div>
      ) : presentation === "unavailable" ? (
        <div class="live-observation-state" role="status">
          {t("live.observations.unavailable")}
        </div>
      ) : presentation === "empty" ? (
        <div class="live-observation-state" role="status">
          {t("live.observations.empty")}
        </div>
      ) : (
        <ul
          class="live-observation-grid"
          aria-label={t("live.observations.records", { count: visible.length })}
        >
          {visible.map((item) => (
            <li
              key={item.activity_instance_id ?? item.activity_id}
              class="live-observation-entry"
            >
              <button
                type="button"
                class="live-observation-item live-work-card"
                data-status={item.status}
                data-selected={
                  (item.activity_instance_id ?? item.activity_id) === selectedActivityId
                    ? "1"
                    : "0"
                }
                aria-expanded={
                  (item.activity_instance_id ?? item.activity_id) === selectedActivityId
                }
                aria-haspopup="dialog"
                aria-controls="live-observation-detail-panel"
                aria-label={t("live.observations.cardLabel", {
                  activity: activityLabel(item),
                })}
                onClick={() => onSelect(
                  (item.activity_instance_id ?? item.activity_id) === selectedActivityId
                    ? null
                    : (item.activity_instance_id ?? item.activity_id),
                )}
              >
                <span class="live-observation-topline">
                  <strong>{activityLabel(item)}</strong>
                  <span class={`live-observation-status is-${item.status}`}>
                    {t(`live.observations.status.${item.status}`)}
                  </span>
                </span>
                <span class="live-observation-detail">
                  {activityContext(item)} · {item.owner_agent}
                </span>
                <span class="live-observation-result">{activityResultLabel(item)}</span>
                {item.reason_codes.length > 0 ? (
                  <span class="live-observation-reason">
                    <code>{item.reason_codes[0]}</code>
                    {item.reason_codes.length > 1
                      ? t("live.observations.reasonMore", {
                          count: item.reason_codes.length - 1,
                        })
                      : null}
                  </span>
                ) : null}
                <span class="live-observation-meta">
                  <span>
                    {t(`live.observations.freshness.${item.freshness}`)}
                    {" · "}
                    {activityDurationLabel(item.duration_ms)}
                  </span>
                  <time dateTime={item.observed_at}>{formatConsoleTime(item.observed_at)}</time>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
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
      title={activityLabel(item)}
      closeLabel={t("live.detail.close")}
      onClose={onClose}
    >
      <dl class="live-detail-list">
        {isV13(item) ? (
          <>
            <dt>{t("live.observations.detail.instanceId")}</dt>
            <dd><code>{item.activity_instance_id}</code></dd>
            <dt>{t("live.observations.detail.summary")}</dt>
            <dd>{activityLabel(item)}</dd>
            <dt>{t("live.observations.detail.scope")}</dt>
            <dd>{t(`live.observations.scope.${item.scope_class}`)}</dd>
          </>
        ) : null}
        <dt>{t("live.observations.detail.activityId")}</dt>
        <dd><code>{item.activity_id}</code></dd>
        <dt>{t("live.observations.detail.kind")}</dt>
        <dd>{appT(`agentActivity.log.lane.${item.kind}`)}</dd>
        <dt>{t("live.observations.detail.status")}</dt>
        <dd>{t(`live.observations.status.${item.status}`)}</dd>
        <dt>{t("live.observations.detail.owner")}</dt>
        <dd>{item.owner_agent}</dd>
        <dt>{t("live.observations.detail.producer")}</dt>
        <dd><code>{item.producer}</code></dd>
        <dt>{t("live.observations.detail.domain")}</dt>
        <dd>
          {item.observation_domain
            ? appT(`agentActivity.observationDomain.${item.observation_domain}`)
            : notObserved}
        </dd>
        <dt>{t("live.observations.detail.observedAt")}</dt>
        <dd><time dateTime={item.observed_at}>{formatConsoleTime(item.observed_at)}</time></dd>
        <dt>{t("live.observations.detail.source")}</dt>
        <dd><code>{item.source}</code></dd>
        <dt>{t("live.observations.detail.freshness")}</dt>
        <dd>{t(`live.observations.freshness.${item.freshness}`)}</dd>
        <dt>{t("live.observations.detail.result")}</dt>
        <dd>{activityResultLabel(item)}</dd>
        {isV13(item) && item.target_count !== null ? (
          <>
            <dt>{t("live.observations.detail.targetCount")}</dt>
            <dd>{item.target_count.toLocaleString()}</dd>
          </>
        ) : null}
        <dt>{t("live.observations.detail.duration")}</dt>
        <dd>{activityDurationLabel(item.duration_ms)}</dd>
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
        <dt>{t("live.observations.detail.correlationId")}</dt>
        <dd>{item.correlation_id ? <code>{item.correlation_id}</code> : notObserved}</dd>
        {item.reason_codes.length > 0 ? (
          <>
            <dt>{t("live.observations.detail.reasonCodes")}</dt>
            <dd>{item.reason_codes.join(", ")}</dd>
          </>
        ) : null}
        <dt>{t("live.observations.detail.authority")}</dt>
        <dd>{t("live.scope.readOnly")}</dd>
      </dl>
      <p class="muted live-detail-note">
        {t("live.observations.detail.readOnly")}
      </p>
    </LiveDetailShell>
  );
}
