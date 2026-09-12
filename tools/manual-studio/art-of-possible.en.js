const sources = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  execution: "docs/roadmap/decisioning/execution-model.md",
  actionOntology: "docs/roadmap/decisioning/action-ontology.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
  ontology: "docs/roadmap/architecture/operating-ontology.md",
  operator: "docs/roadmap/operations/operator-initiated-sre-and-arb.md",
  pantheon: "docs/roadmap/agents/agent-pantheon.md",
  llmStrategy: "docs/roadmap/architecture/llm-strategy.md",
  security: "docs/roadmap/architecture/security-and-identity.md",
  deployment: "docs/roadmap/deployment/deployment.md",
  standingAuthority: "docs/roadmap/decisioning/escalation-and-standing-authority.md",
};

const chapters = {
  today: "The operator workload today",
  scenes: "A day that could work differently",
  boundary: "Safety boundaries and the first decision",
};

function sourceList(...items) {
  return items.map((item) => sources[item]);
}

function slide({ index, state, chapter, title, lead, layout, content, source, sourceLabel, statusLabel }) {
  const number = String(index).padStart(2, "0");
  return {
    eyebrow: `${number} / ${statusLabel(state)}`,
    title,
    lead,
    layout: `briefing-${layout} deck-art-of-possible`,
    content: `
      <div class="briefing-status-row">
        <span class="manual-status" data-state="${state}" aria-label="Design status: ${statusLabel(state)}">${statusLabel(state)}</span>
        <span>${chapter} - ${number} / 10</span>
      </div>
      ${content}
      ${sourceLabel(source)}`,
  };
}

