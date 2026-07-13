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
 *
 * SRP: this file owns dispatch only. Static data lives in
 * `answerer.catalogs.ts`; snapshot lookups + explainers in
 * `answerer.helpers.ts`; pipeline stages in `answerer.resolvers.ts`;
 * per-route enhancers in `answerer.routes.ts`.
 */

import type { ViewSnapshot } from "./context";
import { NO_CONTEXT, type Answer } from "./answerer.catalogs";
import {
  defaultFollowUps,
  factToCitation,
} from "./answerer.helpers";
import {
  genericAnswer,
  resolveCausal,
  resolveDeckMeta,
  resolveGlossary,
  resolveList,
  resolveRecentAgentWork,
  resolveStaticGlossary,
  type ConversationContextTurn,
} from "./answerer.resolvers";
import {
  answerAudit,
  answerBlast,
  answerDashboard,
  answerHil,
  answerLive,
  answerOntology,
  answerPromotion,
  answerRules,
  answerTrace,
} from "./answerer.routes";

// Re-export public types + the route-hint map so `backend.ts` and other
// consumers keep importing from `./answerer` unchanged.
export type { Answer, Citation } from "./answerer.catalogs";
export { ROUTE_ACTION_HINTS } from "./answerer.catalogs";

export function answer(
  query: string,
  snapshot: ViewSnapshot | null,
  history: readonly ConversationContextTurn[] = [],
): Answer {
  const q = query.toLowerCase().trim();
  const recentAgentWork = resolveRecentAgentWork(q, history, snapshot);
  if (recentAgentWork) return recentAgentWork;

  if (snapshot === null) {
    // No route open yet - still resolve FDAI concept questions from the
    // static universal glossary and catalog list questions ('list the
    // agents / tiers / roles') so early questions get real answers instead
    // of a "open a route first" shrug.
    if (q.length > 0) {
      const list = resolveList(q);
      if (list) return list;
      const hit = resolveStaticGlossary(q);
      if (hit) return hit;
    }
    return NO_CONTEXT;
  }
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
