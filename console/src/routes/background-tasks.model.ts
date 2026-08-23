import { formatConsoleTimestamp } from "../time-format";
import {
  panelArray,
  panelBoolean,
  panelNumber,
  panelRecord,
  panelString,
} from "./panel-decode";

export type BackgroundTaskStatus =
  | "queued"
  | "claimed"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "unknown";

export interface BackgroundTaskItem {
  readonly task_id: string;
  readonly attempt_id: string;
  readonly request_summary: string | null;
  readonly request_truncated: boolean;
  readonly accountable_agent: string | null;
  readonly execution_worker: string;
  readonly kind: string;
  readonly status: BackgroundTaskStatus;
  readonly revision: number;
  readonly created_at: string;
  readonly updated_at: string;
  readonly retention_until: string;
  readonly lease_expires_at: string | null;
  readonly budget: Readonly<Record<string, unknown>>;
  readonly usage: Readonly<Record<string, unknown>>;
  readonly result_summary: string | null;
  readonly result_truncated: boolean;
  readonly evidence_refs: readonly string[];
  readonly evidence_truncated: boolean;
  readonly terminal_reason: string | null;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly duration_seconds: number | null;
  readonly completion_state: string | null;
}

export interface BackgroundTaskCursor {
  readonly before_updated_at: string;
  readonly before_task_id: string;
}

export interface BackgroundTaskPage {
  readonly tasks: readonly BackgroundTaskItem[];
  readonly has_more: boolean;
  readonly next_cursor: BackgroundTaskCursor | null;
}

export interface BackgroundTaskProgressItem {
  readonly sequence: number;
  readonly kind: string;
  readonly message: string;
  readonly at: string;
  readonly usage: Readonly<Record<string, unknown>>;
}

export interface BackgroundTaskProgressPage {
  readonly task_id: string;
  readonly status: BackgroundTaskStatus;
  readonly events: readonly BackgroundTaskProgressItem[];
  readonly next_sequence: number;
  readonly has_more: boolean;
}

const STATUSES: readonly BackgroundTaskStatus[] = [
  "queued",
  "claimed",
  "running",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
  "unknown",
];

export function decodeBackgroundTaskPage(value: unknown): BackgroundTaskPage {
  const root = panelRecord(value, "background tasks");
  const cursorValue = root["next_cursor"];
  const cursor = cursorValue === null
    ? null
    : decodeCursor(cursorValue, "background tasks.next_cursor");
  const hasMore = panelBoolean(root, "has_more", "background tasks");
  if (hasMore !== (cursor !== null)) {
    throw new Error("background tasks cursor MUST match has_more");
  }
  return {
    tasks: panelArray(root["tasks"], "background tasks.tasks").map((item, index) =>
      decodeTask(item, `background tasks.tasks[${index}]`)
    ),
    has_more: hasMore,
    next_cursor: cursor,
  };
}

export function decodeBackgroundTaskDetail(value: unknown): BackgroundTaskItem {
  const root = panelRecord(value, "background task detail");
  return decodeTask(root["task"], "background task detail.task");
}

export function decodeBackgroundTaskProgress(value: unknown): BackgroundTaskProgressPage {
  const root = panelRecord(value, "background task progress");
  const events = panelArray(root["events"], "background task progress.events").map(
    (item, index) => {
      const label = `background task progress.events[${index}]`;
      const record = panelRecord(item, label);
      return {
        sequence: nonNegativeInteger(record, "sequence", label),
        kind: panelString(record, "kind", label),
        message: panelString(record, "message", label),
        at: timestamp(record, "at", label),
        usage: panelRecord(record["usage"], `${label}.usage`),
      };
    },
  );
  for (let index = 1; index < events.length; index += 1) {
    if (events[index]!.sequence <= events[index - 1]!.sequence) {
      throw new Error("background task progress sequence MUST increase");
    }
  }
  return {
    task_id: panelString(root, "task_id", "background task progress"),
    status: status(root, "status", "background task progress"),
    events,
    next_sequence: integer(root, "next_sequence", "background task progress", -1),
    has_more: panelBoolean(root, "has_more", "background task progress"),
  };
}

export function appendBackgroundTaskPage(
  current: BackgroundTaskPage,
  requestedCursor: BackgroundTaskCursor,
  page: BackgroundTaskPage,
): BackgroundTaskPage {
  if (cursorKey(current.next_cursor) !== cursorKey(requestedCursor)) return current;
  const seen = new Set(current.tasks.map((task) => task.task_id));
  return {
    ...page,
    tasks: [...current.tasks, ...page.tasks.filter((task) => !seen.has(task.task_id))],
  };
}

