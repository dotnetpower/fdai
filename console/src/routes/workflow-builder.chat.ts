/**
 * Workflow-builder conversational engine - a deterministic, LLM-free
 * interview that co-designs a workflow with the operator through
 * plain-language turns, option chips, and follow-up questions, then hands
 * a finished draft to the UI for validation + visualization.
 *
 * SRP: state machine only. No React, no I/O, no model call. Given the
 * accumulated slots and the operator's latest input (free text or a
 * clicked option token), it returns the next bot turn (explanation +
 * question + option chips) and the updated slots. The UI layer
 * (workflow-builder.chat.tsx) renders turns and, at the `ready` stage,
 * runs the existing validate + flow-map path on `slots.form`.
 *
 * Reuses the same deterministic matcher the form composer uses
 * (`suggestDraftFromText`) so a single free-text sentence can pre-fill
 * trigger + steps; the interview then only asks for what is still
 * missing. Because it is deterministic it works with the LLM narrator
 * absent, matching the deterministic-first contract.
 */

import type { ActionTypePaletteEntry } from "../workflow/validate";
import {
  INITIAL_FORM,
  SIGNAL_TYPE_OPTIONS,
  type DraftStep,
  type FormState,
} from "./workflow-builder.model";
import {
  humanizeActionName,
  signalLabel,
  suggestStepId,
} from "./workflow-builder.helpers";
import { suggestDraftFromText } from "./workflow-builder.intent";

/** Interview stages, in the order the engine walks them. */
export type ChatStage =
  | "welcome"
  | "need_action"
  | "need_trigger"
  | "offer_extra"
  | "confirm_name"
  | "ready";

/** One clickable option chip in a bot turn. `value` is the token echoed
 * back to {@link respondToChat}; `label` is the human text on the chip. */
export interface ChatOption {
  readonly label: string;
  readonly value: string;
  readonly hint?: string;
}

/** Accumulated interview state. `form` is the draft-in-progress (a
 * {@link FormState}), the rest are interview bookkeeping flags. Serializable
 * so the UI can keep it in component state. */
export interface ChatSlots {
  readonly stage: ChatStage;
  readonly form: FormState;
  /** True once the operator has explicitly picked or confirmed a trigger. */
  readonly triggerConfirmed: boolean;
  /** True once at least one real action step is present and confirmed. */
  readonly actionsConfirmed: boolean;
  /** True once the "add another action?" question has been asked. */
  readonly extraOffered: boolean;
  /** True once the workflow name is settled. */
  readonly nameConfirmed: boolean;
  /** Free-text resource mention pulled from the goal (e.g. "aks-cluster-01"). */
  readonly resourceHint: string;
  /** The operator's first plain-language goal, verbatim. */
  readonly goalText: string;
}

/** A single bot turn: what to say, the option chips, and the slots after
 * this turn. `draftReady` is true only at the `ready` stage, signalling the
 * UI to validate + visualize `slots.form`. */
export interface BotTurn {
  readonly text: string;
  readonly options: readonly ChatOption[];
  readonly slots: ChatSlots;
  readonly draftReady: boolean;
}

// ---------------------------------------------------------------------------
// Option-token prefixes (value of a ChatOption)
// ---------------------------------------------------------------------------

/** Prefix on a welcome example chip's value; the rest is the goal text.
 * Exported so the UI echoes the example verbatim without re-hardcoding the
 * literal (single source with {@link OPT}). */
export const SEED_PREFIX = "seed:";

/** Sub-prefix inside a `trigger:` value that carries a full cron expression
 * (`trigger:cron:0 3 * * 0`), distinguishing a schedule from a signal pick. */
const CRON_PREFIX = "cron:";

const OPT = {
  seed: SEED_PREFIX, // welcome example click -> treat as goal text
  trigger: "trigger:", // trigger:<signalType>  |  trigger:cron:<expr>  |  trigger:@weekly
  action: "action:", // action:<actionTypeName>
  done: "done", // offer_extra: finish adding actions
  nameKeep: "name:keep", // confirm_name: keep the suggested name
  refineExtra: "refine:extra",
  refineTrigger: "refine:trigger",
  restart: "restart",
} as const;

const WEEKLY_CRON = "0 3 * * 0";

// ---------------------------------------------------------------------------
// Public entry points
// ---------------------------------------------------------------------------

/** The opening turn: greet, explain what can be built, and offer example
 * goals as clickable chips plus a free-text invitation. */
