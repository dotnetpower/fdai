/** Slides 11-15: show evidence, semantic, temporal, tier, and authority architecture. */
import {
  archBoundary,
  archLegend,
  archLink,
  archNode,
} from "./target-architecture-diagram-kit.js";
import { slide } from "./target-architecture-slide-kit.js";

export function buildTargetArchitectureDecision() {
  return [
    slide({
      index: 11,
      id: "evidence-admission",
      chapter: 3,
      state: "CURRENT",
      diagramKind: "evidence-flow",
      title: "외부 사실은 검증된 근거 봉투를 통과한 뒤 판단 맥락이 됩니다",
      lead: "Inventory, telemetry, policy, audit는 서로 다른 권위를 유지합니다. 인증, 범위, 시간, 완전성, 충돌, 합성 여부를 검증한 사실만 DecisionCase에 들어갑니다.",
      evidence: ["architectureGuide", "constitution", "ontology"],
      takeaway: "한 출처의 최신 값이 다른 출처의 오래됨이나 충돌을 숨길 수 없습니다. 수용 실패는 알 수 없음, 재수집, 범위 축소 또는 판단 보류로 닫힙니다.",
      body: `
        <div class="ta-evidence-admission" data-ta-diagram="evidence-admission" data-diagram-kind="evidence-flow" role="img" aria-label="권위 있는 출처가 근거 봉투 검증과 수용 게이트를 통과해 DecisionCase를 만드는 아키텍처">
          ${archBoundary("AUTHORITATIVE SOURCES", "서로 독립적인 사실 소유자", `
            ${archNode("evidence-inventory", "TOPOLOGY", "Inventory", "Resource · Link · coverage", { tone: "azure" })}
            ${archNode("evidence-telemetry", "OBSERVATION", "Telemetry", "event time · window · source", { tone: "evidence" })}
            ${archNode("evidence-intent", "INTENT", "Policy / objectives", "effective interval · owner", { tone: "policy" })}
            ${archNode("evidence-audit", "HISTORY", "Audit / case history", "immutable revision · outcome", { tone: "store" })}
          `, { id: "evidence-sources", classes: "ta-evidence-sources", tone: "external" })}
          ${archLink("evidence-sources", "evidence-receipt", { kind: "event", label: "typed facts" })}
          ${archBoundary("DECISION-CRITICAL RECEIPT", "한 사실의 근거 봉투", `
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
      title: "운영 온톨로지는 범위, 의도, 현실, 판단, 효과를 한 그래프로 연결합니다",
      lead: "서비스와 리소스의 관계를 고정하고 관측 근거를 DecisionCase에 연결합니다. 목표, 선택지, 실행, 결과를 모든 에이전트가 같은 의미로 읽습니다.",
      evidence: ["architectureGuide", "ontology", "constitution"],
      takeaway: "온톨로지는 공유 semantic read model입니다. 그래프 쓰기는 외부 사실을 만들지 않으며 정책, RiskGate, 승인, 실행 신원은 그래프 밖에 남습니다.",
      body: `
        <div class="ta-semantic-architecture" data-ta-diagram="semantic-architecture" data-diagram-kind="semantic-graph" role="img" aria-label="BusinessService, Workload, Resource, Objective, Observation, DecisionCase, ActionRun, ObservedOutcome을 연결한 운영 온톨로지">
          <div class="ta-semantic-spine">
            ${archNode("sem-service", "OPERATING SCOPE", "BusinessService", "stable identity · ownership", { tone: "semantic", primary: true })}
            ${archLink("sem-service", "sem-workload", { kind: "semantic", label: "implemented_by" })}
            ${archNode("sem-workload", "DEPLOYABLE", "Workload", "version · environment", { tone: "semantic" })}
            ${archLink("sem-workload", "sem-resource", { kind: "semantic", label: "runs_on" })}
            ${archNode("sem-resource", "OBSERVED", "Resource", "provider-neutral identity", { tone: "azure", primary: true })}
            ${archLink("sem-resource", "sem-observation", { kind: "observation", label: "observed by" })}
            ${archNode("sem-observation", "OPERATING REALITY", "Observation / Change", "source · time · completeness", { tone: "evidence" })}
          </div>
          <div class="ta-semantic-decision">
            ${archNode("sem-objective", "OPERATING INTENT", "Objective / Constraint", "SLO · RTO/RPO · Cost · ARB", { tone: "policy", primary: true })}
            ${archLink("sem-objective", "sem-case", { kind: "semantic", label: "protects" })}
            ${archNode("sem-case", "DECISION", "DecisionCase", "immutable context + alternatives", { tone: "decision", primary: true })}
            ${archLink("sem-case", "sem-option", { kind: "decision", label: "considers" })}
            ${archNode("sem-option", "ALTERNATIVE", "ActionOption", "includes hold and no-op", { tone: "decision" })}
            ${archLink("sem-option", "sem-run", { kind: "mutation", label: "executed_as" })}
            ${archNode("sem-run", "EXECUTION", "ActionRun", "attempt + receipt", { tone: "execution" })}
            ${archLink("sem-run", "sem-outcome", { kind: "observation", label: "resulted_in" })}
            ${archNode("sem-outcome", "EFFECT", "ObservedOutcome", "independently measured", { tone: "evidence", primary: true })}
          </div>
          <footer><span><b>GRAPH OWNS</b> meaning · direction · identity · constraints</span><span><b>GRAPH NEVER OWNS</b> judgment · approval · permission · effect</span></footer>
        </div>`,
    }),
    slide({
      index: 13,
      id: "temporal-architecture",
      chapter: 3,
      state: "CONTRACT",
      diagramKind: "temporal",
      title: "각 판단은 정확한 시간과 리비전을 고정해 과거 의미를 보존합니다",
      lead: "event time, effective interval, recorded time, evidence cutoff, freshness expiry를 분리하고 늦은 근거는 과거 맥락을 덮어쓰지 않고 새 DecisionCase를 만듭니다.",
      evidence: ["constitution", "ontology"],
      takeaway: "현재 인스턴스 그래프는 bitemporal history가 아닙니다. 재생은 보존된 결정 맥락, ontology release, policy digest와 evidence revision을 사용합니다.",
      body: `
        <div class="ta-temporal-architecture" data-ta-diagram="temporal-architecture" data-diagram-kind="temporal" role="img" aria-label="사건 시각부터 기록, 판단 기준, 늦은 근거와 새 DecisionCase 리비전까지 연결한 시간 아키텍처">
          <header><span>설명용 시각</span><b>trusted UTC + monotonic elapsed time</b><em>운영 측정값 아님</em></header>
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
            ${archNode("time-v1", "IMMUTABLE", "DecisionCase v1", "release A · policy P · evidence E1", { tone: "decision" })}
            ${archLink("time-v1", "time-v2", { kind: "feedback", label: "new revision" })}
            ${archNode("time-v2", "RE-EVALUATE", "DecisionCase v2", "same event · evidence E1 + E2", { tone: "semantic" })}
            <aside><b>effective interval</b><span>사실이 유효한 기간</span><b>fresh_until</b><span>재사용 가능한 마지막 시각</span><b>replay</b><span>latest가 아닌 원래 digest</span></aside>
          </div>
        </div>`,
    }),
    slide({
      index: 14,
      id: "tier-routing-architecture",
      chapter: 3,
      state: "CURRENT",
      diagramKind: "routing",
      title: "Trust Router는 충분한 판단이 가능한 가장 낮은 Tier를 선택합니다",
      lead: "정확한 정책 일치는 T0, 현재 재검증 가능한 유사 사례는 T1, 남은 모호성만 T2로 이동하며 T2 제안은 별도 품질 검증을 통과해야 합니다.",
      evidence: ["architectureGuide", "deterministic", "execution"],
      takeaway: "Tier는 판단 방법입니다. T0, T1, T2 모두 공통 RiskGate로 들어가며 T2는 현재 관찰 모드 상한을 유지합니다.",
      body: `
        <div class="ta-tier-routing-architecture" data-ta-diagram="tier-routing-architecture" data-diagram-kind="routing" role="img" aria-label="Trust Router가 T0, T1, T2를 선택하고 T2만 품질 게이트를 거쳐 공통 RiskGate에 도달하는 구조">
          ${archNode("tier-signal", "NORMALIZED", "Event + context", "exact target · evidence cutoff", { tone: "input" })}
          ${archLink("tier-signal", "tier-router", { kind: "event" })}
          ${archNode("tier-router", "TRUST ROUTER", "Lowest sufficient Tier", "rule match · similarity · ambiguity", { tone: "decision", primary: true })}
          ${archLink("tier-router", "tier-lanes", { kind: "decision" })}
          ${archBoundary("THREE JUDGMENT PATHS", "판단 방법", `
            <div class="ta-tier-route-lanes">
              <div>${archNode("tier-t0", "T0 · 70-80% TARGET", "Deterministic rules", "policy · checklist · what-if", { tone: "policy" })}<span>exact match</span></div>
              <div>${archNode("tier-t1", "T1 · 15-20% TARGET", "Verified reuse", "case similarity + current recheck", { tone: "semantic" })}<span>known pattern</span></div>
              <div>${archNode("tier-t2", "T2 · 5-10% TARGET", "Grounded reasoning", "two model families + citations", { tone: "model" })}<span>residual ambiguity</span></div>
            </div>
          `, { id: "tier-lanes", classes: "ta-tier-lanes", tone: "control" })}
          ${archLink("tier-lanes", "tier-quality", { kind: "decision" })}
          ${archBoundary("T2 ONLY", "Quality gate", `<div class="ta-quality-checks"><span>schema</span><span>mixed-model agreement</span><span>grounding + citations</span><span>policy recheck</span><span>what-if / dry-run</span><span>security verifier</span></div>`, { id: "tier-quality", classes: "ta-tier-quality", tone: "policy" })}
          ${archLink("tier-quality", "tier-risk", { kind: "decision" })}
          ${archNode("tier-risk", "ALL TIERS", "Unified RiskGate", "authority is evaluated separately", { tone: "execution", primary: true })}
          <footer><span>표시 비율은 설계 목표이며 실제 측정값이 아닙니다.</span><b>no rule · low similarity · model disagreement - hold for review</b></footer>
        </div>`,
    }),
    slide({
      index: 15,
      id: "risk-gate-architecture",
      chapter: 3,
      state: "CURRENT",
      diagramKind: "decision-gate",
      title: "Unified RiskGate는 실행 상한을 높이지 않습니다",
      lead: "위험은 first-match 기준표로 분류하고 여섯 실행 상한 중 최솟값을 적용합니다. 시스템 상태, kill switch, promotion도 상한만 낮춥니다.",
      evidence: ["execution", "security", "constitution"],
      takeaway: "사람 승인과 promotion도 상한을 높이지 못합니다. 하나라도 deny면 차단되고, shadow_only면 승인 여부와 무관하게 변경하지 않습니다.",
      body: `
        <div class="ta-risk-gate-architecture" data-ta-diagram="risk-gate-architecture" data-diagram-kind="decision-gate" role="img" aria-label="위험 기준표, 여섯 실행 상한, 시스템 건강과 kill switch를 최소 연산으로 결합하는 Unified RiskGate">
          <div class="ta-risk-inputs">
            ${archBoundary("AXIS A · AUTHORITATIVE", "Risk classification table", `<span>policy violation</span><span>destructive</span><span>irreversible</span><span>data plane</span><span>cost</span><span>confidence</span>`, { id: "risk-table", tone: "policy" })}
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
