/**
 * Deterministic answerer - pattern-matches operator questions against
 * the current ViewSnapshot and returns a grounded answer.
 *
 * Single responsibility: given (query, snapshot) -> Answer. No I/O, no
 * LLM, no side effects. When a future LLM narrator lands, it will
 * replace this module behind the same interface; every route describer
 * stays the same.
 *
 * The answerer is intentionally rule-based so it works offline, in
 * every deployment, with zero credentials. It also anchors expectations:
 * the "answer any question on screen" promise means we ground on
 * structured facts we KNOW we captured, not on hallucinated free text.
 */

import type { GlossaryTerm, ViewSnapshot } from "./context";
import { TERMS } from "./glossary";

/** Static, universal glossary the deck falls back to when no route has
 *  published a snapshot yet - so a bare "what is HIL?" is answered even from
 *  the empty deck instead of a "open a route first" shrug.
 *
 *  Only high-signal FDAI terms are here (correlation_id, HIL, ActionType,
 *  ...); ambiguous generic words that also occur in unrelated contexts
 *  (mode, agent, tier, outcome) are DELIBERATELY excluded from the null-
 *  snapshot fallback so 'what is dark mode?' does not hijack the response.
 *  Those generic terms remain resolvable from a route's own declared
 *  glossary (where the surrounding facts / records give real context). */
const STATIC_GLOSSARY: readonly GlossaryTerm[] = [
  TERMS.correlationId,
  TERMS.eventId,
  TERMS.actionKind,
  TERMS.gateDecision,
  TERMS.waterfall,
  TERMS.hil,
  TERMS.shadowMode,
  TERMS.actionType,
  TERMS.blastRadius,
];

export interface Citation {
  /** Label the deck shows next to the cited value, e.g. "eps · 4.2". */
  readonly label: string;
  /** Optional value pretty-print (falls back to label). */
  readonly value?: string;
}

export interface Answer {
  /** Multi-line markdown-free reply (rendered as text). */
  readonly text: string;
  /** Facts the deck highlights so the operator sees the source. */
  readonly citations: readonly Citation[];
  /** Suggested follow-up questions the operator can click. */
  readonly followUps: readonly string[];
}

const NO_CONTEXT_FOLLOWUPS: readonly string[] = [
  "what is HIL?",
  "what is a correlation id?",
  "what is the trust router?",
  "what is shadow mode?",
];

const NO_CONTEXT: Answer = {
  text:
    "No route has published a view snapshot yet. Open Live, Dashboard, " +
    "Audit, HIL, Trace, Blast Radius, Promotion, or Ontology and try again. " +
    "You can still ask FDAI concept questions (e.g. 'what is HIL?').",
  citations: [],
  followUps: NO_CONTEXT_FOLLOWUPS,
};

export function answer(query: string, snapshot: ViewSnapshot | null): Answer {
  if (snapshot === null) {
    // No route open yet - still resolve FDAI concept questions from the
    // static universal glossary and catalog list questions ('list the
    // agents / tiers / roles') so early questions get real answers instead
    // of a "open a route first" shrug.
    const q = query.toLowerCase().trim();
    if (q.length > 0) {
      const list = resolveList(q);
      if (list) return list;
      const hit = resolveStaticGlossary(q);
      if (hit) return hit;
    }
    return NO_CONTEXT;
  }
  const q = query.toLowerCase().trim();
  if (q.length === 0) {
    return {
      text: `I can see the ${snapshot.routeLabel}. ${snapshot.headline}`,
      citations: snapshot.facts.slice(0, 6).map(factToCitation),
      followUps: defaultFollowUps(snapshot),
    };
  }

  // Meta questions -------------------------------------------------------
  if (/what.*(you|deck).*see|what.*on.*screen|current.*view/.test(q)) {
    return {
      text: `${snapshot.routeLabel} - ${snapshot.headline}`,
      citations: snapshot.facts.slice(0, 10).map(factToCitation),
      followUps: defaultFollowUps(snapshot),
    };
  }

  // Generic, screen-agnostic resolvers ----------------------------------
  // These run BEFORE the route-specific enhancers so vocabulary ("what is
  // corr-j") and causal ("why did this start") questions are answered from the
  // screen's own declared glossary + records on ANY route - including screens
  // that ship no bespoke answerer (agent-activity, pantheon, workflow-builder,
  // and any future screen). A screen becomes explainable by declaring its
  // purpose/glossary and keeping causal fields in its records, not by adding a
  // per-route branch here.
  const deckMetaHit = resolveDeckMeta(q, snapshot);
  if (deckMetaHit) return deckMetaHit;
  const listHit = resolveList(q);
  if (listHit) return listHit;
  const causalHit = resolveCausal(q, snapshot);
  if (causalHit) return causalHit;
  const glossaryHit = resolveGlossary(q, snapshot);
  if (glossaryHit) return glossaryHit;

  // Route-scoped enhancers ----------------------------------------------
  if (snapshot.routeId === "live") return answerLive(q, snapshot);
  if (snapshot.routeId === "dashboard") return answerDashboard(q, snapshot);
  if (snapshot.routeId === "audit") return answerAudit(q, snapshot);
  if (snapshot.routeId === "rules") return answerRules(q, snapshot);
  if (snapshot.routeId === "hil-queue") return answerHil(q, snapshot);
  if (snapshot.routeId === "promotion-gates") return answerPromotion(q, snapshot);
  if (snapshot.routeId === "blast-radius") return answerBlast(q, snapshot);
  if (snapshot.routeId === "trace") return answerTrace(q, snapshot);
  if (snapshot.routeId === "ontology") return answerOntology(q, snapshot);

  // Generic fallback: search the records + quote facts, so a screen with no
  // bespoke answerer still grounds in what it published instead of shrugging.
  return genericAnswer(q, snapshot);
}

