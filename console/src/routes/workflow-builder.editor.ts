import { cloneForm } from "./workflow-builder.chat.builders";
import { emptyStep, suggestStepId } from "./workflow-builder.helpers";
import type { ApprovalRole, DraftStepKind, FormState } from "./workflow-builder.model";

export type DraftParamType = "string" | "number" | "boolean";
export type DraftParamValue = string | number | boolean;

export function addDraftStep(form: FormState): FormState {
  const next = cloneForm(form);
  const key = Math.max(-1, ...next.steps.map((step) => step.key)) + 1;
  next.steps = [...next.steps, emptyStep(key)];
  return next;
}

export function removeDraftStep(form: FormState, key: number): FormState {
  const next = cloneForm(form);
  next.steps = next.steps.filter((step) => step.key !== key);
  return next;
}

export function moveDraftStep(form: FormState, key: number, offset: -1 | 1): FormState {
  const next = cloneForm(form);
  const index = next.steps.findIndex((step) => step.key === key);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= next.steps.length) return next;
  const steps = [...next.steps];
  [steps[index], steps[target]] = [steps[target]!, steps[index]!];
  next.steps = steps;
  return next;
}

export function setDraftStepAction(
  form: FormState,
  key: number,
  actionTypeRef: string,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (!step) return next;
  const previousSuggestedId = suggestStepId(
    step.kind === "action" ? step.action_type_ref : step.kind,
    next.steps.filter((candidate) => candidate.key !== key).map((candidate) => candidate.id),
  );
  const shouldSuggestId = step.id.trim() === "" || step.id === previousSuggestedId;
  step.kind = "action";
  step.action_type_ref = actionTypeRef;
  if (shouldSuggestId && actionTypeRef) {
    step.id = suggestStepId(
      actionTypeRef,
      next.steps.filter((candidate) => candidate.key !== key).map((candidate) => candidate.id),
    );
  }
  return next;
}

export function setDraftStepKind(
  form: FormState,
  key: number,
  kind: DraftStepKind,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (!step || step.kind === kind) return next;
  const previousSuggestedId = step.kind === "action"
    ? suggestStepId(
        step.action_type_ref,
        next.steps.filter((candidate) => candidate.key !== key).map((candidate) => candidate.id),
      )
    : suggestStepId(
        step.kind,
        next.steps.filter((candidate) => candidate.key !== key).map((candidate) => candidate.id),
      );
  const shouldSuggestId = step.id.trim() === "" || step.id === previousSuggestedId;
  step.kind = kind;
  if (shouldSuggestId) {
    step.id = suggestStepId(
      kind,
      next.steps.filter((candidate) => candidate.key !== key).map((candidate) => candidate.id),
    );
  }
  if (kind === "decision" && step.outcomes.length === 0) step.outcomes = ["", ""];
  if (kind === "parallel" && step.branches.length === 0) step.branches = ["", ""];
  return next;
}

export function updateDraftStepField(
  form: FormState,
  key: number,
  field:
    | "id"
    | "guard_rule_ref"
    | "compensated_by"
    | "on_failure"
    | "wait_for"
    | "timeout_seconds"
    | "quorum"
    | "gate_ref",
  value: string,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (step) step[field] = value;
  return next;
}

export function setDraftListItem(
  form: FormState,
  key: number,
  field: "outcomes" | "branches",
  index: number,
  value: string,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (step && index >= 0 && index < step[field].length) step[field][index] = value;
  return next;
}

export function addDraftListItem(
  form: FormState,
  key: number,
  field: "outcomes" | "branches",
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (step) step[field] = [...step[field], ""];
  return next;
}

export function removeDraftListItem(
  form: FormState,
  key: number,
  field: "outcomes" | "branches",
  index: number,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (step) step[field] = step[field].filter((_, candidateIndex) => candidateIndex !== index);
  return next;
}

export function setDraftStepApprovalRole(
  form: FormState,
  key: number,
  value: ApprovalRole | "",
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (step) step.approval_role = value;
  return next;
}

export function setDraftStepNoSelfApproval(
  form: FormState,
  key: number,
  value: boolean,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === key);
  if (step) step.no_self_approval = value;
  return next;
}

export function draftParamType(value: DraftParamValue): DraftParamType {
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  return "string";
}

export function coerceDraftParam(value: string, type: DraftParamType): DraftParamValue {
  if (type === "number") {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : 0;
  }
  if (type === "boolean") return value === "true";
  return value;
}

export function setDraftParam(
  form: FormState,
  stepKey: number,
  previousName: string,
  name: string,
  value: DraftParamValue,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === stepKey);
  if (!step) return next;
  if (previousName) delete step.params[previousName];
  const normalized = name.trim();
  if (normalized) step.params[normalized] = value;
  return next;
}

export function removeDraftParam(
  form: FormState,
  stepKey: number,
  name: string,
): FormState {
  const next = cloneForm(form);
  const step = next.steps.find((candidate) => candidate.key === stepKey);
  if (step) delete step.params[name];
  return next;
}
