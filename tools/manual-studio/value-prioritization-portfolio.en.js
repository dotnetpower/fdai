/** Slides 18-22: compare eligible candidates and record one accountable portfolio decision. */
import { slide } from "./value-prioritization-slide-kit.en.js";

export function buildValuePrioritizationPortfolio() {
  return [
    slide({
      index: 18,
      id: "selection-logic",
      chapter: 4,
      state: "CONTRACT",
      title: "Scoring is the final comparison stage for eligible candidates only",
      lead: "The operating plan removes candidates using mandatory constraints, eliminates dominated options, and then applies weighted comparison only to the remaining soft objectives.",
      evidence: ["constitution", "planning"],
      takeaway: "A portfolio score helps explain a selection. It does not grant approval, promotion, or execution authority.",
      body: `
        <div class="vp-selection-logic-layout">
          <article class="eligibility" data-vp-node="eligible">
            <small>STAGE 01 - ELIGIBILITY</small>
            <strong data-vp-primary>Remove by mandatory constraints</strong>
            <ul><li>Safety and security</li><li>Data integrity and recovery</li><li>SLO and blast radius</li><li>Evidence freshness and completeness</li></ul>
            <b>Hold or exclude failed candidates</b>
          </article>
          <i class="vp-arrow" data-vp-link data-vp-from="eligible" data-vp-to="pareto" aria-hidden="true"></i>
          <article class="pareto" data-vp-node="pareto">
            <small>STAGE 02 - PARETO</small>
            <strong data-vp-primary>Remove clearly dominated options</strong>
            <p>Remove an option only when another candidate is equal or better on every objective and better on at least one.</p>
            <b>This stage does not select a winner</b>
          </article>
          <i class="vp-arrow" data-vp-link data-vp-from="pareto" data-vp-to="tradeoff" aria-hidden="true"></i>
          <article class="tradeoff" data-vp-node="tradeoff">
            <small>STAGE 03 - TRADE-OFF</small>
            <strong data-vp-primary>Compare trade-offs among remaining objectives</strong>
            <p>Use only deployment-defined weights and impact, and send close results for human review.</p>
            <b>Read and simulate only - no authority to change state</b>
          </article>
        </div>`,
    }),
    slide({
      index: 19,
      id: "uncertainty",
      chapter: 4,
      state: "GUIDE",
      title: "Keep observed, estimated, and unknown values distinct",
      lead: "A portfolio table must show evidence status as well as value to avoid false precision and optimistic rankings.",
      evidence: ["constitution", "planning", "outcomes"],
      takeaway: "Unknown does not mean 0. Define the observation needed for a decision, then keep the candidate on hold.",
      body: `
        <div class="vp-uncertainty-spectrum">
          <article class="observed">
            <header><span>OBSERVED</span><strong data-vp-primary>Observed</strong></header>
            <div class="vp-confidence-shape solid" aria-hidden="true"></div>
            <p>An authoritative source, exact reference time, and completeness evidence are available.</p>
            <b>Use: baseline and current state</b>
          </article>
          <article class="estimated">
            <header><span>ESTIMATED</span><strong data-vp-primary>Estimated as a range</strong></header>
            <div class="vp-confidence-shape range" aria-hidden="true"></div>
            <p>Show the model, assumptions, prediction interval, and uncertainty together.</p>
            <b>Use: simulation and option comparison</b>
          </article>
          <article class="unknown">
            <header><span>UNKNOWN</span><strong data-vp-primary>Unknown</strong></header>
            <div class="vp-confidence-shape unknown-mark" aria-hidden="true">?</div>
            <p>The value cannot be stated responsibly because its source is missing, stale, or conflicting.</p>
            <b>Result: evidence task and review date</b>
          </article>
        </div>`,
    }),
    slide({
      index: 20,
      id: "worked-portfolio",
      chapter: 4,
      state: "EXAMPLE",
      title: "Compare three candidates to choose a first validation scope",
      lead: "The content below is a hypothetical example that explains the method. It does not represent actual organizational candidates, scores, operating outcomes, or FDAI deployment status.",
      evidence: ["constitution", "readiness", "metrics"],
      takeaway: "Start with the candidate that current evidence supports for safe learning, not the one that appears to offer the most value.",
      body: `
        <div class="vp-worked-layout">
          <header><b>Illustrative example</b><span>Qualitative comparison - not operational evidence</span><strong>Common lens: value - repeatability - evidence - safety - effect observation</strong></header>
          <div class="vp-portfolio-head"><span>Candidate</span><span>Value hypothesis</span><span>Current readiness</span><span>Primary boundary</span><span>Disposition</span></div>
          <article class="now">
            <strong data-vp-primary>Change policy deviation review</strong><span>Reduce the manual review queue</span><span>Rules and revision evidence available</span><span>Observe only - no changes</span><b>NOW</b>
          </article>
          <article class="next">
            <strong data-vp-primary>Idle resource adjustment</strong><span>Potential unit-cost improvement</span><span>Cost observer needs completion</span><span>Protect SLO and capacity</span><b>NEXT</b>
          </article>
          <article class="hold">
            <strong data-vp-primary>Operational data store failover</strong><span>Potential recovery-time improvement</span><span>Insufficient drill and independent effect evidence</span><span>High impact - human approval</span><b>HOLD</b>
          </article>
          <footer><span>Why selected</span><strong>The decision is replayable from the current revision and policy, and quality can be compared without changing state.</strong></footer>
        </div>`,
    }),
    slide({
      index: 21,
      id: "portfolio-horizon",
      chapter: 4,
      state: "PROPOSAL",
      title: "Manage the portfolio through transition criteria",
      lead: "Do not lock candidates into a permanent ranking. Operate a portfolio that can move them as evidence and safety contracts change.",
      evidence: ["readiness", "planning"],
      takeaway: "Entry criteria, exit criteria, owner, and review date matter more than the number of candidates in each category.",
      body: `
        <div class="vp-horizon-board">
          <article class="now"><small>NOW</small><strong data-vp-primary>Start in observation mode</strong><span>Baseline, evidence, owner, and safety contract are ready</span><b>Exit: comparative results and independent review</b></article>
          <article class="next"><small>NEXT</small><strong data-vp-primary>Complete one or two evidence gaps</strong><span>Value is clear, but the observer or scope remains incomplete</span><b>Exit: blocking evidence resolved</b></article>
          <article class="later"><small>LATER</small><strong data-vp-primary>Redesign the decision structure</strong><span>Inputs and options still change frequently</span><b>Exit: repeatable decision contract</b></article>
          <article class="stop"><small>STOP</small><strong data-vp-primary>Stop within the current scope</strong><span>Higher-order constraint violated, not measurable, or no value</span><b>Revisit: when a constraint or objective changes</b></article>
          <div class="vp-horizon-axis"><span>Validate now</span><i></i><span>Complete evidence</span><i></i><span>Redefine the problem</span><i></i><span>Do not invest</span></div>
        </div>`,
    }),
    slide({
      index: 22,
      id: "decision-memo",
      chapter: 4,
      state: "GUIDE",
      title: "Use one format for selection, hold, and exclusion reasons",
      lead: "Anyone should be able to reproduce a portfolio decision from the same evidence, and every held candidate needs a return condition.",
      evidence: ["planning", "constitution"],
      takeaway: "A good decision memo justifies the selection while preserving excluded alternatives and their review conditions.",
      body: `
        <div class="vp-memo-layout">
          <aside>
            <small>DECISION RECORD</small>
            <strong>A consistent decision record</strong>
            <p>Record the candidate and disposition, supporting evidence and constraints, and review condition.</p>
          </aside>
          <article>
            <header><b>Illustrative example</b><span>2026-09-09 - Portfolio review</span></header>
            <blockquote>Select change policy deviation review as the first observation-mode candidate.</blockquote>
            <dl>
              <div><dt>Why now</dt><dd>The same decision can be replayed from current rules and change revisions.</dd></div>
              <div><dt>What to protect</dt><dd>Preserve architecture constraints, change safety, and approval separation.</dd></div>
              <div><dt>What not to do</dt><dd>This workshop decision does not authorize approval or resource changes.</dd></div>
              <div><dt>Held candidates</dt><dd>Review again when cost observations and recovery drill evidence are ready.</dd></div>
              <div><dt>Next decision</dt><dd>Independently review observation results and safety metrics to continue, improve, or stop.</dd></div>
            </dl>
          </article>
        </div>`,
    }),
  ];
}
