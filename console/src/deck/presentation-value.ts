const RFC3339_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export interface PresentationTimestamp {
  readonly kind: "timestamp";
  readonly date: string;
  readonly time: string;
  readonly dateTime: string;
}

export interface PresentationActors {
  readonly visible: readonly string[];
  readonly hiddenCount: number;
}

export function presentationTimestamp(
  value: string,
  locale?: string,
  timeZone = resolvedTimeZone(),
): PresentationTimestamp | null {
  if (!RFC3339_TIMESTAMP.test(value)) return null;
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return null;
  const date = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone,
  }).format(instant);
  const clock = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone,
  }).format(instant);
  return {
    kind: "timestamp",
    date,
    time: `${clock} ${presentationTimeZoneLabel(timeZone)}`,
    dateTime: value,
  };
}

export function presentationDuration(start: string, end: string): string | null {
  if (!RFC3339_TIMESTAMP.test(start) || !RFC3339_TIMESTAMP.test(end)) return null;
  const milliseconds = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return null;
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}h ${minutes}m ${seconds}s`
    : minutes > 0
    ? `${minutes}m ${seconds}s`
    : `${seconds}s`;
}

export function presentationActors(value: string, limit = 2): PresentationActors {
  const actors = value.split(",").map((actor) => actor.trim()).filter(Boolean);
  return {
    visible: actors.slice(0, Math.max(1, limit)),
    hiddenCount: Math.max(0, actors.length - Math.max(1, limit)),
  };
}

export function presentationActor(value: string): string {
  if (!value.includes(".") && !value.includes("_") && !value.includes("-")) return value;
  const normalized = value
    .replace(/^fdai(?:\.core)?\./, "")
    .replace(/^notifications?\.(?=hil(?:[._-]|$))/, "")
    .replace(/[._-]+/g, " ")
    .replace(/\b(?:hil)\b/gi, "approval")
    .replace(/\s+/g, " ")
    .trim();
  return normalized
    ? normalized.replace(/\b\w/g, (letter) => letter.toUpperCase())
    : value;
}

export function presentationSeverity(value: string): string {
  const sev = /^sev(?:erity)?\s*[-_]?\s*(\d+)$/i.exec(value.trim());
  if (sev) return `SEV ${sev[1]}`;
  return presentationActivity(value);
}

export function presentationTimeZoneLabel(timeZone = resolvedTimeZone()): string {
  if (timeZone === "Asia/Seoul") return "KST";
  if (timeZone === "UTC" || timeZone === "Etc/UTC") return "UTC";
  return timeZone;
}

export function presentationActivity(value: string): string {
  const words = value.trim().replace(/[._-]+/g, " ").replace(/\s+/g, " ");
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : value;
}

function resolvedTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}
