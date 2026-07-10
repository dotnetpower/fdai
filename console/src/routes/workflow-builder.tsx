/**
 * Workflow builder panel - author a custom business process by mapping
 * ordered steps onto the ontology ActionType catalog.
 *
 * Read-only by construction. The palette is `GET /workflows/action-types`
 * and validation is `POST /workflows/validate` (a pure server-side check;
 * see `workflow/validate.ts`). Nothing here mutates control-plane state:
 * the output is a canonical YAML the operator copies into a
 * `rule-catalog/workflows/<name>.yaml` file and lands as a remediation PR
 * through the git-native path, never a console button
 * (app-shape.instructions.md § Operator console). New workflows are locked
 * to `shadow` mode - promotion to enforce is a separate governance PR
 * (process-automation.md § 6).
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Fragment } from "preact";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, CopyButton, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  type ActionTypePaletteEntry,
  type ActionTypePaletteResponse,
  type ValidateResponse,
  type WorkflowCatalogEntry,
  type WorkflowCatalogResponse,
  validateWorkflowDraft,
} from "../workflow/validate";

interface Props {
  readonly client: ReadApiClient;
}

interface CombinedData {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly workflows: readonly WorkflowCatalogEntry[];
}

interface DraftStep {
  readonly key: number;
  id: string;
  action_type_ref: string;
  guard_rule_ref: string;
  compensated_by: string;
  on_failure: string;
}

interface FormState {
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

function emptyStep(key: number): DraftStep {
  return { key, id: "", action_type_ref: "", guard_rule_ref: "", compensated_by: "", on_failure: "" };
}

/** Curated signal types a workflow can trigger on - the sensing /
 * detection topics the control plane publishes (`fdai.agents.topics`).
 * Each carries a plain-language `label` (what a non-expert reads first)
 * and the exact machine `value`. `signal_type` is a free string
 * server-side (no registry yet), so these are suggestions plus a custom
 * escape hatch. */
