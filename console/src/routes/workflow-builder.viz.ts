/**
 * Workflow-builder visualization model - the pure derivation behind the
 * chat's inline "when -> do -> done" node chain (workflow-builder.chatpanel
 * WorkflowViz). Splitting it out of the component makes the trigger/step/done
 * sequencing and the notify-vs-do labeling unit-testable without a DOM.
 *
 * SRP: FormState + palette -> ordered node list. No preact, no DOM, no I/O.
 */

import type { ActionTypePaletteEntry } from "../workflow/validate";
import { humanizeActionName, signalLabel } from "./workflow-builder.helpers";
import type { FormState } from "./workflow-builder.model";

/** One node in the rendered chain. `kind` drives the small kicker label and
 * `category` the accent color; `ref` is the exact machine value shown in mono
 * beneath the human `name`. */
export interface VizNode {
  readonly kind: "when" | "do" | "notify" | "done";
  readonly name: string;
  readonly ref: string;
  readonly category: string;
}

/** The known ActionType categories that carry a distinct accent; anything
 * else collapses to "other" so a class name is always well-formed. */
const KNOWN_CATEGORIES: ReadonlySet<string> = new Set([
  "remediation",
  "ops",
  "governance",
  "tool",
  "other",
]);

/** Build the ordered node chain: one trigger node, one node per real step
 * (a `tool` step reads as "notify"), then a terminal "done" node. */
export function buildVizModel(
  form: FormState,
  palette: readonly ActionTypePaletteEntry[],
): VizNode[] {
  const catOf = new Map<string, string>();
  for (const p of palette) catOf.set(p.name, normalizeCategory(p.category));

  const triggerName =
    form.triggerKind === "signal"
      ? signalLabel(form.signalType) || form.signalType || "an event"
      : form.schedule || "a schedule";
  const triggerRef = form.triggerKind === "signal" ? form.signalType : form.schedule;

  const nodes: VizNode[] = [
    { kind: "when", name: triggerName, ref: triggerRef, category: "trigger" },
  ];

  for (const step of form.steps) {
    const ref = step.action_type_ref.trim();
    if (ref.length === 0) continue; // skip blank starter rows
    const category = catOf.get(ref) ?? "other";
    nodes.push({
      kind: category === "tool" ? "notify" : "do",
      name: humanizeActionName(ref),
      ref,
      category,
    });
  }

  nodes.push({ kind: "done", name: "done", ref: "", category: "end" });
  return nodes;
}

/** Fold an ActionType category to a known accent bucket. */
function normalizeCategory(category: string | null | undefined): string {
  const c = (category ?? "other").toLowerCase();
  return KNOWN_CATEGORIES.has(c) ? c : "other";
}
