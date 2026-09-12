/** Slides 2-7: define the portfolio decision and its smallest useful unit. */
import { field, slide } from "./value-prioritization-slide-kit.en.js";

export function buildValuePrioritizationFoundations() {
  return [
    slide({
      index: 2,
      id: "selection",
      chapter: 1,
      state: "DECISION",
      title: "Choose the first verifiable decision, not the biggest idea",
      lead: "Gather candidates broadly, but select one decision type whose evidence and ownership can be resolved in this portfolio meeting.",
      evidence: ["constitution", "planning"],
      takeaway: "The result is not a feature list. It is one decision with a baseline, target, owner, and expected effect.",
      body: `
        <div class="vp-selection-field">
          <div class="vp-selection-pool">
            <small>Candidate backlog</small>
            <span>Change review</span><span>Recovery decision</span><span>Capacity adjustment</span><span>Cost anomaly</span><span>Policy deviation</span><span>Operational query</span>
          </div>
          <div class="vp-selection-gates" aria-label="Four questions that narrow the candidates">
            <div><b>01</b><strong data-vp-primary>Is this a recurring decision?</strong><span>Confirm that the same inputs and choice structure recur.</span></div>
            <div><b>02</b><strong data-vp-primary>Is current evidence available?</strong><span>Confirm its source, time, scope, and completeness.</span></div>
            <div><b>03</b><strong data-vp-primary>Can it stop safely?</strong><span>Review recovery and blast radius before execution.</span></div>
            <div><b>04</b><strong data-vp-primary>Can the effect be observed separately?</strong><span>Choose an observation source independent of the executor.</span></div>
          </div>
          <article class="vp-selection-result">
            <small>This decision</small>
            <strong>1 initial observation-mode candidate</strong>
            <span>Record selection and deferral reasons against the same criteria.</span>
          </article>
        </div>`,
    }),
    slide({
      index: 3,
      id: "decision-anatomy",
      chapter: 1,
      state: "GUIDE",
      title: "Use a recurring decision type as the unit, not a project",
      lead: "Define which signal prompts whom to decide what. This creates a unit that can be compared and replayed more effectively than a tool rollout or broad workstream.",
      evidence: ["ontology", "planning"],
      takeaway: "A good candidate asks the same question repeatedly and states the no-action option and completion criteria in one sentence.",
      body: `
        <div class="vp-anatomy-strip" role="img" aria-label="Decision structure from signal through target, options, decision, and effect">
          <article data-vp-node="trigger"><small>TRIGGER</small><strong data-vp-primary>What starts the decision?</strong><span>Observation, change request, schedule, operator request</span></article>
          <i class="vp-arrow" data-vp-link data-vp-from="trigger" data-vp-to="target" aria-hidden="true"></i>
          <article data-vp-node="target"><small>TARGET</small><strong data-vp-primary>What target is evaluated?</strong><span>Exact object ID and revision</span></article>
          <i class="vp-arrow" data-vp-link data-vp-from="target" data-vp-to="options" aria-hidden="true"></i>
          <article data-vp-node="options"><small>OPTIONS</small><strong data-vp-primary>What choices are available?</strong><span>Action, hold, and no-action baseline</span></article>
          <i class="vp-arrow" data-vp-link data-vp-from="options" data-vp-to="outcome" aria-hidden="true"></i>
          <article data-vp-node="outcome"><small>OUTCOME</small><strong data-vp-primary>How is completion known?</strong><span>Independent observation and stop condition</span></article>
        </div>
        <div class="vp-anatomy-example">
          <span><b>Broad statement</b>Optimize cost</span>
          <i aria-hidden="true">-&gt;</i>
          <strong><b>Decision type</b>Classify idle resource candidates as remove, hold, or retain based on evidence and protection objectives</strong>
        </div>`,
    }),
    slide({
      index: 4,
      id: "questions",
      chapter: 1,
      state: "GUIDE",
      title: "Five questions reveal both candidate value and boundaries",
      lead: "Assess recurrence, evidence, safety, and measurability alongside value.",
      evidence: ["constitution", "metrics", "readiness"],
      takeaway: "If a question cannot be answered, assign the missing evidence and an owner instead of merely lowering the score.",
      body: `
        <div class="vp-question-compass">
          <div class="vp-question-center"><small>PORTFOLIO QUESTION</small><strong>Why validate this<br>decision now?</strong></div>
          <ol>
            <li><b>01</b><strong data-vp-primary>What operational loss does it reduce?</strong><span>Separate time, cost, risk, and human touchpoints.</span></li>
            <li><b>02</b><strong data-vp-primary>Does the same decision recur?</strong><span>Check whether inputs and options are stable.</span></li>
            <li><b>03</b><strong data-vp-primary>Is the evidence sufficient?</strong><span>Confirm authority, freshness, scope, and completeness.</span></li>
            <li><b>04</b><strong data-vp-primary>Can failure remain controlled?</strong><span>Confirm stop, recovery, and blast-radius controls.</span></li>
            <li><b>05</b><strong data-vp-primary>Can the outcome be verified independently?</strong><span>Define the expected effect and observation window first.</span></li>
          </ol>
        </div>`,
    }),
    slide({
      index: 5,
      id: "domains",
      chapter: 1,
      state: "CONTRACT",
      title: "Three domains protect different operating objectives",
      lead: "Compare resilience, change safety, and cost governance candidates through the same control boundary within the SRE operating model, without blending their outcome meanings.",
      evidence: ["constitution", "outcomes"],
      takeaway: "The domain defines the objective to protect, the evidence required, and the effect to verify - not just the candidate name.",
      body: `
        <div class="vp-domain-landscape">
          <article class="resilience">
            <header><small>RESILIENCE</small><strong>Resilience</strong></header>
            <dl>${field("Decision", "Recovery path and timing", "Incident, backup, restore, continuity")}${field("Protect", "Service and recovery objectives", "Protect SLO and RTO/RPO within the same scope")}${field("Complete", "Independently verified recovery", "Observe recurrence and recovery state")}</dl>
          </article>
          <article class="change">
            <header><small>CHANGE SAFETY</small><strong>Change safety</strong></header>
            <dl>${field("Decision", "Change permission and conditions", "Exact revision and blast radius")}${field("Protect", "Architecture constraints and reliability", "Separate approval from execution")}${field("Complete", "Post-change effect verification", "Operational outcome, not API response")}</dl>
          </article>
          <article class="cost">
            <header><small>COST GOVERNANCE</small><strong>Cost governance</strong></header>
            <dl>${field("Decision", "Retain, adjust, or hold", "Cost and capacity evidence")}${field("Protect", "Availability and performance", "Pass reliability conditions first")}${field("Complete", "Realized unit cost", "Separate estimated savings from actual effect")}</dl>
          </article>
        </div>`,
    }),
    slide({
      index: 6,
      id: "brief",
      chapter: 1,
      state: "PROPOSAL",
      title: "Turn expectations into verifiable statements at candidate intake",
      lead: "A concise decision brief narrows scope and helps different teams review the same candidate against the same criteria.",
      evidence: ["ontology", "planning", "outcomes"],
      takeaway: "Define the target, baseline, protection objective, observation source, and owner before naming the candidate.",
      body: `
        <div class="vp-brief-sheet">
          <header><span>DECISION BRIEF</span><strong>One-page candidate definition</strong><small>Workshop proposal</small></header>
          <dl>
            ${field("Operational problem", "What is currently slow or risky?", "Observable loss or constraint")}
            ${field("Decision statement", "Who uses which signal to choose what?", "Include action, hold, and no action")}
            ${field("Exact scope", "Which service, target, and environment?", "State exclusions as well")}
            ${field("No-action baseline", "What happens if nothing is done?", "Current operating flow for comparison")}
            ${field("Expected effect", "Which metric should change, and in which direction?", "Unit, period, and observation source")}
            ${field("Protection objective", "What must not degrade?", "SLO, recovery, security, change safety")}
            ${field("Owner", "Who owns the outcome and follow-up work?", "Approval and execution roles remain separate")}
            ${field("Review point", "When and with what evidence is it reassessed?", "Prevent holds without expiration")}
          </dl>
        </div>`,
    }),
    slide({
      index: 7,
      id: "baseline",
      chapter: 1,
      state: "CONTRACT",
      title: "A no-action baseline reveals both improvement and side effects",
      lead: "Compare current operations and FDAI outcomes with the same eligibility criteria and observation window to distinguish speed gains from safety regressions.",
      evidence: ["metrics", "planning"],
      takeaway: "Without a baseline, an expected effect is an unvalidated hypothesis, not prioritization evidence.",
      body: `
        <div class="vp-baseline-compare">
          <article class="baseline">
            <header><small>BASELINE</small><strong>Current operating flow</strong></header>
            <div><span>Same candidate eligibility</span><i></i><span>Same measurement period</span><i></i><span>Same metric definition</span></div>
            <p>Preserve the time spent deciding, waiting, executing, and verifying outcomes in the actual non-FDAI operating process.</p>
          </article>
          <div class="vp-baseline-delta"><small>COMPARE</small><strong>Delta</strong><span>Performance metric improvement</span><span>No safety metric regression</span></div>
          <article class="treatment">
            <header><small>TREATMENT</small><strong>FDAI observation or action</strong></header>
            <div><span>Same candidate eligibility</span><i></i><span>Same measurement period</span><i></i><span>Same metric definition</span></div>
            <p>Reconcile retries and corrections against the latest authoritative observation, and do not hide incomplete cases from the denominator.</p>
          </article>
        </div>`,
    }),
  ];
}
