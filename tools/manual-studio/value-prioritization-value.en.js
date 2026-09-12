/** Slides 13-17: translate the eligible decision into measurable value and bounded authority. */
import { slide } from "./value-prioritization-slide-kit.en.js";

export function buildValuePrioritizationValue() {
  return [
    slide({
      index: 13,
      id: "metrics",
      chapter: 3,
      state: "CONTRACT",
      title: "Translate value into five observable operating outcomes",
      lead: "Every metric records its unit, period, baseline, inclusion and exclusion criteria, and decision purpose under the same comparison contract.",
      evidence: ["metrics", "outcomes"],
      takeaway: "Keep unmeasurable benefits as hypotheses rather than removing them, but do not use them as conclusive evidence for a portfolio decision.",
      body: `
        <div class="vp-metric-system">
          <header><span>COMMON MEASUREMENT CONTRACT</span><strong>Baseline and treatment group - 30 days by default or one fixed-scenario replay</strong><small>Sample size / confidence interval / inclusions and exclusions for each metric</small></header>
          <div>
            <article><small>VALUE 01</small><strong data-vp-primary>Cost per work unit</strong><b>USD / incident / change / optimization</b><span>Includes model, compute, storage, and event processing costs; excludes shared fixed costs.</span></article>
            <article><small>VALUE 02</small><strong data-vp-primary>Automated resolution rate</strong><b>Completed events / all events</b><span>Includes only outcomes closed through independent verification without human touchpoints or subsequent recovery.</span></article>
            <article><small>VALUE 03</small><strong data-vp-primary>MTTR</strong><b>Seconds / mean + median + p90 / confirmed recoveries only</b><span>Unresolved incidents remain a separate count and are not recorded as zero seconds.</span></article>
            <article><small>VALUE 04</small><strong data-vp-primary>Change lead time</strong><b>Seconds / mean + median + p90 / merged changes only</b><span>Compares the flow from change request to merge across the same eligible change set.</span></article>
            <article><small>VALUE 05</small><strong data-vp-primary>Human touchpoints</strong><b>Touchpoints per 100 events</b><span>Counts approvals, manual edits, and manual recovery; excludes simple queries.</span></article>
          </div>
        </div>`,
    }),
    slide({
      index: 14,
      id: "guard-balance",
      chapter: 3,
      state: "CONTRACT",
      title: "Better outcomes cannot offset a single safety violation",
      lead: "Measure success and safety in the same window, but never dilute violations that must remain at exactly zero through averages or weights.",
      evidence: ["constitution", "metrics"],
      takeaway: "Immediately hold any candidate that crosses policy, target, authority, or effect-verification boundaries, even when it is faster or less expensive.",
      body: `
        <div class="vp-guard-balance-layout">
          <section class="outcomes">
            <header><small>SUCCESS METRICS</small><strong>Measures of improvement</strong></header>
            <ul><li>Cost per work unit - down</li><li>Automated resolution rate - up</li><li>MTTR - down</li><li>Change lead time - down</li><li>Human touchpoints - down</li></ul>
            <p>Use the same observation period and eligibility rules as the baseline, plus the actual sample size and confidence interval for each metric.</p>
          </section>
          <div class="vp-balance-pivot"><span>AND</span><strong>PASS<br>TOGETHER</strong><i aria-hidden="true"></i></div>
          <section class="guards">
            <header><small>ZERO-TOLERANCE GUARDS</small><strong>Violations that must equal zero</strong></header>
            <ol>
              <li><b>0</b><span>Policy violations leaking into enforce mode</span></li>
              <li><b>0</b><span>Execution against the wrong target or a stale revision</span></li>
              <li><b>0</b><span>Unauthorized execution outside the registered scope</span></li>
              <li><b>0</b><span>Success claims without independent confirmation</span></li>
            </ol>
          </section>
        </div>`,
    }),
    slide({
      index: 15,
      id: "repeatability-map",
      chapter: 3,
      state: "EXAMPLE",
      title: "Pilot repeatable decisions, not just frequent work",
      lead: "Frequent work with different inputs and options each time is difficult to automate with evidence. Place candidates by both repeatability and frequency.",
      evidence: ["deterministic", "metrics"],
      takeaway: "Review upper-right candidates first, but only after they pass evidence eligibility and the safety contract.",
      body: `
        <div class="vp-repeatability-layout">
          <header><b>ILLUSTRATIVE EXAMPLE</b><span>Qualitative positions, not measurements from an actual organization</span></header>
          <figure>
            <span class="axis-y"><b>HIGH</b>Repetition frequency<b>LOW</b></span>
            <span class="axis-x"><b>LOW</b>Decision-structure repeatability<b>HIGH</b></span>
            <div class="quadrant q1"><small>DISCOVER</small><strong>Identify rule candidates first</strong></div>
            <div class="quadrant q2"><small>REVIEW FIRST</small><strong>Collect shadow-mode samples</strong></div>
            <div class="quadrant q3"><small>HOLD</small><strong>Recheck frequency and operating loss</strong></div>
            <div class="quadrant q4"><small>HUMAN-LED</small><strong>Structure, do not automate</strong></div>
            <article class="candidate drift" aria-label="Example policy-drift review"><b>Change-policy drift</b><span>Same rules and target group</span></article>
            <article class="candidate restore" aria-label="Example recovery-readiness check"><b>Recovery-readiness check</b><span>Scheduled checks and fixed criteria</span></article>
            <article class="candidate resize" aria-label="Example capacity adjustment"><b>Capacity adjustment</b><span>Highly variable context</span></article>
            <article class="candidate migration" aria-label="Example one-time migration"><b>Large-scale migration</b><span>One-time plan</span></article>
          </figure>
        </div>`,
    }),
    slide({
      index: 16,
      id: "tier-fit",
      chapter: 3,
      state: "CONTRACT",
      title: "Tier changes cost, explainability, and hold points",
      lead: "Use the lowest Tier that can make a sufficient decision. Tier selection defines the decision method, not execution authority.",
      evidence: ["deterministic", "execution"],
      takeaway: "A first candidate is easier to learn from and audit when T0 rules or verified T1 reuse can explain it.",
      body: `
        <div class="vp-tier-fit-layout">
          <header><b>DESIGN TARGET / EVENT SHARE</b><span>Not an operational measurement; report each deployment's observation window and sample size</span></header>
          <div class="vp-tier-ramp">
            <article class="t0" style="--vp-share:78">
              <small>T0 / TARGET 70-80%</small><strong data-vp-primary>Rules and policies</strong><span>Evaluate repeatable inputs with the same rule version.</span><em>HOLD: no rule / conflict / incorrect context</em>
            </article>
            <article class="t1" style="--vp-share:48">
              <small>T1 / TARGET 15-20%</small><strong data-vp-primary>Verified case reuse</strong><span>Record similarity, prior outcomes, and the reused action version.</span><em>HOLD: low similarity / no provenance</em>
            </article>
            <article class="t2" style="--vp-share:28">
              <small>T2 / TARGET 5-10%</small><strong data-vp-primary>Grounded reasoning</strong><span>Require proposals from different models and deterministic verification.</span><em>CEILING: shadow mode / no automatic execution</em>
            </article>
          </div>
          <div class="vp-tier-axis"><span>More repeatable and less expensive</span><i></i><span>More ambiguous and costly to verify</span></div>
        </div>`,
    }),
    slide({
      index: 17,
      id: "authority-ceiling",
      chapter: 3,
      state: "EXAMPLE",
      title: "The lowest ceiling sets authority, not the value score",
      lead: "Evaluate the risk matrix, Tier, registered action type (ActionType), blast radius, role, and environment independently, then use the most conservative result as the final ceiling.",
      evidence: ["execution", "constitution"],
      takeaway: "This illustration explains how authority is determined. Expected value and human requests cannot raise any independent ceiling.",
      body: `
        <div class="vp-authority-layout">
          <header><b>ILLUSTRATIVE DECISION</b><strong>Candidate resource-group change in a non-production environment</strong><span>Categorical authority example / not an execution decision</span></header>
          <div class="vp-authority-scale"><span>BLOCK</span><span>SHADOW MODE</span><span>HUMAN APPROVAL</span><span>AUTOMATIC EXECUTION</span></div>
          <div class="vp-authority-rows">
            <div style="--vp-cap:4"><strong>Risk matrix</strong><span><i>Automatic execution</i></span><small>No policy violation</small></div>
            <div style="--vp-cap:4"><strong>Tier</strong><span><i>Automatic execution</i></span><small>T0 rule decision</small></div>
            <div style="--vp-cap:4"><strong>ActionType</strong><span><i>Automatic execution</i></span><small>Registered ceiling</small></div>
            <div class="limiting" style="--vp-cap:3"><strong>Blast radius</strong><span><i>Human approval</i></span><small>Resource group</small></div>
            <div style="--vp-cap:4"><strong>Live impact</strong><span><i>Automatic execution</i></span><small>No additional reduction</small></div>
            <div style="--vp-cap:4"><strong>Role</strong><span><i>Automatic execution</i></span><small>Minimum role satisfied</small></div>
            <div style="--vp-cap:4"><strong>Environment</strong><span><i>Automatic execution</i></span><small>Non-production scope</small></div>
          </div>
          <aside><span>FINAL CEILING</span><strong>HUMAN APPROVAL</strong><small>The lowest independent ceiling determines the overall result</small></aside>
        </div>`,
    }),
  ];
}
