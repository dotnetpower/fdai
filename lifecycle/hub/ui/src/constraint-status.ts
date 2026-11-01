// Whether a blocked candidate Release is waiting out something that resolves on its own (a
// closed maintenance window, an active suppression) or was rejected for a reason that won't
// change until someone acts (a recall, a schema or version mismatch, a missing artifact, data
// residency, an override block, a destructive change). These deserve different colors: the first
// is routine and expected, the second usually needs an operator's attention.
//
// This intentionally mirrors `TIMING_REASONS` in `lifecycle/hub/src/fdai_lifecycle_hub/planning.py`.
// Reason codes are a stable, canonical token shared across the Hub and this UI.
import type { CandidateCheck } from "./api";

const TIMING_REASON_CODES = new Set([
  "maintenance_window_unavailable",
  "maintenance_window_invalid",
  "suppression_window_active",
  "suppression_window_invalid",
  "suppression_scope_invalid",
]);

const CONSTRAINT_REASON_SENTENCES: Readonly<Record<string, string>> = {
  maintenance_window_unavailable: "Waiting for the next open maintenance window that fits the declared duration.",
  maintenance_window_invalid: "The declared maintenance window start/end bounds are invalid.",
  suppression_window_active: "Blocked temporarily while an active suppression window is in effect.",
  suppression_window_invalid: "The declared suppression window bounds or origin are invalid.",
  suppression_scope_invalid: "The suppression window scope selector is malformed.",
  release_version_outside_range: "Candidate release version is outside the installation's subscribed version range.",
  artifact_requirements_missing: "Candidate release manifest declares no required image artifacts.",
  artifact_unavailable: "Required signed release image artifacts are not yet available in the local bundle/registry.",
  data_residency_missing: "Candidate release does not declare supported data-residency regions.",
  data_residency_mismatch: "Candidate release regions do not satisfy the installation's data-residency policy.",
  target_release_digest_mismatch: "Candidate release digest does not match the admitted Plan target digest.",
  plan_type_unsupported: "The requested Plan type is not supported by the lifecycle evaluator.",
  plan_context_mismatch: "Plan context fields do not match the candidate evaluation inputs.",
  schema_downgrade_blocked: "Database schema downgrade is blocked by the forward-only migration contract.",
  schema_step_gap: "Candidate release skips a required intermediate schema revision.",
  recalled_release: "Candidate release has been recalled and cannot be planned.",
  recalled_capability: "Candidate release includes a recalled capability.",
  missing_matching_override_block: "Entity override configuration has no block matching this release version.",
};

export function isTimingReason(reasonCode: string): boolean {
  return TIMING_REASON_CODES.has(reasonCode);
}

export function describeConstraintReason(reasonCode: string): string {
  return CONSTRAINT_REASON_SENTENCES[reasonCode] ?? `Constraint check reported ${reasonCode.replaceAll("_", " ")}.`;
}

export function constraintVerdict(check: CandidateCheck): "passed" | "waiting" | "blocked" {
  if (check.blocks.length === 0) return "passed";
  return check.blocks.every((block) => isTimingReason(block.reason_code)) ? "waiting" : "blocked";
}

export function normalizeConstraintOutcome(
  value: unknown,
): "passed" | "waiting" | "blocking" {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "passed" || trimmed === "waiting" || trimmed === "blocking") {
      return trimmed;
    }
    if (trimmed === "blocked") {
      return "blocking";
    }
    if (isTimingReason(trimmed)) {
      return "waiting";
    }
  }
  return "blocking";
}
