/**
 * Deterministic answerer helpers - snapshot query utilities and small
 * Answer builders shared across the resolvers and per-route answerers.
 *
 * SRP: pure functions. No React, no I/O. Given a ViewSnapshot and a
 * column / value / row, look things up and shape them into an Answer.
 *
 * Extracted from `answerer.ts` so the resolvers and route answerers
 * import one utility surface instead of each file redefining its own.
 */

import type { GlossaryTerm, ViewSnapshot } from "./context";
import type { Answer, Citation } from "./answerer.catalogs";

// ---------------------------------------------------------------------------
// Snapshot lookups
// ---------------------------------------------------------------------------

/** Distinct non-empty string values of one column across every records array. */
export function collectColumnValues(snapshot: ViewSnapshot, column: string): readonly string[] {
  const out = new Set<string>();
  const records = snapshot.records ?? {};
  for (const key of Object.keys(records)) {
    for (const row of records[key] ?? []) {
      const v = row[column];
      if (typeof v === "string" && v.trim() && v !== "-") out.add(v);
    }
  }
  return [...out];
}

/** Rows (across all records arrays) whose `column` equals `value`. */
export function rowsWhere(
  snapshot: ViewSnapshot,
  column: string,
  value: string,
): readonly Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const records = snapshot.records ?? {};
  for (const key of Object.keys(records)) {
    for (const row of records[key] ?? []) {
      if (row[column] === value) out.push(row);
    }
  }
  return out;
}

