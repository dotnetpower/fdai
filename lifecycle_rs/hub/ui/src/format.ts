// Small formatting helpers. No i18n layer: this is a loopback operator tool for Lifecycle I0/I1,
// not a localized product surface (see lifecycle/hub/README.md § Limits).

import type { HubLocale } from "./locale";

const dateTimeFormatterEn = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "medium",
});
const dateTimeFormatterKo = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "medium",
});

export function formatTimestamp(
  iso: string | null,
  originZone?: string,
  locale?: HubLocale,
): string {
  if (iso === null) return "\u2013";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const formatter = locale === "ko" ? dateTimeFormatterKo : dateTimeFormatterEn;
  const formatted = formatter.format(date);
  return originZone ? `${formatted} (${originZone})` : formatted;
}

/** A short "N unit ago" / "in N unit" string, relative to `now` (defaults to the current time). */
export function formatRelative(
  iso: string | null,
  now: Date = new Date(),
  locale?: HubLocale,
): string {
  if (iso === null || Number.isNaN(now.getTime())) return "\u2013";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diffSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const units: readonly [string, number][] = [
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
    ["second", 1],
  ];
  const absSeconds = Math.abs(diffSeconds);
  for (const [unit, secondsPerUnit] of units) {
    if (absSeconds >= secondsPerUnit || unit === "second") {
      const value = Math.round(diffSeconds / secondsPerUnit);
      return new Intl.RelativeTimeFormat(locale === "ko" ? "ko-KR" : undefined, {
        numeric: "auto",
      }).format(value, unit as Intl.RelativeTimeFormatUnit);
    }
  }
  return locale === "ko" ? "지금" : "now";
}

export function formatDurationMinutes(minutes: number, locale?: HubLocale): string {
  if (!Number.isFinite(minutes) || minutes < 0) return "\u2013";
  if (minutes >= 1_440 && minutes % 1_440 === 0) {
    const days = minutes / 1_440;
    if (locale === "ko") return `${days}일`;
    return days === 1 ? "1 day" : `${days} days`;
  }
  if (minutes >= 60 && minutes % 60 === 0) {
    const hours = minutes / 60;
    if (locale === "ko") return `${hours}시간`;
    return hours === 1 ? "1 hour" : `${hours} hours`;
  }
  if (locale === "ko") return `${minutes}분`;
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}
