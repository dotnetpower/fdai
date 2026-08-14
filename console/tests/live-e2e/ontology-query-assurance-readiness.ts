export interface OntologyAssuranceReadinessInput {
  readonly passed: boolean;
  readonly runScope: "full_cohort" | "focused_probe";
  readonly localeCoverageComplete: boolean;
  readonly operationCoverageComplete: boolean;
  readonly answeredCount: number;
  readonly answeredWithCompleteEvidenceCount: number;
  readonly answeredLocaleCoverageComplete: boolean;
}

export function isOntologyAssuranceProductionReady(
  input: OntologyAssuranceReadinessInput,
): boolean {
  return input.passed &&
    input.runScope === "full_cohort" &&
    input.localeCoverageComplete &&
    input.operationCoverageComplete &&
    input.answeredCount > 0 &&
    input.answeredWithCompleteEvidenceCount === input.answeredCount &&
    input.answeredLocaleCoverageComplete;
}
