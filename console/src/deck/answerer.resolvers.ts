/**
 * Deterministic answerer resolvers - screen-agnostic pipeline stages
 * that run BEFORE the per-route enhancers. Each returns an `Answer`
 * when it matches (grounded in glossary / static list / narrative /
 * general search) or `null` to abstain and let the next stage try.
 *
 * SRP: matching + shaping only. All static data lives in
 * `answerer.catalogs.ts`; all snapshot lookups live in
 * `answerer.helpers.ts`; the per-route enhancers live in
 * `answerer.routes.ts`; the main dispatcher lives in `answerer.ts`.
 */

import type { ViewSnapshot } from "./context";
import {
  ACTION_TYPE_ROLES,
  PANTHEON_AGENTS,
  RBAC_ROLES,
  ROUTE_ACTION_HINTS,
  SAFETY_INVARIANTS,
  STATIC_GLOSSARY,
  TRUST_TIERS,
  VERTICALS,
  type Answer,
} from "./answerer.catalogs";
import {
  GENERIC_STOPWORDS,
  causalTargetRows,
  chronological,
  collectColumnValues,
  defaultFollowUps,
  describeChain,
  explainTerm,
  explainValue,
  factToCitation,
  firstString,
  listAnswer,
  summariseRow,
} from "./answerer.helpers";

export interface ConversationContextTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
}

/** Answer agent status / recent-work questions from the trusted context turn
 *  injected when an operator opens an agent-scoped conversation. The parser
 *  only accepts the fixed agent-context envelope, so ordinary prior replies
 *  cannot be mistaken for current operational state. */
