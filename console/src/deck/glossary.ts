/**
 * Shared control-plane glossary - catalog-as-code for the console vocabulary.
 *
 * A route composes its own `glossary` for the view snapshot from these
 * entries instead of hand-writing prose, so every screen explains the SAME
 * term the SAME way (a `correlation id` means the same thing on Agent activity,
 * Audit, and Trace). The answerer resolves "what is X" questions from the
 * published `glossary`, so a screen becomes self-describing by declaring which
 * terms it renders - it never needs a per-route answerer for vocabulary.
 *
 * Single responsibility: hold the term data + tiny composition helpers. No
 * rendering, no I/O, no LLM. Keep entries customer-agnostic and English (the
 * plain text is a source string; L2 localisation happens at render time).
 */

import type { GlossaryTerm } from "./context";

/**
 * The control-plane terms most screens render. Keyed for ergonomic reuse
 * (`TERMS.correlationId`). Add a term here once; every screen that shows it
 * pulls the same definition.
 */
export const TERMS = {
  correlationId: {
    term: "correlation id",
    plain:
      "the investigation key that groups related agent steps and evidence; it does not by itself prove an Incident lifecycle record exists",
    tech: "correlation_id",
    seeAlso: "trace",
    match: "correlation_id",
  },
  eventId: {
    term: "event id",
    plain: "the stable id of one normalized event the control plane processed",
    tech: "event_id",
    match: "event_id",
  },
  actionKind: {
    term: "action kind",
    plain:
      "what kind of work an agent did or proposed (detect, judge, open a remediation PR, queue an approval, record audit)",
    tech: "action_kind",
    match: "action_kind",
  },
  tier: {
    term: "tier",
    plain:
      "which trust tier resolved the event - T0 deterministic rules, T1 lightweight similarity, or T2 frontier-model reasoning",
    tech: "tier",
    seeAlso: "dashboard",
    match: "tier",
  },
  mode: {
    term: "mode",
    plain:
      "shadow (judged and logged only, nothing applied) vs enforce (allowed to act); new actions ship shadow and are promoted after their gate passes",
    tech: "mode",
    seeAlso: "promotion-gates",
    match: "mode",
  },
  outcome: {
    term: "outcome",
    plain:
      "the terminal decision recorded for this step - auto, hil (needs approval), deny, abstain, or a delivery result like a PR opened",
    tech: "outcome",
    match: "outcome",
  },
  gateDecision: {
    term: "gate decision",
    plain:
      "the risk gate's verdict - auto executes, hil needs a human approver, deny refuses, abstain means no rule matched (no-op)",
    tech: "gate_decision",
    match: "gate_decision",
  },
  waterfall: {
    term: "waterfall",
    plain:
      "the timeline view where each incident is one row and each bar is an agent picking the incident up, read left to right as the hand-off cascade",
  },
  hil: {
    term: "HIL",
    plain:
      "human-in-the-loop - a high-risk action parked for a human approver (via Teams/ChatOps), never auto-executed and never self-approved",
    tech: "hil",
    seeAlso: "hil-queue",
  },
  shadowMode: {
    term: "shadow mode",
    plain:
      "a capability that only judges and logs - it never mutates a resource - until it is explicitly promoted to enforce",
    tech: "shadow",
    seeAlso: "promotion-gates",
  },
  actionType: {
    term: "ActionType",
    plain:
      "the ontology entry classing an autonomous action; it binds five roles - initiators, judge, executor, approver, auditor",
    seeAlso: "ontology",
  },
  process: {
    term: "Process",
    plain:
      "the current snapshot of one workflow run, including its step, status, revision, and target; its event journal preserves the transition history",
    tech: "process",
    seeAlso: "workflow-builder",
  },
  viewSpec: {
    term: "ViewSpec",
    plain:
      "the catalog-as-code layout that selects bounded ontology-backed datasets and widgets for a workflow Process; it contains presentation rules, not runtime state",
    tech: "view_spec",
    seeAlso: "processes",
  },
  report: {
    term: "report",
    plain:
      "a read-only catalog definition that combines a bounded time range, declared variables, and server-rendered evidence widgets",
    tech: "ReportSpec",
    seeAlso: "reports",
  },
  widget: {
    term: "widget",
    plain:
      "one typed visualization in a report; its server-owned data is rendered by a matching console component and never executes an action",
    tech: "RenderedWidget",
    seeAlso: "reports",
  },
  userPreference: {
    term: "user preference",
    plain:
      "a presentation choice such as locale, theme, or reduced motion; console display preferences stay in the local browser and never change control-plane state",
    tech: "UserPreference",
    seeAlso: "settings",
  },
  documentCollection: {
    term: "document collection",
    plain:
      "the shared access boundary and retrieval namespace that receives a governed document after ingestion checks pass",
    tech: "collection_id",
    seeAlso: "documents",
    match: "collection",
  },
  processingPurpose: {
    term: "processing purpose",
    plain:
      "the declared use for an uploaded document, such as knowledge-base grounding, manual distillation, or an agent-handover draft",
    tech: "purposes",
    seeAlso: "documents",
    match: "processing_purpose",
  },
  sourceStorageMode: {
    term: "source storage mode",
    plain:
      "how FDAI retains or references the original uploaded source while preserving the same ingestion and access checks",
    tech: "storage_mode",
    seeAlso: "documents",
    match: "source_storage_mode",
  },
  ingestionSafety: {
    term: "ingestion safety checks",
    plain:
      "the quarantine, malware, protection, extraction, and indexing checks that complete before an uploaded document becomes available",
    seeAlso: "documents",
  },
  humanRbac: {
    term: "human RBAC",
    plain:
      "the FDAI App Roles and capability checks that decide what a signed-in operator may view, request, review, or administer",
    tech: "roles",
    seeAlso: "settings-iam",
  },
  blastRadius: {
    term: "blast radius",
    plain:
      "how many resources an action could reach - the risk gate caps it so a single change can never touch more than its scope",
    seeAlso: "blast-radius",
  },
} as const satisfies Record<string, GlossaryTerm>;

/**
 * The pantheon agent term - the 15 fixed agents share one definition shape, so
 * a screen that shows agent names declares `agentTerm()` once.
 */
export function agentTerm(): GlossaryTerm {
  return {
    term: "agent",
    plain:
      "one of the 15 fixed pantheon agents that own the control loop (Huginn senses, Forseti judges, Thor executes, Var approves, Saga audits, ...)",
    tech: "actor",
    seeAlso: "pantheon",
    match: "agent",
  };
}

/**
 * Compose a screen's glossary from shared terms plus any screen-specific ones.
 * Later entries win on a duplicate `term`, so a screen can override a shared
 * definition when its rendering needs a narrower wording.
 */
export function composeGlossary(
  ...groups: readonly (readonly GlossaryTerm[])[]
): readonly GlossaryTerm[] {
  const byTerm = new Map<string, GlossaryTerm>();
  for (const group of groups) {
    for (const entry of group) byTerm.set(entry.term.toLowerCase(), entry);
  }
  return [...byTerm.values()];
}