export function startChat(palette: readonly ActionTypePaletteEntry[]): BotTurn {
  const slots: ChatSlots = {
    stage: "welcome",
    form: cloneForm(INITIAL_FORM),
    triggerConfirmed: false,
    actionsConfirmed: false,
    extraOffered: false,
    nameConfirmed: false,
    resourceHint: "",
    goalText: "",
  };
  const text =
    "Let's design a workflow together. Tell me, in plain words, **what should " +
    "happen automatically** - I'll ask a few questions, show you the exact YAML, " +
    "and let you test it before anything is created.\n\n" +
    "For example, you could say:\n" +
    "- *When a pod on aks-cluster-01 runs high CPU, alert me.*\n" +
    "- *When cost spikes, right-size the resource and post a summary.*\n" +
    "- *Every week, rehearse a DR failover.*";
  const options: ChatOption[] = [
    exampleOption("When a pod on aks-cluster-01 runs high CPU, alert me"),
    exampleOption("When cost spikes, right-size the resource and post a summary"),
    exampleOption("Every week, rehearse a DR failover"),
  ];
  // Guard: an empty palette means the deployment did not wire authoring.
  if (palette.length === 0) {
    return {
      text:
        "I can't reach the ActionType palette on this deployment, so I have no " +
        "building blocks to offer. Enable `ReadApiConfig.workflow_authoring` in the " +
        "composition root, then reopen this page.",
      options: [],
      slots,
      draftReady: false,
    };
  }
  return { text, options, slots, draftReady: false };
}

/** Advance the interview by one turn. `rawInput` is either free text the
 * operator typed or the `value` of a clicked {@link ChatOption}. */
export function respondToChat(
  prev: ChatSlots,
  rawInput: string,
  palette: readonly ActionTypePaletteEntry[],
): BotTurn {
  const input = rawInput.trim();
  if (input === OPT.restart) return startChat(palette);

  let slots = applyInput(prev, input, palette);
  return nextTurn(slots, palette, prev);
}

// ---------------------------------------------------------------------------
// Input handling - fold the operator's answer into the slots
// ---------------------------------------------------------------------------

function applyInput(
  slots: ChatSlots,
  input: string,
  palette: readonly ActionTypePaletteEntry[],
): ChatSlots {
  // Refine options (available after `ready`) reopen an earlier stage.
  if (input === OPT.refineExtra) return { ...slots, stage: "offer_extra", extraOffered: false };
  if (input === OPT.refineTrigger) return { ...slots, stage: "need_trigger", triggerConfirmed: false };

  // Explicit trigger pick.
  if (input.startsWith(OPT.trigger)) {
    const sig = input.slice(OPT.trigger.length);
    const form = cloneForm(slots.form);
    if (sig.startsWith(CRON_PREFIX)) {
      form.triggerKind = "schedule";
      form.schedule = sig.slice(CRON_PREFIX.length);
    } else if (sig === "@weekly") {
      form.triggerKind = "schedule";
      form.schedule = WEEKLY_CRON;
    } else {
      form.triggerKind = "signal";
      form.signalType = sig;
    }
    return { ...slots, form, triggerConfirmed: true };
  }

  // Explicit action pick (need_action or offer_extra).
  if (input.startsWith(OPT.action)) {
    const name = input.slice(OPT.action.length);
    const form = addActionStep(slots.form, name);
    const inExtra = slots.stage === "offer_extra";
    return {
      ...slots,
      form,
      actionsConfirmed: true,
      extraOffered: inExtra ? true : slots.extraOffered,
    };
  }

  // Finish adding extra actions.
  if (input === OPT.done) return { ...slots, extraOffered: true };

  // Keep the suggested name.
  if (input === OPT.nameKeep) return { ...slots, nameConfirmed: true };

  // Otherwise this is free text - interpret it by the current stage.
  const text = input.startsWith(OPT.seed) ? input.slice(OPT.seed.length) : input;
  return applyFreeText(slots, text, palette);
}

