/**
 * Workflow-builder shared model: types + static option catalogs used by
 * the builder form, its helpers, and the intent-suggestion engine.
 *
 * SRP: data-only. No React, no I/O, no side effects; extracted from
 * `workflow-builder.tsx` so components, helpers, and intent matching can
 * all import the same source of truth.
 */

import type {
  ActionTypePaletteEntry,
  WorkflowCatalogEntry,
  WorkflowDefinitionCatalogResponse,
  WorkflowDefinitionEntry,
} from "../workflow/validate";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One editable step row in the builder form. `key` is a stable client-side
 * identity so re-orders and removals do not shuffle React state. */
export interface DraftStep {
  readonly key: number;
  id: string;
  action_type_ref: string;
  guard_rule_ref: string;
  compensated_by: string;
  on_failure: string;
}

/** The full builder form state. Mirrors the workflow YAML shape (minus
 * server-side derived fields) so `buildDraft` is a straight projection. */
export interface FormState {
  name: string;
  version: string;
  description: string;
  triggerKind: "signal" | "schedule";
  signalType: string;
  schedule: string;
  minShadowDays: string;
  minSamples: string;
  minAccuracy: string;
  maxPolicyEscapes: string;
  antiScope: string;
  steps: DraftStep[];
}

/** Combined payload for the read-only list view (palette + shipped
 * catalog) - both loaded in parallel on route entry. */
export interface CombinedData {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
}

export type WorkflowGroup = "built_in" | "shared" | "mine";

export function hasActionTypeRef(
  step: { readonly action_type_ref?: string | null },
): boolean {
  return typeof step.action_type_ref === "string" && step.action_type_ref.trim().length > 0;
}

export function requestedActionType(
  palette: readonly ActionTypePaletteEntry[],
  actionName: string | null,
): ActionTypePaletteEntry | null {
  return actionName === null
    ? null
    : palette.find((entry) => entry.name === actionName) ?? null;
}

export function workflowGroup(value: string | null): WorkflowGroup {
  return value === "shared" || value === "mine" ? value : "built_in";
}

export function workflowGroupLabel(value: WorkflowGroup): string {
  if (value === "built_in") return "Built-in";
  if (value === "shared") return "Shared";
  return "Mine";
}

export function workflowFromDefinition(
  definition: WorkflowDefinitionEntry,
): WorkflowCatalogEntry {
  const document = definition.workflow_document;
  return {
    ...document,
    step_count: document.steps.length,
    yaml: JSON.stringify(document, null, 2),
  };
}

export function workflowSelection(
  workflows: readonly Pick<WorkflowCatalogEntry, "name" | "steps">[],
  requestedWorkflow: string | null,
  requestedAction: string | null,
): string | null {
  if (requestedWorkflow !== null) return requestedWorkflow;
  if (requestedAction !== null) {
    return workflows.find((workflow) =>
      workflow.steps.some((step) => step.action_type_ref === requestedAction)
    )?.name ?? null;
  }
  return workflows.find((workflow) => workflow.steps.some(hasActionTypeRef))?.name
    ?? workflows[0]?.name
    ?? null;
}

// ---------------------------------------------------------------------------
// Trigger-signal picker options
// ---------------------------------------------------------------------------

/** Sentinel value in the signal-picker dropdown for "type a custom
 * signal_type"; `signal_type` is a free string server-side. */
export const CUSTOM_SIGNAL = "__custom__";

/** Curated signal types a workflow can trigger on - the sensing /
 * detection topics the control plane publishes (`fdai.agents.topics`).
 * Each carries a plain-language `label` (what a non-expert reads first)
 * and the exact machine `value`. `signal_type` is a free string
 * server-side (no registry yet), so these are suggestions plus a custom
 * escape hatch. */
export const SIGNAL_TYPE_OPTIONS: readonly {
  readonly value: string;
  readonly label: string;
  readonly hint: string;
}[] = [
  {
    value: "object.drift",
    label: "Configuration drifted",
    hint: "A resource no longer matches its declared / desired state.",
  },
  {
    value: "object.anomaly",
    label: "Anomaly detected",
    hint: "A detector flagged unusual behavior on a resource.",
  },
  {
    value: "object.event",
    label: "Incoming event",
    hint: "A normalized event arrived and passed intake.",
  },
  {
    value: "object.forecast",
    label: "Forecast crossed a threshold",
    hint: "A prediction crossed a configured threshold.",
  },
  {
    value: "object.cost-anomaly",
    label: "Cost spike detected",
    hint: "Spending jumped unexpectedly (cost governance).",
  },
  {
    value: "object.capacity-forecast",
    label: "Capacity forecast produced",
    hint: "A scaling / capacity forecast was produced.",
  },
  {
    value: "object.security-event",
    label: "Security event raised",
    hint: "A security-relevant event was raised.",
  },
  {
    value: "object.resilience-score",
    label: "Resilience score changed",
    hint: "The disaster-recovery / chaos resilience score moved.",
  },
];

