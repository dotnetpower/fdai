import type { AgentOperationalActivityMessage } from "../agent-operational-activity";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import {
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
import { Tooltip } from "../components/tooltip";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import {
  isTileStuck,
  matchesFilter,
  type FilterKind,
  type TileState,
} from "./live.model";
import {
  LiveObservationCard,
  liveObservationPresentation,
  type LiveObservationLoadState,
} from "./live.observations";
import { LiveTile } from "./live.tiles";

export type LiveViewMode = "queue" | "flow";

export type LiveActivityItem =
  | {
      readonly kind: "control";
      readonly key: string;
      readonly observedAt: number;
      readonly tile: TileState;
    }
  | {
      readonly kind: "source";
      readonly key: string;
      readonly observedAt: number;
      readonly activity: AgentOperationalActivityMessage;
    };

export interface LiveActivityCounts {
  readonly all: number;
  readonly control: number;
  readonly source: number;
  readonly hil: number;
  readonly deny: number;
  readonly failed: number;
  readonly stuck: number;
}

export const LIVE_ACTIVITY_FILTERS: readonly FilterKind[] = [
  "all",
  "control",
  "source",
  "hil",
  "deny",
  "failed",
  "stuck",
];
export const LIVE_ACTIVITY_VISIBLE_LIMIT = 15;

/** Order both activity kinds by their immutable start time, never by lifecycle updates. */
export function composeLiveActivityItems(
  tiles: readonly TileState[],
  observations: readonly AgentOperationalActivityMessage[],
  filter: FilterKind,
  now: number,
): readonly LiveActivityItem[] {
  const controlItems = tiles
    .filter((tile) => matchesFilter(tile, filter, now))
    .map((tile): LiveActivityItem => ({
      kind: "control",
      key: `control:${tile.event_id}`,
      observedAt: parsedTime(tile.first_ts, tile.first_seen_at),
      tile,
    }));
  const sourceItems = filter === "all" || filter === "source"
    ? observations.map((activity): LiveActivityItem => ({
        kind: "source",
        key: `source:${activity.activity_instance_id ?? activity.activity_id}`,
        observedAt: parsedTime(activity.started_at ?? activity.observed_at),
        activity,
      }))
    : [];
  return [...controlItems, ...sourceItems].sort(
    (left, right) =>
      right.observedAt - left.observedAt || left.key.localeCompare(right.key),
  );
}

/** Count each visible activity class without treating source reads as decisions. */
export function liveActivityCounts(
  tiles: readonly TileState[],
  observations: readonly AgentOperationalActivityMessage[],
  now: number,
): LiveActivityCounts {
  return {
    all: tiles.length + observations.length,
    control: tiles.length,
    source: observations.length,
    hil: tiles.filter((tile) => tile.gate_decision === "hil").length,
    deny: tiles.filter((tile) => tile.gate_decision === "deny").length,
    failed: tiles.filter((tile) => tile.failed).length,
    stuck: tiles.filter((tile) => isTileStuck(tile, now)).length,
  };
}

/** Limit the card surface while retaining an explicitly selected deep link. */
export function visibleLiveActivityItems(
  items: readonly LiveActivityItem[],
  selectedKey: string | null,
  limit = LIVE_ACTIVITY_VISIBLE_LIMIT,
): readonly LiveActivityItem[] {
  if (!Number.isInteger(limit) || limit < 1) {
    throw new Error("Live activity visible limit MUST be a positive integer");
  }
  const visible = items.slice(0, limit);
  if (selectedKey === null || visible.some((item) => item.key === selectedKey)) {
    return visible;
  }
  const selected = items.find((item) => item.key === selectedKey);
  if (selected === undefined) return visible;
  return [...visible.slice(0, Math.max(0, limit - 1)), selected];
}

function parsedTime(value: string | undefined, fallback = 0): number {
  const timestamp = value === undefined ? Number.NaN : Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : fallback;
}

function emptyActivityMessage({
  filter,
  observationLoadState,
  observationStreamStatus,
  observationError,
  controlEmptyState,
  sample,
}: {
  readonly filter: FilterKind;
  readonly observationLoadState: LiveObservationLoadState;
  readonly observationStreamStatus: LiveConnectionStatus;
  readonly observationError: string | null;
  readonly controlEmptyState: string;
  readonly sample: boolean;
}): { readonly role: "alert" | "status"; readonly text: string } {
  if (filter !== "all" && filter !== "source") {
    return { role: "status", text: t("live.work.noMatch") };
  }
  if (sample && filter === "source") {
    return { role: "status", text: t("live.work.sampleSourceUnavailable") };
  }
  const presentation = liveObservationPresentation(
    observationLoadState,
    observationStreamStatus,
    0,
  );
  if (presentation === "loading") {
    return { role: "status", text: t("live.observations.loading") };
  }
  if (presentation === "error") {
    return {
      role: "alert",
      text: t("live.observations.error", {
        error: observationError ?? t("live.control.notObserved"),
      }),
    };
  }
  if (filter === "source") {
    const key = presentation === "waiting"
      ? "waiting"
      : presentation === "unavailable"
        ? "unavailable"
        : "empty";
    return { role: "status", text: t(`live.observations.${key}`) };
  }
  return { role: "status", text: controlEmptyState };
}

/** Render the shared card workspace while preserving each activity authority boundary. */
export function LiveActivityWorkspace({
  tiles,
  observations,
  observationLoadState,
  observationStreamStatus,
  observationStreamSource,
  observationError,
  sample,
  filter,
  viewMode,
  now,
  controlEmptyState,
  selectedEventId,
  selectedObservationId,
  onFilter,
  onViewMode,
  onSelectEvent,
  onSelectObservation,
}: {
  readonly tiles: readonly TileState[];
  readonly observations: readonly AgentOperationalActivityMessage[];
  readonly observationLoadState: LiveObservationLoadState;
  readonly observationStreamStatus: LiveConnectionStatus;
  readonly observationStreamSource: ObservationSource;
  readonly observationError: string | null;
  readonly sample: boolean;
  readonly filter: FilterKind;
  readonly viewMode: LiveViewMode;
  readonly now: number;
  readonly controlEmptyState: string;
  readonly selectedEventId: string | null;
  readonly selectedObservationId: string | null;
  readonly onFilter: (filter: FilterKind) => void;
  readonly onViewMode: (view: LiveViewMode) => void;
  readonly onSelectEvent: (eventId: string | null) => void;
  readonly onSelectObservation: (activityId: string | null) => void;
}) {
  const counts = liveActivityCounts(tiles, observations, now);
  const orderedItems = composeLiveActivityItems(tiles, observations, filter, now);
  const selectedKey = selectedEventId !== null
    ? `control:${selectedEventId}`
    : selectedObservationId !== null
      ? `source:${selectedObservationId}`
      : null;
  const items = visibleLiveActivityItems(orderedItems, selectedKey);
  const empty = emptyActivityMessage({
    filter,
    observationLoadState,
    observationStreamStatus,
    observationError,
    controlEmptyState,
    sample,
  });
  const sourceWindow = sample
    ? t("live.work.sampleWindow")
    : t("live.work.currentWindow", {
        count: counts.all,
        visible: items.length,
        source: observationStreamStatus === "open"
          ? observationSourceLabel(observationStreamSource)
          : t(`live.status.${observationStreamStatus}`),
      });

  return (
    <section class="live-workspace" aria-labelledby="live-workspace-title">
      <header class="live-work-header">
        <div class="live-work-identity">
          <span class="live-eyebrow">{t("live.work.eyebrow")}</span>
          <h2 id="live-workspace-title">{t("live.work.title")}</h2>
          <small>{t("live.work.summary", {
            total: counts.all,
            control: counts.control,
            source: counts.source,
          })}</small>
        </div>
        <div class="live-filterbar" aria-label={t("live.work.filtersLabel")}>
          {LIVE_ACTIVITY_FILTERS.map((entry, index) => (
            <Tooltip
              key={entry}
              content={t("live.work.filterTitle", {
                filter: t(`live.filter.${entry}`),
                key: index + 1,
              })}
            >
              <button
                type="button"
                class={`live-filter-chip ${filter === entry ? "active" : ""}`}
                aria-pressed={filter === entry}
                aria-keyshortcuts={`${index + 1}`}
                onClick={() => onFilter(entry)}
              >
                {t(`live.filter.${entry}`)}
                <span class="live-filter-count">{counts[entry]}</span>
              </button>
            </Tooltip>
          ))}
        </div>
        <div class="live-work-actions">
          <div
            class="segmented-control"
            role="group"
            aria-label={t("live.work.viewModeLabel")}
          >
            {(["queue", "flow"] as const).map((mode) => (
              <button
                type="button"
                class={viewMode === mode ? "active" : undefined}
                aria-pressed={viewMode === mode}
                onClick={() => onViewMode(mode)}
              >
                {mode === "queue" ? t("live.work.queue") : t("live.work.flow")}
              </button>
            ))}
          </div>
        </div>
      </header>

      {items.length === 0 ? (
        <div
          class={`live-activity-state${empty.role === "alert" ? " is-error" : ""}`}
          role={empty.role}
        >
          {empty.text}
        </div>
      ) : (
        <ul
          class="live-activity-grid"
          data-view={viewMode}
          aria-label={t("live.work.activityLabel", { count: items.length })}
        >
          {items.map((entry) => (
            <li key={entry.key} class="live-activity-entry">
              {entry.kind === "control" ? (
                <LiveTile
                  tile={entry.tile}
                  filter="all"
                  selected={entry.tile.event_id === selectedEventId}
                  now={now}
                  onClick={() => onSelectEvent(
                    entry.tile.event_id === selectedEventId
                      ? null
                      : entry.tile.event_id,
                  )}
                />
              ) : (
                <LiveObservationCard
                  item={entry.activity}
                  selected={
                    (entry.activity.activity_instance_id ??
                      entry.activity.activity_id) === selectedObservationId
                  }
                  onSelect={() => onSelectObservation(
                    (entry.activity.activity_instance_id ??
                      entry.activity.activity_id) === selectedObservationId
                      ? null
                      : (entry.activity.activity_instance_id ??
                        entry.activity.activity_id),
                  )}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <footer class="live-work-footer">
        <span>{sourceWindow}</span>
        <a href={routeHref("agent-activity")}>{t("live.observations.openActivity")}</a>
      </footer>
    </section>
  );
}
