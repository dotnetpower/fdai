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
import { INITIAL_FORM, type FormState } from "./workflow-builder.model";
import { humanizeActionName } from "./workflow-builder.helpers";
import { suggestDraftFromText } from "./workflow-builder.intent";
import {
  actionChips,
  addActionStep,
  cloneForm,
  CRON_PREFIX,
  ensureName,
  exampleOption,
  extractResourceHint,
  extraChips,
  finalizeForm,
  OPT,
  realActions,
  slugifyName,
  triggerChips,
  triggerPhrase,
  WEEKLY_CRON,
} from "./workflow-builder.chat.builders";

// Re-export the pure helpers the UI and the vitest suite import from this
// module so the engine stays their single public entry point.
export { SEED_PREFIX, extractResourceHint, slugifyName } from "./workflow-builder.chat.builders";

/** Interview stages, in the order the engine walks them. */
export type ChatStage =
  | "welcome"
  | "need_action"
  | "need_trigger"
  | "confirm_plan"
  | "offer_extra"
  | "confirm_safety"
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
  /** True once the operator explicitly accepts the inferred trigger and
   * ordered action chain. Inference alone never sets this flag. */
  readonly planConfirmed: boolean;
  /** True once the operator reviews the fail-closed and promotion posture. */
  readonly safetyConfirmed: boolean;
  /** Free-text resource mention pulled from the goal (e.g. "aks-cluster-01"). */
  readonly resourceHint: string;
  /** The operator's first plain-language goal, verbatim. */
  readonly goalText: string;
  /** Bounded inference disclosures that must remain visible at confirmation. */
  readonly warnings: readonly string[];
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
    planConfirmed: false,
    safetyConfirmed: false,
    resourceHint: "",
    goalText: "",
    warnings: [],
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
  if (input === OPT.refineExtra) {
    return { ...slots, stage: "offer_extra", extraOffered: false, safetyConfirmed: false };
  }
  if (input === OPT.refineActions) {
    const form = cloneForm(slots.form);
    form.steps = [];
    return {
      ...slots,
      form,
      stage: "need_action",
      actionsConfirmed: false,
      planConfirmed: false,
      extraOffered: false,
      safetyConfirmed: false,
      warnings: [],
    };
  }
  if (input === OPT.refineTrigger) {
    return {
      ...slots,
      stage: "need_trigger",
      triggerConfirmed: false,
      planConfirmed: false,
      safetyConfirmed: false,
    };
  }
  if (input === OPT.refineSafety) {
    return { ...slots, stage: "confirm_safety", safetyConfirmed: false };
  }

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

  if (input === OPT.planKeep) return { ...slots, planConfirmed: true };

  if (input === OPT.safetyKeep) return { ...slots, safetyConfirmed: true };

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

  // Safety stage: free text is the workflow anti-scope. This is descriptive
  // evidence for review; typed policy and ActionType ceilings remain authoritative.
  if (slots.stage === "confirm_safety") {
    const form = cloneForm(slots.form);
    form.antiScope = text.trim();
    return { ...slots, form, safetyConfirmed: true };
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
    warnings: sug.actionMatchesTruncated
      ? ["More than three distinct actions matched; review and add the omitted steps explicitly."]
      : slots.warnings,
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
    const s: ChatSlots = { ...slots, stage: "need_action" };
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
    const s: ChatSlots = { ...slots, stage: "need_trigger" };
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

  // 3. Inference proposes; the operator explicitly confirms the plan.
  if (!slots.planConfirmed) {
    const s: ChatSlots = { ...slots, stage: "confirm_plan" };
    const warning = slots.warnings.length > 0
      ? `\n\n**Review note:** ${slots.warnings.join(" ")}`
      : "";
    return {
      text:
        `${understoodLine(prev, slots)}Please confirm this trigger and ordered action chain before ` +
        `I continue.${warning}`,
      options: [
        { label: "Use this plan", value: OPT.planKeep },
        { label: "Change the actions", value: OPT.refineActions },
        { label: "Change the trigger", value: OPT.refineTrigger },
      ],
      slots: s,
      draftReady: false,
    };
  }

  // 4. Offer one round of extra / complementary actions.
  if (!slots.extraOffered) {
    const extras = extraChips(palette, slots);
    const s: ChatSlots = { ...slots, stage: "offer_extra" };
    return {
      text:
        `${understoodLine(prev, slots)}Want to **add another step** - for example a ` +
        "notification or a follow-up remediation? You can also keep it as-is.",
      options: [...extras, { label: "No, that's enough", value: OPT.done }],
      slots: s,
      draftReady: false,
    };
  }

  // 5. Make the default failure and promotion posture explicit. Free text
  // entered here becomes anti_scope; skipping keeps it unset.
  if (!slots.safetyConfirmed) {
    const s: ChatSlots = { ...slots, stage: "confirm_safety" };
    return {
      text:
        "Safety review: this draft stays in **shadow** mode, has no automatic failure " +
        "fallback, and requires 14 days, 100 samples, 0.95 accuracy, and zero policy " +
        "escapes before promotion. A failed step stops the run. Keep these safeguards, " +
        "or type what this workflow must never do to record an anti-scope boundary.",
      options: [{ label: "Keep these safeguards", value: OPT.safetyKeep }],
      slots: s,
      draftReady: false,
    };
  }

  // 6. Settle the name.
  if (!slots.nameConfirmed) {
    const suggested = ensureName(slots);
    const s: ChatSlots = { ...slots, form: suggested, stage: "confirm_name" };
    return {
      text:
        `${understoodLine(prev, slots)}Almost done. I'll call it ` +
        `\`${suggested.name}\`. Keep that name, or type a different one.`,
      options: [{ label: `Keep "${suggested.name}"`, value: OPT.nameKeep }],
      slots: s,
      draftReady: false,
    };
  }

  // 7. Ready - finalize description + name and hand off for preview.
  const form = finalizeForm(slots);
  const s: ChatSlots = { ...slots, form, stage: "ready" };
  return {
    text:
      "Here's the workflow I built from our conversation. I've generated the YAML " +
      "and a visual of how it runs, and structurally validated it below (nothing is " +
      "created). Copy the YAML into a remediation PR when you're happy, or keep refining.",
    options: [
      { label: "Add another step", value: OPT.refineExtra },
      { label: "Change the actions", value: OPT.refineActions },
      { label: "Change the trigger", value: OPT.refineTrigger },
      { label: "Review safety", value: OPT.refineSafety },
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
