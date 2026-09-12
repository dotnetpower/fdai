import assert from "node:assert/strict";
import { test } from "node:test";

import { buildTargetArchitectureDeck } from "../target-architecture.js";

const slides = buildTargetArchitectureDeck();
const byId = Object.fromEntries(slides.map((slide) => [slide.architecture.id, slide]));
const text = (id) => `${byId[id].title} ${byId[id].lead} ${byId[id].content}`;
const nodes = (id) => [...byId[id].content.matchAll(/data-ta-node=/g)].length;
const links = (id) => [...byId[id].content.matchAll(/class="ta-arch-link/g)].length;

const rounds = [
  ["01 sparse title hierarchy", () => {
    assert.equal(byId.cover.layout, "briefing-target-cover deck-target-architecture");
    assert.doesNotMatch(byId.cover.content, /<(?:img|article|ol|ul|table|figure)\b/);
  }],
  ["02 L0 reference architecture is complete", () => {
    const content = text("reference-architecture");
    for (const term of ["INPUT SYSTEMS", "SYSTEM OF INTEREST", "OUTCOME SYSTEMS", "GOVERNED DEPENDENCIES"]) assert.match(content, new RegExp(term));
    for (const term of ["Schema-validated Event Bus", "Trust routing", "Quality \\+ Risk", "Independent observer", "Ontology · IQL", "OPA · Rego"]) assert.match(content, new RegExp(term));
    assert.ok(nodes("reference-architecture") >= 18);
  }],
  ["03 C4 system context separates actors and managed cloud", () => {
    const content = text("system-context");
    for (const term of ["ACTORS", "FDAI SYSTEM", "MANAGED ENVIRONMENT", "Operator Service", "Core Control Plane", "Isolated Executor"]) assert.match(content, new RegExp(term));
    assert.match(content, /승인도 typed event로 Core에 돌아가며 Executor를 직접 호출하지 않습니다/);
  }],
  ["04 five layers share contracts but not identity", () => {
    const content = text("layer-architecture");
    for (const layer of ["LAYER 05", "LAYER 04", "LAYER 03", "LAYER 02", "LAYER 01"]) assert.match(content, new RegExp(layer));
    for (const rail of ["EVENT BUS", "VERSIONED CONTRACTS", "GIT", "NO SHARED IDENTITY"]) assert.match(content, new RegExp(rail));
  }],
  ["05 closed control loop includes every authority stage", () => {
    const content = text("closed-control-loop");
    for (const stage of ["Typed signal", "Ingest \\+ correlate", "Lowest sufficient Tier", "Quality \\+ RiskGate", "Eligible ActionRun", "Executor", "Independent effect", "Audit \\+ replay"]) assert.match(content, new RegExp(stage));
    for (const terminal of ["Hold / deny / no-op", "Human approval"]) assert.match(content, new RegExp(terminal));
  }],
  ["06 exactly five deployable services are visible", () => {
    const content = text("service-topology");
    for (const service of ["Core Control Plane", "Operator Service", "Document Ingestion API", "Document Processing Worker", "Isolated Executor"]) assert.match(content, new RegExp(service));
    assert.equal((byId["service-topology"].content.match(/SERVICE 0[1-5]/g) ?? []).length, 5);
    assert.match(content, /15개 에이전트.*Azure 서비스 수가 아닙니다/s);
  }],
  ["07 service channels remain versioned and replayable", () => {
    const content = text("service-event-topology");
    for (const term of ["Versioned service Event Bus", "object\\.\\*", "document\\.\\*", "executor\\.command", "executor\\.receipt", "\\*\\.dlq"]) assert.match(content, new RegExp(term));
    assert.match(content, /메모리나 구현을 직접 읽지 않습니다/);
  }],
  ["08 Core component dependencies point outward through ports", () => {
    const content = text("core-component-architecture");
    for (const term of ["Event ingest", "Operational context", "Trust router \\+ tiers", "Unified RiskGate", "Action orchestration", "Provider-neutral ports", "Concrete Azure and persistence adapters"]) assert.match(content, new RegExp(term));
    assert.match(content, /NO CLOUD SDK/);
  }],
  ["09 all fifteen agents appear in one owned-object topology", () => {
    const content = text("agent-runtime-topology");
    const agents = ["Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi", "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr", "Loki"];
    assert.equal(agents.filter((agent) => new RegExp(`>${agent}<`).test(content)).length, 15);
    assert.equal(nodes("agent-runtime-topology"), 15);
    assert.match(content, /한 에이전트만 씁니다/);
  }],
  ["10 state stores preserve service writer ownership", () => {
    const content = text("data-ownership-architecture");
    for (const role of ["Core role", "Operator role", "Ingestion role", "Worker role", "Executor role"]) assert.match(content, new RegExp(role));
    for (const view of ["Append-only audit", "Current ontology projection", "Private case history", "Operator projections"]) assert.match(content, new RegExp(view));
    assert.match(content, /5 MIGRATION HEADS/);
  }],
  ["11 evidence admission binds all trust dimensions", () => {
    const content = text("evidence-admission");
    for (const field of ["authority", "source identity", "scope \\+ purpose", "event \\+ recorded time", "freshness", "completeness", "provenance", "synthetic status"]) assert.match(content, new RegExp(field));
    for (const outcome of ["missing - reacquire", "stale - refresh", "conflict - preserve", "incomplete - narrow", "synthetic - mechanics only"]) assert.match(content, new RegExp(outcome));
  }],
  ["12 ontology graph links scope to independently observed effect", () => {
    const content = text("semantic-architecture");
    for (const term of ["BusinessService", "Workload", "Resource", "Observation / Change", "Objective / Constraint", "DecisionCase", "ActionOption", "ActionRun", "ObservedOutcome"]) assert.match(content, new RegExp(term));
    for (const edge of ["implemented_by", "runs_on", "protects", "considers", "executed_as", "resulted_in"]) assert.match(content, new RegExp(edge));
    assert.match(content, /GRAPH NEVER OWNS.*judgment · approval · permission · effect/s);
  }],
  ["13 late evidence creates a new immutable context revision", () => {
    const content = text("temporal-architecture");
    for (const point of ["event_time", "recorded_time", "evidence_cutoff", "late evidence", "DecisionCase v1", "DecisionCase v2"]) assert.match(content, new RegExp(point));
    assert.match(content, /latest가 아닌 원래 digest/);
    assert.match(content, /bitemporal history가 아닙니다/);
  }],
  ["14 tier routing sends only T2 through the quality gate", () => {
    const content = text("tier-routing-architecture");
    for (const tier of ["T0", "T1", "T2"]) assert.match(content, new RegExp(tier));
    assert.match(content, /T2 ONLY/);
    assert.match(content, /ALL TIERS/);
    assert.match(content, /실제 측정값이 아닙니다/);
  }],
  ["15 RiskGate uses one minimum replayable decision", () => {
    const content = text("risk-gate-architecture");
    for (const input of ["Risk classification table", "Six ActionType ceilings", "Runtime ceilings"]) assert.match(content, new RegExp(input));
    for (const result of ["AUTO", "HUMAN APPROVAL", "OBSERVATION ONLY", "DENY"]) assert.match(content, new RegExp(result));
    assert.match(content, /minimum authority/);
  }],
  ["16 four execution backends share pre-dispatch safety", () => {
    const content = text("execution-dispatch");
    for (const path of ["PR-NATIVE", "DIRECT API", "PR-MANUAL", "TOOL CALL"]) assert.match(content, new RegExp(path));
    for (const gate of ["RiskGate recheck", "approval binding", "seven safeguards", "audit intent"]) assert.match(content, new RegExp(gate));
  }],
  ["17 isolated Executor owns the only provider effect boundary", () => {
    const content = text("isolated-executor-architecture");
    for (const stage of ["Validate command", "Seven safeguards", "Target lock \\+ attempt", "Workload identity", "Registered effect adapter", "ExecutionReceipt", "Recovery path"]) assert.match(content, new RegExp(stage));
    assert.match(content, /SOLE EFFECT HOLDER/);
    assert.match(content, /end-to-end receipt parity in progress/);
  }],
  ["18 identity zones never merge approval and execution", () => {
    const content = text("trust-zone-architecture");
    for (const zone of ["ZONE 1", "ZONE 2", "ZONE 3", "ZONE 4", "ZONE 5"]) assert.match(content, new RegExp(zone));
    assert.match(content, /APPROVAL.*EXECUTION IDENTITY.*OBSERVATION AUTHORITY/s);
    assert.match(content, /fallback하지 않고 거부됩니다/);
  }],
  ["19 independent effect path closes operational outcome", () => {
    const content = text("effect-verification-architecture");
    for (const stage of ["ExpectedEffect", "Isolated Executor", "Managed target", "Authoritative effect source", "Heimdall", "ObservedOutcome", "Saga"]) assert.match(content, new RegExp(stage));
    assert.match(content, /provider 2xx, broker acceptance, PR merge는 dispatch 증거/);
  }],
  ["20 dependency loss lowers mutation eligibility", () => {
    const content = text("degradation-architecture");
    for (const dependency of ["Saga", "Vidar", "Forseti", "Var", "Heimdall", "Executor"]) assert.match(content, new RegExp(dependency));
    assert.match(content, /no cached authority substitution/);
    assert.match(content, /Saga \/ Vidar lost.*no new mutation/s);
  }],
  ["21 eight provider contracts isolate Azure details", () => {
    const content = text("ports-adapters-architecture");
    for (const contract of ["EventBus", "Runtime", "Secret", "Identity", "Inventory", "Metric", "Log", "Trace"]) assert.match(content, new RegExp(contract));
    assert.match(content, /NO AZURE SDK/);
    assert.match(content, /Azure가 유일한 구현 대상/);
  }],
  ["22 Azure deployment nests region VNet services and private data", () => {
    const content = text("azure-deployment-topology");
    for (const boundary of ["AZURE REGION", "PUBLIC / OPERATOR EDGE", "VNET · CONTAINER APPS SUBNET", "PRIVATE DATA PLANE", "OBSERVABILITY"]) assert.match(content, new RegExp(boundary));
    for (const service of ["Core Control Plane", "Console / Operator", "Document Ingestion API", "Processing Worker", "Isolated Executor"]) assert.match(content, new RegExp(service));
    assert.match(content, /PRODUCTION EVIDENCE REQUIRED/);
  }],
  ["23 Azure network flow separates request data model effect and observation", () => {
    const content = text("azure-network-flow");
    for (let step = 1; step <= 8; step += 1) assert.match(content, new RegExp(`0${step} ·`));
    for (const route of ["Microsoft Entra ID", "Static Web Console", "Operator Service", "Event Hubs", "Core Control Plane", "Isolated Executor", "Managed Azure resource", "Azure Monitor sources"]) assert.match(content, new RegExp(route));
    assert.match(content, /private Application Gateway.*목표 상태/s);
  }],
  ["24 artifact delivery and capability promotion remain independent", () => {
    const content = text("release-promotion-architecture");
    assert.match(content, /TRACK A · ARTIFACT DELIVERY/);
    assert.match(content, /TRACK B · CAPABILITY AUTHORITY/);
    for (const stage of ["Signed OCI image", "Sealed exact plan", "Observation mode", "Frozen scenario evidence", "Promotion registry"]) assert.match(content, new RegExp(stage));
    assert.match(content, /deployment never promotes authority/);
  }],
  ["25 review decision cannot grant production or enforce authority", () => {
    const content = text("architecture-decision-map");
    for (const option of ["조건부 승인", "수정 후 재검토", "판단 보류"]) assert.match(content, new RegExp(option));
    for (let blocker = 1; blocker <= 8; blocker += 1) assert.match(content, new RegExp(`ARB-00${blocker}`));
    assert.match(content, /PRODUCTION BLOCKED/);
    assert.match(content, /NO EFFECT.*deployment · enforce · access grant · resource mutation/s);
  }],
  ["26 status language never paints target as current", () => {
    const all = slides.map((slide) => `${slide.architecture.state} ${slide.content}`).join("\n");
    for (const state of ["CURRENT", "VALIDATED", "STATUS", "GAP", "CONTRACT", "DECISION"]) assert.match(all, new RegExp(state));
    assert.match(all, /TARGET/);
    assert.match(all, /in progress/);
    assert.match(all, /production.*blocked/is);
  }],
  ["27 every retained architecture connection has measurable endpoints", () => {
    const body = slides.slice(1);
    assert.ok(body.every((slide) => nodes(slide.architecture.id) >= 4));
    assert.ok(body.every((slide) => links(slide.architecture.id) >= 2));
    assert.ok(body.reduce((sum, slide) => sum + nodes(slide.architecture.id), 0) >= 220);
    assert.ok(body.reduce((sum, slide) => sum + links(slide.architecture.id), 0) >= 120);
    for (const slide of body) {
      assert.equal(links(slide.architecture.id), [...slide.content.matchAll(/data-ta-link data-ta-from=/g)].length);
    }
  }],
  ["28 connection semantics are visible without color", () => {
    const all = slides.map((slide) => slide.content).join("\n");
    for (const kind of ["request", "event", "decision", "approval", "mutation", "observation", "audit", "rollback", "read", "write"]) assert.match(all, new RegExp(`ta-link-${kind}`));
    assert.match(all, /연결선 범례/);
  }],
  ["29 shared component names remain stable across views", () => {
    const all = slides.map((slide) => `${slide.title} ${slide.content}`).join("\n");
    assert.ok((all.match(/Core Control Plane/g) ?? []).length >= 7);
    assert.ok((all.match(/Isolated Executor/g) ?? []).length >= 8);
    assert.ok((all.match(/Operator Service/g) ?? []).length >= 5);
    assert.ok((all.match(/Event Hubs/g) ?? []).length >= 4);
    assert.ok((all.match(/PostgreSQL/g) ?? []).length >= 4);
  }],
  ["30 the deck remains architecture-first end to end", () => {
    const body = slides.slice(1);
    assert.equal(body.filter((slide) => slide.architecture.diagramKind === "architecture").length, 0);
    assert.equal(body.filter((slide) => /data-ta-diagram=/.test(slide.content)).length, 24);
    assert.ok(new Set(body.map((slide) => slide.architecture.diagramKind)).size >= 20);
    assert.match(text("architecture-decision-map"), /L0 경계, 다섯 서비스, 제어 루프, 신원, 실행과 Azure day-zero 배치/);
  }],
];

for (const [name, verify] of rounds) test(`architecture critique round ${name}`, verify);
