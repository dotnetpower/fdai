// Small formatting helpers. No i18n layer: this is a loopback operator tool for Lifecycle I0/I1,
// not a localized product surface (see lifecycle/hub/README.md § Limits).

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "medium",
});

export function formatTimestamp(iso: string | null, originZone?: string): string {
  if (iso === null) return "\u2013";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const formatted = dateTimeFormatter.format(date);
  return originZone ? `${formatted} (${originZone})` : formatted;
}

/** A short "N unit ago" / "in N unit" string, relative to `now` (defaults to the current time). */
export function formatRelative(iso: string | null, now: Date = new Date()): string {
  if (iso === null) return "\u2013";
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
      return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
        value,
        unit as Intl.RelativeTimeFormatUnit,
      );
    }
  }
  return "now";
}

export function formatDurationMinutes(minutes: number): string {
  if (minutes >= 1_440 && minutes % 1_440 === 0) {
    const days = minutes / 1_440;
    return days === 1 ? "1 day" : `${days} days`;
  }
  if (minutes >= 60 && minutes % 60 === 0) {
    const hours = minutes / 60;
    return hours === 1 ? "1 hour" : `${hours} hours`;
  }
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}
