/** Slides 11-15: show evidence, semantic, temporal, tier, and authority architecture. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.en.js";
import { slide } from "./target-architecture-slide-kit.en.js";

export function buildTargetArchitectureDecision() {
  return [
    slide({
      index: 11,
      id: "evidence-admission",
      chapter: 3,
      state: "CURRENT",
      diagramKind: "evidence-flow",
      title: "Verify evidence envelopes before admitting external facts",
      lead: "Inventory, telemetry, policy, and audit retain separate authority. Only facts verified for identity, scope, time, completeness, conflict, and synthetic status enter a DecisionCase.",
      evidence: ["architectureGuide", "constitution", "ontology"],
      takeaway: "A current value from one source cannot hide stale or conflicting evidence from another. Admission failures close safely as unknown, reacquire, narrower scope, or hold.",
      body: `
        <div class="ta-evidence-admission" data-ta-diagram="evidence-admission" data-diagram-kind="evidence-flow" role="img" aria-label="Architecture in which authoritative sources pass evidence envelope verification and admission gates to create a DecisionCase">
          ${archBoundary("AUTHORITATIVE SOURCES", "Independent owners of facts", `
            ${archNode("evidence-inventory", "TOPOLOGY", "Inventory", "Resource / Link / coverage", { tone: "azure" })}
            ${archNode("evidence-telemetry", "OBSERVATION", "Telemetry", "event time / window / source", { tone: "evidence" })}
            ${archNode("evidence-intent", "INTENT", "Policy / objectives", "effective interval / owner", { tone: "policy" })}
            ${archNode("evidence-audit", "HISTORY", "Audit / case history", "immutable revision / outcome", { tone: "store" })}
          `, { id: "evidence-sources", classes: "ta-evidence-sources", tone: "external" })}
          ${archLink("evidence-sources", "evidence-receipt", { kind: "event", label: "typed facts" })}
          ${archBoundary("DECISION-CRITICAL RECEIPT", "Evidence envelope for one fact", `
            <div class="ta-evidence-fields"><span>authority</span><span>source identity</span><span>scope + purpose</span><span>event + recorded time</span><span>freshness</span><span>completeness</span><span>provenance</span><span>synthetic status</span></div>
          `, { id: "evidence-receipt", classes: "ta-evidence-receipt", tone: "semantic" })}
          ${archLink("evidence-receipt", "evidence-gate", { kind: "decision" })}
          ${archBoundary("INDEPENDENT VERIFICATION", "Evidence admission", `
            <div class="ta-evidence-checks"><span>authenticate</span><span>bind exact revision</span><span>check freshness</span><span>prove coverage</span><span>retain conflict</span></div>
          `, { id: "evidence-gate", classes: "ta-evidence-gate", tone: "policy" })}
          ${archLink("evidence-gate", "evidence-case", { kind: "read", label: "eligible context" })}
          ${archBoundary("IMMUTABLE DECISION INPUT", "DecisionCase", `
            <div class="ta-decision-case-fields"><span>exact target + revision</span><span>objectives + constraints</span><span>evidence cutoff</span><span>ontology release</span><span>policy digest</span><span>no-action baseline</span></div>
            <b>execution_authority = false</b>
          `, { id: "evidence-case", classes: "ta-evidence-case", tone: "decision", status: "SEALED CONTEXT" })}
          <div class="ta-evidence-safe-outcomes"><b>SAFE FAILURES</b><span>missing - reacquire</span><span>stale - refresh</span><span>conflict - preserve</span><span>incomplete - narrow</span><span>synthetic - mechanics only</span></div>
        </div>`,
    }),
    slide({
      index: 12,
      id: "semantic-architecture",
      chapter: 3,
      state: "CONTRACT",
      diagramKind: "semantic-graph",
      title: "The ontology links scope, intent, facts, decisions, and effects",
      lead: "It anchors service and resource relationships and links observed evidence to each DecisionCase. Every agent reads objectives, alternatives, actions, and outcomes with the same meaning.",
      evidence: ["architectureGuide", "ontology", "constitution"],
      takeaway: "The ontology is a shared semantic read model. Graph writes do not create external facts, while policy, RiskGate, approval, and execution identity remain outside the graph.",
      body: `
        <div class="ta-semantic-architecture" data-ta-diagram="semantic-architecture" data-diagram-kind="semantic-graph" role="img" aria-label="Operating ontology connecting BusinessService, Workload, Resource, Objective, Observation, DecisionCase, ActionRun, and ObservedOutcome">
          <div class="ta-semantic-spine">
            ${archNode("sem-service", "OPERATING SCOPE", "BusinessService", "stable identity / ownership", { tone: "semantic", primary: true })}
            ${archLink("sem-service", "sem-workload", { kind: "semantic", label: "implemented_by" })}
            ${archNode("sem-workload", "DEPLOYABLE", "Workload", "version / environment", { tone: "semantic" })}
            ${archLink("sem-workload", "sem-resource", { kind: "semantic", label: "runs_on" })}
            ${archNode("sem-resource", "OBSERVED", "Resource", "provider-neutral identity", { tone: "azure", primary: true })}
            ${archLink("sem-resource", "sem-observation", { kind: "observation", label: "observed by" })}
            ${archNode("sem-observation", "OPERATING REALITY", "Observation / Change", "source / time / completeness", { tone: "evidence" })}
          </div>
          <div class="ta-semantic-decision">
            ${archNode("sem-objective", "OPERATING INTENT", "Objective / Constraint", "SLO / RTO/RPO / Cost / ARB", { tone: "policy", primary: true })}
            ${archLink("sem-objective", "sem-case", { kind: "semantic", label: "protects" })}
            ${archNode("sem-case", "DECISION", "DecisionCase", "immutable context + alternatives", { tone: "decision", primary: true })}
            ${archLink("sem-case", "sem-option", { kind: "decision", label: "considers" })}
            ${archNode("sem-option", "ALTERNATIVE", "ActionOption", "includes hold and no-op", { tone: "decision" })}
            ${archLink("sem-option", "sem-run", { kind: "mutation", label: "executed_as" })}
            ${archNode("sem-run", "EXECUTION", "ActionRun", "attempt + receipt", { tone: "execution" })}
            ${archLink("sem-run", "sem-outcome", { kind: "observation", label: "resulted_in" })}
            ${archNode("sem-outcome", "EFFECT", "ObservedOutcome", "independently measured", { tone: "evidence", primary: true })}
          </div>
          <footer><span><b>GRAPH OWNS</b> meaning / direction / identity / constraints</span><span><b>GRAPH NEVER OWNS</b> judgment / approval / permission / effect</span></footer>
        </div>`,
    }),
    slide({
      index: 13,
      id: "temporal-architecture",
      chapter: 3,
      state: "CONTRACT",
      diagramKind: "temporal",
      title: "Pin times and revisions to preserve each decision's meaning",
      lead: "Event time, effective interval, recorded time, evidence cutoff, and freshness expiry remain distinct. Late evidence creates a new DecisionCase instead of overwriting prior context.",
      evidence: ["constitution", "ontology"],
      takeaway: "The current instance graph is not bitemporal history. Replay uses the preserved decision context, ontology release, policy digest, and evidence revision.",
      body: `
        <div class="ta-temporal-architecture" data-ta-diagram="temporal-architecture" data-diagram-kind="temporal" role="img" aria-label="Temporal architecture connecting event time, recorded time, decision cutoff, late evidence, and a new DecisionCase revision">
          <header><span>Illustrative times</span><b>trusted UTC + monotonic elapsed time</b><em>Not operational measurements</em></header>
          <div class="ta-temporal-line">
            ${archNode("time-event", "09:08", "event_time", "source occurrence", { tone: "input", primary: true })}
            ${archLink("time-event", "time-recorded", { kind: "timeline" })}
            ${archNode("time-recorded", "09:10", "recorded_time", "FDAI accepted fact", { tone: "store", primary: true })}
            ${archLink("time-recorded", "time-cutoff", { kind: "timeline" })}
            ${archNode("time-cutoff", "09:15", "evidence_cutoff", "DecisionCase v1 sealed", { tone: "decision", primary: true })}
            ${archLink("time-cutoff", "time-late", { kind: "timeline" })}
            ${archNode("time-late", "09:18", "late evidence", "new context required", { tone: "model", primary: true })}
          </div>
          <div class="ta-temporal-revisions">
            ${archNode("time-v1", "IMMUTABLE", "DecisionCase v1", "release A / policy P / evidence E1", { tone: "decision" })}
            ${archLink("time-v1", "time-v2", { kind: "feedback", label: "new revision" })}
            ${archNode("time-v2", "RE-EVALUATE", "DecisionCase v2", "same event / evidence E1 + E2", { tone: "semantic" })}
            <aside><b>effective interval</b><span>period when a fact is valid</span><b>fresh_until</b><span>last reusable time</span><b>replay</b><span>original digest, not latest</span></aside>
          </div>
        </div>`,
    }),
    slide({
      index: 14,
      id: "tier-routing-architecture",
      chapter: 3,
      state: "CURRENT",
      diagramKind: "routing",
      title: "The Trust Router selects the lowest Tier sufficient for a decision",
      lead: "Exact policy matches use T0, currently revalidated similar cases use T1, and only residual ambiguity reaches T2. Every T2 proposal must pass a separate quality gate.",
      evidence: ["architectureGuide", "deterministic", "execution"],
      takeaway: "Tiers select the decision method. T0, T1, and T2 all enter the shared RiskGate, while T2 remains capped at observation mode today.",
      body: `
        <div class="ta-tier-routing-architecture" data-ta-diagram="tier-routing-architecture" data-diagram-kind="routing" role="img" aria-label="Architecture in which the Trust Router selects T0, T1, or T2, and only T2 passes a quality gate before reaching the shared RiskGate">
          ${archNode("tier-signal", "NORMALIZED", "Event + context", "exact target / evidence cutoff", { tone: "input" })}
          ${archLink("tier-signal", "tier-router", { kind: "event" })}
          ${archNode("tier-router", "TRUST ROUTER", "Lowest sufficient Tier", "rule match / similarity / ambiguity", { tone: "decision", primary: true })}
          ${archLink("tier-router", "tier-lanes", { kind: "decision" })}
          ${archBoundary("THREE JUDGMENT PATHS", "Decision methods", `
            <div class="ta-tier-route-lanes">
              <div>${archNode("tier-t0", "T0 / 70-80% TARGET", "Deterministic rules", "policy / checklist / what-if", { tone: "policy" })}<span>exact match</span></div>
              <div>${archNode("tier-t1", "T1 / 15-20% TARGET", "Verified reuse", "case similarity + current recheck", { tone: "semantic" })}<span>known pattern</span></div>
              <div>${archNode("tier-t2", "T2 / 5-10% TARGET", "Grounded reasoning", "two model families + citations", { tone: "model" })}<span>residual ambiguity</span></div>
            </div>
          `, { id: "tier-lanes", classes: "ta-tier-lanes", tone: "control" })}
          ${archLink("tier-lanes", "tier-quality", { kind: "decision" })}
          ${archBoundary("T2 ONLY", "Quality gate", `<div class="ta-quality-checks"><span>schema</span><span>mixed-model agreement</span><span>grounding + citations</span><span>policy recheck</span><span>what-if / dry-run</span><span>security verifier</span></div>`, { id: "tier-quality", classes: "ta-tier-quality", tone: "policy" })}
          ${archLink("tier-quality", "tier-risk", { kind: "decision" })}
          ${archNode("tier-risk", "ALL TIERS", "Unified RiskGate", "authority is evaluated separately", { tone: "execution", primary: true })}
          <footer><span>Displayed percentages are design targets, not actual measurements.</span><b>no rule / low similarity / model disagreement - hold for review</b></footer>
        </div>`,
    }),
    slide({
      index: 15,
      id: "risk-gate-architecture",
      chapter: 3,
      state: "CURRENT",
      diagramKind: "decision-gate",
      title: "The Unified RiskGate never raises the execution ceiling",
      lead: "Risk follows a first-match classification table, then the lowest of six execution ceilings applies. System state, the kill switch, and promotion can only lower the ceiling.",
      evidence: ["execution", "security", "constitution"],
      takeaway: "Human approval and promotion cannot raise the ceiling. Any deny blocks execution, and shadow_only makes no change regardless of approval.",
      body: `
        <div class="ta-risk-gate-architecture" data-ta-diagram="risk-gate-architecture" data-diagram-kind="decision-gate" role="img" aria-label="Unified RiskGate combining the risk table, six execution ceilings, system health, and the kill switch through a minimum operation">
          <div class="ta-risk-inputs">
            ${archBoundary("AXIS A / AUTHORITATIVE", "Risk classification table", `<span>policy violation</span><span>destructive</span><span>irreversible</span><span>data plane</span><span>cost</span><span>confidence</span>`, { id: "risk-table", tone: "policy" })}
            ${archBoundary("NEVER-RAISING", "Six ActionType ceilings", `<span>Tier</span><span>registered ceiling</span><span>static blast</span><span>live blast</span><span>principal role</span><span>environment</span>`, { id: "risk-ceilings", tone: "decision" })}
            ${archBoundary("FAIL-SAFE", "Runtime ceilings", `<span>system health</span><span>global kill switch</span><span>promotion state</span>`, { id: "risk-runtime", tone: "blocked" })}
          </div>
          <div class="ta-risk-links">
            ${archLink("risk-table", "risk-min", { kind: "decision", direction: "down" })}
            ${archLink("risk-ceilings", "risk-min", { kind: "decision", direction: "down" })}
            ${archLink("risk-runtime", "risk-min", { kind: "decision", direction: "down" })}
          </div>
          ${archNode("risk-min", "PURE COMBINATOR", "minimum authority", "enforce_auto > enforce_hil > shadow_only > deny", { tone: "policy", primary: true })}
          ${archLink("risk-min", "risk-result", { kind: "decision", direction: "down" })}
          ${archBoundary("UNIFIED RESULT", "One replayable decision", `
            <div class="ta-risk-results"><span>AUTO</span><span>HUMAN APPROVAL</span><span>OBSERVATION ONLY</span><span>DENY</span></div>
          `, { id: "risk-result", classes: "ta-risk-result", tone: "execution" })}
        </div>`,
    }),
  ];
}