export function backgroundTaskTone(
  value: BackgroundTaskStatus,
): "neutral" | "success" | "warning" | "danger" {
  if (value === "succeeded") return "success";
  if (value === "failed" || value === "timed_out" || value === "unknown") return "danger";
  if (value === "cancelled") return "neutral";
  return "warning";
}

export function formatBackgroundTaskTimestamp(value: string | null): string {
  return formatConsoleTimestamp(value);
}

function decodeTask(value: unknown, label: string): BackgroundTaskItem {
  const record = panelRecord(value, label);
  return {
    task_id: panelString(record, "task_id", label),
    attempt_id: panelString(record, "attempt_id", label),
    request_summary: optionalBoundedString(record, "request_summary", label, 500),
    request_truncated: optionalBoolean(record, "request_truncated", label),
    accountable_agent: optionalBoundedString(record, "accountable_agent", label, 256),
    execution_worker: optionalBoundedString(record, "execution_worker", label, 256)
      ?? "background-task-coordinator",
    kind: panelString(record, "kind", label),
    status: status(record, "status", label),
    revision: positiveInteger(record, "revision", label),
    created_at: timestamp(record, "created_at", label),
    updated_at: timestamp(record, "updated_at", label),
    retention_until: timestamp(record, "retention_until", label),
    lease_expires_at: nullableTimestamp(record, "lease_expires_at", label),
    budget: panelRecord(record["budget"], `${label}.budget`),
    usage: panelRecord(record["usage"], `${label}.usage`),
    result_summary: optionalBoundedString(record, "result_summary", label, 2_000),
    result_truncated: optionalBoolean(record, "result_truncated", label),
    evidence_refs: optionalEvidenceRefs(record, label),
    evidence_truncated: optionalBoolean(record, "evidence_truncated", label),
    terminal_reason: nullableString(record, "terminal_reason", label),
    started_at: nullableTimestamp(record, "started_at", label),
    finished_at: nullableTimestamp(record, "finished_at", label),
    duration_seconds: nullableNonNegativeNumber(record, "duration_seconds", label),
    completion_state: nullableString(record, "completion_state", label),
  };
}

function decodeCursor(value: unknown, label: string): BackgroundTaskCursor {
  const record = panelRecord(value, label);
  return {
    before_updated_at: timestamp(record, "before_updated_at", label),
    before_task_id: panelString(record, "before_task_id", label),
  };
}

function status(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): BackgroundTaskStatus {
  const value = panelString(record, key, label);
  if (!STATUSES.includes(value as BackgroundTaskStatus)) {
    throw new Error(`${label}.${key} is invalid`);
  }
  return value as BackgroundTaskStatus;
}

function timestamp(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  const value = panelString(record, key, label);
  if (!Number.isFinite(Date.parse(value))) throw new Error(`${label}.${key} is invalid`);
  return value;
}

function nullableTimestamp(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  if (record[key] === null) return null;
  return timestamp(record, key, label);
}

function nullableString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  if (record[key] === null) return null;
  return panelString(record, key, label);
}

function optionalBoundedString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  maximum: number,
): string | null {
  if (record[key] === undefined || record[key] === null) return null;
  const value = panelString(record, key, label);
  if (value.length === 0 || value.length > maximum) {
    throw new Error(`${label}.${key} MUST be a bounded non-empty string`);
  }
  return value;
}

function optionalBoolean(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): boolean {
  if (record[key] === undefined) return false;
  return panelBoolean(record, key, label);
}

function optionalEvidenceRefs(
  record: Readonly<Record<string, unknown>>,
  label: string,
): readonly string[] {
  if (record["evidence_refs"] === undefined) return [];
  const value = panelArray(record["evidence_refs"], `${label}.evidence_refs`);
  if (
    value.length > 16
    || value.some((item) => typeof item !== "string" || item.length === 0 || item.length > 256)
  ) {
    throw new Error(`${label}.evidence_refs MUST contain at most 16 bounded strings`);
  }
  return value as readonly string[];
}

function nullableNonNegativeNumber(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (record[key] === null) return null;
  const value = panelNumber(record, key, label);
  if (value < 0) throw new Error(`${label}.${key} MUST be non-negative`);
  return value;
}

function integer(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  minimum: number,
): number {
  const value = panelNumber(record, key, label);
  if (!Number.isInteger(value) || value < minimum) {
    throw new Error(`${label}.${key} MUST be an integer >= ${minimum}`);
  }
  return value;
}

function positiveInteger(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  return integer(record, key, label, 1);
}

function nonNegativeInteger(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  return integer(record, key, label, 0);
}

function cursorKey(cursor: BackgroundTaskCursor | null): string {
  return cursor === null ? "" : `${cursor.before_updated_at}\u001f${cursor.before_task_id}`;
}
