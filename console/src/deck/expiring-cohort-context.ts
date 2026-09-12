import type { ViewSnapshot } from "./context";

/** Withdraw expired admission facts even from a conversation's pinned screen snapshot. */
export function withdrawExpiredCohortContext(snapshot: ViewSnapshot, now: number): ViewSnapshot {
  const contexts = snapshot.records?.cohort_comparison_context ?? [];
  const metrics = snapshot.records?.cohort_comparison_metrics ?? [];
  if (contexts.length === 0 && metrics.length === 0) return snapshot;
  const invalid = contexts.length === 0 || contexts.some((context) => {
    const expiry = context.valid_until;
    return typeof expiry !== "string" || !Number.isFinite(Date.parse(expiry)) ||
      Date.parse(expiry) <= now;
  });
  if (!invalid) return snapshot;
  return {
    ...snapshot,
    records: {
      ...snapshot.records,
      cohort_comparison_context: [],
      cohort_comparison_metrics: [],
      cohort_comparison_state: [{ state: "unavailable", reason: "expired_or_missing_expiry" }],
    },
  };
}