/** Fast membership test for the picker; used to decide whether the
 * current `signal_type` is one of the shipped presets or a custom string. */
export const KNOWN_SIGNAL_VALUES: ReadonlySet<string> = new Set(
  SIGNAL_TYPE_OPTIONS.map((o) => o.value),
);

// ---------------------------------------------------------------------------
// Schedule + form defaults + field catalog
// ---------------------------------------------------------------------------

/** Common cron presets so an operator does not have to hand-write a
 * 5-field expression for the usual cadences. */
export const SCHEDULE_PRESETS: readonly { readonly label: string; readonly value: string }[] = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every day 03:00", value: "0 3 * * *" },
  { label: "Every Monday 03:00", value: "0 3 * * 1" },
  { label: "Every Sunday 03:00", value: "0 3 * * 0" },
  { label: "First of month 03:00", value: "0 3 1 * *" },
];

/** Regex the server enforces on a workflow name (schema.json). Surfaced
 * client-side so a bad name is flagged inline, not after a round-trip. */
export const NAME_PATTERN = /^[a-z][a-z0-9_.-]{0,79}$/;

/** Placeholder plain-language intents shown as clickable chips in the
 * IntentComposer so a first-time operator has a starting example. */
export const INTENT_EXAMPLES: readonly string[] = [
  "When cost spikes, right-size the resource and publish a summary",
  "Every week, rehearse a DR failover",
  "When a resource drifts, restrict public access",
];

// The single blank starter row is built lazily in `initialForm()` (below)
// because `emptyStep` lives in `workflow-builder.helpers.ts` and depends
// on `DraftStep`.

/** Empty starter row. Kept alongside the types so `INITIAL_FORM` below can
 * seed one blank step without importing back into `helpers.ts`. */
function _emptyStep(key: number): DraftStep {
  return {
    key,
    id: "",
    action_type_ref: "",
    guard_rule_ref: "",
    compensated_by: "",
    on_failure: "",
  };
}

/** Empty state for a fresh builder session. Also used by the intent
 * suggester as the base to project a partial suggestion onto. */
export const INITIAL_FORM: FormState = {
  name: "",
  version: "1.0.0",
  description: "",
  triggerKind: "signal",
  signalType: "object.drift",
  schedule: "",
  minShadowDays: "14",
  minSamples: "100",
  minAccuracy: "0.95",
  maxPolicyEscapes: "0",
  antiScope: "",
  steps: [_emptyStep(0)],
};

/** Static description of every field in the new-workflow builder, published to
 * the deck's view snapshot (as `records.form_fields`) so the console assistant
 * can answer "what do I enter / select here?" grounded in the real form rather
 * than deflecting. Order mirrors the on-screen sections. */
export const BUILDER_FORM_FIELDS: readonly Record<string, string>[] = [
  { section: "1. Metadata", field: "name", required: "yes", note: "stable dotted id and audit key, lowercase, e.g. cost-aware-remediation" },
  { section: "1. Metadata", field: "version", required: "yes", note: "semver; defaults to 1.0.0" },
  { section: "1. Metadata", field: "description", required: "no", note: "one-line summary, 200 chars or fewer" },
  { section: "2. Trigger", field: "kind", required: "yes", note: "signal (run on an event) or schedule (run on a cron)" },
  { section: "2. Trigger", field: "signal_type", required: "when kind=signal", note: "what happened that starts the workflow; pick a detection signal from trigger_signal_options or choose Custom" },
  { section: "2. Trigger", field: "schedule", required: "when kind=schedule", note: "standard 5-field cron, e.g. 0 3 * * 1 = 03:00 every Monday" },
  { section: "3. Steps", field: "step.id", required: "yes", note: "unique id for the step; auto-suggested from the chosen ActionType (e.g. right_size), editable" },
  { section: "3. Steps", field: "step.action_type_ref", required: "yes", note: "pick one ontology ActionType from the action_types palette" },
  { section: "3. Steps", field: "step.guard_rule_ref", required: "no", note: "optional policy rule that gates the step" },
  { section: "3. Steps", field: "step.compensated_by", required: "no", note: "optional ActionType that undoes this step on rollback" },
  { section: "3. Steps", field: "step.on_failure", required: "no", note: "optional fallback; must be a later step id" },
  { section: "4. Promotion gate", field: "min_shadow_days", required: "yes", note: "days in shadow before promotion is allowed; default 14" },
  { section: "4. Promotion gate", field: "min_samples", required: "yes", note: "minimum shadow samples; default 100" },
  { section: "4. Promotion gate", field: "min_accuracy", required: "yes", note: "accuracy bar between 0 and 1; default 0.95" },
  { section: "4. Promotion gate", field: "max_policy_escapes", required: "yes", note: "maximum allowed policy-violation escapes; default 0" },
  { section: "4. Promotion gate", field: "anti_scope", required: "no", note: "optional note on what this workflow must NOT do" },
];
