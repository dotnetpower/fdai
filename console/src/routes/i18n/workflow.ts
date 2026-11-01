import { getLocale, t as mainT } from "../../i18n";
import { formatConsoleTimestamp } from "../../time-format";
import en from "./workflow.en.json";
import ko from "./workflow.ko.json";

type Catalog = Record<string, unknown>;

const CATALOGS: Record<"en" | "ko", Catalog> = { en, ko };

const STATUS_KEYS: Readonly<Record<string, string>> = {
  critical: "workflow.status.critical",
  high: "workflow.status.high",
  medium: "workflow.status.medium",
  low: "workflow.status.low",
  info: "workflow.status.info",
  ok: "workflow.status.ok",
  warn: "workflow.status.warn",
  warning: "workflow.status.warn",
  fail: "workflow.status.fail",
  unknown: "workflow.status.unknown",
  healthy: "workflow.status.healthy",
  degraded: "workflow.status.degraded",
  unhealthy: "workflow.status.unhealthy",
  shadow: "workflow.status.shadow",
  enforce: "workflow.status.enforce",
  pending: "workflow.status.pending",
  running: "workflow.status.running",
  waiting: "workflow.status.waiting",
  succeeded: "workflow.status.succeeded",
  failed: "workflow.status.failed",
  skipped: "workflow.status.skipped",
  cancelled: "workflow.status.cancelled",
  draft: "workflow.status.draft",
  published: "workflow.status.published",
  retired: "workflow.status.retired",
  compensated: "workflow.status.compensated",
  timed_out: "workflow.status.timed_out",
  compensating: "workflow.status.compensating",
};

const TRIGGER_KEYS: Readonly<Record<string, string>> = {
  deck_open: "workflow.automations.deckOpen",
  schedule: "workflow.automations.schedule",
  signal: "workflow.automations.signal",
};

function localeTag(): "en-US" | "ko-KR" {
  return getLocale() === "ko" ? "ko-KR" : "en-US";
}

function lookup(catalog: Catalog, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.replace(/^workflow\./, "").split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
}

export function t(key: string, params?: Record<string, string | number>): string {
  const template = lookup(CATALOGS[getLocale()], key) ?? lookup(en, key);
  if (template === undefined) return mainT(key, params);
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export function formatNumber(value: number): string {
  return value.toLocaleString(localeTag());
}

export function formatDateTime(value: string | number | Date): string {
  if (typeof value === "string") return formatConsoleTimestamp(value);
  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : formatConsoleTimestamp(parsed.toISOString());
}

export function formatDateTimeValue(value: unknown): string {
  if (typeof value !== "string" && typeof value !== "number" && !(value instanceof Date)) {
    return value === null || value === undefined ? "-" : String(value);
  }
  return formatDateTime(value);
}

export function formatCurrency(value: number, currency: string): string {
  return new Intl.NumberFormat(localeTag(), { style: "currency", currency }).format(value);
}

export function statusLabel(value: string): string {
  const key = STATUS_KEYS[value];
  return key === undefined ? value : t(key);
}

export function triggerLabel(value: string): string {
  const key = TRIGGER_KEYS[value];
  return key === undefined ? value : t(key);
}
