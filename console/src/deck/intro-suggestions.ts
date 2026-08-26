/**
 * Intro suggestions - context-aware starter questions for the empty deck.
 *
 * Pure and DOM-free so it is unit-tested directly. Given the current
 * ``ViewSnapshot`` facts, it surfaces the questions most worth asking right now
 * (failed actions, approvals waiting, denials, stuck work) ahead of a couple of
 * evergreen prompts. When nothing notable is on screen it falls back to the
 * generic set, and with no snapshot at all it offers the route-discovery prompt.
 */

import type { ViewFact, ViewSnapshot } from "./context";
import { tForLocale, type Locale } from "../i18n";

const MAX_SUGGESTIONS = 5;

/** Read a fact as a non-negative count; non-numeric or missing -> 0. */
function count(facts: readonly ViewFact[], key: string): number {
  for (const f of facts) {
    if (f.key !== key) continue;
    if (typeof f.value === "number") return Number.isFinite(f.value) ? f.value : 0;
    if (typeof f.value === "string") {
      const n = Number(f.value);
      return Number.isFinite(n) ? n : 0;
    }
    return 0;
  }
  return 0;
}

export function introSuggestions(
  snapshot: ViewSnapshot | null,
  locale: Locale = "en",
): readonly string[] {
  if (snapshot === null) return [tForLocale(locale, "deck.starterSuggestions.routes")];
  const facts = snapshot.facts;
  const out: string[] = [];

  if (count(facts, "attention.failed") > 0) {
    out.push(tForLocale(locale, "deck.starterSuggestions.failed"));
  }
  if (count(facts, "attention.hil") > 0 || count(facts, "gate.hil") > 0) {
    out.push(tForLocale(locale, "deck.starterSuggestions.approval"));
  }
  if (count(facts, "gate.deny") > 0) {
    out.push(tForLocale(locale, "deck.starterSuggestions.denied"));
  }
  if (count(facts, "attention.stuck") > 0) {
    out.push(tForLocale(locale, "deck.starterSuggestions.stuck"));
  }

  // Evergreen prompts, added after the situational ones.
  out.push(tForLocale(locale, "deck.starterSuggestions.screen"));
  out.push(tForLocale(locale, "deck.starterSuggestions.tierMix"));

  // De-duplicate while preserving order, then cap.
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const s of out) {
    if (seen.has(s)) continue;
    seen.add(s);
    unique.push(s);
  }
  return unique.slice(0, MAX_SUGGESTIONS);
}
