/** Slides 6-10: expose deployable services, Core components, agents, and data ownership. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.en.js";
import { slide } from "./target-architecture-slide-kit.en.js";

export function buildTargetArchitectureRuntime() {
  return [
    slide({
      index: 6,
      id: "service-topology",
      chapter: 2,
      state: "VALIDATED",
      diagramKind: "container",
      title: "FDAI places 15 agents across five independent services",
      lead: "Agents own responsibilities inside Core; they are not Azure services. External HTTPS, internal Kafka, data roles, and effect identities define service boundaries.",
      evidence: ["architectureGuide", "services", "deployment"],
      takeaway: "Each service has its own image, state, migrations, health checks, and identity. Core owns decisions but has no effect identity for managed targets.",
      body: `
        <div class="ta-service-topology" data-ta-diagram="service-topology" data-diagram-kind="container" role="img" aria-label="Container architecture connecting five independent FDAI services through external HTTPS and internal Kafka">
          <div class="ta-service-external">
            ${archNode("svc-operator-user", "HUMAN", "Operator", "", { tone: "human" })}
            ${archNode("svc-upload", "CLIENT", "Document source", "", { tone: "external" })}
          </div>
          <div class="ta-service-external-links">
            ${archLink("svc-operator-user", "svc-operator", { kind: "request", direction: "down", label: "HTTPS" })}
            ${archLink("svc-upload", "svc-ingestion", { kind: "request", direction: "down", label: "HTTPS" })}
          </div>
          <div class="ta-service-apps">
            ${archNode("svc-operator", "SERVICE 02 / HTTPS", "Operator Service", "authenticated read / conversation / proposal", { tone: "service", primary: true, status: "VALIDATED" })}
            ${archNode("svc-ingestion", "SERVICE 03 / HTTPS", "Document Ingestion API", "authenticated intake / validation", { tone: "service", primary: true, status: "VALIDATED" })}
            ${archNode("svc-core", "SERVICE 01 / INTERNAL", "Core Control Plane", "15 agents / decision / coordination", { tone: "control", primary: true, status: "VALIDATED" })}
            ${archNode("svc-worker", "SERVICE 04 / INTERNAL", "Document Processing Worker", "scan / extract / index / reconcile", { tone: "service", primary: true, status: "VALIDATED" })}
            ${archNode("svc-executor", "SERVICE 05 / INTERNAL", "Isolated Executor", "command / lock / provider effect / receipt", { tone: "execution", primary: true, status: "SOLE EFFECT HOLDER" })}
          </div>
          <div class="ta-service-bus-links">
            ${archLink("svc-operator", "svc-bus", { kind: "event", direction: "down" })}
            ${archLink("svc-ingestion", "svc-bus", { kind: "event", direction: "down" })}
            ${archLink("svc-bus", "svc-core", { kind: "event", direction: "up" })}
            ${archLink("svc-bus", "svc-worker", { kind: "event", direction: "up" })}
            ${archLink("svc-bus", "svc-executor", { kind: "approval", direction: "up" })}
          </div>
          ${archNode("svc-bus", "SHARED PLATFORM CONTRACT", "Kafka-compatible Event Fabric", "", { classes: "ta-service-bus", tone: "event", primary: true })}
          <footer><span>SHARED</span><b>wire contracts / Event Hubs / PostgreSQL host / observability</b><span>ISOLATED</span><b>implementation / state / writer role / migration / rollback</b></footer>
        </div>`,
    }),
    slide({
      index: 7,
      id: "service-event-topology",
      chapter: 2,
      state: "VALIDATED",
      diagramKind: "service-flow",
      title: "Services connect through versioned channels, not implementation calls",
      lead: "Operator requests, document processing, Core decisions, Executor commands, and receipts use separate topics and consumer groups for independent restart and replay.",
      evidence: ["architectureGuide", "services", "pantheon"],
      takeaway: "No service reads another service's memory or implementation directly. Each channel isolates delivery failures through its own retries and DLQ.",
      body: `
        <div class="ta-service-event-topology" data-ta-diagram="service-event-topology" data-diagram-kind="service-flow" role="img" aria-label="Service event topology connecting Operator, Ingestion, Worker, Core, and Executor through Kafka topics and projection stores">
          <div class="ta-service-flow-row ta-flow-producers">
            ${archNode("flow-operator", "", "Operator Service", "typed request / approval decision", { tone: "service" })}
            ${archNode("flow-ingestion", "", "Ingestion API", "document accepted / rejected", { tone: "service" })}
            ${archNode("flow-sources", "", "Provider adapters", "inventory / telemetry / change", { tone: "external" })}
          </div>
          <div class="ta-service-flow-links ta-flow-links-in">
            ${archLink("flow-operator", "flow-bus", { kind: "event", direction: "down" })}
            ${archLink("flow-ingestion", "flow-bus", { kind: "event", direction: "down" })}
            ${archLink("flow-sources", "flow-bus", { kind: "event", direction: "down" })}
          </div>
          ${archBoundary("AT-LEAST-ONCE TRANSPORT", "Versioned service Event Bus", `
            <div class="ta-topic-rail"><span>object.*</span><span>document.*</span><span>pipeline.stage</span><span>executor.command</span><span>executor.receipt</span><span>*.dlq</span></div>
          `, { id: "flow-bus", classes: "ta-flow-bus", tone: "event", status: "KAFKA WIRE" })}
          <div class="ta-service-flow-links ta-flow-links-out">
            ${archLink("flow-bus", "flow-worker", { kind: "event", direction: "down" })}
            ${archLink("flow-bus", "flow-core", { kind: "event", direction: "down" })}
            ${archLink("flow-bus", "flow-executor", { kind: "approval", direction: "down" })}
          </div>
          <div class="ta-service-flow-row ta-flow-consumers">
            ${archNode("flow-worker", "", "Processing Worker", "scan / extract / index", { tone: "service" })}
            ${archNode("flow-core", "", "Core Control Plane", "judge / coordinate / audit intent", { tone: "control", primary: true })}
            ${archNode("flow-executor", "", "Isolated Executor", "effect / rollback attempt / receipt", { tone: "execution", primary: true })}
          </div>
          <div class="ta-flow-store-links">
            ${archLink("flow-worker", "flow-projection", { kind: "write", direction: "down" })}
            ${archLink("flow-core", "flow-projection", { kind: "write", direction: "down" })}
            ${archLink("flow-executor", "flow-projection", { kind: "audit", direction: "down" })}
          </div>
          ${archBoundary("SERVICE-OWNED WRITERS", "PostgreSQL projections and ledgers", "", { id: "flow-projection", classes: "ta-flow-projection", tone: "store" })}
          ${archLegend([
            { kind: "event", label: "event" },
            { kind: "approval", label: "command/authority" },
            { kind: "write", label: "owned projection" },
            { kind: "audit", label: "receipt/audit" },
          ])}
        </div>`,
    }),
    slide({
      index: 8,
      id: "core-component-architecture",
      chapter: 2,
      state: "CURRENT",
      diagramKind: "component",
      title: "Core separates decisions, authority, and coordination",
      lead: "Core imports no cloud SDKs and depends only on shared contracts and provider ports. Azure implementations remain behind delivery and composition boundaries.",
      evidence: ["architectureGuide", "projectStructure", "execution"],
      takeaway: "Dependencies point only from Core to abstract contracts. Provider adapters and Console code cannot become reverse dependencies of Core decision logic.",
      body: `
        <div class="ta-core-component" data-ta-diagram="core-component-architecture" data-diagram-kind="component" role="img" aria-label="Components inside the Core Control Plane and their dependency direction through provider ports">
          ${archBoundary("CORE CONTROL PLANE", "Portable decision and coordination components", `
            <div class="ta-core-pipeline">
              ${archNode("core-ingest", "PIPELINE", "Event ingest", "normalize / dedup / correlate", { tone: "input" })}
              ${archLink("core-ingest", "core-context", { kind: "event" })}
              ${archNode("core-context", "PLATFORM", "Operational context", "ontology / evidence / time", { tone: "semantic" })}
              ${archLink("core-context", "core-router", { kind: "read" })}
              ${archNode("core-router", "DECISION", "Trust router + tiers", "T0 / T1 / T2 quality", { tone: "decision", primary: true })}
              ${archLink("core-router", "core-risk", { kind: "decision" })}
              ${archNode("core-risk", "AUTHORITY", "Unified RiskGate", "policy baseline / ceilings / mode", { tone: "policy", primary: true })}
              ${archLink("core-risk", "core-orchestrator", { kind: "approval" })}
              ${archNode("core-orchestrator", "COORDINATE", "Action orchestration", "approval join / audit intent / command", { tone: "control" })}
            </div>
            <div class="ta-core-support">
              ${archNode("core-audit", "EVIDENCE", "Saga audit port", "append-only intent and closure", { tone: "store" })}
              ${archNode("core-recovery", "RECOVERY", "Vidar recovery port", "registered compensation", { tone: "recovery" })}
              ${archNode("core-process", "WORKFLOW", "Durable Process", "revisioned journal / no shared memory", { tone: "service" })}
            </div>
          `, { id: "core-boundary", classes: "ta-core-boundary", tone: "control", status: "NO CLOUD SDK" })}
          <div class="ta-core-port-links">
            ${archLink("core-ports", "core-boundary", { kind: "read", direction: "up", label: "Protocols" })}
          </div>
          ${archBoundary("SHARED CONTRACTS", "Provider-neutral ports", `
            <div class="ta-port-strip"><span>EventBus</span><span>Inventory</span><span>Metric / Log / Trace</span><span>StateStore</span><span>WorkloadIdentity</span><span>ToolExecutor</span></div>
          `, { id: "core-ports", classes: "ta-core-ports", tone: "dependency" })}
          <div class="ta-core-adapter-links">
            ${archLink("core-adapters", "core-ports", { kind: "read", direction: "up", label: "implements" })}
          </div>
          ${archBoundary("DELIVERY + COMPOSITION", "Concrete Azure and persistence adapters", `<span>Event Hubs / Azure Resource Graph / Azure Monitor / PostgreSQL / Git providers / managed identity</span>`, { id: "core-adapters", classes: "ta-core-adapters", tone: "external" })}
        </div>`,
    }),
    slide({
      index: 9,
      id: "agent-runtime-topology",
      chapter: 2,
      state: "CONTRACT",
      diagramKind: "agent-flow",
      title: "The 15 agents fan out and rejoin around object ownership",
      lead: "Huginn normalizes signals, detection and domain evidence converge on Forseti's judgment, Odin resolves conflicts only, and Thor, Var, Vidar, and Saga separate the execution lifecycle.",
      evidence: ["architectureGuide", "pantheon", "constitution"],
      takeaway: "Information can fan out to multiple readers, but only one agent writes each authoritative object. Bragi conversations re-enter the same path as typed proposals.",
      body: `
        <div class="ta-agent-runtime" data-ta-diagram="agent-runtime-topology" data-diagram-kind="agent-flow" role="img" aria-label="Flow of sensing, judgment, operations, governance, and domain evidence across 15 agents">
          <div class="ta-agent-lane ta-agent-sense">
            <small>SENSE</small>
            ${archNode("agent-huginn", "EVENT OWNER", "Huginn", "Event / Change", { tone: "input" })}
            ${archLink("agent-huginn", "agent-heimdall", { kind: "event", direction: "down" })}
            ${archNode("agent-heimdall", "OBSERVER", "Heimdall", "Anomaly / Drift / Outcome", { tone: "evidence" })}
          </div>
          <div class="ta-agent-lane ta-agent-domain">
            <small>DOMAIN EVIDENCE</small>
            ${archNode("agent-njord", "COST", "Njord", "CostAnomaly / Budget", { tone: "semantic" })}
            ${archNode("agent-freyr", "CAPACITY", "Freyr", "Forecast / Sizing", { tone: "semantic" })}
            ${archNode("agent-loki", "RESILIENCE", "Loki", "Experiment / Score", { tone: "semantic" })}
          </div>
          <div class="ta-agent-lane ta-agent-judge">
            <small>JUDGMENT</small>
            ${archNode("agent-forseti", "SOLE JUDGE", "Forseti", "Verdict / RCA / DecisionCase", { tone: "decision", primary: true })}
            ${archLink("agent-forseti", "agent-odin", { kind: "decision", direction: "up" })}
            ${archNode("agent-odin", "ARBITRATE", "Odin", "cross-domain conflict only", { tone: "policy" })}
          </div>
          <div class="ta-agent-lane ta-agent-operate">
            <small>OPERATIONS</small>
            ${archNode("agent-var", "APPROVE", "Var", "Approval", { tone: "approval" })}
            ${archNode("agent-thor", "DISPATCH", "Thor", "ActionRun", { tone: "execution", primary: true })}
            ${archNode("agent-vidar", "RECOVER", "Vidar", "Rollback", { tone: "recovery" })}
          </div>
          <div class="ta-agent-lane ta-agent-govern">
            <small>GOVERNANCE + MEMORY</small>
            ${archNode("agent-saga", "AUDIT", "Saga", "AuditEntry / Issue", { tone: "store" })}
            ${archNode("agent-muninn", "MEMORY", "Muninn", "StateSnapshot / ContextIndex", { tone: "store" })}
            ${archNode("agent-norns", "LEARN", "Norns", "inert RuleCandidate", { tone: "model" })}
            ${archNode("agent-mimir", "CATALOG", "Mimir", "Rule / Policy", { tone: "policy" })}
            ${archNode("agent-bragi", "NARRATE", "Bragi", "Conversation / typed proposal", { tone: "surface" })}
          </div>
          <div class="ta-agent-event-rail"><b>TYPED EVENT FABRIC</b><span>single writer / schema version / correlation / multi-reader fan-out / replay</span></div>
        </div>`,
    }),
    slide({
      index: 10,
      id: "data-ownership-architecture",
      chapter: 2,
      state: "VALIDATED",
      diagramKind: "data",
      title: "Operational records have distinct service ownership",
      lead: "Service writers, Event Bus records, the audit ledger, current ontology projections, and case history each hold different authority. Console consumes read projections only.",
      evidence: ["architectureGuide", "services", "ontology", "deployment"],
      takeaway: "A shared PostgreSQL host does not merge table roles or migration branches. Graph and Console projections never replace authoritative ledgers.",
      body: `
        <div class="ta-data-ownership" data-ta-diagram="data-ownership-architecture" data-diagram-kind="data" role="img" aria-label="Data architecture in which service-owned writers separate PostgreSQL schemas, audit records, ontology projections, and case history">
          <div class="ta-data-writers">
            ${archNode("data-core", "", "Core role", "decision / process / audit intent", { tone: "control" })}
            ${archNode("data-operator", "", "Operator role", "conversation / projections / outbox", { tone: "service" })}
            ${archNode("data-ingestion", "", "Ingestion role", "upload state / validation", { tone: "service" })}
            ${archNode("data-worker", "", "Worker role", "claims / chunks / index", { tone: "service" })}
            ${archNode("data-executor", "", "Executor role", "attempt / lock / receipt", { tone: "execution" })}
          </div>
          <div class="ta-data-write-links">
            ${archLink("data-core", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-operator", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-ingestion", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-worker", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-executor", "data-postgres", { kind: "write", direction: "down" })}
          </div>
          ${archBoundary("ONE HOST / SEPARATE OWNERSHIP", "PostgreSQL Flexible + pgvector", `
            <div class="ta-data-schemas"><span>core schema</span><span>operator schema</span><span>ingestion schema</span><span>worker schema</span><span>executor schema</span></div>
          `, { id: "data-postgres", classes: "ta-data-postgres", tone: "store", status: "5 MIGRATION HEADS" })}
          <div class="ta-data-read-links">
            ${archLink("data-postgres", "data-audit", { kind: "audit", direction: "down" })}
            ${archLink("data-postgres", "data-ontology", { kind: "read", direction: "down" })}
            ${archLink("data-postgres", "data-case", { kind: "read", direction: "down" })}
            ${archLink("data-postgres", "data-console", { kind: "read", direction: "down" })}
          </div>
          <div class="ta-data-read-models">
            ${archNode("data-audit", "AUTHORITATIVE", "Append-only audit", "Saga / hash chain / replay", { tone: "store", primary: true })}
            ${archNode("data-ontology", "READ MODEL", "Current ontology projection", "typed objects / links / completeness", { tone: "semantic", primary: true })}
            ${archNode("data-case", "HISTORY", "Private case history", "content-addressed revisions", { tone: "store" })}
            ${archNode("data-console", "READ ONLY", "Operator projections", "bounded views for Console", { tone: "surface" })}
          </div>
          <footer><b>ZERO OVERLAP</b><span>cross-service implementation imports 0 / writer role overlaps 0 / peer state drift 0</span></footer>
        </div>`,
    }),
  ];
}
