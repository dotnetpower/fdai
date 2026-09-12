/** Slides 21-25: show ports, Azure topology, network flow, delivery, and review decision. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.js";
import { slide } from "./target-architecture-slide-kit.js";

export function buildTargetArchitectureDeployment() {
  return [
    slide({
      index: 21,
      id: "ports-adapters-architecture",
      chapter: 5,
      state: "CURRENT",
      diagramKind: "ports-adapters",
      title: "Core는 여덟 안정 계약을 통해 Azure adapter와 연결됩니다",
      lead: "Core는 Kafka, OCI, 환경 비밀값, OIDC identity, inventory, metrics, logs, traces의 provider-neutral contract만 보고 Azure SDK와 리소스 선택은 delivery 경계에 둡니다.",
      evidence: ["architectureGuide", "portability", "projectStructure"],
      takeaway: "Azure가 유일한 구현 대상입니다. provider-neutral contract는 다른 cloud가 구현됐다는 뜻이 아니라 Core를 바꾸지 않을 확장 경계입니다.",
      body: `
        <div class="ta-ports-adapters" data-ta-diagram="ports-adapters-architecture" data-diagram-kind="ports-adapters" role="img" aria-label="Core, 여덟 provider-neutral contract, Azure adapter, Azure managed service의 ports and adapters 구조">
          ${archBoundary("PORTABLE CORE", "Decision and coordination", `<span>agents</span><span>ontology context</span><span>tiers</span><span>RiskGate</span><span>workflow</span>`, { id: "ports-core", classes: "ta-ports-core", tone: "control", status: "NO AZURE SDK" })}
          ${archLink("ports-core", "ports-contracts", { kind: "read", direction: "down", label: "depends on" })}
          ${archBoundary("SHARED PROTOCOLS", "Eight stable contracts", `
            <div class="ta-contract-grid"><span>EventBus<br><b>Kafka</b></span><span>Runtime<br><b>OCI</b></span><span>Secret<br><b>env / mount</b></span><span>Identity<br><b>OIDC</b></span><span>Inventory<br><b>Resource + Link</b></span><span>Metric<br><b>points</b></span><span>Log<br><b>records</b></span><span>Trace<br><b>spans</b></span></div>
          `, { id: "ports-contracts", classes: "ta-ports-contracts", tone: "dependency" })}
          ${archLink("ports-adapters", "ports-contracts", { kind: "read", direction: "up", label: "implements" })}
          ${archBoundary("DELIVERY LAYER", "Azure adapters", `<span>Event Hubs Kafka</span><span>Container Apps renderer</span><span>Key Vault reference</span><span>Managed Identity token</span><span>ARG + Activity delta</span><span>Azure Monitor queries</span>`, { id: "ports-adapters", classes: "ta-ports-azure-adapters", tone: "azure" })}
          ${archLink("ports-adapters", "ports-services", { kind: "request", direction: "down", label: "provider wire" })}
          ${archBoundary("AZURE MANAGED SERVICES", "Concrete implementation", `<span>Event Hubs</span><span>Container Apps</span><span>Key Vault</span><span>Azure Resource Graph</span><span>Azure Monitor</span><span>Log Analytics + App Insights</span>`, { id: "ports-services", classes: "ta-ports-services", tone: "external", status: "IMPLEMENTED TARGET" })}
        </div>`,
    }),
    slide({
      index: 22,
      id: "azure-deployment-topology",
      chapter: 5,
      state: "STATUS",
      diagramKind: "deployment",
      title: "Azure 기준선은 VNet 통합 Container Apps에 배치합니다",
      lead: "다섯 서비스와 Jobs가 내부 Event Hubs, 서비스별 PostgreSQL role, Key Vault reference, private storage, observability를 각자 신원으로 사용합니다.",
      evidence: ["architectureGuide", "deployment", "portability", "security"],
      takeaway: "5개 서비스와 독립 identity 경계는 검증됐습니다. 이 배치의 production private flow, 운영 준비도, RPO/RTO와 DR은 배포별 근거가 필요합니다.",
      body: `
        <div class="ta-azure-deployment" data-ta-diagram="azure-deployment-topology" data-diagram-kind="deployment" role="img" aria-label="Azure region, VNet, Container Apps subnet, private endpoint subnet, five FDAI services와 managed data services의 배포 토폴로지">
          <div class="ta-azure-outside">
            ${archNode("azure-operator", "", "Operator", "", { tone: "human" })}
            ${archNode("azure-signals", "", "Azure signals", "", { tone: "azure" })}
            ${archNode("azure-git", "", "Git provider", "", { tone: "external" })}
          </div>
          <div class="ta-azure-outside-links">
            ${archLink("azure-operator", "azure-region", { kind: "request", direction: "down" })}
            ${archLink("azure-signals", "azure-region", { kind: "event", direction: "down" })}
            ${archLink("azure-region", "azure-git", { kind: "mutation", direction: "up" })}
          </div>
          ${archBoundary("AZURE REGION", "One day-zero operational cell", `
            <div class="ta-azure-region-grid">
              ${archBoundary("PUBLIC / OPERATOR EDGE", "Authenticated surfaces", `
                ${archNode("azure-console", "", "Console / Operator", "read-only web · authenticated API · no effect role", { tone: "surface" })}
                ${archNode("azure-ingestion", "", "Document Ingestion API", "authenticated upload", { tone: "service" })}
              `, { id: "azure-edge", classes: "ta-azure-edge", tone: "surface" })}
              ${archBoundary("VNET · CONTAINER APPS SUBNET", "Internal runtime environment", `
                ${archNode("azure-core", "NO EFFECT ROLE", "Core Control Plane", "", { tone: "control", primary: true })}
                ${archNode("azure-worker", "INTERNAL · CLAMAV", "Processing Worker", "", { tone: "service" })}
                ${archNode("azure-executor", "EFFECT ROLE", "Isolated Executor", "", { tone: "execution", primary: true })}
                ${archNode("azure-jobs", "SCHEDULED", "Container Apps Jobs", "", { tone: "service" })}
              `, { id: "azure-apps", classes: "ta-azure-apps", tone: "control" })}
              ${archBoundary("PRIVATE DATA PLANE", "Managed services", `
                ${archNode("azure-eventhubs", "KAFKA :9093", "Event Hubs", "primary + operational shards", { tone: "event", primary: true })}
                ${archNode("azure-postgres", "STATE", "PostgreSQL + pgvector", "", { tone: "store", primary: true })}
                ${archNode("azure-storage", "HISTORY", "Private Blob / ADLS", "case history · document data", { tone: "store" })}
                ${archNode("azure-keyvault", "TRUST", "Key Vault + UAMI", "native reference · short-lived token", { tone: "policy" })}
              `, { id: "azure-data", classes: "ta-azure-data", tone: "dependency" })}
              ${archNode("azure-observability", "OBSERVABILITY · OTEL", "Log Analytics + App Insights", "independent telemetry · health · trace · SLO · effect evidence", { tone: "evidence", classes: "ta-azure-observability", primary: true })}
            </div>
          `, { id: "azure-region", classes: "ta-azure-region", tone: "azure", status: "PRODUCTION EVIDENCE REQUIRED" })}
          ${archLegend([
            { kind: "request", label: "HTTPS/request" },
            { kind: "event", label: "Kafka event" },
            { kind: "mutation", label: "delivery/effect" },
          ])}
        </div>`,
    }),
    slide({
      index: 23,
      id: "azure-network-flow",
      chapter: 5,
      state: "STATUS",
      diagramKind: "network-flow",
      title: "요청, 이벤트, 비밀값, 데이터, effect는 서로 다른 Azure 경로를 사용합니다",
      lead: "번호가 있는 흐름은 browser sign-in부터 typed request, Kafka 판단, private data access, isolated effect, 독립 관측과 audit까지의 주 경로를 보여줍니다.",
      evidence: ["architectureGuide", "deployment", "security"],
      takeaway: "Core와 Executor에는 public ingress가 없습니다. 계획된 private Application Gateway와 일부 private endpoint는 목표 상태이므로 현재 배포와 구분합니다.",
      body: `
        <div class="ta-azure-network-flow" data-ta-diagram="azure-network-flow" data-diagram-kind="network-flow" role="img" aria-label="Entra, Console, Operator, Event Hubs, Core, Executor, private data, Azure resource와 observation의 번호가 있는 네트워크 흐름">
          <div class="ta-network-main">
            ${archNode("net-entra", "01 · AUTH", "Microsoft Entra ID", "human JWT + App Roles", { tone: "human" })}
            ${archLink("net-entra", "net-console", { kind: "request", label: "1" })}
            ${archNode("net-console", "02 · SURFACE", "Static Web Console", "read-only client", { tone: "surface" })}
            ${archLink("net-console", "net-operator", { kind: "request", label: "2" })}
            ${archNode("net-operator", "03 · EDGE", "Operator Service", "RBAC · revision · audit", { tone: "service" })}
            ${archLink("net-operator", "net-bus", { kind: "event", label: "3" })}
            ${archNode("net-bus", "04 · INTERNAL", "Event Hubs", "Kafka typed events + approvals", { tone: "event", primary: true })}
            ${archLink("net-bus", "net-core", { kind: "event", label: "4" })}
            ${archNode("net-core", "05 · DECIDE", "Core Control Plane", "context · tier · quality · risk", { tone: "control", primary: true })}
            ${archLink("net-core", "net-executor", { kind: "approval", label: "5" })}
            ${archNode("net-executor", "06 · EFFECT", "Isolated Executor", "private command consumer", { tone: "execution", primary: true })}
            ${archLink("net-executor", "net-target", { kind: "mutation", label: "6" })}
            ${archNode("net-target", "07 · EXTERNAL", "Managed Azure resource", "scoped provider role", { tone: "azure" })}
          </div>
          <div class="ta-network-support">
            ${archNode("net-keyvault", "SECRET", "Key Vault reference", "native reference · no secret over event bus", { tone: "policy", footer: "runtime injection" })}
            ${archNode("net-postgres", "STATE", "PostgreSQL", "service roles · audit · projections", { tone: "store", footer: "private service-owned access" })}
            ${archNode("net-model", "OPTIONAL", "Azure OpenAI / Foundry", "redacted input through T2 adapter", { tone: "model", status: "OPTIONAL PROFILE" })}
            ${archNode("net-git", "DELIVER", "Git provider", "governed remediation PR", { tone: "external", footer: "Executor delivery path" })}
            ${archNode("net-monitor", "08 · OBSERVE", "Azure Monitor sources", "independent effect evidence", { tone: "evidence", primary: true })}
          </div>
          <footer><span data-status="CURRENT">current: authenticated edge + VNet-integrated services</span><span data-status="TARGET">target: private Application Gateway / WAF and profile-specific endpoints</span></footer>
        </div>`,
    }),
    slide({
      index: 24,
      id: "release-promotion-architecture",
      chapter: 5,
      state: "STATUS",
      diagramKind: "delivery",
      title: "코드 산출물 배포와 기능의 적용 모드 승격은 두 개의 독립 제어 경로입니다",
      lead: "같은 서명 이미지를 exact plan으로 배포해도 ActionType은 관찰 모드에 남을 수 있습니다. 적용 모드는 별도의 scenario evidence와 독립 승인을 요구합니다.",
      evidence: ["deployment", "security", "axes"],
      takeaway: "공급망과 protected apply는 구현됐습니다. 자동 dev-to-staging-to-prod 승격, traffic canary, SLO rollback, Console blue/green은 목표 상태입니다.",
      body: `
        <div class="ta-release-promotion" data-ta-diagram="release-promotion-architecture" data-diagram-kind="delivery" role="img" aria-label="서명 이미지 배포 경로와 ActionType 관찰 모드 승격 경로를 독립적으로 보여 주는 release architecture">
          ${archBoundary("TRACK A · ARTIFACT DELIVERY", "Can this exact artifact be deployed?", `
            <div class="ta-release-track">
              ${archNode("release-source", "SOURCE", "Reviewed change", "tests · IaC · dependency · secret scan", { tone: "service", status: "IMPLEMENTED" })}
              ${archLink("release-source", "release-image", { kind: "event" })}
              ${archNode("release-image", "SUPPLY CHAIN", "Signed OCI image", "SBOM · provenance · fixed digest", { tone: "store", status: "IMPLEMENTED" })}
              ${archLink("release-image", "release-plan", { kind: "decision" })}
              ${archNode("release-plan", "DEPLOY", "Sealed exact plan", "identity · peer state · rollback baseline", { tone: "policy", status: "IMPLEMENTED" })}
              ${archLink("release-plan", "release-service", { kind: "mutation" })}
              ${archNode("release-service", "RUNTIME", "Service revision", "health · smoke · rollback", { tone: "azure", status: "IMPLEMENTED" })}
            </div>
          `, { id: "release-artifact-track", classes: "ta-release-artifact", tone: "control" })}
          ${archBoundary("TRACK B · CAPABILITY AUTHORITY", "Can this ActionType change state?", `
            <div class="ta-release-track">
              ${archNode("promote-shadow", "DEFAULT", "Observation mode", "judge + log · no effect", { tone: "semantic", status: "CURRENT" })}
              ${archLink("promote-shadow", "promote-evidence", { kind: "observation" })}
              ${archNode("promote-evidence", "MEASURE", "Frozen scenario evidence", "accuracy · samples · zero escapes", { tone: "evidence" })}
              ${archLink("promote-evidence", "promote-review", { kind: "approval" })}
              ${archNode("promote-review", "INDEPENDENT", "Promotion review", "exact action + version + rollback", { tone: "approval" })}
              ${archLink("promote-review", "promote-registry", { kind: "write" })}
              ${archNode("promote-registry", "AUTHORITY", "Promotion registry", "enforce eligibility only", { tone: "policy", status: "SEPARATE DECISION" })}
            </div>
          `, { id: "release-authority-track", classes: "ta-release-authority", tone: "dependency" })}
          <footer><span data-status="IMPLEMENTED">signed build + protected exact apply</span><span data-status="TARGET">automatic environment promotion + traffic canary + SLO rollback</span><b>deployment never promotes authority</b></footer>
        </div>`,
    }),
    slide({
      index: 25,
      id: "architecture-decision-map",
      chapter: 5,
      state: "DECISION",
      diagramKind: "decision-map",
      title: "이 아키텍처 기준선을 조건부 승인하시겠습니까?",
      lead: "L0 경계, 다섯 서비스, 제어 루프, 신원, 실행과 Azure day-zero 배치를 수락하고 production gate의 열린 근거는 별도 소유자에게 남깁니다.",
      evidence: ["arb", "reviewState", "constitution", "architectureGuide"],
      takeaway: "이 결정은 아키텍처 기준선만 고정합니다. 프로덕션 배포, 기능 승격, 사람 승인, Executor 권한은 각각의 기존 통제 경로를 다시 통과합니다.",
      body: `
        <div class="ta-architecture-decision-map" data-ta-diagram="architecture-decision-map" data-diagram-kind="decision-map" role="img" aria-label="검토한 아키텍처 기준선, production blockers, 조건부 승인과 수정 또는 보류의 결정 경로">
          ${archBoundary("BASELINE UNDER REVIEW", "FDAI Target Architecture", `
            <div class="ta-decision-baseline"><span>headless control plane</span><span>five independent services</span><span>15-agent event choreography</span><span>deterministic-first decisioning</span><span>isolated effect identity</span><span>Azure day-zero cell</span></div>
          `, { id: "decision-baseline", classes: "ta-decision-baseline-boundary", tone: "control", status: "DESIGN CONDITIONAL" })}
          ${archLink("decision-baseline", "decision-options", { kind: "decision" })}
          ${archBoundary("ARB DECISION", "Choose one outcome", `
            <div class="ta-decision-options-map">
              ${archNode("decision-approve", "OPTION 01", "조건부 승인", "기준선 수락 · blocker 별도 종료", { tone: "evidence", primary: true })}
              ${archNode("decision-revise", "OPTION 02", "수정 후 재검토", "경계 · 책임 · provider · safety 변경", { tone: "decision", primary: true })}
              ${archNode("decision-hold", "OPTION 03", "판단 보류", "필수 설계 근거와 review date 요청", { tone: "blocked", primary: true })}
            </div>
          `, { id: "decision-options", classes: "ta-decision-options-boundary", tone: "dependency" })}
          ${archLink("decision-options", "decision-production", { kind: "decision" })}
          ${archBoundary("NOT GRANTED BY THIS REVIEW", "Production approval remains blocked", `
            <div class="ta-decision-blockers"><span>ARB-001 signed image + plan</span><span>ARB-002 private data flow</span><span>ARB-003 operational readiness</span><span>ARB-004 RPO/RTO + drills</span><span>ARB-005 owner bindings</span><span>ARB-006 privacy + retention</span><span>ARB-007 blocking smoke + canary</span><span>ARB-008 performance evidence</span></div>
          `, { id: "decision-production", classes: "ta-decision-production", tone: "blocked", status: "PRODUCTION BLOCKED" })}
          <footer><span>APPROVAL EFFECT</span><b>architecture direction only</b><span>NO EFFECT</span><b>deployment · enforce · access grant · resource mutation</b></footer>
        </div>`,
    }),
  ];
}