function applyFreeText(
  slots: ChatSlots,
  text: string,
  palette: readonly ActionTypePaletteEntry[],
): ChatSlots {
  if (text.trim().length === 0) return slots;

  // Naming stage: the whole line is the workflow name.
  if (slots.stage === "confirm_name") {
    const form = cloneForm(slots.form);
    form.name = slugifyName(text);
    return { ...slots, form, nameConfirmed: true };
  }

  // Trigger stage: infer only the trigger from the sentence.
  if (slots.stage === "need_trigger") {
    const sug = suggestDraftFromText(text, palette);
    const form = cloneForm(slots.form);
    if (sug && sug.triggerConfident) {
      form.triggerKind = sug.form.triggerKind;
      form.signalType = sug.form.signalType;
      form.schedule = sug.form.schedule;
      return { ...slots, form, triggerConfirmed: true };
    }
    // Could not read a trigger - leave it for the option chips.
    return slots;
  }

  // Welcome or need_action: run the full matcher and merge.
  const sug = suggestDraftFromText(text, palette);
  const form = cloneForm(slots.form);
  const goalText = slots.goalText || text.trim();
  const resourceHint = slots.resourceHint || extractResourceHint(text);
  if (!sug) {
    return { ...slots, goalText, resourceHint };
  }
  // Merge matched actions into the draft (dedupe by action_type_ref).
  let merged = form;
  for (const step of sug.form.steps) {
    if (step.action_type_ref) merged = addActionStep(merged, step.action_type_ref);
  }
  // Adopt the matched trigger unless the operator already confirmed one.
  const triggerConfirmed = slots.triggerConfirmed || sug.triggerConfident;
  if (!slots.triggerConfirmed && sug.triggerConfident) {
    merged.triggerKind = sug.form.triggerKind;
    merged.signalType = sug.form.signalType;
    merged.schedule = sug.form.schedule;
  }
  const hasActions = merged.steps.some((s) => s.action_type_ref);
  return {
    ...slots,
    form: merged,
    goalText,
    resourceHint,
    triggerConfirmed,
    actionsConfirmed: slots.actionsConfirmed || hasActions,
  };
}

// ---------------------------------------------------------------------------
// Turn generation - ask for the next missing slot, else preview
// ---------------------------------------------------------------------------

function nextTurn(
  slots: ChatSlots,
  palette: readonly ActionTypePaletteEntry[],
  prev: ChatSlots,
): BotTurn {
  const actions = realActions(slots.form);

  // 1. No action yet -> ask what to do.
  if (actions.length === 0) {
    const s = { ...slots, stage: "need_action" as ChatStage };
    // If we already asked and their answer still resolved to no action, say so
    // instead of silently re-asking the same question.
    const retry = prev.stage === "need_action";
    const lead = retry
      ? "I couldn't map that to an action yet - pick one below, or describe it " +
        'another way (for example "restart the service" or "right-size it").\n\n'
      : understoodLine(prev, slots);
    return {
      text:
        `${lead}First, **what should the workflow do?** Pick an action to run, ` +
        "or describe it and I'll match one.",
      options: actionChips(palette, slots, []),
      slots: s,
      draftReady: false,
    };
  }

  // 2. Trigger not settled -> ask when to run.
  if (!slots.triggerConfirmed) {
    const s = { ...slots, stage: "need_trigger" as ChatStage };
    const retry = prev.stage === "need_trigger";
    const lead = retry
      ? "I couldn't read a trigger from that - choose one of these.\n\n"
      : understoodLine(prev, slots);
    return {
      text:
        `${lead}**When should it run?** Choose the signal that ` +
        "starts it, or a schedule.",
      options: triggerChips(),
      slots: s,
      draftReady: false,
    };
  }

  // 3. Offer one round of extra / complementary actions.
  if (!slots.extraOffered) {
    const extras = extraChips(palette, slots);
    const s = { ...slots, stage: "offer_extra" as ChatStage };
    return {
      text:
        `${understoodLine(prev, slots)}Want to **add another step** - for example a ` +
        "notification or a follow-up remediation? You can also keep it as-is.",
      options: [...extras, { label: "No, that's enough", value: OPT.done }],
      slots: s,
      draftReady: false,
    };
  }

  // 4. Settle the name.
  if (!slots.nameConfirmed) {
    const suggested = ensureName(slots);
    const s = { ...slots, form: suggested, stage: "confirm_name" as ChatStage };
    return {
      text:
        `${understoodLine(prev, slots)}Almost done. I'll call it ` +
        `\`${suggested.name}\`. Keep that name, or type a different one.`,
      options: [{ label: `Keep "${suggested.name}"`, value: OPT.nameKeep }],
      slots: s,
      draftReady: false,
    };
  }

  // 5. Ready - finalize description + name and hand off for preview.
  const form = finalizeForm(slots);
  const s = { ...slots, form, stage: "ready" as ChatStage };
  return {
    text:
      "Here's the workflow I built from our conversation. I've generated the YAML " +
      "and a visual of how it runs, and validated it below (a dry test - nothing is " +
      "created). Copy the YAML into a remediation PR when you're happy, or keep refining.",
    options: [
      { label: "Add another step", value: OPT.refineExtra },
      { label: "Change the trigger", value: OPT.refineTrigger },
      { label: "Start over", value: OPT.restart },
    ],
    slots: s,
    draftReady: true,
  };
}

