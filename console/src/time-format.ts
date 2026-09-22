import { getLocale } from "./i18n";

const timeFormatters = new Map<string, Intl.DateTimeFormat>();
let browserTimeZone: string | undefined;

export function consoleDateTimeLocale(): "en-US" | "ko-KR" {
  return getLocale() === "ko" ? "ko-KR" : "en-US";
}

function cachedTimeFormatter(
  locale: string,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = JSON.stringify([locale, options]);
  const cached = timeFormatters.get(key);
  if (cached) return cached;
  const formatter = new Intl.DateTimeFormat(locale, options);
  if (timeFormatters.size >= 16) timeFormatters.clear();
  timeFormatters.set(key, formatter);
  return formatter;
}

/** Accept only calendar-valid RFC 3339 timestamps without Date.parse normalization. */
export function isRfc3339Timestamp(value: string): boolean {
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/,
  );
  if (match === null) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[8] === undefined ? 0 : Number(match[8]);
  const offsetMinute = match[9] === undefined ? 0 : Number(match[9]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [
    31,
    leapYear ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  return month >= 1
    && month <= 12
    && day >= 1
    && day <= daysInMonth[month - 1]!
    && hour <= 23
    && minute <= 59
    && second <= 59
    && offsetHour <= 23
    && offsetMinute <= 59
    && Number.isFinite(Date.parse(value));
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
  precision: "seconds" | "milliseconds" = "seconds",
): string {
  if (value === null) return empty;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const locale = getLocale() === "ko" ? "ko-KR" : "en-GB";
  const time = cachedTimeFormatter(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    ...(precision === "milliseconds" ? { fractionalSecondDigits: 3 as const } : {}),
    hourCycle: "h23",
    timeZone,
  }).format(parsed);
  return `${time} ${timeZoneLabel(parsed, timeZone)}`;
}

export function formatConsoleCompactTimestamp(
  value: string | null,
  timeZone = resolvedBrowserTimeZone(),
  empty = "-",
): string {
  if (value === null) return empty;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const locale = getLocale() === "ko" ? "ko-KR" : "en-GB";
  const dateTime = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone,
  }).format(parsed);
  return `${dateTime} ${timeZoneLabel(parsed, timeZone)}`;
}

function resolvedBrowserTimeZone(): string {
  browserTimeZone ??= Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  return browserTimeZone;
}

function timeZoneLabel(value: Date, timeZone: string): string {
  if (timeZone === "Asia/Seoul") return "KST";
  if (timeZone === "UTC" || timeZone === "Etc/UTC" || timeZone === "Etc/GMT") return "UTC";
  return cachedTimeFormatter("en-US", {
    timeZone,
    timeZoneName: "short",
  }).formatToParts(value).find((part) => part.type === "timeZoneName")?.value ?? timeZone;
}
