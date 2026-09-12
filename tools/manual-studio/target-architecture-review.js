/** Slides 2-5: establish the system, layer, and closed-loop architecture views. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.js";
import { slide } from "./target-architecture-slide-kit.js";

export function buildTargetArchitectureReview() {
  return [
    slide({
      index: 2,
      id: "reference-architecture",
      chapter: 1,
      state: "CONTRACT",
      diagramKind: "reference",
      title: "한 장으로 보면 FDAI는 근거와 권한을 분리한 운영 제어 영역입니다",
      lead: "외부 신호와 사람 요청은 typed event로 들어오고, 헤드리스 Core가 판단을 조정하며, 격리 실행과 독립 관측이 결과를 닫습니다.",
      evidence: ["architectureGuide", "constitution", "arb"],
      takeaway: "운영자, 모델, 온톨로지, 정책, 이벤트 버스는 모두 판단에 기여할 수 있지만 어느 하나도 단독으로 변경 권한을 만들지 않습니다.",
      body: `
        <div class="ta-reference-architecture" data-ta-diagram="reference-architecture" data-diagram-kind="system" role="img" aria-label="외부 신호, 헤드리스 FDAI 제어 영역, 통제된 의존 기능, 실행과 독립 관측을 연결한 참조 아키텍처">
          ${archBoundary("INPUT SYSTEMS", "운영 신호와 요청", `
            ${archNode("ref-signals", "PROVIDER", "Azure changes", "resource · activity · policy", { tone: "input" })}
            ${archNode("ref-evidence", "OBSERVE", "Telemetry & inventory", "metrics · logs · traces · topology", { tone: "evidence" })}
            ${archNode("ref-people", "HUMAN", "Operator intent", "Console · CLI · ChatOps", { tone: "human" })}
          `, { id: "ref-inputs", classes: "ta-ref-inputs", tone: "external" })}
          ${archLink("ref-inputs", "ref-control", { kind: "event", classes: "ta-ref-input-link" })}
          ${archBoundary("SYSTEM OF INTEREST", "Headless FDAI Control Plane", `
            <div class="ta-ref-control-flow">
              ${archNode("ref-bus", "CHOREOGRAPHY", "Schema-validated Event Bus", "single writer · multi reader · replay", { tone: "event", primary: true })}
              ${archLink("ref-bus", "ref-pipeline", { kind: "event", direction: "down", classes: "ta-ref-bus-link" })}
              <div class="ta-ref-pipeline" data-ta-node="ref-pipeline">
                ${archNode("ref-ingest", "01", "Ingest", "Huginn", { tone: "input" })}
                ${archLink("ref-ingest", "ref-tier", { kind: "event" })}
                ${archNode("ref-tier", "02", "Trust routing", "T0 · T1 · T2", { tone: "decision" })}
                ${archLink("ref-tier", "ref-risk", { kind: "decision" })}
                ${archNode("ref-risk", "03", "Quality + Risk", "verify · authority ceiling", { tone: "policy" })}
                ${archLink("ref-risk", "ref-dispatch", { kind: "approval" })}
                ${archNode("ref-dispatch", "04", "Dispatch", "Forseti · Var · Thor", { tone: "execution" })}
              </div>
            </div>
          `, { id: "ref-control", classes: "ta-ref-control", tone: "control", status: "HEADLESS" })}
          ${archLink("ref-control", "ref-outcomes", { kind: "mutation", classes: "ta-ref-out-link" })}
          ${archBoundary("OUTCOME SYSTEMS", "전달과 효과", `
            ${archNode("ref-delivery", "DELIVER", "PR or provider action", "GitOps · bounded direct API", { tone: "execution" })}
            ${archNode("ref-observer", "VERIFY", "Independent observer", "Heimdall · authoritative source", { tone: "evidence" })}
            ${archNode("ref-audit", "RECORD", "Audit and projections", "Saga · PostgreSQL · Console", { tone: "store" })}
          `, { id: "ref-outcomes", classes: "ta-ref-outcomes", tone: "external" })}
          ${archLink("ref-dependencies", "ref-control", { kind: "read", direction: "up", classes: "ta-ref-dependency-link" })}
          ${archBoundary("GOVERNED DEPENDENCIES", "Core 밖의 교체 가능한 기능", `
            ${archNode("ref-models", "REASON", "Models & tools", "Foundry · Azure OpenAI · registered tools", { tone: "model" })}
            ${archNode("ref-semantics", "MEANING", "Ontology · IQL", "typed scope · bounded queries", { tone: "semantic" })}
            ${archNode("ref-policy", "POLICY", "OPA · Rego · catalogs", "rules · ActionTypes · promotion", { tone: "policy" })}
            ${archNode("ref-state", "STATE", "PostgreSQL & case history", "audit · context · vectors", { tone: "store" })}
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
      title: "사람 접점, FDAI, 관리 대상 클라우드는 서로 다른 시스템 경계입니다",
      lead: "Console과 ChatOps는 조회와 요청을 제공하고, Core는 판단을 조정하며, Isolated Executor만 승인된 effect role을 사용할 수 있습니다.",
      evidence: ["architectureGuide", "appShape", "security"],
      takeaway: "브라우저나 자연어 요청은 실행 경계를 건너뛰지 않습니다. 승인도 typed event로 Core에 돌아가며 Executor를 직접 호출하지 않습니다.",
      body: `
        <div class="ta-system-context" data-ta-diagram="system-context" data-diagram-kind="c4-context" role="img" aria-label="운영자와 외부 시스템, FDAI 시스템 경계, 관리 대상 Azure 사이의 C4 시스템 맥락">
          ${archBoundary("ACTORS", "운영자와 승인자", `
            ${archNode("ctx-operator", "READ / REQUEST", "Operator", "Console · CLI", { tone: "human", primary: true })}
            ${archNode("ctx-approver", "APPROVE", "Independent approver", "Teams · verified identity", { tone: "approval" })}
          `, { id: "ctx-actors", classes: "ta-context-actors", tone: "external" })}
          ${archLink("ctx-actors", "ctx-fdai", { kind: "request" })}
          ${archBoundary("FDAI SYSTEM", "Headless control plane + thin surfaces", `
            <div class="ta-context-fdai-grid">
              ${archNode("ctx-console", "SURFACE", "FDAI Console", "read-only projections", { tone: "surface" })}
              ${archLink("ctx-console", "ctx-operator-api", { kind: "request" })}
              ${archNode("ctx-operator-api", "NON-PRIVILEGED", "Operator Service", "RBAC · revision · audited request", { tone: "service" })}
              ${archLink("ctx-operator-api", "ctx-core", { kind: "event" })}
              ${archNode("ctx-core", "HEADLESS", "Core Control Plane", "15 agents · decision · coordination", { tone: "control", primary: true })}
              ${archLink("ctx-core", "ctx-executor", { kind: "approval" })}
              ${archNode("ctx-executor", "INTERNAL", "Isolated Executor", "sole eligible effect identity", { tone: "execution", primary: true })}
            </div>
          `, { id: "ctx-fdai", classes: "ta-context-fdai", tone: "control" })}
          <div class="ta-context-managed-links">
            ${archLink("ctx-fdai", "ctx-managed", { kind: "mutation" })}
            ${archLink("ctx-managed", "ctx-fdai", { kind: "observation", direction: "left" })}
          </div>
          ${archBoundary("MANAGED ENVIRONMENT", "Azure and delivery systems", `
            ${archNode("ctx-cloud", "TARGET", "Azure resources", "service · workload · resource", { tone: "azure", primary: true })}
            ${archNode("ctx-git", "DELIVERY", "Git providers", "review · merge · revert", { tone: "external" })}
            ${archNode("ctx-observe", "EVIDENCE", "Authoritative sources", "ARG · Monitor · external state", { tone: "evidence" })}
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
      title: "다섯 아키텍처 레이어는 이벤트, 계약, Git만 공유합니다",
      lead: "화면, 사람 승인, 판단, 전달, 카탈로그를 분리하면 한 레이어의 편의 기능이 다른 레이어의 신원이나 권한으로 확장되지 않습니다.",
      evidence: ["architectureGuide", "appShape", "projectStructure"],
      takeaway: "레이어는 같은 프로세스나 신원을 공유하지 않습니다. 아래쪽 계약과 근거가 위쪽 화면을 설명하지만 화면은 운영 사실을 계산하지 않습니다.",
      body: `
        <div class="ta-layer-architecture" data-ta-diagram="layer-architecture" data-diagram-kind="layered" role="img" aria-label="사람 채널, Console, 헤드리스 Core, 작업 전달, 카탈로그와 근거의 다섯 레이어">
          <div class="ta-layer-stack">
            ${archNode("layer-human", "LAYER 05 · HUMAN CHANNEL", "Teams / ChatOps", "승인 요청 · 알림 · 별도 사람 신원", { tone: "human", primary: true })}
            ${archLink("layer-human", "layer-console", { kind: "request", direction: "down" })}
            ${archNode("layer-console", "LAYER 04 · OPERATOR EXPERIENCE", "Console + Operator", "권위 있는 투영 · 범위가 제한된 요청", { tone: "surface", primary: true })}
            ${archLink("layer-console", "layer-core", { kind: "event", direction: "down" })}
            ${archNode("layer-core", "LAYER 03 · BRAIN", "Core + 15 agents", "normalize · decide · authorize · coordinate · audit", { tone: "control", primary: true })}
            ${archLink("layer-core", "layer-delivery", { kind: "approval", direction: "down" })}
            ${archNode("layer-delivery", "LAYER 02 · HANDS", "Action delivery", "PR-native · Isolated Executor · rollback", { tone: "execution", primary: true })}
            ${archLink("layer-delivery", "layer-catalog", { kind: "audit", direction: "down" })}
            ${archNode("layer-catalog", "LAYER 01 · MEMORY", "Rules & knowledge", "rules · policies · ontology · evidence · case history", { tone: "store", primary: true })}
          </div>
          <aside class="ta-layer-rails">
            <div><b>EVENT BUS</b><span>authority-bearing choreography</span></div>
            <div><b>VERSIONED CONTRACTS</b><span>events · actions · evidence · providers</span></div>
            <div><b>GIT</b><span>catalog · IaC · delivery · rollback</span></div>
            <div class="ta-layer-rule"><strong>NO SHARED IDENTITY</strong><span>각 레이어는 실패와 권한을 독립적으로 유지</span></div>
          </aside>
        </div>`,
    }),
    slide({
      index: 5,
      id: "closed-control-loop",
      chapter: 1,
      state: "CURRENT",
      diagramKind: "control-loop",
      title: "신호는 판단, 권한, 실행, 독립 관측을 거쳐서만 닫힙니다",
      lead: "T2만 품질 검증을 추가로 통과하고, 모든 Tier는 공통 RiskGate와 현재 권한을 거쳐 실행, 사람 승인, 보류 또는 차단으로 분기합니다.",
      evidence: ["architectureGuide", "constitution", "execution", "pantheon"],
      takeaway: "이 흐름의 어느 화살표도 생략할 수 없습니다. 거부, 승인 만료, 보류, 복구도 성공과 같은 감사 경로로 종료됩니다.",
      body: `
        <div class="ta-closed-control-loop" data-ta-diagram="closed-control-loop" data-diagram-kind="control-loop" role="img" aria-label="Event ingress에서 Tier 선택, 품질 검증, RiskGate, 승인, 격리 실행, 독립 관측, 감사와 재생으로 이어지는 폐쇄형 제어 루프">
          <div class="ta-loop-main">
            ${archNode("loop-event", "EVENT", "Typed signal", "cloud · detector · operator · job", { tone: "input" })}
            ${archLink("loop-event", "loop-ingest", { kind: "event" })}
            ${archNode("loop-ingest", "HUGINN", "Ingest + correlate", "schema · dedup · identity", { tone: "service" })}
            ${archLink("loop-ingest", "loop-router", { kind: "event" })}
            ${archNode("loop-router", "TRUST ROUTER", "Lowest sufficient Tier", "T0 · T1 · T2", { tone: "decision", primary: true })}
            ${archLink("loop-router", "loop-gate", { kind: "decision" })}
            ${archNode("loop-gate", "VERIFY", "Quality + RiskGate", "T2 quality · policy · authority", { tone: "policy", primary: true })}
            ${archLink("loop-gate", "loop-thor", { kind: "approval" })}
            ${archNode("loop-thor", "THOR", "Eligible ActionRun", "current ceiling rechecked", { tone: "execution" })}
            ${archLink("loop-thor", "loop-executor", { kind: "mutation" })}
            ${archNode("loop-executor", "ISOLATED", "Executor", "lock · effect · receipt", { tone: "execution", primary: true })}
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
            ${archNode("loop-audit", "SAGA", "Audit + replay", "intent · execution · outcome", { tone: "store", primary: true })}
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
