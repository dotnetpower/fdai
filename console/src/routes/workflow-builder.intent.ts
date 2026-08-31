/** Project a verified semantic workflow judgment into a read-only draft. */

import type { ActionTypePaletteEntry } from "../workflow/validate";
import { INITIAL_FORM, type FormState } from "./workflow-builder.model";
import { emptyStep, suggestStepId } from "./workflow-builder.helpers";

export interface WorkflowSemanticJudgment {
  readonly primary_intent: "workflow_draft";
  readonly trigger:
    | { readonly kind: "signal"; readonly signal_type: string }
    | { readonly kind: "schedule"; readonly schedule: string };
  readonly action_type_refs: readonly string[];
  readonly confidence: number;
  readonly ambiguous: boolean;
  readonly execution_authority: false;
}

export interface IntentSuggestion {
  readonly form: FormState;
  readonly reasons: readonly string[];
  readonly triggerConfident: boolean;
  readonly actionMatchesTruncated: boolean;
}

/** Text-only browser calls have no semantic model binding and fail closed. */
export function suggestDraftFromText(
  _text: string,
  _palette: readonly ActionTypePaletteEntry[],
): IntentSuggestion | null {
  return null;
}

/** Build a draft from exact ActionType and trigger identities selected upstream. */
export function suggestDraftFromJudgment(
  judgment: WorkflowSemanticJudgment,
  palette: readonly ActionTypePaletteEntry[],
): IntentSuggestion | null {
  if (
    judgment.primary_intent !== "workflow_draft" ||
    judgment.execution_authority !== false ||
    judgment.ambiguous ||
    !Number.isFinite(judgment.confidence) ||
    judgment.confidence < 0.75 ||
    new Set(judgment.action_type_refs).size !== judgment.action_type_refs.length
  ) {
    return null;
  }
  const entries = judgment.action_type_refs.map((name) =>
    palette.find((item) => item.name === name),
  );
  if (entries.some((entry) => entry === undefined)) return null;

  const selected = entries.slice(0, 3) as ActionTypePaletteEntry[];
  const form: FormState = { ...INITIAL_FORM, steps: [] };
  if (judgment.trigger.kind === "signal") {
    if (!judgment.trigger.signal_type.trim()) return null;
    form.triggerKind = "signal";
    form.signalType = judgment.trigger.signal_type;
  } else {
    if (!judgment.trigger.schedule.trim()) return null;
    form.triggerKind = "schedule";
    form.schedule = judgment.trigger.schedule;
  }

  const taken: string[] = [];
  form.steps = selected.map((entry, key) => {
    const id = suggestStepId(entry.name, taken);
    taken.push(id);
    return {
      key,
      id,
      kind: "action",
      action_type_ref: entry.name,
      guard_rule_ref: "",
      compensated_by: "",
      on_failure: "",
      params: {},
      wait_for: "",
      timeout_seconds: "",
      approval_role: "",
      quorum: "1",
      no_self_approval: true,
      outcomes: [],
      branches: [],
      gate_ref: "",
    };
  });
  if (form.steps.length === 0) form.steps = [emptyStep(0)];
  const first = selected[0];
  if (first) form.name = `${suggestStepId(first.name, []).replace(/_/g, "-")}-workflow`;
  return {
    form,
    reasons: ["verified semantic workflow judgment"],
    triggerConfident: true,
    actionMatchesTruncated: judgment.action_type_refs.length > selected.length,
  };
}
