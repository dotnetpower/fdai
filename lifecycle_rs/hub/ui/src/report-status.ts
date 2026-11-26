// How an execution report's outcome should read to an operator: a plan report can be in progress,
// not just succeeded or failed. Conflating "apply-started" with success would misrepresent an
// unverified dispatch as a completed effect (see FDAI's effect-verified principle).

export type ReportSeverity = "ok" | "pending" | "fail";

const FAILED_OUTCOMES = new Set(["rejected", "rolled-back"]);
const PENDING_OUTCOMES = new Set(["apply-started"]);

export function reportSeverity(outcome: string): ReportSeverity {
  if (FAILED_OUTCOMES.has(outcome)) return "fail";
  if (PENDING_OUTCOMES.has(outcome)) return "pending";
  return "ok"; // dry-run-admitted, applied
}

const ICON_BY_SEVERITY: Record<ReportSeverity, string> = {
  ok: "✓",
  pending: "◷",
  fail: "✕",
};

/** The `.ic`/`.timeline li` modifier class this severity should render with. */
export function reportSeverityClass(severity: ReportSeverity): "ok" | "warn" | "fail" {
  return severity === "pending" ? "warn" : severity;
}

export function reportSeverityIcon(outcome: string): string {
  return ICON_BY_SEVERITY[reportSeverity(outcome)];
}
