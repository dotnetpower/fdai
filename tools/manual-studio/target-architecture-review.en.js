/** Slides 2-5: establish the system, layer, and closed-loop architecture views. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.en.js";
import { slide } from "./target-architecture-slide-kit.en.js";

export function buildTargetArchitectureReview() {
  return [
    slide({
      index: 2,
      id: "reference-architecture",
      chapter: 1,
      state: "CONTRACT",
      diagramKind: "reference",
      title: "FDAI separates evidence, decisions, and change authority",
      lead: "External signals and human requests enter as typed events, the headless Core coordinates decisions, and isolated execution plus independent observation close the outcome.",
      evidence: ["architectureGuide", "constitution", "arb"],
      takeaway: "Operators, models, ontology, policy, and the event bus can all inform a decision, but none can create change authority alone.",
      body: `
        <div class="ta-reference-architecture" data-ta-diagram="reference-architecture" data-diagram-kind="system" role="img" aria-label="Reference architecture connecting external signals, the headless FDAI control plane, governed dependencies, execution, and independent observation">
          ${archBoundary("INPUT SYSTEMS", "Operational signals and requests", `
            ${archNode("ref-signals", "PROVIDER", "Azure changes", "resource / activity / policy", { tone: "input" })}
            ${archNode("ref-evidence", "OBSERVE", "Telemetry & inventory", "metrics / logs / traces / topology", { tone: "evidence" })}
            ${archNode("ref-people", "HUMAN", "Operator intent", "Console / CLI / ChatOps", { tone: "human" })}
          `, { id: "ref-inputs", classes: "ta-ref-inputs", tone: "external" })}
          ${archLink("ref-inputs", "ref-control", { kind: "event", classes: "ta-ref-input-link" })}
          ${archBoundary("SYSTEM OF INTEREST", "Headless FDAI Control Plane", `
            <div class="ta-ref-control-flow">
              ${archNode("ref-bus", "CHOREOGRAPHY", "Schema-validated Event Bus", "single writer / multi reader / replay", { tone: "event", primary: true })}
              ${archLink("ref-bus", "ref-pipeline", { kind: "event", direction: "down", classes: "ta-ref-bus-link" })}
              <div class="ta-ref-pipeline" data-ta-node="ref-pipeline">
                ${archNode("ref-ingest", "01", "Ingest", "Huginn", { tone: "input" })}
                ${archLink("ref-ingest", "ref-tier", { kind: "event" })}
                ${archNode("ref-tier", "02", "Trust routing", "T0 / T1 / T2", { tone: "decision" })}
                ${archLink("ref-tier", "ref-risk", { kind: "decision" })}
                ${archNode("ref-risk", "03", "Quality + Risk", "verify / authority ceiling", { tone: "policy" })}
                ${archLink("ref-risk", "ref-dispatch", { kind: "approval" })}
                ${archNode("ref-dispatch", "04", "Dispatch", "Forseti / Var / Thor", { tone: "execution" })}
              </div>
            </div>
          `, { id: "ref-control", classes: "ta-ref-control", tone: "control", status: "HEADLESS" })}
          ${archLink("ref-control", "ref-outcomes", { kind: "mutation", classes: "ta-ref-out-link" })}
          ${archBoundary("OUTCOME SYSTEMS", "Delivery and effect", `
            ${archNode("ref-delivery", "DELIVER", "PR or provider action", "GitOps / bounded direct API", { tone: "execution" })}
            ${archNode("ref-observer", "VERIFY", "Independent observer", "Heimdall / authoritative source", { tone: "evidence" })}
            ${archNode("ref-audit", "RECORD", "Audit and projections", "Saga / PostgreSQL / Console", { tone: "store" })}
          `, { id: "ref-outcomes", classes: "ta-ref-outcomes", tone: "external" })}
          ${archLink("ref-dependencies", "ref-control", { kind: "read", direction: "up", classes: "ta-ref-dependency-link" })}
          ${archBoundary("GOVERNED DEPENDENCIES", "Replaceable capabilities outside Core", `
            ${archNode("ref-models", "REASON", "Models & tools", "Foundry / Azure OpenAI / registered tools", { tone: "model" })}
            ${archNode("ref-semantics", "MEANING", "Ontology / IQL", "typed scope / bounded queries", { tone: "semantic" })}
            ${archNode("ref-policy", "POLICY", "OPA / Rego / catalogs", "rules / ActionTypes / promotion", { tone: "policy" })}
            ${archNode("ref-state", "STATE", "PostgreSQL & case history", "audit / context / vectors", { tone: "store" })}
          `, { id: "ref-dependencies", classes: "ta-ref-dependencies", tone: "dependency" })}
          ${archLegend([
            { kind: "event", label: "event" },
            { kind: "read", label: "read/context" },
            { kind: "approval", label: "authority" },
            { kind: "mutation", label: "mutation" },
          ])}
        </div>`,
    }),
    slide({
      index: 3,
      id: "system-context",
      chapter: 1,
      state: "CONTRACT",
      diagramKind: "context",
      title: "Separate human interfaces, FDAI, and the managed cloud",
      lead: "Console and ChatOps provide queries and requests, Core coordinates decisions, and only the Isolated Executor can use the approved effect role.",
      evidence: ["architectureGuide", "appShape", "security"],
      takeaway: "Browser and natural-language requests cannot bypass execution boundaries. Approval also returns to Core as a typed event and never invokes the Executor directly.",
      body: `
        <div class="ta-system-context" data-ta-diagram="system-context" data-diagram-kind="c4-context" role="img" aria-label="C4 system context linking operators and external systems, the FDAI system boundary, and managed Azure">
          ${archBoundary("ACTORS", "Operators and approvers", `
            ${archNode("ctx-operator", "READ / REQUEST", "Operator", "Console / CLI", { tone: "human", primary: true })}
            ${archNode("ctx-approver", "APPROVE", "Independent approver", "Teams / verified identity", { tone: "approval" })}
          `, { id: "ctx-actors", classes: "ta-context-actors", tone: "external" })}
          ${archLink("ctx-actors", "ctx-fdai", { kind: "request" })}
          ${archBoundary("FDAI SYSTEM", "Headless control plane + thin surfaces", `
            <div class="ta-context-fdai-grid">
              ${archNode("ctx-console", "SURFACE", "FDAI Console", "read-only projections", { tone: "surface" })}
              ${archLink("ctx-console", "ctx-operator-api", { kind: "request" })}
              ${archNode("ctx-operator-api", "NON-PRIVILEGED", "Operator Service", "RBAC / revision / audited request", { tone: "service" })}
              ${archLink("ctx-operator-api", "ctx-core", { kind: "event" })}
              ${archNode("ctx-core", "HEADLESS", "Core Control Plane", "15 agents / decision / coordination", { tone: "control", primary: true })}
              ${archLink("ctx-core", "ctx-executor", { kind: "approval" })}
              ${archNode("ctx-executor", "INTERNAL", "Isolated Executor", "sole eligible effect identity", { tone: "execution", primary: true })}
            </div>
          `, { id: "ctx-fdai", classes: "ta-context-fdai", tone: "control" })}
          <div class="ta-context-managed-links">
            ${archLink("ctx-fdai", "ctx-managed", { kind: "mutation" })}
            ${archLink("ctx-managed", "ctx-fdai", { kind: "observation", direction: "left" })}
          </div>
          ${archBoundary("MANAGED ENVIRONMENT", "Azure and delivery systems", `
            ${archNode("ctx-cloud", "TARGET", "Azure resources", "service / workload / resource", { tone: "azure", primary: true })}
            ${archNode("ctx-git", "DELIVERY", "Git providers", "review / merge / revert", { tone: "external" })}
            ${archNode("ctx-observe", "EVIDENCE", "Authoritative sources", "ARG / Monitor / external state", { tone: "evidence" })}
          `, { id: "ctx-managed", classes: "ta-context-managed", tone: "external" })}
          ${archLegend([
            { kind: "request", label: "human request" },
            { kind: "event", label: "typed event" },
            { kind: "approval", label: "authority join" },
            { kind: "mutation", label: "effect" },
            { kind: "observation", label: "independent evidence" },
          ])}
        </div>`,
    }),
    slide({
      index: 4,
      id: "layer-architecture",
      chapter: 1,
      state: "CONTRACT",
      diagramKind: "layered",
      title: "The five architecture layers share only events, contracts, and Git",
      lead: "Separating surfaces, human approval, decision-making, delivery, and catalogs prevents convenience in one layer from expanding into another layer's identity or authority.",
      evidence: ["architectureGuide", "appShape", "projectStructure"],
      takeaway: "Layers do not share a process or identity. Lower-layer contracts and evidence explain upper-layer surfaces, but surfaces do not calculate operational facts.",
      body: `
        <div class="ta-layer-architecture" data-ta-diagram="layer-architecture" data-diagram-kind="layered" role="img" aria-label="Five layers for human channels, Console, the headless Core, action delivery, and catalogs with evidence">
          <div class="ta-layer-stack">
            ${archNode("layer-human", "LAYER 05 - HUMAN CHANNEL", "Teams / ChatOps", "approval requests / notifications / separate human identity", { tone: "human", primary: true })}
            ${archLink("layer-human", "layer-console", { kind: "request", direction: "down" })}
            ${archNode("layer-console", "LAYER 04 - OPERATOR EXPERIENCE", "Console + Operator", "authoritative projections / scoped requests", { tone: "surface", primary: true })}
            ${archLink("layer-console", "layer-core", { kind: "event", direction: "down" })}
            ${archNode("layer-core", "LAYER 03 - BRAIN", "Core + 15 agents", "normalize / decide / authorize / coordinate / audit", { tone: "control", primary: true })}
            ${archLink("layer-core", "layer-delivery", { kind: "approval", direction: "down" })}
            ${archNode("layer-delivery", "LAYER 02 - HANDS", "Action delivery", "PR-native / Isolated Executor / rollback", { tone: "execution", primary: true })}
            ${archLink("layer-delivery", "layer-catalog", { kind: "audit", direction: "down" })}
            ${archNode("layer-catalog", "LAYER 01 - MEMORY", "Rules & knowledge", "rules / policies / ontology / evidence / case history", { tone: "store", primary: true })}
          </div>
          <aside class="ta-layer-rails">
            <div><b>EVENT BUS</b><span>authority-bearing choreography</span></div>
            <div><b>VERSIONED CONTRACTS</b><span>events / actions / evidence / providers</span></div>
            <div><b>GIT</b><span>catalog / IaC / delivery / rollback</span></div>
            <div class="ta-layer-rule"><strong>NO SHARED IDENTITY</strong><span>Each layer keeps failures and authority independent</span></div>
          </aside>
        </div>`,
    }),
    slide({
      index: 5,
      id: "closed-control-loop",
      chapter: 1,
      state: "CURRENT",
      diagramKind: "control-loop",
      title: "A signal closes only after decision, authority, execution, and independent observation",
      lead: "Only T2 passes an additional quality check; every Tier passes the shared RiskGate and current authority before branching to execution, human approval, hold, or denial.",
      evidence: ["architectureGuide", "constitution", "execution", "pantheon"],
      takeaway: "No arrow in this flow can be skipped. Denial, approval expiry, hold, and recovery close through the same audit path as success.",
      body: `
        <div class="ta-closed-control-loop" data-ta-diagram="closed-control-loop" data-diagram-kind="control-loop" role="img" aria-label="Closed control loop from event ingress through Tier selection, quality verification, RiskGate, approval, isolated execution, independent observation, audit, and replay">
          <div class="ta-loop-main">
            ${archNode("loop-event", "EVENT", "Typed signal", "cloud / detector / operator / job", { tone: "input" })}
            ${archLink("loop-event", "loop-ingest", { kind: "event" })}
            ${archNode("loop-ingest", "HUGINN", "Ingest + correlate", "schema / dedup / identity", { tone: "service" })}
            ${archLink("loop-ingest", "loop-router", { kind: "event" })}
            ${archNode("loop-router", "TRUST ROUTER", "Lowest sufficient Tier", "T0 / T1 / T2", { tone: "decision", primary: true })}
            ${archLink("loop-router", "loop-gate", { kind: "decision" })}
            ${archNode("loop-gate", "VERIFY", "Quality + RiskGate", "T2 quality / policy / authority", { tone: "policy", primary: true })}
            ${archLink("loop-gate", "loop-thor", { kind: "approval" })}
            ${archNode("loop-thor", "THOR", "Eligible ActionRun", "current ceiling rechecked", { tone: "execution" })}
            ${archLink("loop-thor", "loop-executor", { kind: "mutation" })}
            ${archNode("loop-executor", "ISOLATED", "Executor", "lock / effect / receipt", { tone: "execution", primary: true })}
          </div>
          <div class="ta-loop-branches">
            ${archNode("loop-t0", "T0", "Rules / policy", "repeatable", { tone: "policy" })}
            ${archNode("loop-t1", "T1", "Verified reuse", "known pattern", { tone: "semantic" })}
            ${archNode("loop-t2", "T2", "Grounded reasoning", "mixed-model quality gate", { tone: "model" })}
            ${archNode("loop-hil", "VAR", "Human approval", "typed approval event returns to Core", { tone: "approval" })}
            ${archNode("loop-hold", "SAFE TERMINAL", "Hold / deny / no-op", "reason + audit", { tone: "blocked" })}
          </div>
          <div class="ta-loop-close">
            ${archNode("loop-target", "MANAGED", "Target system", "effect belongs to provider", { tone: "azure" })}
            ${archLink("loop-target", "loop-observe", { kind: "observation" })}
            ${archNode("loop-observe", "HEIMDALL", "Independent effect", "authoritative observation window", { tone: "evidence", primary: true })}
            ${archLink("loop-observe", "loop-audit", { kind: "audit" })}
            ${archNode("loop-audit", "SAGA", "Audit + replay", "intent / execution / outcome", { tone: "store", primary: true })}
          </div>
          ${archLegend([
            { kind: "event", label: "event" },
            { kind: "decision", label: "decision" },
            { kind: "approval", label: "approval" },
            { kind: "mutation", label: "mutation" },
            { kind: "observation", label: "observation" },
            { kind: "audit", label: "audit" },
          ])}
        </div>`,
    }),
  ];
}
