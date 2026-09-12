/** Slides 16-20: show dispatch, isolated execution, trust, effects, and degradation architecture. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.en.js";
import { slide } from "./target-architecture-slide-kit.en.js";

export function buildTargetArchitectureExecution() {
  return [
    slide({
      index: 16,
      id: "execution-dispatch",
      chapter: 4,
      state: "CURRENT",
      diagramKind: "dispatch",
      title: "One eligible ActionRun leaves through exactly one of four registered delivery paths",
      lead: "The RiskGate outcome and the ActionType execution_path select dispatch. A backend cannot bypass approval, locking, recovery, audit, or effect verification, and it cannot create a new role.",
      evidence: ["architectureGuide", "execution", "security"],
      takeaway: "PR-native, direct API, PR-manual, and tool calls differ only in delivery method. Every path rechecks the same current authority and safety contract.",
      body: `
        <div class="ta-execution-dispatch" data-ta-diagram="execution-dispatch" data-diagram-kind="dispatch" role="img" aria-label="Eligible ActionRun passing through a shared pre-dispatch gate and branching to one of four execution paths">
          ${archNode("dispatch-run", "ELIGIBLE", "ActionRun", "target / revision / idempotency / ExpectedEffect", { tone: "decision", primary: true })}
          ${archLink("dispatch-run", "dispatch-gates", { kind: "decision" })}
          ${archBoundary("EVERY PATH", "Pre-dispatch safety boundary", `<span>RiskGate recheck</span><span>approval binding</span><span>seven safeguards</span><span>audit intent</span>`, { id: "dispatch-gates", classes: "ta-dispatch-gates", tone: "policy" })}
          ${archLink("dispatch-gates", "dispatch-paths", { kind: "approval" })}
          ${archBoundary("ACTIONTYPE SELECTS ONE", "Delivery backends", `
            <div class="ta-dispatch-path-grid">
              ${archNode("dispatch-pr-native", "PR-NATIVE", "Policy merge PR", "review / revert / optional auto merge", { tone: "execution" })}
              ${archNode("dispatch-direct", "DIRECT API", "Provider call", "isolated identity / typed rollback", { tone: "execution" })}
              ${archNode("dispatch-pr-manual", "PR-MANUAL", "Human merge PR", "no automatic merge", { tone: "approval" })}
              ${archNode("dispatch-tool", "TOOL CALL", "Registered function", "bounded capability / no substrate mutation", { tone: "service" })}
            </div>
          `, { id: "dispatch-paths", classes: "ta-dispatch-paths", tone: "control" })}
          ${archLink("dispatch-paths", "dispatch-outcome", { kind: "audit" })}
          ${archNode("dispatch-outcome", "TERMINAL RECEIPT", "Delivery outcome", "success not claimed until independent observation", { tone: "store", primary: true })}
          <footer><b>BACKEND RULE</b><span>same authority roles / same target lock / same rollback contract / same audit lifecycle</span></footer>
        </div>`,
    }),
    slide({
      index: 17,
      id: "isolated-executor-architecture",
      chapter: 4,
      state: "STATUS",
      diagramKind: "component",
      title: "Locking, effect identity, and provider mutation meet only inside the Isolated Executor",
      lead: "The Executor validates a versioned command and attempts a provider effect with a short-lived workload identity only when all seven safeguards are bound to the current revision.",
      evidence: ["architectureGuide", "services", "security", "execution"],
      takeaway: "The service and effect identity separation is validated. Complete safeguard receipts and equivalent independent effect closure across Workflow and isolated execution paths remain in progress.",
      body: `
        <div class="ta-isolated-executor" data-ta-diagram="isolated-executor-architecture" data-diagram-kind="component" role="img" aria-label="Internal flow from Executor command receipt through validation, seven safeguards, locking, workload identity, provider effect, receipt, and rollback">
          ${archNode("executor-command", "EXECUTOR COMMAND", "Versioned command", "schema / correlation / deadline / exact target", { tone: "event", primary: true })}
          ${archLink("executor-command", "executor-boundary", { kind: "approval" })}
          ${archBoundary("INTERNAL SERVICE - NO PUBLIC INGRESS", "Isolated Executor", `
            <div class="ta-executor-pipeline">
              ${archNode("executor-validate", "01", "Validate command", "schema / ActionType / authority / deadline", { tone: "policy" })}
              ${archLink("executor-validate", "executor-safeguards", { kind: "decision" })}
              ${archNode("executor-safeguards", "02", "Seven safeguards", "stop / rollback / impact / dry-run / lock / idempotency / audit", { tone: "policy", primary: true })}
              ${archLink("executor-safeguards", "executor-lock", { kind: "decision" })}
              ${archNode("executor-lock", "03", "Target lock + attempt", "durable claim / duplicate suppression", { tone: "store" })}
              ${archLink("executor-lock", "executor-identity", { kind: "approval" })}
              ${archNode("executor-identity", "04", "Workload identity", "audience-scoped OIDC / action allowlist", { tone: "execution", primary: true })}
            </div>
            <div class="ta-executor-status"><span data-status="VALIDATED">service + identity boundary validated</span><span data-status="GAP">end-to-end receipt parity in progress</span></div>
          `, { id: "executor-boundary", classes: "ta-executor-boundary", tone: "execution", status: "SOLE EFFECT HOLDER" })}
          ${archLink("executor-boundary", "executor-provider", { kind: "mutation" })}
          ${archNode("executor-provider", "PROVIDER", "Registered effect adapter", "Azure ARM / Git / bounded tool", { tone: "azure", primary: true })}
          <div class="ta-executor-return">
            ${archNode("executor-receipt", "EVENT BUS", "ExecutionReceipt", "attempt / provider ref / rollback ref / terminal status", { tone: "store" })}
            ${archNode("executor-rollback", "VIDAR", "Recovery path", "normal typed pipeline / independent verification", { tone: "recovery" })}
          </div>
          ${archLegend([
            { kind: "approval", label: "authority" },
            { kind: "mutation", label: "effect" },
            { kind: "audit", label: "receipt" },
            { kind: "rollback", label: "recovery" },
          ])}
        </div>`,
    }),
    slide({
      index: 18,
      id: "trust-zone-architecture",
      chapter: 4,
      state: "VALIDATED",
      diagramKind: "trust-boundary",
      title: "Human approval, service decisions, and workload execution occupy separate trust zones",
      lead: "The Entra principal, non-privileged Operator identity, Core coordination identity, Executor workload identity, and provider role cannot substitute for one another.",
      evidence: ["architectureGuide", "security", "services", "appShape"],
      takeaway: "Approval satisfies an authority condition for a specific ActionRun; it does not issue an Azure role. An unknown identity ref is denied rather than falling back to an aggregate identity.",
      body: `
        <div class="ta-trust-zone-architecture" data-ta-diagram="trust-zone-architecture" data-diagram-kind="trust-boundary" role="img" aria-label="Separate trust zones for human identity, Console, Operator, Core, Isolated Executor, and the Azure effect role">
          ${archBoundary("ZONE 1 - HUMAN", "Entra identity", `
            ${archNode("trust-human", "MFA + APP ROLE", "Operator / approver", "requester and approver remain distinct", { tone: "human", primary: true })}
          `, { id: "trust-human-zone", classes: "ta-trust-zone", tone: "human" })}
          ${archLink("trust-human-zone", "trust-edge-zone", { kind: "request" })}
          ${archBoundary("ZONE 2 - EDGE", "Console + Operator Service", `
            ${archNode("trust-console", "STATIC", "FDAI Console", "no browser authorization logic", { tone: "surface" })}
            ${archNode("trust-operator", "SERVICE MI", "Operator identity", "read projections / submit typed request", { tone: "service", primary: true })}
          `, { id: "trust-edge-zone", classes: "ta-trust-zone", tone: "surface" })}
          ${archLink("trust-edge-zone", "trust-core-zone", { kind: "event" })}
          ${archBoundary("ZONE 3 - DECISION", "Core Control Plane", `
            ${archNode("trust-core", "NO EFFECT ROLE", "Decision identity", "judge / risk / approval join / audit intent", { tone: "control", primary: true })}
          `, { id: "trust-core-zone", classes: "ta-trust-zone", tone: "control" })}
          ${archLink("trust-core-zone", "trust-executor-zone", { kind: "approval" })}
          ${archBoundary("ZONE 4 - EFFECT", "Isolated Executor", `
            ${archNode("trust-executor", "UAMI + OIDC", "Workload identity", "non-interactive / exact audience / action whitelist / target scope", { tone: "execution", primary: true })}
          `, { id: "trust-executor-zone", classes: "ta-trust-zone", tone: "execution" })}
          ${archLink("trust-executor-zone", "trust-provider-zone", { kind: "mutation" })}
          ${archBoundary("ZONE 5 - PROVIDER", "Azure effective access", `
            ${archNode("trust-provider", "DENY BY DEFAULT", "Scoped provider role", "resource or governed RG / never subscription-wide", { tone: "azure", primary: true })}
          `, { id: "trust-provider-zone", classes: "ta-trust-zone", tone: "external" })}
          <footer><span>APPROVAL</span><b>is not</b><span>EXECUTION IDENTITY</span><b>is not</b><span>OBSERVATION AUTHORITY</span></footer>
        </div>`,
    }),
    slide({
      index: 19,
      id: "effect-verification-architecture",
      chapter: 4,
      state: "GAP",
      diagramKind: "effect-loop",
      title: "Operational success is decided by an observation path separate from the Executor receipt",
      lead: "The plan first fixes the ExpectedEffect and observation window. After the ActionRun, Heimdall observes the result through an authoritative source separate from the execution channel and creates an ObservedOutcome.",
      evidence: ["architectureGuide", "constitution", "ontology", "security"],
      takeaway: "A provider 2xx, broker acceptance, or PR merge is dispatch evidence. Missing or conflicting observations close as pending, mismatch, timeout, or unscorable instead of success.",
      body: `
        <div class="ta-effect-verification" data-ta-diagram="effect-verification-architecture" data-diagram-kind="effect-loop" role="img" aria-label="Effect verification architecture connecting ExpectedEffect, Executor, managed target, independent observer, ObservedOutcome, and Saga audit">
          <div class="ta-effect-plan">
            ${archNode("effect-expected", "BEFORE", "ExpectedEffect", "metric / direction / range / source / window", { tone: "decision", primary: true })}
            ${archLink("effect-expected", "effect-executor", { kind: "decision" })}
            ${archNode("effect-executor", "ATTEMPT", "Isolated Executor", "locked effect + execution receipt", { tone: "execution", primary: true })}
            ${archLink("effect-executor", "effect-target", { kind: "mutation" })}
            ${archNode("effect-target", "EXTERNAL TRUTH", "Managed target", "provider owns current state", { tone: "azure", primary: true })}
          </div>
          <div class="ta-effect-observation">
            ${archNode("effect-source", "SEPARATE CHANNEL", "Authoritative effect source", "telemetry / inventory / health / Git state", { tone: "evidence", primary: true })}
            ${archLink("effect-source", "effect-heimdall", { kind: "observation", direction: "left" })}
            ${archNode("effect-heimdall", "OBSERVER", "Heimdall", "freshness / completeness / conflict / window", { tone: "evidence" })}
            ${archLink("effect-heimdall", "effect-outcome", { kind: "observation", direction: "left" })}
            ${archNode("effect-outcome", "CLOSE", "ObservedOutcome", "matched / mismatched / timeout / unscorable", { tone: "store", primary: true })}
            ${archLink("effect-outcome", "effect-saga", { kind: "audit", direction: "left" })}
            ${archNode("effect-saga", "AUDIT", "Saga", "intent + execution + outcome", { tone: "store" })}
          </div>
          <div class="ta-effect-cross-link">${archLink("effect-target", "effect-source", { kind: "observation", direction: "down" })}</div>
          <footer><span data-status="IMPLEMENTED">semantic contracts + reducers</span><span data-status="GAP">isolated runtime end-to-end effect closure in progress</span></footer>
        </div>`,
    }),
    slide({
      index: 20,
      id: "degradation-architecture",
      chapter: 4,
      state: "CONTRACT",
      diagramKind: "resilience",
      title: "A dependency failure does not promote another role",
      lead: "FDAI checks the state of audit, recovery, judgment, human approval, independent observation, and execution separately. It holds or blocks change unless the complete contract remains available.",
      evidence: ["architectureGuide", "constitution", "pantheon", "security"],
      takeaway: "Safe degradation is not a hidden fallback. It names whether read, deny, queue, or shadow paths remain and never infers an effect.",
      body: `
        <div class="ta-degradation-architecture" data-ta-diagram="degradation-architecture" data-diagram-kind="resilience" role="img" aria-label="Degradation architecture where the states of Saga, Vidar, Forseti, Var, Heimdall, and Executor reduce central mutation eligibility">
          <div class="ta-dependency-row">
            ${archNode("dep-saga", "AUDIT", "Saga", "hard dependency", { tone: "store" })}
            ${archNode("dep-vidar", "RECOVERY", "Vidar", "hard dependency", { tone: "recovery" })}
            ${archNode("dep-forseti", "JUDGE", "Forseti", "no verdict fallback", { tone: "decision" })}
            ${archNode("dep-var", "APPROVAL", "Var", "approval lane only", { tone: "approval" })}
            ${archNode("dep-heimdall", "OBSERVER", "Heimdall", "effect closure", { tone: "evidence" })}
            ${archNode("dep-executor", "EFFECT", "Executor", "command consumer", { tone: "execution" })}
          </div>
          <div class="ta-dependency-links">
            ${archLink("dep-saga", "dep-eligibility", { kind: "audit", direction: "down" })}
            ${archLink("dep-vidar", "dep-eligibility", { kind: "rollback", direction: "down" })}
            ${archLink("dep-forseti", "dep-eligibility", { kind: "decision", direction: "down" })}
            ${archLink("dep-var", "dep-eligibility", { kind: "approval", direction: "down" })}
            ${archLink("dep-heimdall", "dep-eligibility", { kind: "observation", direction: "down" })}
            ${archLink("dep-executor", "dep-eligibility", { kind: "mutation", direction: "down" })}
          </div>
          ${archBoundary("RUNTIME SAFETY REDUCER", "Mutation eligibility", `<span>available contracts only</span><span>no cached authority substitution</span><span>stale verdicts expire</span>`, { id: "dep-eligibility", classes: "ta-dependency-eligibility", tone: "policy" })}
          ${archLink("dep-eligibility", "dep-outcomes", { kind: "decision", direction: "down" })}
          ${archBoundary("SAFE DEGRADATION", "Remaining paths", `
            <div class="ta-degradation-outcomes"><span><b>Saga / Vidar lost</b> no new mutation</span><span><b>Forseti lost</b> ingest + queue</span><span><b>Var lost</b> approval work waits</span><span><b>Heimdall lost</b> outcome remains pending</span><span><b>Executor lost</b> verdict expires and re-judges</span></div>
          `, { id: "dep-outcomes", classes: "ta-dependency-outcomes", tone: "blocked" })}
        </div>`,
    }),
  ];
}
