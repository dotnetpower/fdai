/** Slides 23-25: convert the selected candidate into a bounded first validation. */
import { slide } from "./value-prioritization-slide-kit.en.js";

export function buildValuePrioritizationAction() {
  return [
    slide({
      index: 23,
      id: "promotion-path",
      chapter: 5,
      state: "STATUS",
      title: "Validate value and safety for selected candidates in shadow mode",
      lead: "New capabilities begin with decisions and records. An execution mode is considered only after separate promotion evidence and authority review.",
      evidence: ["constitution", "execution", "metrics"],
      takeaway: "Portfolio selection starts observation. It does not grant change authority or promise future promotion.",
      body: `
        <div class="vp-promotion-layout">
          <div class="vp-promotion-track">
            <article data-vp-node="baseline"><small>01 - BASELINE</small><strong data-vp-primary>Measure current operations</strong><span>Use the same eligibility rules and metric definitions</span><b>Implemented measurement contract</b></article>
            <i class="vp-arrow" data-vp-link data-vp-from="baseline" data-vp-to="shadow" aria-hidden="true"></i>
            <article data-vp-node="shadow"><small>02 - SHADOW</small><strong data-vp-primary>Decide and record</strong><span>Compare outcomes without changing state</span><b>Default mode for new capabilities</b></article>
            <i class="vp-arrow" data-vp-link data-vp-from="shadow" data-vp-to="review" aria-hidden="true"></i>
            <article data-vp-node="review"><small>03 - REVIEW</small><strong data-vp-primary>Independent promotion review</strong><span>Samples, accuracy, safety metrics, and effect evidence</span><b>Separate human decision</b></article>
            <i class="vp-arrow" data-vp-link data-vp-from="review" data-vp-to="mode" aria-hidden="true"></i>
            <article data-vp-node="mode"><small>04 - MODE</small><strong data-vp-primary>Retain or apply within limits</strong><span>Recheck current risk and authority every time</span><b>Demote to shadow mode on regression</b></article>
          </div>
          <div class="vp-promotion-status">
            <span><b>Current implementation</b>Deterministic measurement and promotion evaluation</span>
            <span><b>Open evidence</b>Real operational comparison cohort, not synthetic</span>
            <span><b>Invariant boundary</b>T2 remains capped at shadow mode</span>
          </div>
        </div>`,
    }),
    slide({
      index: 24,
      id: "thirty-days",
      chapter: 5,
      state: "PROPOSAL",
      title: "Use the first 30 days to build comparable evidence, not features",
      lead: "This schedule is a workshop proposal. Adjust the timing to your change cadence and sample arrival rate, but retain the exit conditions.",
      evidence: ["metrics", "readiness", "planning"],
      takeaway: "Success after 30 days is not autonomous execution. It is a reproducible candidate definition and an evidence package for the next investment decision.",
      body: `
        <div class="vp-thirty-days-plan">
          <header><b>Workshop proposal - 30 days</b><span>The timeline is proposed, not operational performance</span></header>
          <ol>
            <li><small>DAY 01-05</small><strong data-vp-primary>Lock the decision</strong><span>Agree on the target, no-action baseline, protection objective, and owner, then freeze them in one revision.</span><em>Deliverable - Decision brief</em></li>
            <li><small>DAY 06-10</small><strong data-vp-primary>Connect evidence</strong><span>Validate sources, time, completeness, relationships, and the independent observation window.</span><em>Deliverable - Evidence map</em></li>
            <li><small>DAY 11-20</small><strong data-vp-primary>Compare in shadow mode</strong><span>Compare human decisions with FDAI recommendations under the same protocol without changing state.</span><em>Deliverable - Shadow review</em></li>
            <li><small>DAY 21-30</small><strong data-vp-primary>Reassess the portfolio</strong><span>Decide whether to continue, improve, or stop. Keep execution mode subject to a separate review.</span><em>Deliverable - Decision memo</em></li>
          </ol>
          <footer><span>Stop conditions</span><strong>Do not advance if a policy violation, target mismatch, evidence loss, or inability to verify independently occurs.</strong></footer>
        </div>`,
    }),
    slide({
      index: 25,
      id: "commitment",
      chapter: 5,
      state: "DECISION",
      title: "Make one decision today",
      lead: "Agree which recurring decision to observe, who owns it, and what evidence it requires.",
      evidence: ["constitution", "planning", "metrics"],
      takeaway: "After the decision, selected and deferred candidates each have an owner, the next required evidence, and a review date.",
      body: `
        <div class="vp-commitment-layout">
          <section>
            <small>THE DECISION</small>
            <blockquote>Which single decision<br>will you select as the first<br>shadow-mode candidate?</blockquote>
            <p>Start with a narrow scope and preserve extensive evidence.</p>
          </section>
          <ol aria-label="Five items to confirm before the workshop ends">
            <li><b>01</b><span>Recurring decision type</span><strong>One sentence</strong></li>
            <li><b>02</b><span>Exact target and excluded work</span><strong>One scope</strong></li>
            <li><b>03</b><span>No-action baseline and expected effect</span><strong>One comparison</strong></li>
            <li><b>04</b><span>Evidence sources and independent observer</span><strong>One evidence map</strong></li>
            <li><b>05</b><span>Owner and review date</span><strong>One commitment</strong></li>
          </ol>
          <footer><span>Workshop deliverables</span><strong>Decision brief + Evidence map + Shadow review</strong></footer>
        </div>`,
    }),
  ];
}
