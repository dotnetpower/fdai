/**
 * Workflow-builder chat builders - the pure, stateless half of the
 * conversational engine: the option-token grammar, chip builders, form/slot
 * helpers, and small string utilities. The orchestration (the state machine
 * that folds an operator's answer into the next turn) lives in
 * `workflow-builder.chat.ts`; splitting the two keeps each file to one axis of
 * change (pure builders vs. turn orchestration) and under the size budget.
 *
 * SRP: no state machine, no React, no I/O. Given slots + palette, produce
 * chips, projected forms, or normalized strings. Types are imported from the
 * engine module (type-only, erased at runtime, so there is no import cycle).
 */

import type { ActionTypePaletteEntry } from "../workflow/validate";
import {
  INITIAL_FORM,
  SIGNAL_TYPE_OPTIONS,
  type DraftStep,
  type FormState,
} from "./workflow-builder.model";
import { humanizeActionName, signalLabel, suggestStepId } from "./workflow-builder.helpers";
import { suggestDraftFromText } from "./workflow-builder.intent";
import type { ChatOption, ChatSlots } from "./workflow-builder.chat";

// ---------------------------------------------------------------------------
// Option-token grammar (the `value` of a ChatOption)
// ---------------------------------------------------------------------------

/** Prefix on a welcome example chip's value; the rest is the goal text.
 * Exported so the UI echoes the example verbatim without re-hardcoding the
 * literal (single source with {@link OPT}). */
export const SEED_PREFIX = "seed:";

/** Sub-prefix inside a `trigger:` value that carries a full cron expression
 * (`trigger:cron:0 3 * * 0`), distinguishing a schedule from a signal pick. */
export const CRON_PREFIX = "cron:";

/** Weekly cron used by the schedule chip; matches the "Every Sunday 03:00"
 * preset so the recap can phrase it as "every week". */
export const WEEKLY_CRON = "0 3 * * 0";

export const OPT = {
  seed: SEED_PREFIX, // welcome example click -> treat as goal text
  trigger: "trigger:", // trigger:<signalType>  |  trigger:cron:<expr>  |  trigger:@weekly
  action: "action:", // action:<actionTypeName>
  done: "done", // offer_extra: finish adding actions
  nameKeep: "name:keep", // confirm_name: keep the suggested name
  planKeep: "plan:keep",
  safetyKeep: "safety:keep",
  refineExtra: "refine:extra",
  refineActions: "refine:actions",
  refineTrigger: "refine:trigger",
  refineSafety: "refine:safety",
  restart: "restart",
} as const;

// ---------------------------------------------------------------------------
// Explanations
// ---------------------------------------------------------------------------

/** Plain-language phrase for the current trigger. */
export function triggerPhrase(form: FormState): string {
  if (form.triggerKind === "schedule") {
    return form.schedule === WEEKLY_CRON ? "every week" : `on schedule \`${form.schedule}\``;
  }
  return signalLabel(form.signalType).toLowerCase() || form.signalType;
}

// ---------------------------------------------------------------------------
// Option builders
// ---------------------------------------------------------------------------

export function exampleOption(text: string): ChatOption {
  return { label: text, value: `${OPT.seed}${text}` };
}

/** Action chips for `need_action`: goal-relevant matches first (via the
 * matcher's ranking), then a spread across categories so the operator sees
 * variety. */
export function actionChips(
  palette: readonly ActionTypePaletteEntry[],
  slots: ChatSlots,
  exclude: readonly string[],
): ChatOption[] {
  const used = new Set([...exclude, ...realActions(slots.form).map((s) => s.action_type_ref)]);
  const picks: ActionTypePaletteEntry[] = [];

  // Goal-relevant first.
  if (slots.goalText) {
    const sug = suggestDraftFromText(slots.goalText, palette);
    for (const step of sug?.form.steps ?? []) {
      const entry = palette.find((p) => p.name === step.action_type_ref);
      if (entry && !used.has(entry.name)) {
        picks.push(entry);
        used.add(entry.name);
      }
    }
  }
  // Then one representative per category for spread.
  const byCat = new Map<string, ActionTypePaletteEntry>();
  for (const p of palette) {
    const cat = p.category ?? "other";
    if (!used.has(p.name) && !byCat.has(cat)) byCat.set(cat, p);
  }
  for (const p of byCat.values()) {
    if (picks.length >= 6) break;
    picks.push(p);
  }
  return picks.slice(0, 6).map(actionOption);
}

/** Complementary actions for `offer_extra`: keep suggestions tied to the
 * stated goal, then offer only bounded communication follow-ups. Never fill
 * the row with arbitrary mutations merely because they occupy another
 * palette category. */
export function extraChips(
  palette: readonly ActionTypePaletteEntry[],
  slots: ChatSlots,
): ChatOption[] {
  const used = new Set(realActions(slots.form).map((s) => s.action_type_ref));
  const out: ActionTypePaletteEntry[] = [];

  if (slots.goalText) {
    const suggestion = suggestDraftFromText(slots.goalText, palette);
    for (const step of suggestion?.form.steps ?? []) {
      const entry = palette.find((candidate) => candidate.name === step.action_type_ref);
      if (entry && !used.has(entry.name)) {
        out.push(entry);
        used.add(entry.name);
      }
    }
  }

  for (const entry of palette) {
    if (out.length >= 4) break;
    if (
      !used.has(entry.name)
      && /(^|[.\-_])(notif|notify|summary|card|incident|issue|ticket)([.\-_]|$)/i.test(entry.name)
    ) {
      out.push(entry);
      used.add(entry.name);
    }
  }
  return out.slice(0, 4).map(actionOption);
}