// ---------------------------------------------------------------------------
// Explanations + option builders
// ---------------------------------------------------------------------------

/** A short "here's what I understood" recap, shown when the draft changed
 * since the previous turn so the operator sees the engine's reading. */
function understoodLine(prev: ChatSlots, now: ChatSlots): string {
  const actions = realActions(now.form);
  const changed =
    realActions(prev.form).length !== actions.length ||
    prev.triggerConfirmed !== now.triggerConfirmed;
  if (!changed || (actions.length === 0 && !now.triggerConfirmed)) return "";
  const parts: string[] = [];
  if (now.triggerConfirmed) parts.push(`**when** ${triggerPhrase(now.form)}`);
  if (actions.length > 0) {
    const verbs = actions.map((a) => `**${humanizeActionName(a.action_type_ref)}**`).join(", then ");
    parts.push(`**do** ${verbs}`);
  }
  if (parts.length === 0) return "";
  const res = now.resourceHint ? ` (on \`${now.resourceHint}\`)` : "";
  return `Got it - ${parts.join(", ")}${res}.\n\n`;
}

/** Plain-language phrase for the current trigger. */
function triggerPhrase(form: FormState): string {
  if (form.triggerKind === "schedule") {
    return form.schedule === WEEKLY_CRON ? "every week" : `on schedule \`${form.schedule}\``;
  }
  return signalLabel(form.signalType).toLowerCase() || form.signalType;
}

function exampleOption(text: string): ChatOption {
  return { label: text, value: `${OPT.seed}${text}` };
}

/** Action chips for `need_action`: goal-relevant matches first (via the
 * matcher's ranking), then a spread across categories so the operator sees
 * variety. */
function actionChips(
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

/** Complementary actions for `offer_extra`: prefer a notification/tool step
 * if none is present, else spread across unused categories. */
function extraChips(
  palette: readonly ActionTypePaletteEntry[],
  slots: ChatSlots,
): ChatOption[] {
  const used = new Set(realActions(slots.form).map((s) => s.action_type_ref));
  const out: ActionTypePaletteEntry[] = [];
  const hasTool = realActions(slots.form).some((s) => {
    const e = palette.find((p) => p.name === s.action_type_ref);
    return e?.category === "tool";
  });
  if (!hasTool) {
    const notify = palette.find(
      (p) => p.category === "tool" && /notif|summary|card|issue|ticket/i.test(p.name),
    );
    if (notify) {
      out.push(notify);
      used.add(notify.name);
    }
  }
  const byCat = new Map<string, ActionTypePaletteEntry>();
  for (const p of palette) {
    const cat = p.category ?? "other";
    if (!used.has(p.name) && !byCat.has(cat)) byCat.set(cat, p);
  }
  for (const p of byCat.values()) {
    if (out.length >= 4) break;
    out.push(p);
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

function triggerChips(): ChatOption[] {
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
// Form helpers
// ---------------------------------------------------------------------------

/** Steps that carry a real action ref (ignores blank starter rows). */
function realActions(form: FormState): DraftStep[] {
  return form.steps.filter((s) => s.action_type_ref.trim().length > 0);
}

/** Append an action step, deduped by action ref, with a unique suggested id. */
function addActionStep(form: FormState, actionName: string): FormState {
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
    { key, id, action_type_ref: actionName, guard_rule_ref: "", compensated_by: "", on_failure: "" },
  ];
  return next;
}

/** Ensure the form has a name, suggested from the first action + resource. */
function ensureName(slots: ChatSlots): FormState {
  const form = cloneForm(slots.form);
  if (form.name.trim()) return form;
  const first = realActions(form)[0];
  const base = first ? suggestStepId(first.action_type_ref, []).replace(/_/g, "-") : "workflow";
  form.name = slugifyName(`${base}-workflow`);
  return form;
}

/** Fill in description (from the goal + resource) at the end. */
function finalizeForm(slots: ChatSlots): FormState {
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
  const verbs = realActions(form).map((s) => humanizeActionName(s.action_type_ref)).join(", then ");
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
function cloneForm(form: FormState): FormState {
  return { ...form, steps: form.steps.map((s) => ({ ...s })) };
}
