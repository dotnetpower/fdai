import { getLocale } from "./i18n";

export function isRfc3339Timestamp(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value));
}

export function formatConsoleTimestamp(value: string | null, empty = "-"): string {
  if (value === null) return empty;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(getLocale(), {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(parsed);
}

export function formatConsoleTime(
  value: string | null,
  timeZone = resolvedBrowserTimeZone(),
  empty = "-",
): string {
  if (value === null) return empty;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const locale = getLocale() === "ko" ? "ko-KR" : "en-GB";
  const time = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    timeZone,
  }).format(parsed);
  return `${time} ${timeZoneLabel(parsed, timeZone)}`;
}

function resolvedBrowserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function timeZoneLabel(value: Date, timeZone: string): string {
  if (timeZone === "Asia/Seoul") return "KST";
  if (timeZone === "UTC" || timeZone === "Etc/UTC" || timeZone === "Etc/GMT") return "UTC";
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "short",
  }).formatToParts(value).find((part) => part.type === "timeZoneName")?.value ?? timeZone;
}