export function resolveRecentAgentWork(
  q: string,
  history: readonly ConversationContextTurn[],
  snapshot?: ViewSnapshot | null,
): Answer | null {
  const asksAboutWork =
    /\b(what|which).*(working on|worked on|been doing|doing now)\b|\b(current|recent|latest) (work|activity|incident)\b/.test(q) ||
    /최근|요즘|현재|무슨 일|하고 있/.test(q);
  if (!asksAboutWork) return null;

  const context = [...history]
    .reverse()
    .find(
      (turn) =>
        turn.role === "assistant" &&
        turn.content.startsWith("Context for a conversation about the FDAI agent "),
    )?.content;
  if (!context) return null;

  const agent = context.match(/^Context for a conversation about the FDAI agent ([^(\n]+)(?: \(|\.)/m)?.[1]?.trim();
  if (!agent) return null;

  const selectedAgent = snapshot?.records?.selected_agent?.find(
    (row) => row.agent === agent || q.includes(String(row.agent ?? "").toLowerCase()),
  );
  if (selectedAgent) {
    const currentState = String(selectedAgent.state ?? "unknown");
    const currentTask = String(selectedAgent.task ?? "Current task unavailable");
    const correlation = selectedAgent.correlation_id;
    const incident = snapshot?.records?.incidents?.find(
      (row) => correlation != null && row.correlation_id === correlation,
    );
    const incidentText = incident
      ? ` ${agent} is currently working on:\n- ${String(incident.ticket ?? incident.correlation_id ?? "incident")} (${String(incident.status ?? "unknown")}, ${String(incident.severity ?? "unknown")}) ${String(incident.title ?? "Untitled incident")}`
      : ` ${agent} has no active incident on the current screen.`;
    return {
      text: `${agent} is currently ${currentState} - ${currentTask}.${incidentText}`,
      citations: [
        { label: `${agent} state`, value: currentState },
        ...(incident
          ? [{ label: "incident", value: String(incident.ticket ?? correlation) }]
          : []),
      ],
      followUps: incident ? ["why did the current incident start?"] : [],
    };
  }

  const state = context.match(/^Current state: ([^\n]+)$/m)?.[1]?.trim();
  const incidentsBlock = context.match(
    new RegExp(`^Recent incidents ${agent.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")} worked \\(newest first\\):\\n+([\\s\\S]*?)(?:\\n\\n|$)`, "m"),
  )?.[1];
  const incidents = incidentsBlock
    ?.split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- ")) ?? [];

  const statusText = state ? `${agent} is currently ${state}` : `${agent}'s current state is not available.`;
  const workText =
    incidents.length > 0
      ? ` Most recently, ${agent} worked on:\n${incidents.join("\n")}`
      : ` ${agent} has no recent incident activity in this conversation context.`;
  return {
    text: `${statusText}${workText}`,
    citations: [{ label: `${agent} context`, value: `${incidents.length} recent incident(s)` }],
    followUps: incidents.length > 0 ? [`why did the latest incident start?`] : [],
  };
}

// ---------------------------------------------------------------------------
// Glossary resolvers (screen-declared + universal fallback)
// ---------------------------------------------------------------------------

/**
 * Explain a term the screen declared. Handles two shapes:
 *  - a value chip the operator quoted (e.g. "corr-j") that lives in a glossed
 *    records column -> name the term AND summarise the group it identifies, and
 *  - the term name / tech token appearing in the query -> plain definition.
 * Returns null when the screen declares no glossary or nothing matches.
 */
export function resolveGlossary(q: string, snapshot: ViewSnapshot): Answer | null {
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
    /무엇|뭐|뭔|무슨|설명|의미|뜻/.test(q);
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
export function resolveStaticGlossary(q: string): Answer | null {
  const asking =
    /\bwhat\b|\bwhich\b|\bexplain\b|\bdefine\b|\bmean(s|ing)?\b|\bwhats\b|\bwhat's\b/.test(q) ||
    /무엇|뭐|뭔|무슨|설명|의미|뜻/.test(q);
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

/** Deck / operator-meta questions ("help", "what can I do here", "how do I
 *  search / export / filter"). Kept read-only + narrow so genuine data queries
 *  are not hijacked. Returns null for anything not clearly a deck-meta ask. */
export function resolveDeckMeta(q: string, snapshot: ViewSnapshot): Answer | null {
  // Help / "what can you do" - describe the deck itself.
  if (/^\??help\?*$|^\?+$|\bwhat can you (do|help)\b|\bhow (do|can) i use (the deck|this deck|you)\b/.test(q)) {
    return {
      text:
        "I'm the FDAI console deck - a read-only screen-aware translator. " +
        "Ask me about anything on the current page (numbers, rows, chips, terms, " +
        "why an incident started, who can approve what). I ground every answer in " +
        "the snapshot on the right of this overlay; I never execute an action. " +
        "Try: 'what requires approval?', 'why did corr-j start?', 'what can I do here?'.",
      citations: [{ label: "route", value: snapshot.routeLabel }],
      followUps: [
        "what can I do here?",
        "what do you see on this screen?",
        "what requires approval?",
      ],
    };
  }

  // "What can I do here?" - per-route action hint (deterministic; the LLM
  // path additionally injects the RBAC capability block).
  if (/\bwhat can i do (here|on (this|the) (page|screen))\b|\bwhat.*(can i do here)\b|\bwhat.*this(?: [a-z0-9_-]+){0,3} (page|screen) for\b/.test(q)) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    const purpose = snapshot.purpose ? `${snapshot.purpose} ` : "";
    const generic =
      "This console is read-only: you can search, filter, and drill into rows to " +
      "understand an incident; nothing executes from a button here. Approvals happen " +
      "in Teams/ChatOps, and changes are delivered as governance PRs.";
    return {
      text: hint
        ? `${purpose}${hint} ${generic}`
        : `${purpose || `${snapshot.routeLabel}: `}${generic}`,
      citations: [{ label: "route", value: snapshot.routeLabel }],
      followUps: ["what requires approval?", "what does an Approver do?"],
    };
  }

  // "How do I search / filter / export / open X" - short "look at the header/
  // detail drawer" hint. Very narrow so screen data questions are not caught:
  // requires the verb to sit at the tail of the query (with '?' / EOL / a
  // 'here / this / the page / the screen' anchor), so 'how do I search rules
  // for foo?' (with a specific object) falls through to the data path.
  if (/\bhow (do|can) i (search|filter|export|open|drill|navigate)(\s+(here|through this|on (this|the) (page|screen)|the (page|screen)|this))?\s*\??\s*$/.test(q)) {
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
// Catalog list resolvers ("list the agents / tiers / roles / ...")
// ---------------------------------------------------------------------------

/** Catalog list questions ("list the 15 agents", "list the tiers", "list all
 *  roles", "list the verticals", "list the safety invariants"). Answered from
 *  the fixed architecture, so a screen with no records still gets the list.
 *
 *  Ambiguity guard: for common English nouns (roles, tiers, agents, verticals),
 *  a definite-scope word ('the / all / every / 15 / 5 / four / three') is
 *  required so 'list roles' as a screen column-list on the Rules route still
 *  falls through to the per-route enhancer. Unambiguous FDAI-specific tokens
 *  (pantheon, actiontype, rbac) fire without the scope word. */
export function resolveList(q: string): Answer | null {
  const listVerb =
    /\blist\b|\bshow\b|\bwhat are (the |all )?/.test(q) ||
    /목록|보여줘/.test(q); // KO: list / show
  if (!listVerb) return null;

  // Unambiguous, FDAI-specific catalog tokens fire without a scope word.
  if (/\bactiontype\b|\baction type\b|\baction-type\b|\baction_type\b|\baction (kind|role)/.test(q)) {
    return listAnswer("The five roles every ActionType binds", ACTION_TYPE_ROLES);
  }
  if (/\bpantheon\b/.test(q)) {
    return listAnswer("The 15 pantheon agents", PANTHEON_AGENTS);
  }
  if (/\brbac\b/.test(q)) {
    return listAnswer("The RBAC roles (Entra App Roles, cumulative)", RBAC_ROLES);
  }

  // Ambiguous catalog tokens require a definite-scope word so a screen
  // column-list ('list roles' on a page with a role column) still falls
  // through to the per-route enhancer.
  const scoped = /\bthe\b|\ball\b|\bevery\b|\b15\b|\b5\b|\bfour\b|\bthree\b/.test(q);
  if (!scoped) return null;

  if (/\bagent(s)?\b|에이전트/.test(q)) {
    return listAnswer("The 15 pantheon agents", PANTHEON_AGENTS);
  }
  if (/\btier(s)?\b|\bt0\b|\bt1\b|\bt2\b|티어/.test(q)) {
    return listAnswer("The three trust tiers", TRUST_TIERS);
  }
  if (/\brole(s)?\b|\bpermission(s)?\b|역할/.test(q)) {
    return listAnswer("The RBAC roles (Entra App Roles, cumulative)", RBAC_ROLES);
  }
  if (/\bvertical(s)?\b|버티컬/.test(q)) {
    return listAnswer("The three initial verticals", VERTICALS);
  }
  if (/\bsafety\b|\binvariant(s)?\b|안전/.test(q)) {
    return listAnswer("The four safety invariants", SAFETY_INVARIANTS);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Causal resolver ("why did this start?")
// ---------------------------------------------------------------------------

/**
 * Answer "why did this start / what triggered it" by quoting the causal
 * narrative already recorded on the target rows (`detail` -> `summary` ->
 * `reason`). The target is: the correlation the operator quoted, else the
 * screen's selection, else the most recent row that carries a narrative.
 * Returns null for non-causal questions or when no narrative is on screen.
 */
export function resolveCausal(q: string, snapshot: ViewSnapshot): Answer | null {
  // Korean markers (\uXXXX, source stays ASCII): why / cause / reason /
  // occur / start.
  const causal =
    /\bwhy\b|\bcause[ds]?\b|\breason\b|\btrigger(ed)?\b|\bstart(ed)?\b|\bhappen(ed)?\b/.test(q) ||
    /왜|원인|이유|발생|시작/.test(q);
  if (!causal) return null;
  const rows = causalTargetRows(q, snapshot);
  if (rows.length === 0) return null;
  const ordered = chronological(rows);
  const target = ordered[0]!;
  const narrative = firstString(target, "cause", "detail", "summary", "reason");
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

// ---------------------------------------------------------------------------
// Generic fallback ("no bespoke enhancer" search)
// ---------------------------------------------------------------------------

/**
 * Last-resort grounded answer for a screen with no bespoke enhancer: search
 * the published records for the query tokens and quote matches, else restate
 * the headline + purpose and offer the glossary terms the screen declared.
 */
export function genericAnswer(q: string, snapshot: ViewSnapshot): Answer {
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