const CUSTOM_SIGNAL = "__custom__";
const SIGNAL_TYPE_OPTIONS: readonly {
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
const KNOWN_SIGNAL_VALUES: ReadonlySet<string> = new Set(
  SIGNAL_TYPE_OPTIONS.map((o) => o.value),
);

/** Plain-language label for a signal value, or "" if it is a custom one. */
function signalLabel(value: string): string {
  return SIGNAL_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? "";
}

/** Human-friendly label for an ActionType machine name
 * ("remediate.right-size" -> "Right-size"). Shown wherever an operator
 * reads an action, always with the exact machine name kept alongside. */
function humanizeActionName(name: string): string {
  const seg = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : name;
  const words = seg.replace(/[-_]/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Common cron presets so an operator does not have to hand-write a
 * 5-field expression for the usual cadences. */
const SCHEDULE_PRESETS: readonly { readonly label: string; readonly value: string }[] = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every day 03:00", value: "0 3 * * *" },
  { label: "Every Monday 03:00", value: "0 3 * * 1" },
  { label: "Every Sunday 03:00", value: "0 3 * * 0" },
  { label: "First of month 03:00", value: "0 3 1 * *" },
];

const INITIAL_FORM: FormState = {
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
  steps: [emptyStep(0)],
};

/** Static description of every field in the new-workflow builder, published to
 * the deck's view snapshot (as `records.form_fields`) so the console assistant
 * can answer "what do I enter / select here?" grounded in the real form rather
 * than deflecting. Order mirrors the on-screen sections. */
const BUILDER_FORM_FIELDS: readonly Record<string, string>[] = [
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

/** Regex the server enforces on a workflow name (schema.json). Surfaced
 * client-side so a bad name is flagged inline, not after a round-trip. */
const NAME_PATTERN = /^[a-z][a-z0-9_.-]{0,79}$/;

/** Turn a built-in workflow into an editable draft so an operator can
 * clone-and-tweak instead of starting from a blank form. */
function catalogToForm(w: WorkflowCatalogEntry): FormState {
  return {
    name: `${w.name}-copy`,
    version: w.version,
    description: w.description ?? "",
    triggerKind: w.trigger.kind === "schedule" ? "schedule" : "signal",
    signalType: w.trigger.signal_type ?? "object.drift",
    schedule: w.trigger.schedule ?? "",
    minShadowDays: String(w.promotion_gate.min_shadow_days),
    minSamples: String(w.promotion_gate.min_samples),
    minAccuracy: String(w.promotion_gate.min_accuracy),
    maxPolicyEscapes: String(w.promotion_gate.max_policy_escapes),
    antiScope: w.anti_scope ?? "",
    steps: w.steps.map((s, i) => ({
      key: i,
      id: s.id,
      action_type_ref: s.action_type_ref,
      guard_rule_ref: s.guard_rule_ref ?? "",
      compensated_by: s.compensated_by ?? "",
      on_failure: s.on_failure ?? "",
    })),
  };
}

/** Humanize a server issue key ("draft:steps.s1.action_type_ref") into a
 * readable location ("steps > s1 > action type ref") for the issues table,
 * keeping the raw key available as a tooltip. */
function humanizeIssueKey(key: string): string {
  const noPrefix = key.replace(/^draft:/, "").trim();
  if (noPrefix === "" || noPrefix === "<root>") return "workflow";
  return noPrefix.replace(/\./g, " > ").replace(/_/g, " ");
}

/** Turn a dotted workflow name ("cost-aware-remediation") into a readable
 * title ("Cost aware remediation") for template cards. */
export function humanizeName(name: string): string {
  const words = name.replace(/[._-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Suggest a snake_case step id from an ActionType ref so the operator does
 * not have to invent one. "remediate.right-size" -> "right_size", made
 * unique against ids already used in the draft. */
export function suggestStepId(actionTypeRef: string, takenIds: readonly string[]): string {
  const leaf = actionTypeRef.split(/[./:]/).pop() ?? actionTypeRef;
  const base =
    leaf
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "step";
  const taken = new Set(takenIds);
  if (!taken.has(base)) return base;
  for (let i = 2; ; i += 1) {
    const candidate = `${base}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** Assemble the JSON draft the validate endpoint expects, dropping empty
 * optional fields so the server sees a clean mapping. */
function buildDraft(form: FormState): Record<string, unknown> {
  const trigger: Record<string, unknown> = { kind: form.triggerKind };
  if (form.triggerKind === "signal") trigger["signal_type"] = form.signalType.trim();
  else trigger["schedule"] = form.schedule.trim();

  const steps = form.steps.map((s) => {
    const step: Record<string, unknown> = {
      id: s.id.trim(),
      action_type_ref: s.action_type_ref.trim(),
    };
    if (s.guard_rule_ref.trim()) step["guard_rule_ref"] = s.guard_rule_ref.trim();
    if (s.compensated_by.trim()) step["compensated_by"] = s.compensated_by.trim();
    if (s.on_failure.trim()) step["on_failure"] = s.on_failure.trim();
    return step;
  });

  const draft: Record<string, unknown> = {
    schema_version: "1.0.0",
    name: form.name.trim(),
    version: form.version.trim(),
    trigger,
    default_mode: "shadow",
    promotion_gate: {
      min_shadow_days: Number(form.minShadowDays),
      min_samples: Number(form.minSamples),
      min_accuracy: Number(form.minAccuracy),
      max_policy_escapes: Number(form.maxPolicyEscapes),
    },
    steps,
  };
  if (form.description.trim()) draft["description"] = form.description.trim();
  if (form.antiScope.trim()) draft["anti_scope"] = form.antiScope.trim();
  return draft;
}

export function WorkflowBuilderRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [palette, catalog] = await Promise.all([
          client.panel<ActionTypePaletteResponse>("/workflows/action-types"),
          client.panel<WorkflowCatalogResponse>("/workflows/catalog"),
        ]);
        if (!cancelled) {
          setState({
            status: "ready",
            data: { palette: palette.action_types, workflows: catalog.workflows },
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes("404")) {
            setState({
              status: "unavailable",
              message:
                "The workflow authoring routes are not wired on this deployment. " +
                "Set ReadApiConfig.workflow_authoring in the composition root to enable them.",
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack">
      <PageHeader title={t("route.workflowBuilder")} subtitle={t("workflowBuilder.subtitle")} />
      <AsyncBoundary state={state} resourceLabel="workflow builder">
        {(data) => <WorkflowShell data={data} />}
      </AsyncBoundary>
    </div>
  );
}

/** Top-level view switch: the read-only built-in list, or the new-workflow
 * builder. Authoring is deliberately gated behind an explicit "New
 * workflow" action so the default surface is safe inspection. */
function WorkflowShell({ data }: { readonly data: CombinedData }) {
  const [mode, setMode] = useState<"list" | "new">("list");
  const [seed, setSeed] = useState<FormState | null>(null);

  usePublishViewContext(
    () => {
      const isNew = mode === "new";
      // In the builder ("new") the operator is filling a form; ground the deck
      // in the form schema, the selectable trigger signals, and the ActionType
      // palette so "what do I enter / select here?" is answerable. In the list
      // view, ground it in the shipped workflows instead.
      const records: Record<string, readonly Record<string, unknown>[]> = isNew
        ? {
            form_fields: BUILDER_FORM_FIELDS,
            trigger_signal_options: [
              ...SIGNAL_TYPE_OPTIONS.map((o) => ({ value: o.value, hint: o.hint })),
              { value: "(custom)", hint: "choose Custom to type any other signal_type string" },
            ],
            action_types: data.palette.map((p) => ({
              name: p.name,
              category: p.category ?? "-",
              rollback: p.rollback_contract,
              hil_tiers: p.hil_tiers.length > 0 ? p.hil_tiers.join(",") : "none",
              summary: p.description ?? "-",
            })),
          }
        : {
            workflows: data.workflows.map((w) => ({
              name: w.name,
              description: w.description ?? "-",
              trigger:
                w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule,
              steps: w.step_count,
              step_actions: w.steps.map((s) => s.action_type_ref).join(" -> "),
              mode: w.default_mode,
            })),
          };
      return {
        routeId: "workflow-builder",
        routeLabel: "Workflow builder",
        purpose:
          "Inspect the built-in workflows (a trigger plus an ordered chain of " +
          "ActionType steps) and author a new one. New workflows are locked to " +
          "shadow mode; promotion to enforce is a separate reviewed PR. " +
          "Read-only inspection by default.",
        glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.mode]),
        headline: isNew
          ? `New-workflow builder open - fill the form; ${data.palette.length} ActionTypes to choose from`
          : `${data.workflows.length} built-in workflows - ${data.palette.length} ActionTypes`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "built_in_count", value: data.workflows.length, group: "workflow" },
          { key: "palette_size", value: data.palette.length, group: "workflow" },
          { key: "mode", value: isNew ? "new (builder form open)" : "list", group: "workflow" },
          ...(isNew
            ? [
                {
                  key: "default_mode",
                  value: "shadow (locked; promotion is a separate PR)",
                  group: "workflow",
                },
              ]
            : []),
        ],
        records,
      };
    },
    [data.workflows, data.palette, mode],
  );

  if (mode === "new") {
    return (
      <BuilderBody
        palette={data.palette}
        initial={seed ?? INITIAL_FORM}
        onBack={() => setMode("list")}
      />
    );
  }
  return (
    <BuiltInList
      workflows={data.workflows}
      onNew={() => {
        setSeed(null);
        setMode("new");
      }}
      onClone={(w) => {
        setSeed(catalogToForm(w));
        setMode("new");
      }}
    />
  );
}

/** Live "when -> do" summary of the draft, mirroring Palantir Automate's
 * condition -> effect mental model. Updates as the operator edits the
 * trigger and steps so the workflow reads as one plain sentence before any
 * validation. */
function WorkflowSummary({ form }: { readonly form: FormState }) {
  const triggerVerb = form.triggerKind === "signal" ? "When" : "On schedule";
  const triggerLabel =
    form.triggerKind === "signal"
      ? signalLabel(form.signalType) || form.signalType.trim() || "an event"
      : form.schedule.trim() || "a schedule";
  const actions = form.steps.map((s) => s.action_type_ref.trim()).filter(Boolean);
  return (
    <div class="wf-summary" aria-live="polite">
      <span class="wf-summary-clause">
        <span class="wf-summary-label">{triggerVerb}</span> <code>{triggerLabel}</code>
      </span>
      <span class="wf-summary-arrow" aria-hidden="true">
        →
      </span>
      <span class="wf-summary-clause">
        <span class="wf-summary-label">do</span>{" "}
        {actions.length === 0 ? (
          <span class="muted">(add a step)</span>
        ) : (
          actions.map((a, i) => (
            <Fragment key={i}>
              {i > 0 ? <span class="wf-summary-then"> then </span> : null}
              <code title={a}>{humanizeActionName(a)}</code>
            </Fragment>
          ))
        )}
      </span>
    </div>
  );
}

/** A horizontal, clickable flow map of the draft (trigger -> steps -> end),
 * the graphical companion to the "when -> do" summary. Each step node jumps
 * to its editor card and surfaces the branch/rollback structure (guard,
 * compensated-by, on-failure) that a flat card list hides. */
function WorkflowFlow({
  form,
  onSelect,
}: {
  readonly form: FormState;
  readonly onSelect: (key: number) => void;
}) {
  const triggerLabel =
    form.triggerKind === "signal"
      ? signalLabel(form.signalType) || form.signalType.trim() || "event"
      : form.schedule.trim() || "schedule";
  return (
    <div class="wf-flow" role="list" aria-label="Workflow flow map">
      <div class="wf-node wf-node-trigger" role="listitem">
        <span class="wf-node-kind">{form.triggerKind === "signal" ? "when" : "on"}</span>
        <span class="wf-node-title mono">{triggerLabel}</span>
      </div>
      {form.steps.map((step, index) => {
        const action = step.action_type_ref.trim();
        return (
          <Fragment key={step.key}>
            <span class="wf-flow-arrow" aria-hidden="true">
              →
            </span>
            <button
              type="button"
              class={action ? "wf-node" : "wf-node wf-node-empty"}
              role="listitem"
              onClick={() => onSelect(step.key)}
              title={action ? `Jump to step: ${action}` : "Jump to this step"}
            >
              <span class="wf-node-kind">#{index + 1}</span>
              <span class="wf-node-title">{action ? humanizeActionName(action) : "unset"}</span>
              <span class="wf-node-badges" aria-hidden="true">
                {step.guard_rule_ref.trim() ? <span title="Guarded">🛡</span> : null}
                {step.compensated_by.trim() ? <span title="Has rollback">↩</span> : null}
                {step.on_failure.trim() ? <span title="Has on-failure fallback">⤵</span> : null}
              </span>
            </button>
          </Fragment>
        );
      })}
      <span class="wf-flow-arrow" aria-hidden="true">
        →
      </span>
      <div class="wf-node wf-node-end" role="listitem">
        <span class="wf-node-title">done</span>
      </div>
    </div>
  );
}

/** Launchpad: a card grid that lets an operator start a new workflow from a
 * shipped template (clone-and-tweak) or from a blank form. Replacing the
 * blank-form-first flow removes the "empty canvas" problem - the default
 * surface is now "pick something close and adjust". */
function TemplateGallery({
  workflows,
  onNew,
  onClone,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly onNew: () => void;
  readonly onClone: (w: WorkflowCatalogEntry) => void;
}) {
  return (
    <section class="stack-section">
      <h3 class="section-title">Start a new workflow</h3>
      <p class="muted small">
        Start from a template that is close to what you want and adjust it, or start from a blank
        form. Either way the draft opens in the builder - nothing is created until you validate and
        open a PR.
      </p>
      <div class="template-gallery">
        {workflows.map((w) => (
          <button
            type="button"
            class="template-card"
            key={w.name}
            onClick={() => onClone(w)}
          >
            <span class="template-card-title">{humanizeName(w.name)}</span>
            <span class="template-card-desc">{w.description ?? "No description."}</span>
            <span class="template-card-meta">
              <span class="badge tag">
                {w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule}
              </span>
              <span class="muted small">
                {w.step_count} step{w.step_count === 1 ? "" : "s"}
              </span>
            </span>
            <span class="template-card-cta">Use as template →</span>
          </button>
        ))}
        <button
          type="button"
          class="template-card template-card-blank"
          onClick={onNew}
        >
          <span class="template-card-title">Start from scratch</span>
          <span class="template-card-desc">
            Begin with an empty form and map each step onto an ActionType yourself.
          </span>
          <span class="template-card-cta">Blank workflow →</span>
        </button>
      </div>
    </section>
  );
}

/** Read-only list of shipped workflows + a details drawer per row. */
function BuiltInList({
  workflows,
  onNew,
  onClone,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly onNew: () => void;
  readonly onClone: (w: WorkflowCatalogEntry) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const current = workflows.find((w) => w.name === selected) ?? null;

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? workflows.filter((w) => {
        const trig = w.trigger.kind === "signal" ? w.trigger.signal_type ?? "" : w.trigger.schedule ?? "";
        return (
          w.name.toLowerCase().includes(needle) ||
          w.trigger.kind.includes(needle) ||
          trig.toLowerCase().includes(needle) ||
          w.default_mode.includes(needle)
        );
      })
    : workflows;
  const shadowCount = workflows.filter((w) => w.default_mode !== "enforce").length;
  const enforceCount = workflows.length - shadowCount;

  return (
    <div class="stack">
      <div class="callout">
        <strong>What is this?</strong> A workflow is a built-in business process - an ordered
        list of steps, each one mapped to a governed ontology <code>ActionType</code>. The same
        trust-routing control loop dispatches every step, so each step keeps its safety
        invariants (stop-condition, rollback, blast-radius cap, audit). Pick a template to start
        fast, or browse the shipped workflows read-only below.
      </div>

      <TemplateGallery workflows={workflows} onNew={onNew} onClone={onClone} />

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Browse built-in workflows ({workflows.length})</h3>
        </div>
        {workflows.length === 0 ? (
          <p class="muted small">No built-in workflows are served on this deployment.</p>
        ) : (
          <>
            <div class="list-toolbar">
              <input
                class="form-input"
                type="search"
                value={filter}
                placeholder="Filter by name, trigger, or mode..."
                aria-label="Filter workflows"
                onInput={(e) => setFilter((e.target as HTMLInputElement).value)}
              />
              <span class="muted small">
                Showing {shown.length} of {workflows.length} - {shadowCount} shadow,{" "}
                {enforceCount} enforce
              </span>
            </div>
            <div class="scroll">
              <table class="data-table data-table-clickable">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trigger</th>
                    <th>Steps</th>
                    <th>Mode</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((w) => {
                    const isOpen = w.name === selected;
                    const toggle = () => setSelected(isOpen ? null : w.name);
                    return (
                      <tr
                        key={w.name}
                        class={isOpen ? "row-active" : ""}
                        onClick={toggle}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            toggle();
                          }
                        }}
                        tabIndex={0}
                        role="button"
                        aria-expanded={isOpen}
                        style="cursor: pointer"
                      >
                        <td class="mono">{w.name}</td>
                        <td class="mono muted">
                          <span class="badge tag">{w.trigger.kind}</span>{" "}
                          {w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule}
                        </td>
                        <td>{w.step_count}</td>
                        <td>
                          <span
                            class={w.default_mode === "enforce" ? "badge enforce" : "badge shadow"}
                          >
                            {w.default_mode}
                        </span>
                      </td>
                      <td class="chevron-col">
                        <span class="row-chevron">{isOpen ? "▾" : "▸"}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </>
        )}
      </section>

      {current ? <WorkflowDetail workflow={current} onClone={onClone} /> : null}
    </div>
  );
}

/** Read-only detail: property table + steps + raw catalog YAML. */
function WorkflowDetail({
  workflow,
  onClone,
}: {
  readonly workflow: WorkflowCatalogEntry;
  readonly onClone: (w: WorkflowCatalogEntry) => void;
}) {
  const gate = workflow.promotion_gate;
  return (
    <section class="stack-section">
      <div class="section-header">
        <h3 class="section-title mono">{workflow.name}</h3>
        <button type="button" class="btn btn-small" onClick={() => onClone(workflow)}>
          Use as template
        </button>
      </div>
      {workflow.description ? <p class="muted">{workflow.description}</p> : null}
      <div class="prop-grid">
        <div class="prop">
          <span class="prop-label">Version</span>
          <span class="mono">{workflow.version}</span>
        </div>
        <div class="prop">
          <span class="prop-label">Trigger</span>
          <span class="mono">
            {workflow.trigger.kind}:{" "}
            {workflow.trigger.kind === "signal"
              ? workflow.trigger.signal_type
              : workflow.trigger.schedule}
          </span>
        </div>
        <div class="prop">
          <span class="prop-label">Default mode</span>
          <span class={workflow.default_mode === "enforce" ? "badge enforce" : "badge shadow"}>
            {workflow.default_mode}
          </span>
        </div>
        <div class="prop">
          <span class="prop-label">Promotion gate</span>
          <span class="mono small">
            {gate.min_shadow_days}d, {gate.min_samples} samples, acc &ge; {gate.min_accuracy},
            escapes &le; {gate.max_policy_escapes}
          </span>
        </div>
      </div>

      <h4 class="section-subtitle">Steps ({workflow.steps.length})</h4>
      <div class="scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Step id</th>
              <th>ActionType</th>
              <th>Guard</th>
              <th>Compensated by</th>
              <th>On failure</th>
              <th>Params</th>
            </tr>
          </thead>
          <tbody>
            {workflow.steps.map((s, i) => (
              <tr key={s.id}>
                <td>{i + 1}</td>
                <td class="mono">{s.id}</td>
                <td class="mono">{s.action_type_ref}</td>
                <td class="mono muted">{s.guard_rule_ref ?? "-"}</td>
                <td class="mono muted">{s.compensated_by ?? "-"}</td>
                <td class="mono muted">{s.on_failure ?? "-"}</td>
                <td class="mono muted">{formatParams(s.params)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {workflow.anti_scope ? (
        <p class="muted small">
          <strong>Anti-scope:</strong> {workflow.anti_scope}
        </p>
      ) : null}

      <div class="code-actions">
        <CopyButton text={workflow.yaml} label="Copy YAML" />
      </div>
      <pre class="mono scroll code-block">{workflow.yaml}</pre>
    </section>
  );
}

function BuilderBody({
  palette,
  initial,
  onBack,
}: {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly initial: FormState;
  readonly onBack: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial);
  const [nextKey, setNextKey] = useState(initial.steps.length);
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [validating, setValidating] = useState(false);
  const [transportError, setTransportError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  // Move focus to the first field when the builder opens (keyboard + SR
  // users land on the form, not the top of the page).
  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Bring the validation outcome into view - on a long form the result
  // section sits below the fold and is easy to miss.
  useEffect(() => {
    if (result || transportError) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [result, transportError]);

  const paletteByName = useMemo(
    () => new Map(palette.map((p) => [p.name, p])),
    [palette],
  );

  // ActionType options grouped by category so the step dropdowns are
  // scannable (30+ actions in one flat list is a guessing game).
  const groupedPalette = useMemo(() => {
    const byCat = new Map<string, ActionTypePaletteEntry[]>();
    for (const p of palette) {
      const cat = p.category ?? "other";
      const arr = byCat.get(cat);
      if (arr) arr.push(p);
      else byCat.set(cat, [p]);
    }
    return [...byCat.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [palette]);

  function requestBack(): void {
    if (dirty && !window.confirm("Discard this draft and return to the list?")) return;
    onBack();
  }

  function patch(fields: Partial<FormState>): void {
    setForm((prev) => ({ ...prev, ...fields }));
    setResult(null);
    setDirty(true);
  }

  function patchStep(key: number, fields: Partial<DraftStep>): void {
    setForm((prev) => ({
      ...prev,
      steps: prev.steps.map((s) => (s.key === key ? { ...s, ...fields } : s)),
    }));
    setResult(null);
    setDirty(true);
  }

  function addStep(): void {
    setForm((prev) => ({ ...prev, steps: [...prev.steps, emptyStep(nextKey)] }));
    setNextKey((k) => k + 1);
    setResult(null);
    setDirty(true);
  }

  function removeStep(key: number): void {
    setForm((prev) => ({ ...prev, steps: prev.steps.filter((s) => s.key !== key) }));
    setResult(null);
    setDirty(true);
  }

  function moveStep(index: number, delta: number): void {
    setForm((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.steps.length) return prev;
      const next = [...prev.steps];
      const a = next[index];
      const b = next[target];
      if (a === undefined || b === undefined) return prev;
      next[index] = b;
      next[target] = a;
      return { ...prev, steps: next };
    });
    setResult(null);
    setDirty(true);
  }

  function selectStep(key: number): void {
    const el = document.getElementById(`wf-step-${key}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.add("step-card-flash");
    window.setTimeout(() => el?.classList.remove("step-card-flash"), 900);
  }

  async function onValidate(): Promise<void> {
    setValidating(true);
    setTransportError(null);
    setResult(null);
    try {
      const res = await validateWorkflowDraft(buildDraft(form));
      setResult(res);
    } catch (err) {
      setTransportError(err instanceof Error ? err.message : String(err));
    } finally {
      setValidating(false);
    }
  }

  function resetForm(): void {
    setForm(INITIAL_FORM);
    setNextKey(1);
    setResult(null);
    setTransportError(null);
    setDirty(false);
  }

  const stepIds = form.steps.map((s) => s.id.trim()).filter(Boolean);

  // Client-side readiness: what still blocks a useful validate call. Shown
  // as a checklist so the operator is never guessing why Validate is off.
  const nameValid = NAME_PATTERN.test(form.name.trim());
  const triggerFilled =
    form.triggerKind === "signal" ? form.signalType.trim() !== "" : form.schedule.trim() !== "";
  const incompleteSteps = form.steps.filter(
    (s) => s.id.trim() === "" || s.action_type_ref.trim() === "",
  ).length;
  const missing: string[] = [];
  if (!nameValid) missing.push(form.name.trim() === "" ? "a name" : "a valid name");
  if (!triggerFilled) missing.push(form.triggerKind === "signal" ? "a signal type" : "a schedule");
  if (incompleteSteps > 0)
    missing.push(`${incompleteSteps} step${incompleteSteps > 1 ? "s" : ""} to be completed`);
  const ready = missing.length === 0;

  return (
    <div class="stack">
      <div class="section-header">
        <button type="button" class="btn btn-small" onClick={requestBack}>
          ← Back to built-in workflows
        </button>
      </div>

      <div class="callout">
        <strong>New workflow.</strong> Fill in the fields below to draft a custom business
        process. Each step maps to one governed ontology <code>ActionType</code>; you never write
        raw mutation logic. When you validate, the server checks the draft against the same rules
        the catalog loader uses and returns a ready-to-commit YAML. The console does not deploy it
        - you copy the YAML into <code>rule-catalog/workflows/</code> and open a PR, so review and
        rollback come for free. New workflows start in <span class="badge shadow">shadow</span>{" "}
        mode (judge and log, no changes) until a separate promotion PR.
      </div>

      <WorkflowSummary form={form} />

      {palette.length === 0 ? (
        <div class="empty error">
          <p class="mono">
            No ActionTypes are served on this deployment, so steps cannot be mapped. Wire the
            ActionType catalog (ReadApiConfig.workflow_authoring) to author workflows.
          </p>
        </div>
      ) : null}

      {/* Metadata */}
      <section class="stack-section">
        <h3 class="section-title">1. Workflow metadata</h3>
        <p class="muted small">
          <strong>Name</strong> is the stable id and audit key (lowercase dotted, e.g.{" "}
          <code>cost-aware-remediation</code>). <strong>Description</strong> is a one-line summary
          (&le; 200 chars).
        </p>
        <div class="form-grid">
          <label class="form-field">
            <span class="form-label">Name (dotted id)</span>
            <input
              ref={nameRef}
              id="wf-name"
              aria-describedby="wf-name-hint"
              class={form.name.trim() !== "" && !nameValid ? "form-input mono input-bad" : "form-input mono"}
              value={form.name}
              placeholder="cost-aware-remediation"
              onInput={(e) => patch({ name: (e.target as HTMLInputElement).value })}
            />
            <span
              id="wf-name-hint"
              class={form.name.trim() !== "" && !nameValid ? "field-hint hint-bad" : "field-hint"}
            >
              {form.name.trim() !== "" && !nameValid
                ? "Lowercase letters/digits/._- only, must start with a letter (max 80)."
                : "Lowercase dotted id, e.g. cost-aware-remediation."}
            </span>
          </label>
          <label class="form-field">
            <span class="form-label">Version</span>
            <input
              class="form-input mono"
              value={form.version}
              onInput={(e) => patch({ version: (e.target as HTMLInputElement).value })}
            />
          </label>
          <label class="form-field form-field-wide">
            <span class="form-label">Description (&le; 200 chars)</span>
            <input
              class="form-input"
              value={form.description}
              onInput={(e) => patch({ description: (e.target as HTMLInputElement).value })}
            />
          </label>
        </div>
      </section>

      {/* Trigger */}
      <section class="stack-section">
        <h3 class="section-title">2. Trigger</h3>
        <p class="muted small">
          When the workflow runs. <strong>Signal</strong> starts it when the control plane
          publishes a matching event (a <em>signal type</em>); <strong>schedule</strong> starts it
          on a cron expression. The signal type is <em>what happened</em> that should kick off the
          process - pick one of the detection signals below (e.g. <code>object.drift</code> = a
          resource drifted from its declared state), or choose <em>Custom</em> to type another.
        </p>
        <div class="form-grid">
          <label class="form-field">
            <span class="form-label">Kind</span>
            <select
              class="form-input"
              value={form.triggerKind}
              onChange={(e) =>
                patch({ triggerKind: (e.target as HTMLSelectElement).value as "signal" | "schedule" })
              }
            >
              <option value="signal">signal - run on an event</option>
              <option value="schedule">schedule - run on a cron</option>
            </select>
          </label>
          {form.triggerKind === "signal" ? (
            <SignalTypeField
              value={form.signalType}
              onChange={(v) => patch({ signalType: v })}
            />
          ) : (
            <label class="form-field">
              <span class="form-label">Schedule (cron)</span>
              <select
                class="form-input"
                value={SCHEDULE_PRESETS.some((p) => p.value === form.schedule) ? form.schedule : ""}
                onChange={(e) => {
                  const v = (e.target as HTMLSelectElement).value;
                  if (v) patch({ schedule: v });
                }}
              >
                <option value="">Presets...</option>
                {SCHEDULE_PRESETS.map((p) => (
                  <option value={p.value} key={p.value}>
                    {p.label} ({p.value})
                  </option>
                ))}
              </select>
              <input
                class="form-input mono"
                value={form.schedule}
                placeholder="0 3 * * 1"
                onInput={(e) => patch({ schedule: (e.target as HTMLInputElement).value })}
              />
              <span class="field-hint">Standard 5-field cron. Example: 0 3 * * 1 = 03:00 every Monday.</span>
            </label>
          )}
        </div>
      </section>

      {/* Steps */}
      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">3. Steps ({form.steps.length})</h3>
          <button type="button" class="btn btn-small" onClick={addStep}>
            + Add step
          </button>
        </div>
        <p class="muted small">
          The ordered actions the workflow runs. Each step maps to one ontology ActionType (pick
          from the dropdown) and inherits that action's four safety invariants (stop-condition,
          rollback, blast-radius cap, audit). Optional per step: a <strong>guard</strong> rule
          that gates it, a <strong>compensated by</strong> action that undoes it on rollback, and
          an <strong>on failure</strong> fallback (must be a later step). The card shows the
          selected action's safety posture.
        </p>
        <WorkflowFlow form={form} onSelect={selectStep} />
        <div class="stack">
          {form.steps.map((step, index) => {
            const at = paletteByName.get(step.action_type_ref);
            const laterIds = stepIds.slice(index + 1);
            const stepIncomplete = step.id.trim() === "" || step.action_type_ref.trim() === "";
            return (
              <Fragment key={step.key}>
                <div
                  id={`wf-step-${step.key}`}
                  class={stepIncomplete ? "step-card step-card-incomplete" : "step-card"}
                >
                  <div class="step-card-head">
                    <span class="badge">#{index + 1}</span>
                  <div class="step-move">
                    {stepIncomplete ? (
                      <span class="field-hint hint-bad">needs id + ActionType</span>
                    ) : null}
                    <button
                      type="button"
                      class="btn btn-small"
                      disabled={index === 0}
                      onClick={() => moveStep(index, -1)}
                      aria-label="Move step up"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      class="btn btn-small"
                      disabled={index === form.steps.length - 1}
                      onClick={() => moveStep(index, 1)}
                      aria-label="Move step down"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      class="btn btn-small btn-danger"
                      disabled={form.steps.length === 1}
                      onClick={() => removeStep(step.key)}
                      aria-label="Remove step"
                    >
                      Remove
                    </button>
                  </div>
                </div>
                <div class="form-grid">
                  <label class="form-field">
                    <span class="form-label">Step id</span>
                    <input
                      class="form-input mono"
                      value={step.id}
                      placeholder="annotate_cost"
                      onInput={(e) =>
                        patchStep(step.key, { id: (e.target as HTMLInputElement).value })
                      }
                    />
                  </label>
                  <label class="form-field">
                    <span class="form-label">Action to run</span>
                    <select
                      class="form-input mono"
                      value={step.action_type_ref}
                      onChange={(e) => {
                        const value = (e.target as HTMLSelectElement).value;
                        const fields: Partial<DraftStep> = { action_type_ref: value };
                        // Auto-suggest a step id when the operator has not set
                        // one yet, so picking an action is enough to get a valid
                        // step. Never clobber an id the operator already typed.
                        if (value && step.id.trim() === "") {
                          const taken = form.steps
                            .filter((s) => s.key !== step.key)
                            .map((s) => s.id.trim())
                            .filter(Boolean);
                          fields.id = suggestStepId(value, taken);
                        }
                        patchStep(step.key, fields);
                      }}
                    >
                      <option value="">(pick an action)</option>
                      <ActionTypeOptions grouped={groupedPalette} />
                    </select>
                  </label>
                  <label class="form-field">
                    <span class="form-label">Guard rule ref (optional)</span>
                    <input
                      class="form-input mono"
                      value={step.guard_rule_ref}
                      onInput={(e) =>
                        patchStep(step.key, {
                          guard_rule_ref: (e.target as HTMLInputElement).value,
                        })
                      }
                    />
                  </label>
                  <label class="form-field">
                    <span class="form-label">Compensated by (optional)</span>
                    <select
                      class="form-input mono"
                      value={step.compensated_by}
                      onChange={(e) =>
                        patchStep(step.key, {
                          compensated_by: (e.target as HTMLSelectElement).value,
                        })
                      }
                    >
                      <option value="">(none)</option>
                      <ActionTypeOptions grouped={groupedPalette} />
                    </select>
                  </label>
                  <label class="form-field">
                    <span class="form-label">On failure (later step)</span>
                    <select
                      class="form-input mono"
                      value={step.on_failure}
                      onChange={(e) =>
                        patchStep(step.key, {
                          on_failure: (e.target as HTMLSelectElement).value,
                        })
                      }
                    >
                      <option value="">(none)</option>
                      {laterIds.map((id) => (
                        <option value={id} key={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {at ? <ActionTypeHint at={at} /> : null}
                </div>
                {index < form.steps.length - 1 ? (
                  <div class="step-connector" aria-hidden="true">
                    then ↓
                  </div>
                ) : null}
              </Fragment>
            );
          })}
        </div>
      </section>

      {/* Promotion gate (advanced - defaults are sensible, so this is
          collapsed by default to keep the first-run form short). */}
      <section class="stack-section">
        <details class="advanced-details">
          <summary>
            <span class="section-title">4. Promotion gate</span>{" "}
            <span class="muted small">(advanced - the defaults are fine for most workflows)</span>
          </summary>
          <p class="muted small">
            The bar the workflow must clear before it can be promoted from{" "}
            <span class="badge shadow">shadow</span> (judge and log, no mutation) to enforce.
            Promotion is always a separate governance PR that measures these thresholds - the
            builder only records them.
          </p>
          <div class="form-grid">
            <label class="form-field">
              <span class="form-label">Min shadow days</span>
              <input
                class="form-input mono"
                type="number"
                value={form.minShadowDays}
                onInput={(e) => patch({ minShadowDays: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field">
              <span class="form-label">Min samples</span>
              <input
                class="form-input mono"
                type="number"
                value={form.minSamples}
                onInput={(e) => patch({ minSamples: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field">
              <span class="form-label">Min accuracy</span>
              <input
                class="form-input mono"
                type="number"
                step="0.01"
                value={form.minAccuracy}
                onInput={(e) => patch({ minAccuracy: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field">
              <span class="form-label">Max policy escapes</span>
              <input
                class="form-input mono"
                type="number"
                value={form.maxPolicyEscapes}
                onInput={(e) => patch({ maxPolicyEscapes: (e.target as HTMLInputElement).value })}
              />
            </label>
            <label class="form-field form-field-wide">
              <span class="form-label">Anti-scope (optional)</span>
              <input
                class="form-input"
                value={form.antiScope}
                onInput={(e) => patch({ antiScope: (e.target as HTMLInputElement).value })}
              />
            </label>
          </div>
        </details>
      </section>

      {/* Validate + result */}
      <section class="stack-section" ref={resultRef}>
        <div class="section-header">
          <h3 class="section-title">5. Validate &amp; export</h3>
          <div class="code-actions">
            <button type="button" class="btn btn-small" onClick={resetForm} disabled={validating}>
              Reset
            </button>
            <button
              type="button"
              class="btn"
              onClick={onValidate}
              disabled={validating || !ready}
            >
              {validating ? "Validating..." : "Validate draft"}
            </button>
          </div>
        </div>
        <p class="muted small">
          Runs the draft through the server-side workflow validator. If anything is wrong you get a
          list of exactly what and where; if it passes you get a canonical YAML to copy into a
          <code> rule-catalog/workflows/&lt;name&gt;.yaml</code> file and open as a PR.
        </p>
        {!ready ? (
          <p class="field-hint hint-bad" role="status">
            Before validating, add {missing.join(", ")}.
          </p>
        ) : null}
        {transportError ? (
          <div class="empty error" role="alert">
            <p class="mono">{transportError}</p>
          </div>
        ) : null}
        <div aria-live="polite">
          {result ? <ValidationResult result={result} name={form.name} /> : null}
        </div>
      </section>
    </div>
  );
}

/** Render the ActionType palette as category-grouped <optgroup>s for a
 * step dropdown. Shared by the action_type_ref and compensated_by selects. */
function ActionTypeOptions({
  grouped,
}: {
  readonly grouped: readonly (readonly [string, readonly ActionTypePaletteEntry[]])[];
}) {
  return (
    <>
      {grouped.map(([cat, entries]) => (
        <optgroup label={cat} key={cat}>
          {entries.map((p) => (
            <option value={p.name} key={p.name}>
              {humanizeActionName(p.name)} ({p.name})
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

/** Render a step's params map as a compact "k=v, k=v" string, or "-". */
function formatParams(params: Record<string, string | number | boolean> | undefined): string {
  if (!params) return "-";
  const pairs = Object.entries(params);
  if (pairs.length === 0) return "-";
  return pairs.map(([k, v]) => `${k}=${v}`).join(", ");
}

function ActionTypeHint({ at }: { readonly at: ActionTypePaletteEntry }) {
  return (
    <div class="at-hint">
      <strong>{humanizeActionName(at.name)}</strong>
      <span class="mono muted">{at.name}</span>
      <span class="badge">{at.category ?? at.operation}</span>
      <span class="mono muted">rollback: {at.rollback_contract}</span>
      {at.irreversible ? <span class="badge hil">irreversible</span> : null}
      {at.hil_tiers.length > 0 ? (
        <span class="badge hil" title="Needs a human approval at this tier">
          needs approval @ {at.hil_tiers.join(", ")}
        </span>
      ) : null}
      {at.description ? <span class="muted small">{at.description}</span> : null}
    </div>
  );
}

/** Signal-type picker: a dropdown of the control plane's detection
 * signals plus a Custom escape hatch (the field is a free string
 * server-side). Shows the selected signal's plain-language meaning. */
function SignalTypeField({
  value,
  onChange,
}: {
  readonly value: string;
  readonly onChange: (v: string) => void;
}) {
  const isKnown = KNOWN_SIGNAL_VALUES.has(value);
  const selectValue = isKnown ? value : CUSTOM_SIGNAL;
  const activeHint = SIGNAL_TYPE_OPTIONS.find((o) => o.value === value)?.hint;
  return (
    <label class="form-field">
      <span class="form-label">What starts it (signal)</span>
      <select
        class="form-input"
        value={selectValue}
        onChange={(e) => {
          const v = (e.target as HTMLSelectElement).value;
          onChange(v === CUSTOM_SIGNAL ? "" : v);
        }}
      >
        {SIGNAL_TYPE_OPTIONS.map((o) => (
          <option value={o.value} key={o.value}>
            {o.label} ({o.value})
          </option>
        ))}
        <option value={CUSTOM_SIGNAL}>Custom (type your own)...</option>
      </select>
      {selectValue === CUSTOM_SIGNAL ? (
        <input
          class="form-input mono"
          value={value}
          placeholder="object.my-signal"
          onInput={(e) => onChange((e.target as HTMLInputElement).value)}
        />
      ) : null}
      <span class="field-hint">
        {activeHint ?? "A custom event type the control plane publishes (object.<kebab-name>)."}
      </span>
    </label>
  );
}

function ValidationResult({
  result,
  name,
}: {
  readonly result: ValidateResponse;
  readonly name: string;
}) {
  if (!result.valid) {
    return (
      <div class="stack">
        <div class="badge deny">{result.issues.length} issue(s) - not yet valid</div>
        <div class="scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Where</th>
                <th>Problem</th>
              </tr>
            </thead>
            <tbody>
              {result.issues.map((issue, i) => (
                <tr key={i}>
                  <td class="mono" title={issue.key}>
                    {humanizeIssueKey(issue.key)}
                  </td>
                  <td>{issue.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  const fileName = `${name.trim() || "workflow"}.yaml`;
  const yaml = result.yaml_preview ?? "";
  function download(): void {
    const blob = new Blob([yaml], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div class="stack">
      <div class="badge enforce">Valid - ready for a remediation PR</div>
      <p class="muted small">
        Copy this into <code class="mono">rule-catalog/workflows/{fileName}</code> and open a
        remediation PR. The console does not commit - authoring stays git-native so audit,
        review, and rollback come for free.
      </p>
      <div class="code-actions">
        <CopyButton text={yaml} label="Copy YAML" />
        <button type="button" class="btn btn-small" onClick={download}>
          Download {fileName}
        </button>
      </div>
      <pre class="mono scroll code-block">{yaml}</pre>
    </div>
  );
}
