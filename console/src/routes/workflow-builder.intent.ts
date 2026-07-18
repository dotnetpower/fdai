/**
 * Workflow-builder intent-suggestion engine - plain-language description
 * -> (trigger + ordered steps) draft, deterministic and read-only.
 *
 * SRP: matching only. Given the user's text and the live ActionType
 * palette, propose a starting draft (or abstain by returning null).
 * Never mutates anything and never talks to a model - keeps a
 * non-expert first-run experience without a network round-trip.
 */

import type { ActionTypePaletteEntry } from "../workflow/validate";
import { INITIAL_FORM, type FormState } from "./workflow-builder.model";
import {
  emptyStep,
  humanizeActionName,
  signalLabel,
  suggestStepId,
} from "./workflow-builder.helpers";

/** One trigger group: a signal (or a schedule surrogate) and the set of
 * keywords whose presence in the user's text votes for it. */
interface SignalKeywordGroup {
  readonly signal: string;
  readonly kind: "signal" | "schedule";
  readonly schedule?: string;
  readonly words: readonly string[];
}

const SIGNAL_KEYWORDS: readonly SignalKeywordGroup[] = [
  {
    signal: "object.cost-anomaly",
    kind: "signal",
    words: ["cost", "costs", "spend", "spending", "budget", "bill", "billing", "expensive", "overspend", "saving"],
  },
  {
    signal: "object.security-event",
    kind: "signal",
    words: ["security", "secure", "vulnerab", "breach", "exposed", "exposure", "attack", "threat", "malicious"],
  },
  {
    signal: "object.capacity-forecast",
    kind: "signal",
    words: ["scale", "scaling", "capacity", "traffic", "load", "saturation", "throughput", "utiliz"],
  },
  {
    signal: "__schedule_weekly",
    kind: "schedule",
    schedule: "0 3 * * 0",
    words: ["drill", "rehearse", "rehearsal", "weekly", "failover", "disaster", "recovery", "chaos", "schedule"],
  },
  {
    signal: "object.forecast",
    kind: "signal",
    words: ["forecast", "predict", "prediction", "trend", "anticipate"],
  },
  {
    signal: "object.anomaly",
    kind: "signal",
    words: ["anomaly", "anomalous", "unusual", "abnormal", "spike", "weird"],
  },
  {
    signal: "object.drift",
    kind: "signal",
    words: ["drift", "desired", "declared", "baseline", "noncompliant", "compliance", "config", "misconfig"],
  },
];

/** Phrase -> ActionType name substring, so common phrasings map to a real
 * action even when the words differ from the action's own name. */
const ACTION_SYNONYMS: readonly { readonly words: readonly string[]; readonly match: string }[] = [
  { words: ["right size", "rightsize", "downsize", "resize", "shrink"], match: "right-size" },
  { words: ["scale out", "scale up", "add capacity", "grow"], match: "scale-out" },
  { words: ["scale in", "scale down"], match: "scale-in" },
  { words: ["encrypt", "encryption"], match: "enable-encryption" },
  { words: ["backup", "back up"], match: "enable-backup-protection" },
  { words: ["restart", "reboot", "bounce"], match: "restart-service" },
  { words: ["notify", "alert", "tell me", "summary", "report", "publish"], match: "publish-change-summary" },
  { words: ["tag", "label"], match: "tag-add" },
  { words: ["rotate secret", "rotate password", "rotate key"], match: "rotate-secret" },
  { words: ["certificate", "tls"], match: "rotate-cert" },
  { words: ["public access", "expose", "disable public"], match: "disable-public-access" },
  { words: ["firewall", "restrict network"], match: "restrict-network-access" },
  { words: ["rbac", "least privilege"], match: "enable-rbac" },
  { words: ["failover", "fail over"], match: "failover-primary" },
  { words: ["drain"], match: "drain-connection" },
  { words: ["flush cache"], match: "flush-cache" },
];

export interface IntentSuggestion {
  readonly form: FormState;
  readonly reasons: readonly string[];
  /** True when a trigger was read from the text with confidence; false when
   * the matcher fell back to the default drift trigger. Lets callers branch
   * on trigger confidence without string-matching `reasons`. */
  readonly triggerConfident: boolean;
  /** True when more distinct ActionTypes matched than the bounded preview
   * can safely propose. The chat MUST disclose this instead of silently
   * dropping the remaining actions. */
  readonly actionMatchesTruncated: boolean;
}

/** Over-generic words that appear in many ActionType names/descriptions;
 * excluded from token scoring so they do not drag in unrelated actions
 * (e.g. "resource" pulling in remove-orphan-resource). Specific verbs and
 * nouns like "access" / "encryption" are deliberately NOT here. */
const TOKEN_STOPWORDS: ReadonlySet<string> = new Set([
  "resource",
  "resources",
  "service",
  "services",
  "policy",
  "policies",
  "object",
  "event",
  "state",
  "when",
  "every",
  "that",
  "this",
  "with",
  "from",
  "your",
  "will",
  "should",
  "some",
  "them",
]);

