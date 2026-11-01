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
  trajectory: {
    term: "trajectory",
    plain:
      "one correlation's recorded audit steps in order - which agent received, decided, approved, acted, and recorded each step, with timing and handoffs between agents",
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
  backgroundTask: {
    term: "background task",
    plain:
      "an owner-scoped detached read-only investigation with durable progress and a terminal result; inspecting it grants no cancel, retry, mutation, or execution authority",
    tech: "background_task",
    seeAlso: "background-tasks",
    match: "task_id",
  },
  resource: {
    term: "Resource",
    plain:
      "one observed cloud resource identity in the current inventory generation; graph selection and traversal remain read-only",
    tech: "Resource",
    seeAlso: "ontology",
    match: "resource_id",
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
  detectionReadiness: {
    term: "detection coverage",
    plain:
      "the retained evidence showing which supported resources were candidates, evaluated, held, or produced findings; an evaluation without a finding is not a health claim",
    tech: "AnalyzerCoverage",
    seeAlso: "detection-coverage",
    match: "detection_readiness",
  },
  consoleSecurityBoundary: {
    term: "console security boundary",
    plain:
      "the FDAI Console web SPA holds zero cloud or executor credentials, verifies Entra ID and server-owned GET /iam/self RBAC, forbids arbitrary HTML/SVG/JS execution, verifies SHA-256 guidance digests, and keeps execution_authority=false",
    tech: "execution_authority=false",
    seeAlso: "code-security",
  },
  executionAuthority: {
    term: "execution authority",
    plain:
      "whether a surface or projection can mutate cloud resources; all Console views, rules, framework assessments, and chat responses keep execution_authority=false",
    tech: "execution_authority",
    seeAlso: "promotion-gates",
  },
  codeSecurityReview: {
    term: "code security review",
    plain:
      "a signed multi-lens repository scan and isolated Kata sandbox verification record showing P0-P4 priority, severity, confidence, and known-exploited counts without auto-execution authority",
    tech: "CodeSecurityReview",
    seeAlso: "code-security",
  },
  verificationPack: {
    term: "verification pack",
    plain:
      "an immutable adjudication and rescan verification bundle tracking fixed_verified, still_present, inconclusive, and false_positive verdicts for code security findings",
    tech: "CodeSecurityPack",
    seeAlso: "code-security",
  },
  t0Rule: {
    term: "T0 detection rule",
    plain:
      "a deterministic Rego or policy expression rule that evaluates inventory snapshots and proposes a paired ActionType without bypassing risk or HIL gates",
    tech: "Rule",
    seeAlso: "rules",
  },
  wafControl: {
    term: "Azure WAF control",
    plain:
      "one of the 59 Azure Well-Architected Framework controls across Reliability, Security, Cost, Operational Excellence, and Performance Efficiency evaluated in shadow mode",
    tech: "azure-waf",
    seeAlso: "rules",
  },
  cafControl: {
    term: "Azure CAF control",
    plain:
      "one of the 15 Cloud Adoption Framework methodology and landing-zone governance areas requiring procedure and execution evidence",
    tech: "azure-caf",
    seeAlso: "rules",
  },
  mcsbBenchmark: {
    term: "MCSB control",
    plain:
      "a Microsoft Cloud Security Benchmark control (86 v1 controls plus 74 v2-preview controls including AI-1..AI-7) where decisive evidence is required for satisfaction",
    tech: "azure-mcsb",
    seeAlso: "rules",
  },
  waraRecommendation: {
    term: "WARA recommendation",
    plain:
      "one of the 456 Azure Well-Architected Review Assessment (APRL) reliability recommendations with source-pinned KQL evaluators and illustrated architecture guidance",
    tech: "azure-wara",
    seeAlso: "rules",
  },
  msrcCsaf: {
    term: "MSRC CSAF advisory",
    plain:
      "a signed OASIS CSAF 2.0 Microsoft Security Response Center vulnerability record mapped to canonical ResourceTypes, version windows, CWE classes, and P0-P3 KEV priority tiers",
    tech: "msrc_csaf",
    seeAlso: "rules",
  },
  cvePriorityTier: {
    term: "CVE priority tier",
    plain:
      "the deterministic exploitability priority tier (P0 Immediate for exploited/KEV, P1 Urgent, P2 Scheduled, P3 Monitor) combining exploit status, CVSS v3.1 attack surface, and runtime exposure",
    tech: "priority_tier",
    seeAlso: "rules",
  },
  owaspLlmTop10: {
    term: "OWASP LLM Top 10 & MITRE ATLAS",
    plain:
      "the AI security threat taxonomy mapped onto MCSB v2-preview controls AI-1 through AI-7 covering prompt injection, excessive agency, supply chain, and red-teaming",
    tech: "owasp_llm_ref",
    seeAlso: "rules",
  },
  zeroSecretSpa: {
    term: "zero-secret SPA",
    plain:
      "the architectural guarantee that the FDAI Console browser bundle holds zero cloud credentials, database DSNs, or Thor executor keys",
    tech: "zero_secret_spa",
    seeAlso: "settings-iam",
  },
  sevenSafeguards: {
    term: "7 constitutional safeguards",
    plain:
      "the mandatory execution preconditions: stop condition, tested rollback, blast-radius limit, dry-run success, logical-target lock, idempotency key, and two-phase audit",
    tech: "seven_safeguards",
    seeAlso: "promotion-gates",
  },
  entraRbac: {
    term: "Entra ID RBAC projection",
    plain:
      "server-verified GET /iam/self mapping of Entra ID JWT claims onto Reader, Contributor, Approver, Owner, or BreakGlass roles",
    tech: "iam_self_rbac",
    seeAlso: "settings-iam",
  },
  governedDocumentRag: {
    term: "governed document RAG",
    plain:
      "quarantine-scanned, ACL-scoped document retrieval (query.governed_documents) where every excerpt carries SHA-256 digests and instruction_authority=false",
    tech: "query.governed_documents",
    seeAlso: "documents",
  },
  cisaKev: {
    term: "CISA KEV",
    plain:
      "the Known Exploited Vulnerabilities catalog integrated into MSRC CSAF 2.0 and Code Security Review to escalate actively exploited CVEs to P0 Immediate priority",
    tech: "known_exploited",
    seeAlso: "code-security",
  },
  xssAndActiveContentRejection: {
    term: "active-content & XSS rejection",
    plain:
      "persistence and projection guards that reject script tags, data:text/html, meta refresh, and CSS @import before any code-security or operational artifact reaches the browser",
    tech: "active_content_rejection",
    seeAlso: "code-security",
  },
  dsseRemediationPack: {
    term: "DSSE Ed25519 remediation pack",
    plain:
      "an RFC 8032 Ed25519 DSSE-signed remediation bundle verified against the state-store revocation registry before export; importing a pack never produces fixed_verified without a rescan",
    tech: "dsse_remediation_pack",
    seeAlso: "code-security",
  },
  sagaHashChainAudit: {
    term: "Saga SHA-256 audit chain",
    plain:
      "the append-only SHA-256 hash-chained audit ledger with committed head-hash ancestry verification and two-phase execution receipts",
    tech: "saga_audit_chain",
    seeAlso: "audit",
  },
  msalSessionStorageBoundary: {
    term: "MSAL session & CORS boundary",
    plain:
      "browser token isolation with credentials: omit on chat/stream fetches and strict FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS origin enforcement",
    tech: "cors_session_boundary",
    seeAlso: "settings-iam",
  },
  promptInjectionIsolation: {
    term: "prompt-injection & V-CLAIM defense",
    plain:
      "strict separation of untrusted user prose/attachments from system prompts combined with schema-constrained outputs, deterministic V-CLAIM checks, and independent AdaptiveReview",
    tech: "prompt_injection_defense",
    seeAlso: "governance",
  },
} as const satisfies Record<string, GlossaryTerm>;

export const SECURITY_AND_RULES_GLOSSARY: readonly GlossaryTerm[] = [
  TERMS.consoleSecurityBoundary,
  TERMS.executionAuthority,
  TERMS.codeSecurityReview,
  TERMS.verificationPack,
  TERMS.t0Rule,
  TERMS.wafControl,
  TERMS.cafControl,
  TERMS.mcsbBenchmark,
  TERMS.waraRecommendation,
  TERMS.msrcCsaf,
  TERMS.cvePriorityTier,
  TERMS.owaspLlmTop10,
  TERMS.zeroSecretSpa,
  TERMS.sevenSafeguards,
  TERMS.shadowMode,
  TERMS.entraRbac,
  TERMS.governedDocumentRag,
  TERMS.cisaKev,
  TERMS.xssAndActiveContentRejection,
  TERMS.dsseRemediationPack,
  TERMS.sagaHashChainAudit,
  TERMS.msalSessionStorageBoundary,
  TERMS.promptInjectionIsolation,
  TERMS.tier,
  TERMS.mode,
  TERMS.hil,
  TERMS.actionType,
  TERMS.humanRbac,
];

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
