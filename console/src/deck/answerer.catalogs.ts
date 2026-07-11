/**
 * Deterministic answerer catalogs - static data lists and Answer types.
 *
 * SRP: pure data. Fixed lists (the 15-agent pantheon, trust tiers, RBAC
 * roles, verticals, safety invariants, ActionType roles) and canonical
 * text (route action hints, universal glossary, no-context fallback)
 * that never depend on the ViewSnapshot.
 *
 * Extracted from `answerer.ts` so the pipeline modules
 * (helpers / resolvers / route answerers / main dispatcher) share one
 * source of truth and additions do not touch behaviour code.
 */

import type { GlossaryTerm } from "./context";
import { TERMS } from "./glossary";

// ---------------------------------------------------------------------------
// Public Answer shape
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// No-context (no snapshot published) fallback
// ---------------------------------------------------------------------------

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
export const STATIC_GLOSSARY: readonly GlossaryTerm[] = [
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

export const NO_CONTEXT_FOLLOWUPS: readonly string[] = [
  "what is HIL?",
  "what is a correlation id?",
  "what is the trust router?",
  "what is shadow mode?",
];

export const NO_CONTEXT: Answer = {
  text:
    "No route has published a view snapshot yet. Open Live, Dashboard, " +
    "Audit, HIL, Trace, Blast Radius, Promotion, or Ontology and try again. " +
    "You can still ask FDAI concept questions (e.g. 'what is HIL?').",
  citations: [],
  followUps: NO_CONTEXT_FOLLOWUPS,
};

// ---------------------------------------------------------------------------
// Per-route "what can I do here" hints
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

// ---------------------------------------------------------------------------
// Catalog lists ("list the agents / tiers / roles / ...")
// ---------------------------------------------------------------------------

export const PANTHEON_AGENTS: readonly string[] = [
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

export const TRUST_TIERS: readonly string[] = [
  "T0 - deterministic policy / checklist (target 70-80%): policy eval, config drift, what-if.",
  "T1 - lightweight similarity + small model (15-20%): reuse of past incident actions.",
  "T2 - frontier-LLM reasoning (5-10%, novel only): must clear the quality gate before executing.",
];

export const RBAC_ROLES: readonly string[] = [
  "Reader - view every screen (read-only) and ask this deck.",
  "Contributor - + author draft remediation / governance PRs.",
  "Approver - + review governance PRs and approve/reject runtime HIL, exemptions, overrides, quorum promotions (via Teams/ChatOps, never self-approval).",
  "Owner - + kill-switch, emergency access, group membership, infra IaC.",
  "BreakGlass - emergency-only, activated out of band (incident id + timebox).",
];

export const VERTICALS: readonly string[] = [
  "Change Safety (safe change + drift remediation)",
  "Resilience (disaster recovery + chaos/resilience testing)",
  "Cost Governance (FinOps)",
];

export const SAFETY_INVARIANTS: readonly string[] = [
  "stop-condition (kill-switch for the action)",
  "rollback path (tested; declared by rollback_contract)",
  "blast-radius cap (scope / batch / rate)",
  "audit-log entry (append-only)",
];

export const ACTION_TYPE_ROLES: readonly string[] = [
  "initiators (who may raise this action)",
  "judge (Forseti - who decides auto/hil/deny/abstain)",
  "executor (Thor - the sole privileged mutator)",
  "approver (Var - required for high-risk / HIL)",
  "auditor (Saga - append-only audit + Handoff)",
];