// ---------------------------------------------------------------------------
// Screen-agnostic resolvers (glossary, causal, generic search)
// ---------------------------------------------------------------------------

/** Distinct non-empty string values of one column across every records array. */
function collectColumnValues(snapshot: ViewSnapshot, column: string): readonly string[] {
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
function rowsWhere(
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

function firstString(row: Record<string, unknown>, ...keys: readonly string[]): string | null {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s[0]!.toUpperCase() + s.slice(1);
}

/** Rows sorted oldest-first by `recorded_at` (rows without a stamp keep order). */
function chronological(
  rows: readonly Record<string, unknown>[],
): readonly Record<string, unknown>[] {
  return [...rows].sort((a, b) => {
    const ta = new Date(String(a.recorded_at ?? "")).getTime();
    const tb = new Date(String(b.recorded_at ?? "")).getTime();
    if (Number.isNaN(ta) || Number.isNaN(tb)) return 0;
    return ta - tb;
  });
}

/**
 * Explain a term the screen declared. Handles two shapes:
 *  - a value chip the operator quoted (e.g. "corr-j") that lives in a glossed
 *    records column -> name the term AND summarise the group it identifies, and
 *  - the term name / tech token appearing in the query -> plain definition.
 * Returns null when the screen declares no glossary or nothing matches.
 */
function resolveGlossary(q: string, snapshot: ViewSnapshot): Answer | null {
  const glossary = snapshot.glossary ?? [];
  if (glossary.length === 0) return null;

  // 1) Value chip: "what is corr-j" - the operator quotes an on-screen value.
  for (const term of glossary) {
    if (!term.match) continue;
    const values = collectColumnValues(snapshot, term.match);
    const hit = values.find((v) => v.length >= 2 && q.includes(v.toLowerCase()));
    if (hit) return explainValue(hit, term, snapshot);
  }

  // 2) Term name / tech token in the query - only when the operator is asking
  //    what/which/explain (so a passing mention of "mode" is not hijacked).
  // Korean markers (\uXXXX to keep the source ASCII per the language policy):
  // what / which-thing / meaning / explain / sense.
  const asking =
    /\bwhat\b|\bwhich\b|\bexplain\b|\bdefine\b|\bmean(s|ing)?\b|\bwhats\b|\bwhat's\b/.test(q) ||
    /\uBB34\uC5C7|\uBB50|\uBB54|\uBB34\uC2A8|\uC124\uBA85|\uC758\uBBF8|\uB73B/.test(q);
  if (!asking) return null;
  for (const term of glossary) {
    const names = [term.term.toLowerCase(), term.tech?.toLowerCase()].filter(
      (n): n is string => Boolean(n),
    );
    if (names.some((n) => q.includes(n))) return explainTerm(term);
  }
  return null;
}

/**
 * Resolve a term question from the static universal glossary - used when NO
 * route has published a snapshot yet, so early "what is HIL?" still gets a
 * real definition instead of a "open a route first" shrug. Same asking-gate
 * as :func:`resolveGlossary` so a passing mention like "mode" is not
 * hijacked into a definition.
 */
function resolveStaticGlossary(q: string): Answer | null {
  const asking =
    /\bwhat\b|\bwhich\b|\bexplain\b|\bdefine\b|\bmean(s|ing)?\b|\bwhats\b|\bwhat's\b/.test(q) ||
    /\uBB34\uC5C7|\uBB50|\uBB54|\uBB34\uC2A8|\uC124\uBA85|\uC758\uBBF8|\uB73B/.test(q);
  if (!asking) return null;
  for (const term of STATIC_GLOSSARY) {
    const names = [term.term.toLowerCase(), term.tech?.toLowerCase()].filter(
      (n): n is string => Boolean(n),
    );
    if (names.some((n) => q.includes(n))) return explainTerm(term);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Deck-meta resolvers - "help", "what can I do here", "how do I search"
// ---------------------------------------------------------------------------

/** Per-route "what can I do on this screen" hints. Kept declarative + English
 *  source so the same map serves the deterministic answerer AND the LLM path
 *  (route hints are injected into the snapshot the model reads). Exported so
 *  the backend client (`backend.ts`) can attach the hint to `view_context`
 *  as `_route_actions` - then the LLM answers 'what can I do here?' from
 *  the same source of truth as the deterministic fallback, not by inventing. */
export const ROUTE_ACTION_HINTS: Readonly<Record<string, string>> = {
  live:
    "Live cockpit: watch tiles as events flow in, click a tile to open its trace, " +
    "hover a tile to see its action + resource, and read the tier/gate mix at the top.",
  dashboard:
    "Dashboard: read shadow vs enforce share, top action kinds, and HIL pending; " +
    "narrow the window from the header controls; drill into a bar to jump to Audit.",
  audit:
    "Audit: search rows by seq/correlation/action, filter by mode (shadow/enforce), " +
    "click a row to open its trace; export is via the header if enabled.",
  rules:
    "Rules: search by id/category/severity, click a rule to open its detail drawer " +
    "with provenance + remediation + shadow accuracy; enable/disable is governance-only.",
  "hil-queue":
    "HIL queue: read pending approvals and their risk reason; approvals happen in " +
    "Teams/ChatOps Adaptive Cards, never in this console (approve/reject are external).",
  "promotion-gates":
    "Promotion gates: see which ActionTypes are ready to promote and which are blocked; " +
    "promotion itself is a governance PR (this console only shows the readiness).",
  "blast-radius":
    "Blast radius: pick an action to see the resources it could touch and whether the " +
    "traversal hit the cap; this is a preview - the risk gate enforces the cap.",
  trace:
    "Trace: reconstruct the full chain for one correlation id - detection, judgment, " +
    "approval, execution, audit. Follow the ordered rows to read the hand-off cascade.",
  ontology:
    "Ontology: browse ObjectTypes / LinkTypes / ActionTypes; open one to see its " +
    "declared roles (initiators, judge, executor, approver, auditor) and rollback contract.",
  pantheon:
    "Agent pantheon: the 15 named agents that own the loop; hover an agent to see " +
    "its two-port responsibilities and its typed contract.",
  "agent-activity":
    "Agent activity: per-agent timeline from the audit log; group by correlation id " +
    "to see the hand-off cascade for one incident.",
  "workflow-builder":
    "Workflow builder: compose a pipeline; save produces a governance PR - nothing " +
    "runs from this screen directly.",
  provision:
    "Provision: watch a bootstrap pipeline (plan/apply); progress streams live; " +
    "no privileged action runs from the console (executor holds the only identity).",
};

/** Deck / operator-meta questions ("help", "what can I do here", "how do I
 *  search / export / filter"). Kept read-only + narrow so genuine data queries
 *  are not hijacked. Returns null for anything not clearly a deck-meta ask. */
function resolveDeckMeta(q: string, snapshot: ViewSnapshot): Answer | null {
  // Help / "what can you do" - describe the deck itself.
  if (/^\??help\?*$|^\?+$|\bwhat can you (do|help)\b|\bhow (do|can) i use (the deck|this deck|you)\b/.test(q)) {
    return {
      text:
        "I'm the FDAI console deck - a read-only screen-aware translator. " +
        "Ask me about anything on the current page (numbers, rows, chips, terms, " +
        "why an incident started, who can approve what). I ground every answer in " +
        "the snapshot on the right of this overlay; I never execute an action. " +
        "Try: 'what is HIL?', 'why did corr-j start?', 'what can I do here?'.",
      citations: [{ label: "route", value: snapshot.routeLabel }],
      followUps: [
        "what can I do here?",
        "what do you see on this screen?",
        "what is HIL?",
      ],
    };
  }

  // "What can I do here?" - per-route action hint (deterministic; the LLM
  // path additionally injects the RBAC capability block).
  if (/\bwhat can i do (here|on (this|the) (page|screen))\b|\bwhat.*(can i do here)\b|\bwhat.*this (page|screen) for\b/.test(q)) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    const generic =
      "This console is read-only: you can search, filter, and drill into rows to " +
      "understand an incident; nothing executes from a button here. Approvals happen " +
      "in Teams/ChatOps, and changes are delivered as governance PRs.";
    return {
      text: hint ? `${hint} ${generic}` : `${snapshot.routeLabel}: ${generic}`,
      citations: [{ label: "route", value: snapshot.routeLabel }],
      followUps: ["what is HIL?", "what does an Approver do?"],
    };
  }

  // "How do I search / filter / export / open X" - short "look at the header/
  // detail drawer" hint. Very narrow so screen data questions are not caught.
  if (/\bhow (do|can) i (search|filter|export|open|drill|navigate)\b/.test(q)) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    return {
      text:
        (hint ? `${hint} ` : "") +
        "Search + filter live in the header of each list; click a row to open its detail drawer.",
      citations: [{ label: "route", value: snapshot.routeLabel }],
      followUps: [],
    };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Catalog list resolvers - concrete lists that don't depend on the snapshot.
// "list the agents / tiers / roles / verticals / safety invariants / ActionType
// roles" answered from the fixed architecture (never invented). Guarded by an
// explicit "list" verb + a catalog keyword so screen data lists ('list rules',
// 'list tiles') fall through to the per-route enhancer.
// ---------------------------------------------------------------------------

const PANTHEON_AGENTS: readonly string[] = [
  "Odin (Master Planner - arbitrates cross-vertical, final tie-breaker)",
  "Thor (Responder - dispatcher + only privileged executor; never judges)",
  "Forseti (Judge - issues Verdict after mixed-model cross-check + verifier + grounding)",
  "Huginn (Event Collector - deterministic-first sensing, no LLM in hot-path)",
  "Heimdall (Observer - deterministic-first sensing, no LLM in hot-path)",
  "Var (Approver - HIL approval principal; distinct from Thor, no self-approval)",
  "Vidar (Recovery - rollback + DR failover principal)",
  "Bragi (Narrator - conversational-port translator only, never executes)",
  "Saga (Auditor - append-only audit + Handoff-to-GitHub-issue executor)",
  "Mimir (Rule Steward - governance staff)",
  "Norns (Learner - governance staff)",
  "Muninn (Memory - governance staff)",
  "Njord (Cost specialist - advisory to Forseti)",
  "Freyr (Capacity specialist - advisory to Forseti)",
  "Loki (Chaos specialist - advisory to Forseti)",
];

const TRUST_TIERS: readonly string[] = [
  "T0 - deterministic policy / checklist (target 70-80%): policy eval, config drift, what-if.",
  "T1 - lightweight similarity + small model (15-20%): reuse of past incident actions.",
  "T2 - frontier-LLM reasoning (5-10%, novel only): must clear the quality gate before executing.",
];

const RBAC_ROLES: readonly string[] = [
  "Reader - view every screen (read-only) and ask this deck.",
  "Contributor - + author draft remediation / governance PRs.",
  "Approver - + review governance PRs and approve/reject runtime HIL, exemptions, overrides, quorum promotions (via Teams/ChatOps, never self-approval).",
  "Owner - + kill-switch, emergency access, group membership, infra IaC.",
  "BreakGlass - emergency-only, activated out of band (incident id + timebox).",
];

const VERTICALS: readonly string[] = [
  "Change Safety (safe change + drift remediation)",
  "Resilience (disaster recovery + chaos/resilience testing)",
  "Cost Governance (FinOps)",
];

const SAFETY_INVARIANTS: readonly string[] = [
  "stop-condition (kill-switch for the action)",
  "rollback path (tested; declared by rollback_contract)",
  "blast-radius cap (scope / batch / rate)",
  "audit-log entry (append-only)",
];

const ACTION_TYPE_ROLES: readonly string[] = [
  "initiators (who may raise this action)",
  "judge (Forseti - who decides auto/hil/deny/abstain)",
  "executor (Thor - the sole privileged mutator)",
  "approver (Var - required for high-risk / HIL)",
  "auditor (Saga - append-only audit + Handoff)",
];

function _listAnswer(title: string, items: readonly string[]): Answer {
  return {
    text: `${title}:\n` + items.map((s) => `- ${s}`).join("\n"),
    citations: [{ label: title, value: `${items.length} item(s)` }],
    followUps: [],
  };
}

/** Catalog list questions ("list the 15 agents", "list the tiers", "list all
 *  roles", "list the verticals", "list the safety invariants"). Answered from
 *  the fixed architecture, so a screen with no records still gets the list. */
function resolveList(q: string): Answer | null {
  const listVerb =
    /\blist\b|\bshow\b|\bwhat are (the |all )?/.test(q) ||
    /\ubaa9\ub85d|\ubcf4\uc5ec\uc918/.test(q); // KO: list / show
  if (!listVerb) return null;
  // ActionType roles first: the query "list actiontype roles" also contains
  // the word "roles" and would otherwise land on the RBAC branch.
  if (/\bactiontype\b|\baction type\b|\baction-type\b|\baction_type\b|\baction (kind|role)/.test(q)) {
    return _listAnswer("The five roles every ActionType binds", ACTION_TYPE_ROLES);
  }
  if (/\bagent(s)?\b|\bpantheon\b|\uc5d0\uc774\uc804\ud2b8/.test(q)) {
    return _listAnswer("The 15 pantheon agents", PANTHEON_AGENTS);
  }
  if (/\btier(s)?\b|\bt0\b|\bt1\b|\bt2\b|\ud2f0\uc5b4/.test(q)) {
    return _listAnswer("The three trust tiers", TRUST_TIERS);
  }
  if (/\brole(s)?\b|\brbac\b|\bpermission(s)?\b|\uc5ed\ud560/.test(q)) {
    return _listAnswer("The RBAC roles (Entra App Roles, cumulative)", RBAC_ROLES);
  }
  if (/\bvertical(s)?\b|\ubc84\ud2f0\uceec/.test(q)) {
    return _listAnswer("The three initial verticals", VERTICALS);
  }
  if (/\bsafety\b|\binvariant(s)?\b|\uc548\uc804/.test(q)) {
    return _listAnswer("The four safety invariants", SAFETY_INVARIANTS);
  }
  return null;
}

/** Plain definition of one glossary term. */
function explainTerm(term: GlossaryTerm): Answer {
  const tech = term.tech ? ` (internally \`${term.tech}\`)` : "";
  const see = term.seeAlso ? ` Open the ${term.seeAlso} panel to dig deeper.` : "";
  return {
    text: `${capitalize(term.term)}${tech}: ${term.plain}.${see}`,
    citations: [{ label: term.term, value: term.tech ?? "" }],
    followUps: term.seeAlso ? [`open ${term.seeAlso}`] : [],
  };
}

/** Name the term a quoted value belongs to and summarise its group + why. */
function explainValue(value: string, term: GlossaryTerm, snapshot: ViewSnapshot): Answer {
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

/**
 * Answer "why did this start / what triggered it" by quoting the causal
 * narrative already recorded on the target rows (`detail` -> `summary` ->
 * `reason`). The target is: the correlation the operator quoted, else the
 * screen's selection, else the most recent row that carries a narrative.
 * Returns null for non-causal questions or when no narrative is on screen.
 */
function resolveCausal(q: string, snapshot: ViewSnapshot): Answer | null {
  // Korean markers (\uXXXX, source stays ASCII): why / cause / reason /
  // occur / start.
  const causal =
    /\bwhy\b|\bcause[ds]?\b|\breason\b|\btrigger(ed)?\b|\bstart(ed)?\b|\bhappen(ed)?\b/.test(q) ||
    /\uC65C|\uC6D0\uC778|\uC774\uC720|\uBC1C\uC0DD|\uC2DC\uC791/.test(q);
  if (!causal) return null;
  const rows = causalTargetRows(q, snapshot);
  if (rows.length === 0) return null;
  const ordered = chronological(rows);
  const target = ordered[0]!;
  const narrative = firstString(target, "detail", "summary", "reason");
  if (!narrative) return null;
  const corr = firstString(target, "correlation_id");
  const label = corr ? `${corr}` : String(target.action_kind ?? "this");
  // Multi-hop: after the root cause, reconstruct the ordered hand-off chain
  // from the on-screen rows so the operator reads the whole story (root ->
  // ... -> terminal), grounded in records - no extra backend call.
  const chain = describeChain(ordered);
  return {
    text: `${label} started because: ${narrative}${chain}`,
    citations: [
      ...(corr ? [{ label: "correlation", value: corr }] : []),
      { label: "steps", value: String(ordered.length) },
    ],
    followUps: corr ? [`what is ${corr}?`, `open trace`] : [],
  };
}

/**
 * Render the ordered hand-off chain for a multi-step incident: each step's
 * agent, action, and outcome, in time order. Returns "" for a single step
 * (the root-cause narrative already covers it). Read-only, from records only.
 */
function describeChain(ordered: readonly Record<string, unknown>[]): string {
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
function causalTargetRows(
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
function selectionRows(snapshot: ViewSnapshot): readonly Record<string, unknown>[] {
  const records = snapshot.records ?? {};
  const out: Record<string, unknown>[] = [];
  for (const key of Object.keys(records)) {
    if (key === "selected" || key.startsWith("selected_")) {
      for (const row of records[key] ?? []) out.push(row);
    }
  }
  return out;
}

/**
 * Last-resort grounded answer for a screen with no bespoke enhancer: search
 * the published records for the query tokens and quote matches, else restate
 * the headline + purpose and offer the glossary terms the screen declared.
 */
function genericAnswer(q: string, snapshot: ViewSnapshot): Answer {
  const terms = (q.match(/[a-z0-9-]{3,}/g) ?? []).filter(
    (w) => !GENERIC_STOPWORDS.has(w),
  );
  if (terms.length > 0) {
    const records = snapshot.records ?? {};
    const hits: Record<string, unknown>[] = [];
    for (const key of Object.keys(records)) {
      for (const row of records[key] ?? []) {
        const hay = JSON.stringify(row).toLowerCase();
        if (terms.some((w) => hay.includes(w))) hits.push(row);
      }
      if (hits.length >= 6) break;
    }
    if (hits.length > 0) {
      const sample = hits.slice(0, 6);
      return {
        text:
          `${hits.length} matching row(s) on this screen:\n` +
          sample.map((r) => `- ${summariseRow(r)}`).join("\n"),
        citations: sample.map((r) => ({
          label: String(r.action_kind ?? r.agent ?? r.id ?? "row"),
          value: String(r.correlation_id ?? r.mode ?? r.outcome ?? "-"),
        })),
        followUps: [],
      };
    }
  }
  const purpose = snapshot.purpose ? ` ${snapshot.purpose}` : "";
  const glossary = snapshot.glossary ?? [];
  const ask =
    glossary.length > 0
      ? ` Ask me what these mean: ${glossary.slice(0, 4).map((g) => g.term).join(", ")}.`
      : "";
  return {
    text: `${snapshot.routeLabel} - ${snapshot.headline}.${purpose}${ask}`,
    citations: snapshot.facts.slice(0, 8).map(factToCitation),
    followUps: glossary.slice(0, 3).map((g) => `what is ${g.term}?`),
  };
}

const GENERIC_STOPWORDS: ReadonlySet<string> = new Set([
  "how", "the", "and", "for", "what", "which", "does", "did", "why", "who",
  "this", "that", "show", "list", "there", "here", "was", "were", "are",
]);

/** One-line summary of an arbitrary records row for the generic search. */
function summariseRow(r: Record<string, unknown>): string {
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function factToCitation(f: { key: string; value: unknown }): Citation {
  return { label: f.key, value: f.value === null ? "-" : String(f.value) };
}

function findFact(snapshot: ViewSnapshot, key: string): string | number | boolean | null {
  const f = snapshot.facts.find((x) => x.key === key);
  return f?.value ?? null;
}

function defaultFollowUps(snapshot: ViewSnapshot): readonly string[] {
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
// Route-specific answerers
// ---------------------------------------------------------------------------

function answerLive(q: string, snapshot: ViewSnapshot): Answer {
  const tiles = (snapshot.records?.tiles ?? []) as readonly Record<string, unknown>[];
  const attention = findFact(snapshot, "attention.total") ?? 0;

  if (/attention|need.*(look|action)|urgent/.test(q)) {
    const hil = findFact(snapshot, "attention.hil") ?? 0;
    const deny = findFact(snapshot, "attention.deny") ?? 0;
    const failed = findFact(snapshot, "attention.failed") ?? 0;
    const stuck = findFact(snapshot, "attention.stuck") ?? 0;
    return {
      text:
        Number(attention) === 0
          ? "No attention needed. Autonomy is holding: 0 HIL, 0 deny, 0 failed, 0 stuck."
          : `${attention} items need attention: ${hil} HIL waiting, ${deny} denied, ${failed} failed, ${stuck} stuck (>20s without reaching audit).`,
      citations: [
        { label: "HIL", value: String(hil) },
        { label: "Deny", value: String(deny) },
        { label: "Failed", value: String(failed) },
        { label: "Stuck", value: String(stuck) },
      ],
      followUps: ["which tiles are failed?", "which are stuck?"],
    };
  }

  if (/vertical|change|resilience|cost/.test(q)) {
    const change = findFact(snapshot, "verticals.change") ?? 0;
    const resilience = findFact(snapshot, "verticals.resilience") ?? 0;
    const cost = findFact(snapshot, "verticals.cost") ?? 0;
    const unknown = findFact(snapshot, "verticals.unknown") ?? 0;
    return {
      text: `Verticals represented: change ${change}, resilience ${resilience}, cost ${cost}, unknown ${unknown}.`,
      citations: [
        { label: "change", value: String(change) },
        { label: "resilience", value: String(resilience) },
        { label: "cost", value: String(cost) },
        { label: "unknown", value: String(unknown) },
      ],
      followUps: ["list change tiles", "list cost tiles"],
    };
  }

  if (/failed|failure|error/.test(q)) {
    const failedTiles = tiles.filter((t) => t.failed === true);
    return {
      text:
        failedTiles.length === 0
          ? "No failed tiles right now."
          : `${failedTiles.length} tile(s) marked failed: ${failedTiles.map((t) => `${t.action_type ?? t.rule ?? "(no rule)"} on ${t.resource_type ?? "?"}`).slice(0, 6).join("; ")}`,
      citations: failedTiles.slice(0, 6).map((t) => ({
        label: String(t.action_type ?? t.rule ?? "(no rule)"),
        value: String(t.resource_type ?? "-"),
      })),
      followUps: ["what verticals are they in?"],
    };
  }

  if (/stuck|stall/.test(q)) {
    const stuck = tiles.filter((t) => t.stuck === true);
    return {
      text: stuck.length === 0
        ? "No stuck tiles."
        : `${stuck.length} tile(s) stuck without reaching audit.`,
      citations: stuck.slice(0, 6).map((t) => ({
        label: String(t.action_type ?? "(routing)"),
        value: String(t.resource_type ?? "-"),
      })),
      followUps: [],
    };
  }

  if (/tier|t0|t1|t2/.test(q)) {
    const t0 = findFact(snapshot, "tier.t0") ?? "0%";
    const t1 = findFact(snapshot, "tier.t1") ?? "0%";
    const t2 = findFact(snapshot, "tier.t2") ?? "0%";
    return {
      text: `Tier mix over the 60s window: T0 ${t0}, T1 ${t1}, T2 ${t2}.`,
      citations: [
        { label: "T0", value: String(t0) },
        { label: "T1", value: String(t1) },
        { label: "T2", value: String(t2) },
      ],
      followUps: ["what is the current EPS?"],
    };
  }

  if (/gate|auto|hil|deny/.test(q)) {
    const auto = findFact(snapshot, "gate.auto") ?? "0%";
    const hil = findFact(snapshot, "gate.hil") ?? "0%";
    const abstain = findFact(snapshot, "gate.abstain") ?? "0%";
    const deny = findFact(snapshot, "gate.deny") ?? "0%";
    return {
      text: `Gate mix (60s): auto ${auto}, hil ${hil}, abstain ${abstain}, deny ${deny}.`,
      citations: [
        { label: "auto", value: String(auto) },
        { label: "hil", value: String(hil) },
        { label: "abstain", value: String(abstain) },
        { label: "deny", value: String(deny) },
      ],
      followUps: [],
    };
  }

  if (/eps|per\s*sec|events?\s*per|throughput|rate/.test(q)) {
    return {
      text: `Throughput: ${findFact(snapshot, "eps") ?? "0.0"} events per second over the last 60s.`,
      citations: [{ label: "eps", value: String(findFact(snapshot, "eps") ?? "0.0") }],
      followUps: ["what is the session total?"],
    };
  }

  if (/session|total|since|watching/.test(q)) {
    return {
      text: `Watching this session for ${findFact(snapshot, "session.duration") ?? "-"}, ${findFact(snapshot, "session.total") ?? 0} terminal events observed.`,
      citations: [
        { label: "duration", value: String(findFact(snapshot, "session.duration") ?? "-") },
        { label: "total events", value: String(findFact(snapshot, "session.total") ?? 0) },
      ],
      followUps: [],
    };
  }

  if (/how many.*tile|tile.*count|total.*tile/.test(q)) {
    const active = findFact(snapshot, "tiles.active") ?? 0;
    const empty = findFact(snapshot, "tiles.empty") ?? 0;
    const shadow = findFact(snapshot, "tiles.shadow") ?? 0;
    return {
      text: `${active} active tile(s), ${empty} empty slot(s). ${shadow} tile(s) have executed in shadow mode.`,
      citations: [
        { label: "active", value: String(active) },
        { label: "empty", value: String(empty) },
        { label: "shadow", value: String(shadow) },
      ],
      followUps: [],
    };
  }

  if (/list.*tile|which tile|show.*tile/.test(q)) {
    const sample = tiles.slice(0, 8);
    return {
      text: sample.length === 0
        ? "No tiles to list right now."
        : `${sample.length} sample tile(s):\n` +
          sample
            .map(
              (t) =>
                `- ${t.action_type ?? t.rule ?? "(no rule)"} on ${t.resource_type ?? "?"} - tier ${t.tier ?? "abstain"}, gate ${t.gate_decision ?? "-"}`,
            )
            .join("\n"),
      citations: sample.map((t) => ({
        label: String(t.action_type ?? "(routing)"),
        value: String(t.resource_type ?? "-"),
      })),
      followUps: [],
    };
  }

  return {
    text: `Live cockpit - ${snapshot.headline}. Ask about attention, tiles, verticals, gates, tiers, EPS, or session totals.`,
    citations: snapshot.facts.slice(0, 8).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerDashboard(q: string, snapshot: ViewSnapshot): Answer {
  if (/shadow/.test(q)) {
    return {
      text: `Shadow share: ${findFact(snapshot, "shadow_share")}. Enforce share: ${findFact(snapshot, "enforce_share")}.`,
      citations: [
        { label: "shadow", value: String(findFact(snapshot, "shadow_share")) },
        { label: "enforce", value: String(findFact(snapshot, "enforce_share")) },
      ],
      followUps: [],
    };
  }
  if (/hil/.test(q)) {
    return {
      text: `${findFact(snapshot, "hil_pending")} HIL approval(s) pending on the current audit window.`,
      citations: [{ label: "HIL pending", value: String(findFact(snapshot, "hil_pending")) }],
      followUps: [],
    };
  }
  if (/(action|kind|outcome|common)/.test(q)) {
    const kinds = (snapshot.records?.by_action_kind ?? []) as readonly Record<string, unknown>[];
    const outcomes = (snapshot.records?.by_outcome ?? []) as readonly Record<string, unknown>[];
    return {
      text: `Top action kinds: ${kinds.slice(0, 5).map((r) => `${r.key} (${r.count})`).join(", ")}. Top outcomes: ${outcomes.slice(0, 5).map((r) => `${r.key} (${r.count})`).join(", ")}.`,
      citations: kinds.slice(0, 5).map((r) => ({ label: String(r.key), value: String(r.count) })),
      followUps: [],
    };
  }
  return {
    text: `Dashboard - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerAudit(q: string, snapshot: ViewSnapshot): Answer {
  const rows = (snapshot.records?.items ?? []) as readonly Record<string, unknown>[];
  if (/how many|count/.test(q)) {
    return {
      text: `${rows.length} audit row(s) currently loaded in this view.`,
      citations: [{ label: "rows", value: String(rows.length) }],
      followUps: [],
    };
  }
  if (/mode|shadow|enforce/.test(q)) {
    const modes = new Map<string, number>();
    for (const r of rows) {
      const m = String(r.mode ?? "unknown");
      modes.set(m, (modes.get(m) ?? 0) + 1);
    }
    return {
      text: `Mode distribution: ${[...modes.entries()].map(([k, v]) => `${k}=${v}`).join(", ")}.`,
      citations: [...modes.entries()].map(([k, v]) => ({ label: k, value: String(v) })),
      followUps: [],
    };
  }
  if (/latest|newest|most recent|last/.test(q)) {
    const latest = rows[0];
    return {
      text: latest
        ? `Latest entry: seq ${latest.seq} at ${latest.recorded_at} - ${latest.action_kind} by ${latest.actor} in ${latest.mode} mode.`
        : "No audit rows loaded.",
      citations: latest
        ? [
            { label: "seq", value: String(latest.seq) },
            { label: "kind", value: String(latest.action_kind) },
            { label: "mode", value: String(latest.mode) },
          ]
        : [],
      followUps: [],
    };
  }
  return {
    text: `Audit - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerRules(q: string, snapshot: ViewSnapshot): Answer {
  const rules = (snapshot.records?.rules ?? []) as readonly Record<string, unknown>[];
  // Pull candidate search terms from the query (ascii tokens >= 3 chars) and
  // match them against the visible rule rows. This lets an offline operator
  // still get a grounded answer for rules currently on the page.
  const terms = q.match(/[a-z0-9-]{3,}/g) ?? [];
  const stop = new Set([
    "how", "the", "and", "for", "what", "which", "does", "recommended",
    "value", "values", "setting", "settings", "find", "show", "list", "rule", "rules",
  ]);
  const needles = terms.filter((w) => !stop.has(w));
  const hits = needles.length
    ? rules.filter((r) => {
        const hay = JSON.stringify(r).toLowerCase();
        return needles.some((w) => hay.includes(w));
      })
    : [];
  if (hits.length > 0) {
    const sample = hits.slice(0, 6);
    return {
      text:
        `${hits.length} matching rule(s) on this page:\n` +
        sample
          .map(
            (r) =>
              `- ${r.id} (${r.severity}, ${r.category} / ${r.resource_type}) - remediation ${r.remediation ?? "-"}`,
          )
          .join("\n"),
      citations: sample.map((r) => ({
        label: String(r.id),
        value: String(r.remediation ?? r.resource_type ?? "-"),
      })),
      followUps: [],
    };
  }
  if (needles.length > 0) {
    return {
      text:
        `No rule matching "${needles.join(" ")}" is on the current page. ` +
        `Type it into the Rules search box to filter the full catalog ` +
        `(${findFact(snapshot, "total_rules") ?? "?"} rules, ` +
        `${findFact(snapshot, "active_rules") ?? "?"} active).`,
      citations: [
        { label: "total_rules", value: String(findFact(snapshot, "total_rules") ?? "?") },
        { label: "categories", value: String(findFact(snapshot, "categories_available") ?? "-") },
      ],
      followUps: [],
    };
  }
  return {
    text:
      `Rules catalog - ${snapshot.headline}. Categories available: ` +
      `${findFact(snapshot, "categories_available") ?? "-"}. ` +
      `Use the search box or the origin/category/severity/source filters to narrow it.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerHil(q: string, snapshot: ViewSnapshot): Answer {
  const items = (snapshot.records?.items ?? []) as readonly Record<string, unknown>[];
  if (/how many|count|waiting|pending/.test(q)) {
    return {
      text: `${items.length} HIL item(s) waiting for approval.`,
      citations: [{ label: "pending", value: String(items.length) }],
      followUps: items.length > 0 ? ["list all pending kinds"] : [],
    };
  }
  if (/list|kinds?|show/.test(q)) {
    return {
      text: items.length === 0
        ? "The HIL queue is empty."
        : `Waiting kinds: ${items.map((i) => i.action_kind).join(", ")}.`,
      citations: items.map((i) => ({ label: String(i.action_kind), value: String(i.reason ?? "") })),
      followUps: [],
    };
  }
  return {
    text: `HIL queue - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerPromotion(q: string, snapshot: ViewSnapshot): Answer {
  const rows = (snapshot.records?.rows ?? []) as readonly Record<string, unknown>[];
  if (/ready/.test(q)) {
    const ready = rows.filter((r) => r.ready === true);
    return {
      text: ready.length === 0
        ? "No ActionTypes are ready to promote."
        : `Ready (${ready.length}): ${ready.map((r) => r.action_type_name).join(", ")}.`,
      citations: ready.slice(0, 8).map((r) => ({
        label: String(r.action_type_name),
        value: `${(Number(r.accuracy) * 100).toFixed(1)}%`,
      })),
      followUps: ["which are blocked?"],
    };
  }
  if (/block/.test(q)) {
    const blocked = rows.filter((r) => r.ready !== true);
    return {
      text: `${blocked.length} ActionType(s) still blocked. Common gaps: ${blocked.slice(0, 5).flatMap((r) => (r.gaps as string[]) ?? []).slice(0, 6).join("; ")}.`,
      citations: blocked.slice(0, 8).map((r) => ({
        label: String(r.action_type_name),
        value: String((r.gaps as string[])?.[0] ?? ""),
      })),
      followUps: ["which have policy escapes?"],
    };
  }
  if (/escape|violation/.test(q)) {
    const escapes = rows.filter((r) => Number(r.policy_escapes ?? 0) > 0);
    return {
      text: escapes.length === 0
        ? "No policy escapes recorded in the current window."
        : `${escapes.length} ActionType(s) with escapes: ${escapes.map((r) => `${r.action_type_name} (${r.policy_escapes})`).join(", ")}.`,
      citations: escapes.slice(0, 8).map((r) => ({
        label: String(r.action_type_name),
        value: String(r.policy_escapes),
      })),
      followUps: [],
    };
  }
  return {
    text: `Promotion gates - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerBlast(q: string, snapshot: ViewSnapshot): Answer {
  if (/(how many|count|affected)/.test(q)) {
    return {
      text: `${findFact(snapshot, "affected_count") ?? 0} resource(s) reachable at depth ${findFact(snapshot, "depth")}.`,
      citations: [
        { label: "affected", value: String(findFact(snapshot, "affected_count") ?? 0) },
        { label: "depth", value: String(findFact(snapshot, "depth")) },
      ],
      followUps: [],
    };
  }
  if (/(truncat|cap|limit)/.test(q)) {
    return {
      text: findFact(snapshot, "truncated") === true
        ? "Traversal WAS truncated at the depth cap; raise depth to see more."
        : "Traversal completed within the depth cap; no truncation.",
      citations: [{ label: "truncated", value: String(findFact(snapshot, "truncated")) }],
      followUps: [],
    };
  }
  return {
    text: `Blast radius - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerTrace(q: string, snapshot: ViewSnapshot): Answer {
  if (/how many|step/.test(q)) {
    return {
      text: `${findFact(snapshot, "step_count") ?? 0} pipeline step(s) recorded for correlation ${findFact(snapshot, "correlation_id")}.`,
      citations: [
        { label: "steps", value: String(findFact(snapshot, "step_count") ?? 0) },
        { label: "correlation", value: String(findFact(snapshot, "correlation_id")) },
      ],
      followUps: [],
    };
  }
  if (/terminal|end|last/.test(q)) {
    return {
      text: `Terminal stage: ${findFact(snapshot, "terminal_stage") ?? "(none recorded)"}.`,
      citations: [{ label: "terminal", value: String(findFact(snapshot, "terminal_stage") ?? "-") }],
      followUps: [],
    };
  }
  return {
    text: `Trace - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}

function answerOntology(q: string, snapshot: ViewSnapshot): Answer {
  if (/object/.test(q)) {
    return {
      text: `${findFact(snapshot, "object_type_count") ?? 0} ObjectType(s) registered.`,
      citations: [{ label: "ObjectTypes", value: String(findFact(snapshot, "object_type_count") ?? 0) }],
      followUps: [],
    };
  }
  if (/link/.test(q)) {
    return {
      text: `${findFact(snapshot, "link_type_count") ?? 0} LinkType(s) registered.`,
      citations: [{ label: "LinkTypes", value: String(findFact(snapshot, "link_type_count") ?? 0) }],
      followUps: [],
    };
  }
  return {
    text: `Ontology - ${snapshot.headline}.`,
    citations: snapshot.facts.slice(0, 6).map(factToCitation),
    followUps: defaultFollowUps(snapshot),
  };
}
