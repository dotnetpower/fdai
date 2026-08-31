import type { WorkflowCatalogStep, WorkflowIssue } from "../workflow/validate";
import type { FormState } from "./workflow-builder.model";

const BRANCH_LABEL = /^[a-z][a-z0-9_-]{0,63}$/;

export function workflowGateRefs(
  workflows: readonly { readonly steps: readonly WorkflowCatalogStep[] }[],
): readonly string[] {
  return [...new Set(
    workflows.flatMap((workflow) =>
      workflow.steps.flatMap((step) => step.kind === "gate" && step.gate_ref
        ? [step.gate_ref]
        : [])
    ),
  )].sort();
}

export function validateDraftStructure(
  form: FormState,
  gateRefs: readonly string[],
): WorkflowIssue[] {
  const issues: WorkflowIssue[] = [];
  const indexById = new Map<string, number>();
  for (const [index, step] of form.steps.entries()) {
    const id = step.id.trim();
    if (!id) continue;
    if (indexById.has(id)) {
      issues.push(issue(step.id || String(index), "id", `duplicate step id '${id}'`));
    } else {
      indexById.set(id, index);
    }
  }

  for (const [index, step] of form.steps.entries()) {
    const stepKey = step.id.trim() || String(index);
    const failureTarget = step.on_failure.trim();
    if (failureTarget) {
      const targetIndex = indexById.get(failureTarget);
      if (targetIndex === undefined) {
        issues.push(issue(stepKey, "on_failure", `unknown failure target '${failureTarget}'`));
      } else if (targetIndex <= index) {
        issues.push(issue(
          stepKey,
          "on_failure",
          `failure target '${failureTarget}' must be a later step to prevent a cycle`,
        ));
      }
    }
    if (step.kind === "decision") {
      validateLabels(issues, stepKey, "outcomes", step.outcomes, "decision outcome");
    }
    if (step.kind === "parallel") {
      validateLabels(issues, stepKey, "branches", step.branches, "parallel branch");
    }
    if (step.kind === "gate") {
      const gateRef = step.gate_ref.trim();
      if (!gateRef) {
        issues.push(issue(stepKey, "gate_ref", "gate step requires a reviewed evidence gate"));
      } else if (!gateRefs.includes(gateRef)) {
        issues.push(issue(
          stepKey,
          "gate_ref",
          `unsupported gate reference '${gateRef}' is not present in the workflow catalog`,
        ));
      }
    }
  }
  return issues;
}

function validateLabels(
  issues: WorkflowIssue[],
  stepKey: string,
  field: "outcomes" | "branches",
  values: readonly string[],
  label: string,
): void {
  const normalized = values.map((value) => value.trim());
  if (normalized.length < 2) {
    issues.push(issue(stepKey, field, `${label} list requires at least 2 entries`));
    return;
  }
  const seen = new Set<string>();
  for (const value of normalized) {
    if (!BRANCH_LABEL.test(value)) {
      issues.push(issue(
        stepKey,
        field,
        `${label} '${value || "<empty>"}' must use a lowercase catalog label`,
      ));
    } else if (seen.has(value)) {
      issues.push(issue(stepKey, field, `${label} '${value}' must be unique`));
    }
    seen.add(value);
  }
}

function issue(step: string, field: string, message: string): WorkflowIssue {
  return { key: `draft:steps.${step}.${field}`, message };
}
