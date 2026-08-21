/** Answer types and route context supplied to the model-backed backend. */

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

/** Per-route hints injected into the bounded context sent to the backend. */
export const ROUTE_ACTION_HINTS: Readonly<Record<string, string>> = {
  live:
    "Live cockpit: watch tiles as events flow in, click a tile to open its trace, " +
    "hover a tile to see its action + resource, and read the tier/gate mix at the top.",
  dashboard:
    "Dashboard: read shadow vs enforce share, top action kinds, and approvals pending; " +
    "narrow the window from the header controls; drill into a bar to jump to Audit.",
  audit:
    "Audit: search rows by seq/correlation/action, filter by mode (shadow/enforce), " +
    "click a row to open its trace; export is via the header if enabled.",
  rules:
    "Rules: search by id/category/severity, click a rule to open its detail drawer " +
    "with provenance + remediation + shadow accuracy; enable/disable is governance-only.",
  "hil-queue":
    "Approvals: read pending items and their risk reason; decisions happen in " +
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
    "Workflow builder: design a workflow by chatting with the builder - describe it " +
    "in plain words, answer a few questions, and it generates the YAML; saving is a " +
    "governance PR, nothing runs from this screen directly.",
  provision:
    "Provision: watch a bootstrap pipeline (plan/apply); progress streams live; " +
    "no privileged action runs from the console (executor holds the only identity).",
};
