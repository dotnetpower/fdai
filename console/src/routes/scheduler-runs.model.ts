import {
  panelArray,
  panelBoolean,
  panelNullableString,
  panelNumber,
  panelRecord,
  panelString,
} from "./panel-decode";
import { formatConsoleTimestamp } from "../time-format";

export type SchedulerRunStatus = "claimed" | "published" | "failed" | "lost";

export interface SchedulerRunItem {
  readonly run_id: string;
  readonly task_id: string;
  readonly scheduled_for: string;
  readonly claimed_at: string;
  readonly status: SchedulerRunStatus;
  readonly attempt: number;
  readonly completed_at: string | null;
  readonly error_kind: string | null;
}

export interface SchedulerRunPage {
  readonly task_id: string;
  readonly source: string;
  readonly durable: boolean;
  readonly items: readonly SchedulerRunItem[];
  readonly next_cursor: string | null;
}

export interface SchedulerRunSummary {
  readonly loaded: number;
  readonly published: number;
  readonly failedOrLost: number;
  readonly publishRate: number | null;
  readonly medianCloseMs: number | null;
  readonly p95CloseMs: number | null;
}

const RUN_STATUSES: readonly SchedulerRunStatus[] = ["claimed", "published", "failed", "lost"];

export function decodeSchedulerRunPage(value: unknown): SchedulerRunPage {
  const root = panelRecord(value, "scheduler runs");
  return {
    task_id: panelString(root, "task_id", "scheduler runs"),
    source: panelString(root, "source", "scheduler runs"),
    durable: panelBoolean(root, "durable", "scheduler runs"),
    items: panelArray(root["items"], "scheduler runs.items").map((item, index) => {
      const label = `scheduler runs.items[${index}]`;
      const record = panelRecord(item, label);
      const status = panelString(record, "status", label);
      if (!RUN_STATUSES.includes(status as SchedulerRunStatus)) {
        throw new Error(`${label}.status is invalid`);
      }
      return {
        run_id: panelString(record, "run_id", label),
        task_id: panelString(record, "task_id", label),
        scheduled_for: panelString(record, "scheduled_for", label),
        claimed_at: panelString(record, "claimed_at", label),
        status: status as SchedulerRunStatus,
        attempt: panelNumber(record, "attempt", label),
        completed_at: panelNullableString(record, "completed_at", label),
        error_kind: panelNullableString(record, "error_kind", label),
      };
    }),
    next_cursor: panelNullableString(root, "next_cursor", "scheduler runs"),
  };
}

export function appendSchedulerRunPage(
  current: SchedulerRunPage,
  requestedCursor: string,
  page: SchedulerRunPage,
): SchedulerRunPage {
  if (current.next_cursor !== requestedCursor || current.task_id !== page.task_id) return current;
  const seen = new Set(current.items.map((item) => `${item.run_id}:${item.attempt}`));
  return {
    ...page,
    items: [
      ...current.items,
      ...page.items.filter((item) => !seen.has(`${item.run_id}:${item.attempt}`)),
    ],
  };
}

export function schedulerRunTone(status: SchedulerRunStatus): "success" | "warning" | "danger" {
  if (status === "published") return "success";
  if (status === "claimed") return "warning";
  return "danger";
}

export function summarizeSchedulerRuns(
  items: readonly SchedulerRunItem[],
): SchedulerRunSummary {
  const published = items.filter((item) => item.status === "published").length;
  const failedOrLost = items.filter(
    (item) => item.status === "failed" || item.status === "lost",
  ).length;
  const durations = items.flatMap((item) => {
    if (item.completed_at === null) return [];
    const claimed = Date.parse(item.claimed_at);
    const completed = Date.parse(item.completed_at);
    if (!Number.isFinite(claimed) || !Number.isFinite(completed) || completed < claimed) return [];
    return [completed - claimed];
  }).sort((left, right) => left - right);
  return {
    loaded: items.length,
    published,
    failedOrLost,
    publishRate: items.length === 0 ? null : published / items.length,
    medianCloseMs: percentile(durations, 0.5),
    p95CloseMs: percentile(durations, 0.95),
  };
}

function percentile(values: readonly number[], quantile: number): number | null {
  if (values.length === 0) return null;
  const index = Math.min(values.length - 1, Math.ceil(values.length * quantile) - 1);
  return values[index] ?? null;
}

export function formatSchedulerTimestamp(value: string | null): string {
  return formatConsoleTimestamp(value);
}