function actionOption(p: ActionTypePaletteEntry): ChatOption {
  return {
    label: humanizeActionName(p.name),
    value: `${OPT.action}${p.name}`,
    hint: p.description ?? p.name,
  };
}

/** Curated trigger-signal values shown as chips, in the order an operator
 * most often reaches for. Values only - the human label and hint are pulled
 * from {@link SIGNAL_TYPE_OPTIONS} so the chip, the summary line, and the
 * visualization all read the same single source of truth. */
const CURATED_SIGNAL_VALUES: readonly string[] = [
  "object.anomaly",
  "object.drift",
  "object.cost-anomaly",
  "object.security-event",
  "object.capacity-forecast",
];

export function triggerChips(): ChatOption[] {
  const signals: ChatOption[] = CURATED_SIGNAL_VALUES.map((v) => {
    const opt = SIGNAL_TYPE_OPTIONS.find((o) => o.value === v);
    const chip: ChatOption = {
      label: opt?.label ?? signalLabel(v) ?? v,
      value: `${OPT.trigger}${v}`,
    };
    return opt?.hint ? { ...chip, hint: opt.hint } : chip;
  });
  const schedule: ChatOption = {
    label: "Every week (schedule)",
    value: `${OPT.trigger}${CRON_PREFIX}${WEEKLY_CRON}`,
    hint: "Run on a weekly cron instead of reacting to a signal.",
  };
  return [...signals, schedule];
}

// ---------------------------------------------------------------------------
// Form / slot helpers
// ---------------------------------------------------------------------------

/** Steps that carry a real action ref (ignores blank starter rows). */
export function realActions(form: FormState): DraftStep[] {
  return form.steps.filter((s) => s.action_type_ref.trim().length > 0);
}

/** Append an action step, deduped by action ref, with a unique suggested id. */
export function addActionStep(form: FormState, actionName: string): FormState {
  const next = cloneForm(form);
  const steps = realActions(next);
  if (steps.some((s) => s.action_type_ref === actionName)) return next;
  const taken = steps.map((s) => s.id);
  const id = suggestStepId(actionName, taken);
  // Unique client key: one past the max existing key (across all rows, not
  // just the real ones) so a new step never collides with a leftover blank
  // starter row's key and shuffles React state.
  const key = Math.max(-1, ...next.steps.map((s) => s.key)) + 1;
  next.steps = [
    ...steps,
    {
      key,
      id,
      action_type_ref: actionName,
      guard_rule_ref: "",
      compensated_by: "",
      on_failure: "",
      params: {},
    },
  ];
  return next;
}

/** Ensure the form has a name, suggested from the first action + resource. */
export function ensureName(slots: ChatSlots): FormState {
  const form = cloneForm(slots.form);
  if (form.name.trim()) return form;
  const first = realActions(form)[0];
  const base = first ? suggestStepId(first.action_type_ref, []).replace(/_/g, "-") : "workflow";
  form.name = slugifyName(`${base}-workflow`);
  return form;
}

/** Fill in description (from the goal + resource) at the end. */
export function finalizeForm(slots: ChatSlots): FormState {
  const form = ensureName(slots);
  if (!form.description.trim()) {
    const goal = slots.goalText.trim();
    const res = slots.resourceHint ? ` (${slots.resourceHint})` : "";
    const body = goal ? goal : summarize(form);
    // Keep the whole description within the 200-char server cap even when the
    // resource suffix is long: reserve room for the suffix, never slice below 0.
    const budget = Math.max(0, 200 - res.length);
    form.description = (body.slice(0, budget) + res).slice(0, 200);
  }
  return form;
}

/** A "when X, do Y" summary used when no goal text was captured. */
function summarize(form: FormState): string {
  const verbs = realActions(form)
    .map((s) => humanizeActionName(s.action_type_ref))
    .join(", then ");
  return `When ${triggerPhrase(form)}, ${verbs.toLowerCase()}`;
}

// ---------------------------------------------------------------------------
// Small pure utilities
// ---------------------------------------------------------------------------

/** Model-family prefixes that look like a resource token (`claude-opus-4`,
 * `gpt-4`) but are not infrastructure; excluded from the resource hint so a
 * cost/LLM sentence does not mis-tag a model name as the target resource. */
const MODEL_NAME_PREFIXES = /^(gpt|claude|opus|sonnet|haiku|gemini|llama|mistral|phi|grok|o[0-9])\b/;

/** Pull a resource-like token from free text ("aks-cluster-01", "vm-1"). */
export function extractResourceHint(text: string): string {
  const m = text.match(/\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*-\d+|[a-z]+-[a-z0-9-]*\d+)\b/i);
  const hint = m?.[1] ?? "";
  if (hint && MODEL_NAME_PREFIXES.test(hint.toLowerCase())) return "";
  return hint;
}

/** Normalize free text into a schema-legal workflow name. */
export function slugifyName(text: string): string {
  const slug = text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/^[^a-z]+/, "")
    .slice(0, 80)
    // Truncation to 80 chars can re-introduce a trailing hyphen; strip it so
    // the result still satisfies NAME_PATTERN (`^[a-z][a-z0-9_.-]{0,79}$`).
    .replace(/-+$/g, "");
  return slug || "workflow";
}

/** Deep-copy a FormState (steps array is mutable). */
export function cloneForm(form: FormState): FormState {
  return {
    ...form,
    steps: form.steps.map((step) => ({ ...step, params: { ...step.params } })),
  };
}