export function buildArtOfPossibleDeck({ sourceLabel, statusLabel }) {
  return [
    {
      brandLogo: "assets/microsoft-logo.png",
      eyebrow: "FUTURE EXPERIENCE",
      deckTitle: "FDAI / FUTURE EXPERIENCE",
      title: "Art of the Possible",
      lead: `
        <strong class="aop-cover-subtitle">A different day for cloud operations</strong>
        <span class="aop-cover-summary">Verified rules handle repeatable work. People direct and approve; independent observation verifies the outcome.</span>
        <small class="aop-cover-principles" aria-label="Decide with verified rules, require human approval, confirm through independent observation">
          <span>Verified rules</span><i aria-hidden="true"></i><span>Human approval</span><i aria-hidden="true"></i><span>Independent verification</span>
        </small>`,
      layout: "briefing-cover deck-art-of-possible",
      content: `
        <figure class="briefing-cover-art">
          <img src="assets/art-possible.jpeg" alt="">
        </figure>
        ${sourceLabel(sourceList("constitution"))}`,
    },
    slide({
      index: 2,
      state: "CURRENT",
      chapter: chapters.today,
      title: "Operators spend most of the day connecting scattered signals",
      lead: "Operators classify alerts, find evidence, and then wait for approval. Little time remains to recover the service and confirm the outcome.",
      layout: "aop-today",
      source: sourceList("operator", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-today-board" aria-label="Example allocation of an operator's day">
          <header>
            <b>Example</b>
            <strong>One operator's day</strong>
            <span>Based on 100% of working time - 24-hour measurement window - not measured from an actual organization</span>
          </header>
          <figure class="aop-today-strip">
            <figcaption>Working time is divided this way</figcaption>
            <div>
              <span class="triage" style="--aop-span:34"><b>Alert triage</b><i>34%</i></span>
              <span class="gather" style="--aop-span:26"><b>Evidence collection</b><i>26%</i></span>
              <span class="wait" style="--aop-span:18"><b>Approval wait</b><i>18%</i></span>
              <span class="fix" style="--aop-span:12"><b>Actual recovery</b><i>12%</i></span>
              <span class="report" style="--aop-span:10"><b>Reporting</b><i>10%</i></span>
            </div>
          </figure>
          <div class="aop-today-pain">
            <article><small>Signal correlation</small><strong>People connect signals manually</strong><span>Memory and experience connect metrics, logs, and recent changes from the same incident window.</span><b>Result - Earlier decision evidence is hard to reconstruct when an incident recurs</b></article>
            <article><small>Approval and authority</small><strong>Approval spans separate conversations</strong><span>Who authorized what and when is recorded separately from actual execution.</span><b>Result - Past approval and authority are hard to verify</b></article>
            <article><small>Outcome confirmation</small><strong>Actions lack separate effect checks</strong><span>A completion report exists, but independent observation does not confirm improvement.</span><b>Result - Measured improvement is hard to demonstrate</b></article>
          </div>
        </section>`,
    }),
    slide({
      index: 3,
      state: "TARGET",
      chapter: chapters.scenes,
      title: "With FDAI, an operator's day could work differently",
      lead: "FDAI supports detection, signal correlation, decisioning, and outcome confirmation. People review blast radius and recovery plans, then make decisions that require authority.",
      layout: "aop-day",
      source: sourceList("constitution", "execution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-day-compare" aria-label="Comparison of the current response and a response supported by FDAI">
          <div class="aop-day-legend">
            <span class="human">Work owned by people</span>
            <span class="auto">Work supported by FDAI</span>
            <b>Compare the same five stages in order</b>
          </div>
          <ol class="aop-day-lane now" aria-label="Current response">
            <li class="lane-tag"><small>Today</small><strong>People connect every stage manually</strong></li>
            <li class="human"><small>Detect</small><strong>A flood of alerts</strong><span>Operator classifies</span></li>
            <li class="human"><small>Connect</small><strong>Review multiple screens</strong><span>Operator correlates</span></li>
            <li class="human"><small>Decide</small><strong>Rely on individual experience</strong><span>Operator decides</span></li>
            <li class="human"><small>Approve</small><strong>Request approval in conversation</strong><span>Operator tracks</span></li>
            <li class="human"><small>Confirm</small><strong>Rely on completion reports</strong><span>Operator infers</span></li>
          </ol>
          <ol class="aop-day-lane next" aria-label="Response supported by FDAI">
            <li class="lane-tag"><small>With FDAI</small><strong>People focus on approval and direction</strong></li>
            <li class="auto"><small>Detect</small><strong>Deduplicated events</strong><span>FDAI organizes events</span></li>
            <li class="auto"><small>Connect</small><strong>Correlated by relationships and time</strong><span>FDAI assembles evidence</span></li>
            <li class="auto"><small>Decide</small><strong>Rule-based decisions and options</strong><span>FDAI proposes</span></li>
            <li class="human"><small>Approve</small><strong>Review evidence and approve</strong><span>Person decides</span></li>
            <li class="auto"><small>Confirm</small><strong>Confirm effects through independent observation</strong><span>FDAI verifies</span></li>
          </ol>
          <p class="aop-day-summary"><b>What changes</b>People move away from repetitive work to review blast radius and recovery plans, then focus on the required approvals and direction.</p>
        </section>`,
    }),
    slide({
      index: 4,
      state: "TARGET",
      chapter: chapters.scenes,
      title: "Scene 1 - Receive evidence and options, not a flood of alerts",
      lead: "The Huginn agent, responsible for event collection, organizes scattered signals. The Forseti agent, responsible for decisions, applies verified rules. Operators review the evidence and blast radius before making required decisions.",
      layout: "aop-scene",
      source: sourceList("pantheon", "constitution", "llmStrategy"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-scene" aria-label="Evidence, decisions, and the operator's role in an early-morning incident response">
          <header><b>Example scenario</b><strong>03:14 Payment service latency increases</strong><span>Only signals from the same incident window are grouped into one response candidate</span></header>
          <div class="aop-scene-grid">
            <article class="evidence">
              <small>Evidence for the operator</small>
              <strong>Review evidence and options together</strong>
              <ul>
                <li>Same-window signals and preceding changes</li>
                <li>Affected services and SLO burn</li>
                <li>Collection time and freshness</li>
                <li>Earlier resolutions of these symptoms</li>
              </ul>
              <b>Exclude stale or conflicting evidence</b>
            </article>
            <i aria-hidden="true"></i>
            <article class="judge">
              <small>FDAI decision - Forseti</small>
              <strong>Apply verified rules first</strong>
              <ul>
                <li>T0 rules and policies for repeatable decisions</li>
                <li>Expected effect of each option</li>
                <li>Blast radius and tested rollback</li>
                <li>Hold when evidence is insufficient</li>
              </ul>
              <b>Model-only inferences remain in shadow mode</b>
            </article>
            <i aria-hidden="true"></i>
            <article class="human">
              <small>Operator - Approval</small>
              <strong>Review, then approve or reject</strong>
              <ul>
                <li>Confirm blast radius and tested rollback</li>
                <li>Silence is never approval</li>
                <li>Separate approver and executor</li>
                <li>Audit all decision evidence</li>
              </ul>
              <b>Approvals expire; a quorum may be required</b>
            </article>
          </div>
        </section>`,
    }),
    slide({
      index: 5,
      state: "TARGET",
      chapter: chapters.scenes,
      title: "Scene 2 - Change meetings begin with an impact graph",
      lead: "Following how a resource connects to services and protected objectives enables decisions based on a verifiable blast radius and explicit conditions instead of impressions.",
      layout: "aop-change",
      source: sourceList("operator", "ontology", "actionOntology"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-change-view" aria-label="Change impact graph and conditions to review in the meeting">
          <div class="aop-change-legend"><b>Example topology</b><span>Arrows show the direction of stored relationships. Relationships alone do not establish causation</span></div>
          <figure class="aop-impact-map">
            <article class="target"><small>Change target</small><strong>Payment database</strong><span>Revision 1842 to evaluate</span></article>
            <i aria-hidden="true"><em>runs_on</em></i>
            <article class="workload"><small>Workload</small><strong>checkout-api</strong><span>Unit of deployment and operation</span></article>
            <i aria-hidden="true"><em>implemented_by</em></i>
            <article class="service"><small>Business service</small><strong>Payment</strong><span>Accountable team and criticality</span></article>
            <i aria-hidden="true"><em>governed_by</em></i>
            <article class="objective"><small>Protected objective</small><strong>Availability SLO</strong><span>Measurement window and target</span></article>
          </figure>
          <ol class="aop-change-check">
            <li><small>01</small><strong>Revision to evaluate</strong><span>Identify the exact change revision to review</span></li>
            <li><small>02</small><strong>Blast radius confirmed through relationships</strong><span>Follow relationships to identify affected targets instead of guessing</span></li>
            <li><small>03</small><strong>Approval conditions and owner</strong><span>Record the approval conditions and accountable owner together</span></li>
          </ol>
          <p class="aop-change-boundary"><b>Boundary</b>Review approval does not grant authority to change a resource. A reviewed change must still pass policy, risk, approval requirements, and safeguards in the ActionType execution path.</p>
        </section>`,
    }),
    slide({
      index: 6,
      state: "TARGET",
      chapter: chapters.scenes,
      title: "Scene 3 - Protect reliability before comparing costs",
      lead: "The Njord agent, responsible for cost, checks safety and reliability conditions first. It compares savings only among options that satisfy every condition.",
      layout: "aop-cost",
      source: sourceList("constitution", "execution", "metrics"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-cost-view" aria-label="Conditions checked before cost comparison and eligibility of each candidate">
          <figure class="aop-cost-ladder">
            <figcaption>Conditions checked before cost</figcaption>
            <div style="--aop-step:0"><small>01</small><strong>Safety and security</strong><span>Exclude options that do not satisfy these conditions</span></div>
            <div style="--aop-step:1"><small>02</small><strong>Reliability objectives</strong><span>Must satisfy SLO, RTO, and RPO</span></div>
            <div style="--aop-step:2"><small>03</small><strong>Change validation and recovery</strong><span>Must validate outcomes before the change and support rollback</span></div>
            <div style="--aop-step:3"><small>04</small><strong>Cost comparison</strong><span>Compare savings after every condition passes</span></div>
          </figure>
          <div class="aop-cost-options">
            <header><b>Example</b><strong>Candidate eligibility and estimated savings</strong><span>Percentages are illustrative examples</span></header>
            <article class="excluded">
              <span class="verdict">Excluded</span>
              <div class="option-copy"><strong>Reduce production instances</strong><em>Availability SLO headroom falls below the threshold</em></div>
              <div class="option-save"><b>Example savings 18%</b><i style="--aop-save:100" aria-hidden="true"></i></div>
            </article>
            <article class="eligible">
              <span class="verdict">Eligible</span>
              <div class="option-copy"><strong>Reconfigure reserved capacity</strong><em>Does not affect reliability objectives</em></div>
              <div class="option-save"><b>Example savings 12%</b><i style="--aop-save:67" aria-hidden="true"></i></div>
            </article>
            <article class="eligible">
              <span class="verdict">Eligible</span>
              <div class="option-copy"><strong>Remove idle resources</strong><em>Impact is limited to individual resources</em></div>
              <div class="option-save"><b>Example savings 6%</b><i style="--aop-save:33" aria-hidden="true"></i></div>
            </article>
            <footer>Independent observation confirms actual savings, not the proposed value.</footer>
          </div>
        </section>`,
    }),
    slide({
      index: 7,
      state: "PRINCIPLE",
      chapter: chapters.boundary,
      title: "Keep conversation, decisions, approval, and execution separate",
      lead: "The Bragi agent, responsible for conversation translation, converts natural-language requests into typed intent. It does not decide, approve, or execute, and language alone never grants authority.",
      layout: "aop-lanes",
      source: sourceList("pantheon", "security"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-lane-board" aria-label="Separation of responsibilities from a natural-language request through execution">
          <div class="aop-lane-row">
            <article class="person"><small>Request</small><strong>Person</strong><span>Describe the goal and required help</span><b><i>Record</i>Natural-language request</b><em>A request alone does not grant authority</em></article>
            <i aria-hidden="true"></i>
            <article class="narrator"><small>Translation - Bragi</small><strong>Structure intent</strong><span>Identify target, scope, time, and constraints</span><b><i>Record</i>Typed intent</b><em>Does not make decisions</em></article>
            <i aria-hidden="true"></i>
            <article class="judge"><small>Decision - Forseti</small><strong>Decide from evidence</strong><span>Apply verified rules and policies first</span><b><i>Record</i>Verdict</b><em>Does not execute</em></article>
            <i aria-hidden="true"></i>
            <article class="approver"><small>Approval relay - Var</small><strong>Relay the human decision</strong><span>Confirm quorum and validity period</span><b><i>Record</i>Approval</b><em>Cannot self-approve</em></article>
            <i aria-hidden="true"></i>
            <article class="executor"><small>Execution - Thor</small><strong>Execute only eligible work</strong><span>Use a separate execution identity</span><b><i>Record</i>ActionRun</b><em>Separate approver and execution identities</em></article>
          </div>
          <div class="aop-lane-rail">
            <span class="rail-key">correlation_id</span>
            <p>Trace each request through decisions, approval, execution, and recovery confirmation with one identifier.</p>
          </div>
          <div class="aop-lane-support">
            <article><strong>Saga agent, responsible for audit</strong><span>Records every stage in an append-only ledger</span></article>
            <article><strong>Vidar agent, responsible for recovery</strong><span>Owns rollback and recovery</span></article>
            <article><strong>15 fixed agents</strong><span>Configuration cannot change each agent's role</span></article>
          </div>
        </section>`,
    }),
    slide({
      index: 8,
      state: "BOUNDARY",
      chapter: chapters.boundary,
      title: "Use the lowest authority ceiling and verify seven safeguards",
      lead: "Calculate the permitted level separately for controls such as risk, blast radius, and role authority. The lowest level becomes the actual authority, and no control can raise another control's ceiling.",
      layout: "aop-ceiling",
      source: sourceList("execution", "constitution", "security"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-ceiling-view" aria-label="Multiple ceilings that set actual authority and safeguards required before execution">
          <figure class="aop-ceiling-chart">
            <figcaption>
              <b>Example verdict</b>
              <span class="scale"><i>Blocked</i><i>Shadow mode</i><i>Human approval</i><i>Autonomous execution</i></span>
            </figcaption>
            <div class="rows">
              <div><strong>Risk matrix</strong><span class="track"><i style="--aop-cap:4">Autonomous execution</i></span></div>
              <div><strong>Tier ceiling</strong><span class="track"><i style="--aop-cap:4">Autonomous execution</i></span></div>
              <div><strong>ActionType ceiling</strong><span class="track"><i style="--aop-cap:3">Human approval</i></span></div>
              <div class="lowest"><strong>Blast radius</strong><span class="track"><i style="--aop-cap:3">Human approval</i></span></div>
              <div><strong>Current load</strong><span class="track"><i style="--aop-cap:4">Autonomous execution</i></span></div>
              <div><strong>Role authority</strong><span class="track"><i style="--aop-cap:4">Autonomous execution</i></span></div>
              <div><strong>Environment restriction</strong><span class="track"><i style="--aop-cap:4">Autonomous execution</i></span></div>
            </div>
            <p class="aop-ceiling-result"><b>Result</b>Human approval is required. The single lowest ceiling among all controls determines the overall authority.</p>
          </figure>
          <aside class="aop-safeguards">
            <small>Seven safeguards to verify before changing state autonomously</small>
            <ul>
              <li><b>01</b>Stop condition</li>
              <li><b>02</b>Tested recovery procedure</li>
              <li><b>03</b>Blast-radius limit</li>
              <li><b>04</b>Successful dry run</li>
              <li><b>05</b>Target lock</li>
              <li><b>06</b>Stable idempotency key</li>
              <li><b>07</b>Pre- and post-execution audit</li>
            </ul>
            <p>If any safeguard is unverified, stop execution and request human review.</p>
          </aside>
        </section>`,
    }),
    slide({
      index: 9,
      state: "METRIC",
      chapter: chapters.boundary,
      title: "Verify the effect independently before recording success",
      lead: "Success can be recorded only after an observer separate from the executor checks authoritative data sources for the defined period.",
      layout: "aop-closure",
      source: sourceList("constitution", "ontology", "metrics"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-closure-view" aria-label="Effect verification process and safety metrics">
          <figure class="aop-closure-chain">
            <figcaption>Sequence for confirming success</figcaption>
            <div class="steps">
              <article><small>Before execution</small><strong>ExpectedEffect</strong><span>Define the metric, direction, allowed range, and observation window</span><em>Example - Error rate at or below 2%, observation window 15 minutes</em></article>
              <i aria-hidden="true"></i>
              <article><small>Execution</small><strong>ActionRun</strong><span>Attempt execution and preserve evidence that the request was delivered</span><em>Example - Stable idempotency key, target lock maintained</em></article>
              <i aria-hidden="true"></i>
              <article class="observed"><small>Independent observation</small><strong>ObservedOutcome</strong><span>An observer separate from the executor confirms the actual effect</span><em>Example - Error rate 0.6%, SLO recovery confirmed</em></article>
            </div>
            <p class="aop-closure-note"><b>Not success</b>An API response, message broker acceptance, or PR merge alone is not recorded as success. When sources disagree, do not average the results; leave the outcome in review.</p>
          </figure>
          <aside class="aop-closure-guards">
            <small>Zero-tolerance safety metrics</small>
            <div class="zeros">
              <article><b>0</b><span>Policy-violating outcomes allowed</span></article>
              <article><b>0</b><span>Wrong-target or stale-revision executions</span></article>
              <article><b>0</b><span>Out-of-authority executions</span></article>
              <article><b>0</b><span>Unverified outcomes marked successful</span></article>
            </div>
            <p><b>At least 30 each</b>Compare only real, non-synthetic cases. The scenario, period, and revision must be the same.</p>
          </aside>
        </section>`,
    }),
    slide({
      index: 10,
      state: "DECISION",
      chapter: chapters.boundary,
      title: "Choose a small pilot; keep target claims separate",
      lead: "The scenes in this guide describe the target operating experience. Next, select one measurable decision with clear boundaries to evaluate its value and feasibility.",
      layout: "aop-decision",
      source: sourceList("deployment", "standingAuthority", "execution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="aop-decision-view" aria-label="Current implementation, work in progress, target state, and the next decision">
          <div class="aop-status-band">
            <article class="now"><small>Current implementation</small><strong>Decide and record in shadow mode</strong><span>Make rule-based decisions, preserve evidence, and safely separate identities and deployment paths</span></article>
            <article class="wip"><small>In progress</small><strong>Verify the full execution path</strong><span>Establish evidence that workflows and the isolated executor enforce the same safeguards</span></article>
            <article class="target"><small>Target</small><strong>Expand within human-approved conditions</strong><span>A3-E execution integration and automatic environment promotion are not yet available</span></article>
          </div>
          <div class="aop-decision-cards">
            <article><small>01 Select</small><strong>One repeatable decision</strong><span>Choose a recurring decision with clear boundaries</span><em>Check: At least 30 repeats per month?</em></article>
            <article><small>02 Conditions</small><strong>Baseline and rollback</strong><span>Confirm the no-action baseline, safeguards, and tested rollback</span><em>Check: Has rollback been tested?</em></article>
            <article><small>03 Measure</small><strong>Independent verification</strong><span>Define the expected effect and observation window before execution</span><em>Check: Can a separate observer verify the effect?</em></article>
            <article class="next"><small>04 Next</small><strong>Evaluate value and feasibility</strong><span>Evaluate the selected scenario in the next guide</span><em>Output: 1 candidate, owner, and review date</em></article>
          </div>
        </section>`,
    }),
  ];
}
