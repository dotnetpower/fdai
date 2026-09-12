/** Slides 16-20: show dispatch, isolated execution, trust, effects, and degradation architecture. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.js";
import { slide } from "./target-architecture-slide-kit.js";

export function buildTargetArchitectureExecution() {
  return [
    slide({
      index: 16,
      id: "execution-dispatch",
      chapter: 4,
      state: "CURRENT",
      diagramKind: "dispatch",
      title: "한 적격 ActionRun은 네 전달 경로 중 등록된 하나로만 나갑니다",
      lead: "RiskGate 결과와 ActionType의 execution_path가 dispatch를 선택합니다. backend는 승인, 잠금, 복구, 감사와 효과 검증을 우회하거나 새 역할을 만들 수 없습니다.",
      evidence: ["architectureGuide", "execution", "security"],
      takeaway: "PR-native, direct API, PR-manual, tool call은 전달 방법만 다릅니다. 모든 경로는 동일한 현재 권한과 안전 계약을 다시 확인합니다.",
      body: `
        <div class="ta-execution-dispatch" data-ta-diagram="execution-dispatch" data-diagram-kind="dispatch" role="img" aria-label="적격 ActionRun이 공통 pre-dispatch gate를 거쳐 네 실행 경로 중 하나로 분기되는 구조">
          ${archNode("dispatch-run", "ELIGIBLE", "ActionRun", "target · revision · idempotency · ExpectedEffect", { tone: "decision", primary: true })}
          ${archLink("dispatch-run", "dispatch-gates", { kind: "decision" })}
          ${archBoundary("EVERY PATH", "Pre-dispatch safety boundary", `<span>RiskGate recheck</span><span>approval binding</span><span>seven safeguards</span><span>audit intent</span>`, { id: "dispatch-gates", classes: "ta-dispatch-gates", tone: "policy" })}
          ${archLink("dispatch-gates", "dispatch-paths", { kind: "approval" })}
          ${archBoundary("ACTIONTYPE SELECTS ONE", "Delivery backends", `
            <div class="ta-dispatch-path-grid">
              ${archNode("dispatch-pr-native", "PR-NATIVE", "Policy merge PR", "review · revert · optional auto merge", { tone: "execution" })}
              ${archNode("dispatch-direct", "DIRECT API", "Provider call", "isolated identity · typed rollback", { tone: "execution" })}
              ${archNode("dispatch-pr-manual", "PR-MANUAL", "Human merge PR", "no automatic merge", { tone: "approval" })}
              ${archNode("dispatch-tool", "TOOL CALL", "Registered function", "bounded capability · no substrate mutation", { tone: "service" })}
            </div>
          `, { id: "dispatch-paths", classes: "ta-dispatch-paths", tone: "control" })}
          ${archLink("dispatch-paths", "dispatch-outcome", { kind: "audit" })}
          ${archNode("dispatch-outcome", "TERMINAL RECEIPT", "Delivery outcome", "success not claimed until independent observation", { tone: "store", primary: true })}
          <footer><b>BACKEND RULE</b><span>same authority roles · same target lock · same rollback contract · same audit lifecycle</span></footer>
        </div>`,
    }),
    slide({
      index: 17,
      id: "isolated-executor-architecture",
      chapter: 4,
      state: "STATUS",
      diagramKind: "component",
      title: "Isolated Executor 안에서만 잠금, effect identity, provider mutation이 만납니다",
      lead: "Executor는 versioned command를 검증하고 일곱 안전장치가 현재 리비전에 결합됐을 때만 짧은 수명의 작업 신원으로 공급자 효과를 시도합니다.",
      evidence: ["architectureGuide", "services", "security", "execution"],
      takeaway: "서비스와 effect identity 분리는 검증됐습니다. Workflow와 격리 실행 경로의 완전한 safeguard receipt 및 독립 effect closure 동등성은 진행 중입니다.",
      body: `
        <div class="ta-isolated-executor" data-ta-diagram="isolated-executor-architecture" data-diagram-kind="component" role="img" aria-label="Executor command 수신부터 validation, 일곱 안전장치, 잠금, workload identity, provider effect, receipt와 rollback까지의 내부 구조">
          ${archNode("executor-command", "EXECUTOR COMMAND", "Versioned command", "schema · correlation · deadline · exact target", { tone: "event", primary: true })}
          ${archLink("executor-command", "executor-boundary", { kind: "approval" })}
          ${archBoundary("INTERNAL SERVICE · NO PUBLIC INGRESS", "Isolated Executor", `
            <div class="ta-executor-pipeline">
              ${archNode("executor-validate", "01", "Validate command", "schema · ActionType · authority · deadline", { tone: "policy" })}
              ${archLink("executor-validate", "executor-safeguards", { kind: "decision" })}
              ${archNode("executor-safeguards", "02", "Seven safeguards", "stop · rollback · impact · dry-run · lock · idempotency · audit", { tone: "policy", primary: true })}
              ${archLink("executor-safeguards", "executor-lock", { kind: "decision" })}
              ${archNode("executor-lock", "03", "Target lock + attempt", "durable claim · duplicate suppression", { tone: "store" })}
              ${archLink("executor-lock", "executor-identity", { kind: "approval" })}
              ${archNode("executor-identity", "04", "Workload identity", "audience-scoped OIDC · action allowlist", { tone: "execution", primary: true })}
            </div>
            <div class="ta-executor-status"><span data-status="VALIDATED">service + identity boundary validated</span><span data-status="GAP">end-to-end receipt parity in progress</span></div>
          `, { id: "executor-boundary", classes: "ta-executor-boundary", tone: "execution", status: "SOLE EFFECT HOLDER" })}
          ${archLink("executor-boundary", "executor-provider", { kind: "mutation" })}
          ${archNode("executor-provider", "PROVIDER", "Registered effect adapter", "Azure ARM · Git · bounded tool", { tone: "azure", primary: true })}
          <div class="ta-executor-return">
            ${archNode("executor-receipt", "EVENT BUS", "ExecutionReceipt", "attempt · provider ref · rollback ref · terminal status", { tone: "store" })}
            ${archNode("executor-rollback", "VIDAR", "Recovery path", "normal typed pipeline · independent verification", { tone: "recovery" })}
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
      title: "사람 승인, 서비스 판단, 작업 실행은 서로 다른 trust zone에 있습니다",
      lead: "Entra principal, 비특권 Operator identity, Core coordination identity, Executor workload identity, provider role은 교차 대체되지 않습니다.",
      evidence: ["architectureGuide", "security", "services", "appShape"],
      takeaway: "승인은 특정 ActionRun의 권한 조건을 충족할 뿐 Azure role을 발급하지 않습니다. 알 수 없는 identity ref는 aggregate identity로 fallback하지 않고 거부됩니다.",
      body: `
        <div class="ta-trust-zone-architecture" data-ta-diagram="trust-zone-architecture" data-diagram-kind="trust-boundary" role="img" aria-label="사람 신원, Console, Operator, Core, Isolated Executor, Azure effect role의 분리된 trust zone">
          ${archBoundary("ZONE 1 · HUMAN", "Entra identity", `
            ${archNode("trust-human", "MFA + APP ROLE", "Operator / approver", "requester and approver remain distinct", { tone: "human", primary: true })}
          `, { id: "trust-human-zone", classes: "ta-trust-zone", tone: "human" })}
          ${archLink("trust-human-zone", "trust-edge-zone", { kind: "request" })}
          ${archBoundary("ZONE 2 · EDGE", "Console + Operator Service", `
            ${archNode("trust-console", "STATIC", "FDAI Console", "no browser authorization logic", { tone: "surface" })}
            ${archNode("trust-operator", "SERVICE MI", "Operator identity", "read projections · submit typed request", { tone: "service", primary: true })}
          `, { id: "trust-edge-zone", classes: "ta-trust-zone", tone: "surface" })}
          ${archLink("trust-edge-zone", "trust-core-zone", { kind: "event" })}
          ${archBoundary("ZONE 3 · DECISION", "Core Control Plane", `
            ${archNode("trust-core", "NO EFFECT ROLE", "Decision identity", "judge · risk · approval join · audit intent", { tone: "control", primary: true })}
          `, { id: "trust-core-zone", classes: "ta-trust-zone", tone: "control" })}
          ${archLink("trust-core-zone", "trust-executor-zone", { kind: "approval" })}
          ${archBoundary("ZONE 4 · EFFECT", "Isolated Executor", `
            ${archNode("trust-executor", "UAMI + OIDC", "Workload identity", "non-interactive · exact audience · action whitelist · target scope", { tone: "execution", primary: true })}
          `, { id: "trust-executor-zone", classes: "ta-trust-zone", tone: "execution" })}
          ${archLink("trust-executor-zone", "trust-provider-zone", { kind: "mutation" })}
          ${archBoundary("ZONE 5 · PROVIDER", "Azure effective access", `
            ${archNode("trust-provider", "DENY BY DEFAULT", "Scoped provider role", "resource or governed RG · never subscription-wide", { tone: "azure", primary: true })}
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
      title: "Executor 영수증과 별도의 관측 경로가 운영 성공을 판정합니다",
      lead: "계획은 ExpectedEffect와 관측 창을 먼저 고정하고, ActionRun 뒤 Heimdall이 실행 채널과 다른 권위 있는 출처에서 결과를 관측해 ObservedOutcome을 만듭니다.",
      evidence: ["architectureGuide", "constitution", "ontology", "security"],
      takeaway: "provider 2xx, broker acceptance, PR merge는 dispatch 증거입니다. 관측이 없거나 충돌하면 성공 대신 pending, mismatch, timeout 또는 unscorable로 마감합니다.",
      body: `
        <div class="ta-effect-verification" data-ta-diagram="effect-verification-architecture" data-diagram-kind="effect-loop" role="img" aria-label="ExpectedEffect, Executor, managed target, independent observer, ObservedOutcome와 Saga audit을 연결한 효과 검증 아키텍처">
          <div class="ta-effect-plan">
            ${archNode("effect-expected", "BEFORE", "ExpectedEffect", "metric · direction · range · source · window", { tone: "decision", primary: true })}
            ${archLink("effect-expected", "effect-executor", { kind: "decision" })}
            ${archNode("effect-executor", "ATTEMPT", "Isolated Executor", "locked effect + execution receipt", { tone: "execution", primary: true })}
            ${archLink("effect-executor", "effect-target", { kind: "mutation" })}
            ${archNode("effect-target", "EXTERNAL TRUTH", "Managed target", "provider owns current state", { tone: "azure", primary: true })}
          </div>
          <div class="ta-effect-observation">
            ${archNode("effect-source", "SEPARATE CHANNEL", "Authoritative effect source", "telemetry · inventory · health · Git state", { tone: "evidence", primary: true })}
            ${archLink("effect-source", "effect-heimdall", { kind: "observation", direction: "left" })}
            ${archNode("effect-heimdall", "OBSERVER", "Heimdall", "freshness · completeness · conflict · window", { tone: "evidence" })}
            ${archLink("effect-heimdall", "effect-outcome", { kind: "observation", direction: "left" })}
            ${archNode("effect-outcome", "CLOSE", "ObservedOutcome", "matched · mismatched · timeout · unscorable", { tone: "store", primary: true })}
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
      title: "의존성 장애는 다른 역할을 승격하지 않습니다",
      lead: "감사, 복구, 판정, 사람 승인, 독립 관측, 실행의 상태를 각각 검사하고 complete contract가 남지 않으면 변경을 보류하거나 차단합니다.",
      evidence: ["architectureGuide", "constitution", "pantheon", "security"],
      takeaway: "안전한 degradation은 hidden fallback이 아닙니다. 읽기, deny, queue, shadow 중 어떤 경로가 남는지 이름을 붙이고 effect는 추측하지 않습니다.",
      body: `
        <div class="ta-degradation-architecture" data-ta-diagram="degradation-architecture" data-diagram-kind="resilience" role="img" aria-label="Saga, Vidar, Forseti, Var, Heimdall, Executor의 상태가 중앙 mutation eligibility를 낮추는 장애 저하 아키텍처">
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
