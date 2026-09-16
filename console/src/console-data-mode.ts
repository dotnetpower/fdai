export type ConsoleDataMode = "live" | "sample";

const SAMPLE_PARAM = "data";
const SAMPLE_STORAGE_KEY = "fdai:console:data-mode";
const SAMPLE_PANEL_IDS = new Set([
  "dashboard",
  "live",
  "incidents",
  "audit",
  "trace",
  "rca",
  "hil-queue",
  "provision",
  "onboarding",
  "detection-readiness",
  "configuration-baselines",
  "processes",
  "workflow-apps",
  "scheduler-runs",
  "background-tasks",
  "automation-blueprints",
  "scheduled-continuations",
  "conversation-delivery",
  "operating-outcomes",
  "control-assurance",
  "verticals",
  "trust-routing",
  "llm-cost",
  "cost-governance",
]);

export function supportsSampleData(panelId: string): boolean {
  return SAMPLE_PANEL_IDS.has(panelId);
}

export function consoleDataMode(
  panelId: string,
  search: URLSearchParams,
  preferred: ConsoleDataMode = "live",
): ConsoleDataMode {
  return supportsSampleData(panelId) &&
      (search.get(SAMPLE_PARAM) === "sample" || preferred === "sample")
    ? "sample"
    : "live";
}

export function consoleDataModeHref(
  mode: ConsoleDataMode,
  pathname: string,
  search: string,
): string {
  const params = new URLSearchParams(search);
  if (mode === "sample") params.set(SAMPLE_PARAM, "sample");
  else params.delete(SAMPLE_PARAM);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function readConsoleDataMode(): ConsoleDataMode {
  if (typeof sessionStorage === "undefined") return "live";
  return sessionStorage.getItem(SAMPLE_STORAGE_KEY) === "sample" ? "sample" : "live";
}

export function writeConsoleDataMode(mode: ConsoleDataMode): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(SAMPLE_STORAGE_KEY, mode);
}
