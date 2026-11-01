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
    "Rules (/rules): inspect Detection Rules (52 active T0 Rego + 8,517 collected Azure Policy/CIS kube-bench) " +
    "and 6 framework tabs (Azure WAF, Azure CAF, MCSB v1/v2-preview with AI-1..AI-7 OWASP LLM/MITRE ATLAS, " +
    "Azure WARA, and MSRC CSAF 2.0 9,058 CVEs with P0-P3 KEV priority). All views are read-only (execution_authority=false).",
  "code-security":
    "Code security (/code-security): review signed multi-lens repository security scans, Kata sandbox verification " +
    "verdicts, P0-P4 / critical-to-low issue counts, known-exploited findings, and adjudication packs (execution_authority=false).",
  "settings-iam":
    "IAM settings (/settings-iam): inspect Entra ID principal identity and server-verified GET /iam/self FDAI roles " +
    "(Reader, Contributor, Approver, Owner). The Console browser never holds cloud or executor credentials.",
  documents:
    "Documents (/documents): inspect governed document ingestion, quarantine/malware/extraction checks, " +
    "collection access boundaries, and handover goal checklists (execution_authority=false).",
  stewardship:
    "Stewardship (/stewardship): review accountable human stewards and scoped duty handovers mapped to the " +
    "fixed 15-agent Pantheon without granting personal IAM or execution authority.",
  "assurance-twin":
    "Assurance twin (/assurance-twin): inspect shadow twin validation, scenario replay, and challenger readiness " +
    "without mutating production resources.",
  "cost-governance":
    "Cost governance (/cost-governance): review FinOps anomaly candidates, pseudonymous cost attribution, and " +
    "budget guardrails (execution_authority=false).",
  "execution-backends":
    "Execution backends (/execution-backends): inspect read-only status and health of isolated execution backends " +
    "without exposing credentials or Thor's executor identity.",
  "hil-queue":
    "Approvals: review pending items and their risk reason; eligible approvers can record " +
    "approve or reject in FDAI Console or a supported channel. A decision never executes " +
    "the managed-resource action.",
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
  architecture:
    "Architecture (/architecture): inspect the live cloud resource topology, dependency edges, " +
    "and layer health projections without mutating infrastructure (execution_authority=false).",
  agents:
    "Agents (/agents): inspect the fixed 15-agent Pantheon charters, owned ObjectTypes, and " +
    "single-writer pub/sub boundaries (execution_authority=false).",
  onboarding:
    "Onboarding (/onboarding): verify read-only target subscription prerequisites, RBAC roles, " +
    "and telemetry readiness before enabling observation loops.",
  capabilities:
    "Capabilities (/capabilities): review available vs enabled capabilities and their shadow/enforce " +
    "promotion mode without bypassing governance gates.",
  "configuration-baselines":
    "Configuration baselines (/configuration-baselines): inspect golden configuration baselines and " +
    "Heimdall drift checks in shadow mode (execution_authority=false).",
  chaos:
    "Chaos (/chaos): review Loki chaos scenarios, blast-radius guards, and steady-state hypotheses " +
    "in shadow mode.",
  "slo-burn":
    "SLO burn (/slo-burn): inspect error-budget burn rates, multi-window alerts, and linked " +
    "ControlObjectives (execution_authority=false).",
  finops:
    "FinOps (/finops): inspect Njord and Freyr right-sizing and cost-anomaly projections " +
    "(execution_authority=false).",
};
