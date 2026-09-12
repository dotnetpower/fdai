/** Slides 8-12: prove that a candidate is eligible before comparing value. */
import { slide } from "./value-prioritization-slide-kit.en.js";

export function buildValuePrioritizationEligibility() {
  return [
    slide({
      index: 8,
      id: "evidence-gate",
      chapter: 2,
      state: "CONTRACT",
      title: "Evidence readiness is an entry condition, not a portfolio weight",
      lead: "Evidence is ready only when source, time, purpose, scope, and completeness are verified. If any condition is unmet, the candidate returns for remediation without scoring.",
      evidence: ["constitution", "readiness"],
      takeaway: "An unready candidate receives a clear hold reason and remediation task, not a low score.",
      body: `
        <div class="vp-evidence-gate-layout">
          <div class="vp-evidence-input"><small>CANDIDATE</small><strong>High expected value</strong><span>Value alone does not establish eligibility</span></div>
          <ol aria-label="Four evidence eligibility checks">
            <li><b>01</b><strong data-vp-primary>Source authority</strong><span>Authenticated producer and exact revision</span><em>Hold if absent</em></li>
            <li><b>02</b><strong data-vp-primary>Time fitness</strong><span>Decision time and freshness policy satisfied</span><em>Hold if stale</em></li>
            <li><b>03</b><strong data-vp-primary>Purpose and scope</strong><span>Target and use allowed for this decision</span><em>Hold if mismatched</em></li>
            <li><b>04</b><strong data-vp-primary>Completeness</strong><span>Evidence explains gaps and observation coverage</span><em>Hold if incomplete</em></li>
          </ol>
          <div class="vp-evidence-output"><small>ELIGIBLE</small><strong>Compare value</strong><span>Only candidates that pass all four checks</span></div>
        </div>`,
    }),
    slide({
      index: 9,
      id: "evidence-clock",
      chapter: 2,
      state: "CONTRACT",
      title: "A fact's value depends on event time and recorded time",
      lead: "Separating event time, effective interval, recorded time, and evidence cutoff prevents late evidence from overwriting an earlier decision.",
      evidence: ["constitution", "ontology"],
      takeaway: "Freshness is verified against source-specific policy and the decision cutoff, not the last update shown on screen.",
      body: `
        <div class="vp-evidence-clock-layout">
          <header><span>One decision context</span><strong>As of 2026-09-09T09:15:00Z</strong><small>Illustrative example</small></header>
          <div class="vp-clock-track">
            <article class="event"><small>09:08</small><strong data-vp-primary>event_time</strong><span>When the source event occurred</span></article>
            <i aria-hidden="true"></i>
            <article class="effective"><small>09:08-09:18</small><strong data-vp-primary>effective_time</strong><span>Interval when the fact is valid</span></article>
            <i aria-hidden="true"></i>
            <article class="recorded"><small>09:10</small><strong data-vp-primary>recorded_time</strong><span>When FDAI recorded the fact</span></article>
            <i aria-hidden="true"></i>
            <article class="cutoff"><small>09:15</small><strong data-vp-primary>evidence_cutoff</strong><span>Latest time included in the decision</span></article>
          </div>
          <div class="vp-clock-rules">
            <span><b>Late evidence</b>Creates a new revision without rewriting the existing decision.</span>
            <span><b>Expired evidence</b>Downgrades a prior ready state to unknown.</span>
            <span><b>Conflicting evidence</b>Goes to human review instead of being hidden by averaging.</span>
          </div>
        </div>`,
    }),
    slide({
      index: 10,
      id: "scope-graph",
      chapter: 2,
      state: "CONTRACT",
      title: "Confirm targets and relationships to find impact and ownership",
      lead: "Do not select candidates by resource name alone. Follow directional relationships across services, workloads, objectives, and ownership.",
      evidence: ["ontology", "constitution"],
      takeaway: "If relationships are missing or a query is truncated, narrow or hold the candidate instead of concluding there is no impact.",
      body: `
        <div class="vp-scope-graph-layout" role="img" aria-label="Directional relationships from a change candidate to its workload, service, objective, and owner">
          <article class="resource" data-vp-node="resource"><small>RESOURCE</small><strong data-vp-primary>Change candidate</strong><span>Exact ID - revision 1842</span></article>
          <i class="vp-graph-link link-runs" data-vp-link data-vp-from="workload" data-vp-to="resource" data-vp-direction="left" aria-hidden="true"><span>runs_on</span></i>
          <article class="workload" data-vp-node="workload"><small>WORKLOAD</small><strong data-vp-primary>checkout-api</strong><span>Unit of deployment and operation</span></article>
          <i class="vp-graph-link link-implements" data-vp-link data-vp-from="service" data-vp-to="workload" data-vp-direction="left" aria-hidden="true"><span>implemented_by</span></i>
          <article class="service" data-vp-node="service"><small>BUSINESS SERVICE</small><strong data-vp-primary>Payment service</strong><span>Criticality and operating scope</span></article>
          <i class="vp-graph-link link-objective" data-vp-link data-vp-from="service" data-vp-to="objective" aria-hidden="true"><span>governed_by</span></i>
          <article class="objective" data-vp-node="objective"><small>OBJECTIVE</small><strong data-vp-primary>Availability objective</strong><span>Measurement window and tolerance</span></article>
          <i class="vp-graph-link link-owner" data-vp-link data-vp-from="service" data-vp-to="owner" data-vp-direction="down" aria-hidden="true"><span>owned_by</span></i>
          <article class="owner" data-vp-node="owner"><small>OWNERSHIP</small><strong data-vp-primary>Service owner</strong><span>Accountable for outcomes and handoff</span></article>
          <aside><b>Illustrative topology</b><span>Relationships support impact analysis but do not prove causation.</span></aside>
        </div>`,
    }),
    slide({
      index: 11,
      id: "precedence",
      chapter: 2,
      state: "CONTRACT",
      title: "Compare value and cost only after higher-order constraints pass",
      lead: "Apply constitutional precedence first so lower cost or greater speed cannot offset safety, recovery, SLO, or change-control requirements.",
      evidence: ["constitution", "planning"],
      takeaway: "Weights support soft tradeoffs among eligible candidates; they cannot revive a candidate that fails a mandatory constraint.",
      body: `
        <div class="vp-precedence-layout">
          <ol>
            <li style="--vp-level:0"><b>01</b><strong data-vp-primary>Safety - security - compliance - identity</strong><span>Remove candidates with violations</span></li>
            <li style="--vp-level:1"><b>02</b><strong data-vp-primary>Data integrity - recoverability</strong><span>Remove candidates with loss or no recovery path</span></li>
            <li style="--vp-level:2"><b>03</b><strong data-vp-primary>SLO - RTO - RPO - error budget</strong><span>Remove candidates that violate protected objectives</span></li>
            <li style="--vp-level:3"><b>04</b><strong data-vp-primary>Change safety - impact containment</strong><span>Remove candidates with uncontrolled scope</span></li>
            <li style="--vp-level:4"><b>05</b><strong data-vp-primary>Performance - operational efficiency</strong><span>Compare among eligible candidates</span></li>
            <li style="--vp-level:5"><b>06</b><strong data-vp-primary>Cost optimization</strong><span>Compare among eligible candidates</span></li>
          </ol>
          <div class="vp-precedence-key"><span class="hard">Mandatory constraints</span><span class="soft">Comparable objectives</span><strong>Apply from top to bottom</strong></div>
        </div>`,
    }),
    slide({
      index: 12,
      id: "safeguards",
      chapter: 2,
      state: "CONTRACT",
      title: "Define all seven safeguards before implementation",
      lead: "Before implementation, a state-changing candidate must define stop, recovery, impact, validation, lock, deduplication, and audit contracts.",
      evidence: ["constitution", "execution"],
      takeaway: "A missing safeguard blocks execution eligibility, but shadow-mode diagnosis may continue with a remediation plan.",
      body: `
        <div class="vp-safeguard-passport">
          <header><small>ACTION ELIGIBILITY</small><strong>Safety passport for a state-changing candidate</strong><span>Execution blocked until 7 / 7 are verified</span></header>
          <ol>
            <li><b>01</b><strong data-vp-primary>Stop condition</strong><span>Machine-evaluable termination criteria</span></li>
            <li><b>02</b><strong data-vp-primary>Tested recovery</strong><span>Rollback or bounded forward recovery</span></li>
            <li><b>03</b><strong data-vp-primary>Blast radius</strong><span>Calculated target count and maximum scope</span></li>
            <li><b>04</b><strong data-vp-primary>Successful dry run</strong><span>Bound to the current plan and target revision</span></li>
            <li><b>05</b><strong data-vp-primary>Logical target lock</strong><span>Blocks concurrent work and stale targets</span></li>
            <li><b>06</b><strong data-vp-primary>Deduplication key</strong><span>A retry cannot produce a second effect</span></li>
            <li><b>07</b><strong data-vp-primary>Two-phase audit</strong><span>Records intent before execution and outcome at closure</span></li>
          </ol>
          <div class="vp-passport-verdict"><span>Unmet</span><strong>Execution held</strong><i></i><span>All verified</span><strong>Separate authority review</strong></div>
        </div>`,
    }),
  ];
}
