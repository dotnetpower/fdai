export type LlmUsageRangePreset = "24h" | "7d" | "30d" | "custom";

export interface LlmUsageRange {
  readonly preset: LlmUsageRangePreset;
  readonly from: string;
  readonly to: string;
}

const DAY_MS = 86_400_000;
const MAX_RANGE_DAYS = 90;

function utcDayStart(value: Date): Date {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate()));
}

function validRange(from: Date, to: Date): boolean {
  const duration = to.getTime() - from.getTime();
  return Number.isFinite(duration) && duration > 0 && duration <= MAX_RANGE_DAYS * DAY_MS;
}

export function presetLlmUsageRange(
  preset: Exclude<LlmUsageRangePreset, "custom">,
  now: Date,
): LlmUsageRange {
  if (preset === "24h") {
    return {
      preset,
      from: new Date(now.getTime() - DAY_MS).toISOString(),
      to: now.toISOString(),
    };
  }
  const days = preset === "7d" ? 7 : 30;
  const today = utcDayStart(now);
  const from = new Date(today.getTime() - (days - 1) * DAY_MS);
  const to = new Date(today.getTime() + DAY_MS);
  return { preset, from: from.toISOString(), to: to.toISOString() };
}

export function customLlmUsageRange(fromDate: string, toDate: string): LlmUsageRange | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(fromDate) || !/^\d{4}-\d{2}-\d{2}$/.test(toDate)) {
    return null;
  }
  const from = new Date(`${fromDate}T00:00:00.000Z`);
  const inclusiveEnd = new Date(`${toDate}T00:00:00.000Z`);
  const to = new Date(inclusiveEnd.getTime() + DAY_MS);
  if (!validRange(from, to)) return null;
  return { preset: "custom", from: from.toISOString(), to: to.toISOString() };
}

export function llmUsageRangeFromSearch(search: URLSearchParams, now: Date): LlmUsageRange {
  const rawFrom = search.get("from");
  const rawTo = search.get("to");
  if (rawFrom && rawTo) {
    const from = new Date(rawFrom);
    const to = new Date(rawTo);
    if (validRange(from, to)) {
      const rawPreset = search.get("range");
      const preset: LlmUsageRangePreset = rawPreset === "24h" || rawPreset === "7d" || rawPreset === "30d"
        ? rawPreset
        : "custom";
      return { preset, from: from.toISOString(), to: to.toISOString() };
    }
  }
  const rawPreset = search.get("range");
  if (rawPreset === "24h" || rawPreset === "30d") return presetLlmUsageRange(rawPreset, now);
  return presetLlmUsageRange("7d", now);
}

export function llmUsageRangeSearchParams(
  range: LlmUsageRange,
): Readonly<Record<string, string>> {
  return { range: range.preset, from: range.from, to: range.to };
}

export function llmUsageRangeApiParams(
  range: LlmUsageRange,
): Readonly<Record<string, string>> {
  return { from: range.from, to: range.to };
}

export function llmUsageRangeInputDates(range: LlmUsageRange): {
  readonly fromDate: string;
  readonly toDate: string;
} {
  return {
    fromDate: range.from.slice(0, 10),
    toDate: new Date(new Date(range.to).getTime() - 1).toISOString().slice(0, 10),
  };
}

export function llmUsageRangeDays(range: LlmUsageRange): number {
  return Math.round((new Date(range.to).getTime() - new Date(range.from).getTime()) / DAY_MS);
}

export function llmUsageRangeLabel(range: LlmUsageRange, locale: string): string {
  const from = new Date(range.from);
  const to = new Date(new Date(range.to).getTime() - 1);
  const options: Intl.DateTimeFormatOptions = range.preset === "24h"
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }
    : { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  const formatter = new Intl.DateTimeFormat(locale, options);
  return `${formatter.format(from)} - ${formatter.format(to)}`;
}