export function firstString(row: Record<string, unknown>, ...keys: readonly string[]): string | null {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

export function capitalize(s: string): string {
  return s.length === 0 ? s : s[0]!.toUpperCase() + s.slice(1);
}

/** Rows sorted oldest-first by `recorded_at` (rows without a stamp keep order). */
export function chronological(
  rows: readonly Record<string, unknown>[],
): readonly Record<string, unknown>[] {
  return [...rows].sort((a, b) => {
    const ta = new Date(String(a.recorded_at ?? "")).getTime();
    const tb = new Date(String(b.recorded_at ?? "")).getTime();
    if (Number.isNaN(ta) || Number.isNaN(tb)) return 0;
    return ta - tb;
  });
}

// ---------------------------------------------------------------------------
// Glossary explanations
// ---------------------------------------------------------------------------

/** Plain definition of one glossary term. */
export function explainTerm(term: GlossaryTerm): Answer {
  const tech = term.tech ? ` (internally \`${term.tech}\`)` : "";
  const see = term.seeAlso ? ` Open the ${term.seeAlso} panel to dig deeper.` : "";
  return {
    text: `${capitalize(term.term)}${tech}: ${term.plain}.${see}`,
    citations: [{ label: term.term, value: term.tech ?? "" }],
    followUps: term.seeAlso ? [`open ${term.seeAlso}`] : [],
  };
}

/** Name the term a quoted value belongs to and summarise its group + why. */
export function explainValue(value: string, term: GlossaryTerm, snapshot: ViewSnapshot): Answer {
  const rows = term.match ? rowsWhere(snapshot, term.match, value) : [];
  const ordered = chronological(rows);
  const agents = [...new Set(ordered.map((r) => String(r.agent ?? r.actor ?? "")).filter(Boolean))];
  const groupText =
    ordered.length > 0
      ? ` It has ${ordered.length} step(s) on this screen${
          agents.length > 0 ? ` (${agents.slice(0, 6).join(" -> ")})` : ""
        }.`
      : "";
  const why = ordered.length > 0 ? firstString(ordered[0]!, "detail", "summary", "reason") : null;
  const whyText = why ? ` It started because: ${why}` : "";
  const see = term.seeAlso ? ` Open ${term.seeAlso} to reconstruct the full chain.` : "";
  return {
    text: `${value} is a ${term.term} - ${term.plain}.${groupText}${whyText}${see}`,
    citations: [
      { label: term.term, value },
      ...(ordered.length > 0 ? [{ label: "steps", value: String(ordered.length) }] : []),
    ],
    followUps: why ? [] : [`why did ${value} start?`],
  };
}

// ---------------------------------------------------------------------------
// Causal narrative helpers
// ---------------------------------------------------------------------------

/**
 * Render the ordered hand-off chain for a multi-step incident: each step's
 * agent, action, and outcome, in time order. Returns "" for a single step
 * (the root-cause narrative already covers it). Read-only, from records only.
 */
export function describeChain(ordered: readonly Record<string, unknown>[]): string {
  if (ordered.length < 2) return "";
  const steps = ordered.slice(0, 8).map((r, i) => {
    const agent = String(r.agent ?? r.actor ?? "?");
    const kind = String(r.action_kind ?? r.stage ?? "step");
    const outcome = firstString(r, "outcome", "decision");
    const tail = outcome ? ` -> ${outcome}` : "";
    return `${i + 1}. ${agent} ${kind}${tail}`;
  });
  return `\nHand-off chain:\n${steps.join("\n")}`;
}

/** The rows a causal question is about (quoted chip -> selection -> newest). */
export function causalTargetRows(
  q: string,
  snapshot: ViewSnapshot,
): readonly Record<string, unknown>[] {
  // 1) A correlation the operator quoted in the query.
  const corrValues = collectColumnValues(snapshot, "correlation_id");
  const quoted = corrValues.find((v) => v.length >= 2 && q.includes(v.toLowerCase()));
  if (quoted) return rowsWhere(snapshot, "correlation_id", quoted);

  // 2) The screen's current selection, if it published one.
  const selected = selectionRows(snapshot);
  if (selected.length > 0) return selected;

  // 3) The single newest row that actually carries a narrative.
  const records = snapshot.records ?? {};
  const withNarrative: Record<string, unknown>[] = [];
  for (const key of Object.keys(records)) {
    for (const row of records[key] ?? []) {
      if (firstString(row, "detail", "summary", "reason")) withNarrative.push(row);
    }
  }
  if (withNarrative.length === 0) return [];
  const newest = chronological(withNarrative).at(-1)!;
  // If it belongs to a correlation, return the whole incident so the earliest
  // step (the trigger) is chosen by the caller.
  const corr = firstString(newest, "correlation_id");
  return corr ? rowsWhere(snapshot, "correlation_id", corr) : [newest];
}

/** Rows the screen marked as the current selection (records key `selected_*`). */
export function selectionRows(snapshot: ViewSnapshot): readonly Record<string, unknown>[] {
  const records = snapshot.records ?? {};
  const out: Record<string, unknown>[] = [];
  for (const key of Object.keys(records)) {
    if (key === "selected" || key.startsWith("selected_")) {
      for (const row of records[key] ?? []) out.push(row);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Generic search + fact helpers
// ---------------------------------------------------------------------------

/** One-line summary of an arbitrary records row for the generic search. */
export function summariseRow(r: Record<string, unknown>): string {
  const head =
    firstString(r, "action_kind", "id", "action_type", "term") ??
    String(r.agent ?? r.actor ?? "row");
  const detail = firstString(r, "summary", "detail", "reason", "resource_type");
  const corr = firstString(r, "correlation_id");
  const parts = [head];
  if (corr) parts.push(`(${corr})`);
  if (detail) parts.push(`- ${detail}`);
  return parts.join(" ");
}

export const GENERIC_STOPWORDS: ReadonlySet<string> = new Set([
  "how", "the", "and", "for", "what", "which", "does", "did", "why", "who",
  "this", "that", "show", "list", "there", "here", "was", "were", "are",
]);

export function factToCitation(f: { key: string; value: unknown }): Citation {
  return { label: f.key, value: f.value === null ? "-" : String(f.value) };
}

export function findFact(snapshot: ViewSnapshot, key: string): string | number | boolean | null {
  const f = snapshot.facts.find((x) => x.key === key);
  return f?.value ?? null;
}

// ---------------------------------------------------------------------------
// Default follow-up suggestions (per route)
// ---------------------------------------------------------------------------

export function defaultFollowUps(snapshot: ViewSnapshot): readonly string[] {
  switch (snapshot.routeId) {
    case "live":
      return [
        "how many tiles need attention?",
        "what verticals are represented?",
        "which tiles are failed?",
        "what is the current T0 share?",
      ];
    case "dashboard":
      return [
        "what is the shadow share?",
        "how many events are enforced?",
        "which action kinds are most common?",
      ];
    case "audit":
      return [
        "how many audit rows are visible?",
        "what modes are represented?",
        "what is the latest entry?",
      ];
    case "rules":
      return [
        "how many rules are active?",
        "what categories are available?",
        "how do I find a specific rule?",
      ];
    case "hil-queue":
      return ["how many items are waiting?", "list all pending kinds"];
    case "promotion-gates":
      return [
        "which ActionTypes are ready to promote?",
        "which are blocked?",
        "which have policy escapes?",
      ];
    case "blast-radius":
      return [
        "how many resources are affected?",
        "was the traversal truncated?",
      ];
    case "trace":
      return [
        "how many steps did this trace produce?",
        "what was the terminal stage?",
      ];
    case "ontology":
      return [
        "how many ObjectTypes are registered?",
        "how many LinkTypes are registered?",
      ];
    default:
      return [];
  }
}

// ---------------------------------------------------------------------------
// Small Answer builder
// ---------------------------------------------------------------------------

export function listAnswer(title: string, items: readonly string[]): Answer {
  return {
    text: `${title}:\n` + items.map((s) => `- ${s}`).join("\n"),
    citations: [{ label: title, value: `${items.length} item(s)` }],
    followUps: [],
  };
}
