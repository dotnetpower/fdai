/** Slides 6-10: expose deployable services, Core components, agents, and data ownership. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.js";
import { slide } from "./target-architecture-slide-kit.js";

export function buildTargetArchitectureRuntime() {
  return [
    slide({
      index: 6,
      id: "service-topology",
      chapter: 2,
      state: "VALIDATED",
      diagramKind: "container",
      title: "FDAI는 15개 에이전트를 다섯 독립 서비스에 배치합니다",
      lead: "에이전트는 Core 안의 책임 소유자이며 Azure 서비스 수가 아닙니다. 외부 HTTPS, 내부 Kafka, 데이터 역할, effect identity가 서비스 경계를 만듭니다.",
      evidence: ["architectureGuide", "services", "deployment"],
      takeaway: "다섯 서비스는 독립 이미지, 상태, 마이그레이션, 상태 점검과 신원을 가집니다. Core는 판단을 소유하지만 관리 대상 효과 신원은 갖지 않습니다.",
      body: `
        <div class="ta-service-topology" data-ta-diagram="service-topology" data-diagram-kind="container" role="img" aria-label="외부 HTTPS와 내부 Kafka를 통해 연결된 다섯 독립 FDAI 서비스의 컨테이너 아키텍처">
          <div class="ta-service-external">
            ${archNode("svc-operator-user", "HUMAN", "Operator", "", { tone: "human" })}
            ${archNode("svc-upload", "CLIENT", "Document source", "", { tone: "external" })}
          </div>
          <div class="ta-service-external-links">
            ${archLink("svc-operator-user", "svc-operator", { kind: "request", direction: "down", label: "HTTPS" })}
            ${archLink("svc-upload", "svc-ingestion", { kind: "request", direction: "down", label: "HTTPS" })}
          </div>
          <div class="ta-service-apps">
            ${archNode("svc-operator", "SERVICE 02 · HTTPS", "Operator Service", "authenticated read · conversation · proposal", { tone: "service", primary: true, status: "VALIDATED" })}
            ${archNode("svc-ingestion", "SERVICE 03 · HTTPS", "Document Ingestion API", "authenticated intake · validation", { tone: "service", primary: true, status: "VALIDATED" })}
            ${archNode("svc-core", "SERVICE 01 · INTERNAL", "Core Control Plane", "15 agents · decision · coordination", { tone: "control", primary: true, status: "VALIDATED" })}
            ${archNode("svc-worker", "SERVICE 04 · INTERNAL", "Document Processing Worker", "scan · extract · index · reconcile", { tone: "service", primary: true, status: "VALIDATED" })}
            ${archNode("svc-executor", "SERVICE 05 · INTERNAL", "Isolated Executor", "command · lock · provider effect · receipt", { tone: "execution", primary: true, status: "SOLE EFFECT HOLDER" })}
          </div>
          <div class="ta-service-bus-links">
            ${archLink("svc-operator", "svc-bus", { kind: "event", direction: "down" })}
            ${archLink("svc-ingestion", "svc-bus", { kind: "event", direction: "down" })}
            ${archLink("svc-bus", "svc-core", { kind: "event", direction: "up" })}
            ${archLink("svc-bus", "svc-worker", { kind: "event", direction: "up" })}
            ${archLink("svc-bus", "svc-executor", { kind: "approval", direction: "up" })}
          </div>
          ${archNode("svc-bus", "SHARED PLATFORM CONTRACT", "Kafka-compatible Event Fabric", "", { classes: "ta-service-bus", tone: "event", primary: true })}
          <footer><span>공유</span><b>wire contracts · Event Hubs · PostgreSQL host · observability</b><span>분리</span><b>implementation · state · writer role · migration · rollback</b></footer>
        </div>`,
    }),
    slide({
      index: 7,
      id: "service-event-topology",
      chapter: 2,
      state: "VALIDATED",
      diagramKind: "service-flow",
      title: "서비스 사이는 구현 호출이 아니라 버전이 있는 채널로 연결됩니다",
      lead: "Operator 요청, 문서 처리, Core 판단, Executor 명령과 영수증은 서로 다른 topic과 consumer group을 사용해 독립적으로 재시작하고 재생합니다.",
      evidence: ["architectureGuide", "services", "pantheon"],
      takeaway: "서비스 하나가 다른 서비스의 메모리나 구현을 직접 읽지 않습니다. 전송 실패는 해당 채널의 재시도와 DLQ로 격리됩니다.",
      body: `
        <div class="ta-service-event-topology" data-ta-diagram="service-event-topology" data-diagram-kind="service-flow" role="img" aria-label="Operator, Ingestion, Worker, Core, Executor를 Kafka topic과 projection store로 연결한 서비스 이벤트 토폴로지">
          <div class="ta-service-flow-row ta-flow-producers">
            ${archNode("flow-operator", "", "Operator Service", "typed request · approval decision", { tone: "service" })}
            ${archNode("flow-ingestion", "", "Ingestion API", "document accepted · rejected", { tone: "service" })}
            ${archNode("flow-sources", "", "Provider adapters", "inventory · telemetry · change", { tone: "external" })}
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
            ${archNode("flow-worker", "", "Processing Worker", "scan · extract · index", { tone: "service" })}
            ${archNode("flow-core", "", "Core Control Plane", "judge · coordinate · audit intent", { tone: "control", primary: true })}
            ${archNode("flow-executor", "", "Isolated Executor", "effect · rollback attempt · receipt", { tone: "execution", primary: true })}
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
      title: "Core 내부는 수집, 의미, 판단, 권한, 조정 컴포넌트로 분리됩니다",
      lead: "Core는 cloud SDK를 가져오지 않고 shared contracts와 provider ports에만 의존합니다. Azure 구현은 delivery와 composition 경계에 머뭅니다.",
      evidence: ["architectureGuide", "projectStructure", "execution"],
      takeaway: "의존 방향은 Core에서 추상 계약으로만 향합니다. provider adapter나 Console 코드는 Core 판단 로직의 역방향 의존성이 될 수 없습니다.",
      body: `
        <div class="ta-core-component" data-ta-diagram="core-component-architecture" data-diagram-kind="component" role="img" aria-label="Core Control Plane 내부 컴포넌트와 provider port 의존 방향">
          ${archBoundary("CORE CONTROL PLANE", "Portable decision and coordination components", `
            <div class="ta-core-pipeline">
              ${archNode("core-ingest", "PIPELINE", "Event ingest", "normalize · dedup · correlate", { tone: "input" })}
              ${archLink("core-ingest", "core-context", { kind: "event" })}
              ${archNode("core-context", "PLATFORM", "Operational context", "ontology · evidence · time", { tone: "semantic" })}
              ${archLink("core-context", "core-router", { kind: "read" })}
              ${archNode("core-router", "DECISION", "Trust router + tiers", "T0 · T1 · T2 quality", { tone: "decision", primary: true })}
              ${archLink("core-router", "core-risk", { kind: "decision" })}
              ${archNode("core-risk", "AUTHORITY", "Unified RiskGate", "policy baseline · ceilings · mode", { tone: "policy", primary: true })}
              ${archLink("core-risk", "core-orchestrator", { kind: "approval" })}
              ${archNode("core-orchestrator", "COORDINATE", "Action orchestration", "approval join · audit intent · command", { tone: "control" })}
            </div>
            <div class="ta-core-support">
              ${archNode("core-audit", "EVIDENCE", "Saga audit port", "append-only intent and closure", { tone: "store" })}
              ${archNode("core-recovery", "RECOVERY", "Vidar recovery port", "registered compensation", { tone: "recovery" })}
              ${archNode("core-process", "WORKFLOW", "Durable Process", "revisioned journal · no shared memory", { tone: "service" })}
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
          ${archBoundary("DELIVERY + COMPOSITION", "Concrete Azure and persistence adapters", `<span>Event Hubs · Azure Resource Graph · Azure Monitor · PostgreSQL · Git providers · managed identity</span>`, { id: "core-adapters", classes: "ta-core-adapters", tone: "external" })}
        </div>`,
    }),
    slide({
      index: 9,
      id: "agent-runtime-topology",
      chapter: 2,
      state: "CONTRACT",
      diagramKind: "agent-flow",
      title: "15개 에이전트는 객체 소유권을 따라 fan-out하고 다시 결합합니다",
      lead: "Huginn이 신호를 정규화하고, 감지와 도메인 근거가 Forseti 판단에 모이며, Odin은 충돌만 조정하고 Thor, Var, Vidar, Saga가 실행 수명 주기를 분리합니다.",
      evidence: ["architectureGuide", "pantheon", "constitution"],
      takeaway: "정보는 여러 독자에게 퍼질 수 있지만 권위 있는 객체는 한 에이전트만 씁니다. Bragi 대화도 typed proposal로 같은 경로에 재진입합니다.",
      body: `
        <div class="ta-agent-runtime" data-ta-diagram="agent-runtime-topology" data-diagram-kind="agent-flow" role="img" aria-label="15개 에이전트의 sensing, judgment, operations, governance, domain evidence 흐름">
          <div class="ta-agent-lane ta-agent-sense">
            <small>SENSE</small>
            ${archNode("agent-huginn", "EVENT OWNER", "Huginn", "Event · Change", { tone: "input" })}
            ${archLink("agent-huginn", "agent-heimdall", { kind: "event", direction: "down" })}
            ${archNode("agent-heimdall", "OBSERVER", "Heimdall", "Anomaly · Drift · Outcome", { tone: "evidence" })}
          </div>
          <div class="ta-agent-lane ta-agent-domain">
            <small>DOMAIN EVIDENCE</small>
            ${archNode("agent-njord", "COST", "Njord", "CostAnomaly · Budget", { tone: "semantic" })}
            ${archNode("agent-freyr", "CAPACITY", "Freyr", "Forecast · Sizing", { tone: "semantic" })}
            ${archNode("agent-loki", "RESILIENCE", "Loki", "Experiment · Score", { tone: "semantic" })}
          </div>
          <div class="ta-agent-lane ta-agent-judge">
            <small>JUDGMENT</small>
            ${archNode("agent-forseti", "SOLE JUDGE", "Forseti", "Verdict · RCA · DecisionCase", { tone: "decision", primary: true })}
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
            ${archNode("agent-saga", "AUDIT", "Saga", "AuditEntry · Issue", { tone: "store" })}
            ${archNode("agent-muninn", "MEMORY", "Muninn", "StateSnapshot · ContextIndex", { tone: "store" })}
            ${archNode("agent-norns", "LEARN", "Norns", "inert RuleCandidate", { tone: "model" })}
            ${archNode("agent-mimir", "CATALOG", "Mimir", "Rule · Policy", { tone: "policy" })}
            ${archNode("agent-bragi", "NARRATE", "Bragi", "Conversation · typed proposal", { tone: "surface" })}
          </div>
          <div class="ta-agent-event-rail"><b>TYPED EVENT FABRIC</b><span>single writer · schema version · correlation · multi-reader fan-out · replay</span></div>
        </div>`,
    }),
    slide({
      index: 10,
      id: "data-ownership-architecture",
      chapter: 2,
      state: "VALIDATED",
      diagramKind: "data",
      title: "운영 기록은 서비스별로 소유권을 분리합니다",
      lead: "각 서비스 writer, Event Bus 기록, audit ledger, current ontology projection, case history가 서로 다른 권위를 가지며 Console은 읽기 투영만 사용합니다.",
      evidence: ["architectureGuide", "services", "ontology", "deployment"],
      takeaway: "PostgreSQL host를 공유해도 table role과 migration branch는 분리됩니다. 그래프와 Console 투영은 권위 있는 원장을 대체하지 않습니다.",
      body: `
        <div class="ta-data-ownership" data-ta-diagram="data-ownership-architecture" data-diagram-kind="data" role="img" aria-label="서비스 소유 writer가 PostgreSQL schema, audit, ontology projection, case history를 분리하는 데이터 아키텍처">
          <div class="ta-data-writers">
            ${archNode("data-core", "", "Core role", "decision · process · audit intent", { tone: "control" })}
            ${archNode("data-operator", "", "Operator role", "conversation · projections · outbox", { tone: "service" })}
            ${archNode("data-ingestion", "", "Ingestion role", "upload state · validation", { tone: "service" })}
            ${archNode("data-worker", "", "Worker role", "claims · chunks · index", { tone: "service" })}
            ${archNode("data-executor", "", "Executor role", "attempt · lock · receipt", { tone: "execution" })}
          </div>
          <div class="ta-data-write-links">
            ${archLink("data-core", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-operator", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-ingestion", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-worker", "data-postgres", { kind: "write", direction: "down" })}
            ${archLink("data-executor", "data-postgres", { kind: "write", direction: "down" })}
          </div>
          ${archBoundary("ONE HOST · SEPARATE OWNERSHIP", "PostgreSQL Flexible + pgvector", `
            <div class="ta-data-schemas"><span>core schema</span><span>operator schema</span><span>ingestion schema</span><span>worker schema</span><span>executor schema</span></div>
          `, { id: "data-postgres", classes: "ta-data-postgres", tone: "store", status: "5 MIGRATION HEADS" })}
          <div class="ta-data-read-links">
            ${archLink("data-postgres", "data-audit", { kind: "audit", direction: "down" })}
            ${archLink("data-postgres", "data-ontology", { kind: "read", direction: "down" })}
            ${archLink("data-postgres", "data-case", { kind: "read", direction: "down" })}
            ${archLink("data-postgres", "data-console", { kind: "read", direction: "down" })}
          </div>
          <div class="ta-data-read-models">
            ${archNode("data-audit", "AUTHORITATIVE", "Append-only audit", "Saga · hash chain · replay", { tone: "store", primary: true })}
            ${archNode("data-ontology", "READ MODEL", "Current ontology projection", "typed objects · links · completeness", { tone: "semantic", primary: true })}
            ${archNode("data-case", "HISTORY", "Private case history", "content-addressed revisions", { tone: "store" })}
            ${archNode("data-console", "READ ONLY", "Operator projections", "bounded views for Console", { tone: "surface" })}
          </div>
          <footer><b>ZERO OVERLAP</b><span>다른 서비스 구현 import 0 · writer role overlap 0 · peer state drift 0</span></footer>
        </div>`,
    }),
  ];
}