/** Match a plain-language description to a trigger + steps drawn from the
 * live palette. Returns null when nothing matches (abstain). */
export function suggestDraftFromText(
  text: string,
  palette: readonly ActionTypePaletteEntry[],
): IntentSuggestion | null {
  const lower = text.toLowerCase();
  if (lower.trim().length < 3) return null;
  // Normalize punctuation to spaces so "right-size" matches the "right size"
  // synonym phrase and hyphenated input is tokenized cleanly.
  const norm = lower.replace(/[^a-z0-9]+/g, " ");
  const tokens = norm.split(" ").filter((w) => w.length >= 4 && !TOKEN_STOPWORDS.has(w));
  const reasons: string[] = [];

  const leafOf = (name: string): string => name.split(/[./:]/).pop() ?? name;

  // --- Actions: synonym phrases first, then token overlap on name+label ---
  const scored = new Map<string, number>();
  const excluded = new Set<string>();
  for (const syn of ACTION_SYNONYMS) {
    const matchedWords = syn.words.filter((word) => norm.includes(word));
    if (matchedWords.length === 0) continue;
    // Target one action: prefer an exact leaf match, else the shortest name
    // that contains the fragment - so "right size" boosts remediate.right-size,
    // not also remediate.right-size-role.
    const exact = palette.find((p) => leafOf(p.name) === syn.match);
    const target =
      exact ??
      palette
        .filter((p) => p.name.includes(syn.match))
        .sort((a, b) => a.name.length - b.name.length)[0];
    if (!target) continue;
    if (matchedWords.every((word) => phraseIsNegated(norm, word))) {
      excluded.add(target.name);
      scored.delete(target.name);
      continue;
    }
    scored.set(target.name, (scored.get(target.name) ?? 0) + 5);
  }
  for (const p of palette) {
    if (excluded.has(p.name)) continue;
    const bag = `${humanizeActionName(p.name)} ${p.name}`.toLowerCase();
    let s = 0;
    for (const tok of tokens) if (bag.includes(tok)) s += 1;
    if (s > 0) scored.set(p.name, (scored.get(p.name) ?? 0) + s);
  }
  // Rank, then drop near-duplicate variants (a leaf that extends an
  // already-picked leaf, e.g. right-size-role after right-size).
  const ranked = [...scored.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const actions: ActionTypePaletteEntry[] = [];
  const pickedLeaves: string[] = [];
  let actionMatchesTruncated = false;
  for (const [name] of ranked) {
    const leaf = leafOf(name);
    if (pickedLeaves.some((l) => leaf.startsWith(l) || l.startsWith(leaf))) continue;
    const entry = palette.find((p) => p.name === name);
    if (entry) {
      if (actions.length >= 3) {
        actionMatchesTruncated = true;
        break;
      }
      actions.push(entry);
      pickedLeaves.push(leaf);
    }
  }

  // --- Trigger: strongest signal keyword group, else infer from actions ---
  let best: SignalKeywordGroup | null = null;
  let bestScore = 0;
  for (const g of SIGNAL_KEYWORDS) {
    const score = g.words.reduce((n, w) => (norm.includes(w) ? n + 1 : n), 0);
    if (score > bestScore) {
      best = g;
      bestScore = score;
    }
  }
  if (actions.length === 0 && best === null) return null; // abstain

  const triggerConfident = best !== null;
  const form: FormState = { ...INITIAL_FORM, steps: [] };
  if (best) {
    if (best.kind === "schedule") {
      form.triggerKind = "schedule";
      form.schedule = best.schedule ?? "0 3 * * 0";
      reasons.push(`schedule (matched "${best.words.find((w) => norm.includes(w))}")`);
    } else {
      form.triggerKind = "signal";
      form.signalType = best.signal;
      reasons.push(`${signalLabel(best.signal)} (matched "${best.words.find((w) => norm.includes(w))}")`);
    }
  } else {
    form.triggerKind = "signal";
    form.signalType = "object.drift";
    reasons.push("Configuration drifted (default trigger)");
  }

  const taken: string[] = [];
  form.steps = actions.map((a, i) => {
    const id = suggestStepId(a.name, taken);
    taken.push(id);
    reasons.push(`do ${humanizeActionName(a.name)}`);
    return {
      key: i,
      id,
      action_type_ref: a.name,
      guard_rule_ref: "",
      compensated_by: "",
      on_failure: "",
      params: {},
    };
  });
  if (form.steps.length === 0) form.steps = [emptyStep(0)];

  // Suggested name from the first action; the operator can rename it.
  const firstAction = actions[0];
  if (firstAction) {
    const slug = suggestStepId(firstAction.name, []).replace(/_/g, "-");
    form.name = `${slug}-workflow`;
  }
  form.description = text.trim().slice(0, 200);
  return { form, reasons, triggerConfident, actionMatchesTruncated };
}

function phraseIsNegated(normalizedText: string, phrase: string): boolean {
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  return new RegExp(`(?:do\\s+not|don\\s+t|never|avoid|without)\\s+(?:\\w+\\s+){0,2}${escaped}`).test(
    normalizedText,
  );
}
