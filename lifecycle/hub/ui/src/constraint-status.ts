// Whether a blocked candidate Release is waiting out something that resolves on its own (a
// closed maintenance window, an active suppression) or was rejected for a reason that won't
// change until someone acts (a recall, a schema or version mismatch, a missing artifact, data
// residency, an override block, a destructive change). These deserve different colors: the first
// is routine and expected, the second usually needs an operator's attention.
//
// This intentionally mirrors `TIMING_REASONS` in `lifecycle/hub/src/fdai_lifecycle_hub/planning.py`.
// Reason codes are a stable, canonical token shared across the Hub and this UI.
const TIMING_REASON_CODES = new Set([
  "maintenance_window_unavailable",
  "maintenance_window_invalid",
  "suppression_window_active",
  "suppression_window_invalid",
  "suppression_scope_invalid",
]);

export function isTimingReason(reasonCode: string): boolean {
  return TIMING_REASON_CODES.has(reasonCode);
}

export function constraintVerdict(check: CandidateCheck): "passed" | "waiting" | "blocked" {
  if (check.blocks.length === 0) return "passed";
  return check.blocks.every((block) => isTimingReason(block.reason_code)) ? "waiting" : "blocked";
}
import type { CandidateCheck } from "./api";
