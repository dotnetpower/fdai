const sources = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
  observability: "docs/roadmap/rules-and-detection/observability-and-detection.md",
  operator: "docs/roadmap/operations/operator-initiated-sre-and-arb.md",
  recovery: "docs/roadmap/decisioning/recovery-and-chaos-enforcement.md",
};

function sourceList(...items) {
  return items.map((item) => sources[item]);
}

function slide({
  index,
  state,
  chapter,
  title,
  lead,
  layout,
  content,
  source,
  sourceLabel,
  statusLabel,
}) {
  const number = String(index).padStart(2, "0");
  return {
    eyebrow: `${number} / ${statusLabel(state)}`,
    title,
    lead,
    layout: `briefing-${layout} deck-sre-incident-response`,
    content: `
      <div class="briefing-status-row">
        <span class="manual-status" data-state="${state}" aria-label="Design state: ${statusLabel(state)}">${statusLabel(state)}</span>
        <span>${chapter} / ${number} / 10</span>
      </div>
      ${content}
      ${sourceLabel(source)}`,
  };
}

export function buildSreIncidentResponseDeck({ sourceLabel, statusLabel }) {
  return [
    {
      eyebrow: "FDAI / SRE INCIDENT RESPONSE & MTTR",
      title: "From alerts to verified service recovery",
      lead: "Connect signals, response procedures, AI analysis, and controlled recovery in one Incident model.",
      layout: "briefing-cover deck-sre-incident-response",
      content: `
        <figure class="briefing-cover-art">
          <img src="assets/sre-incident-response.png" alt="">
          <figcaption>SRE RESPONSE</figcaption>
        </figure>
        <ol class="briefing-cover-index" aria-label="Key sections of SRE Incident Response & MTTR">
          <li><small>01</small><span>Detection and impact assessment</span></li>
          <li><small>02</small><span>Controlled recovery and failover</span></li>
          <li><small>03</small><span>MTTR and operational outcomes</span></li>
        </ol>
        <div class="sre-cover-promise" aria-label="Operational value provided by this guide">
          <span>INCIDENT TO OUTCOME</span>
          <strong>Reduce signals</strong><i></i><strong>Control recovery</strong><i></i><strong>Prove outcomes</strong>
        </div>
        ${sourceLabel(sourceList("observability", "operator", "metrics"))}`,
    },
    slide({
      index: 2,
      state: "CURRENT",
      chapter: "Detection and impact assessment",
      title: "Consolidate high-volume operational signals into one actionable Incident",
      lead: "FDAI preserves healthy observations while reducing duplicate events and correlating only signals from the same failure window with supporting evidence.",
      layout: "sre-signal",
      source: sourceList("observability", "operator"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-signal-board" aria-label="Example operational signal correlation">
          <header><span>Example response window / 15 minutes</span><strong>checkout-api latency increase</strong><b>P1 candidate</b></header>
          <div class="sre-signal-kpis">
            <article><small>Raw signals</small><strong>1,284</strong><span>Metrics / logs / changes</span></article>
            <article><small>Deduplicated</small><strong>92%</strong><span>Same symptom and target</span></article>
            <article><small>Correlated episodes</small><strong>7</strong><span>By time and dependency</span></article>
            <article><small>Incident candidates</small><strong>1</strong><span>18 evidence keys</span></article>
          </div>
          <div class="sre-signal-detail">
            <figure>
              <figcaption>Signal compression flow</figcaption>
              <div><b>Telemetry</b><span style="--signal-width:100%"><i>1,284</i></span></div>
              <div><b>Normalized events</b><span style="--signal-width:68%"><i>103</i></span></div>
              <div><b>Correlated episodes</b><span style="--signal-width:42%"><i>7</i></span></div>
              <div><b>Response candidates</b><span style="--signal-width:22%"><i>1</i></span></div>
            </figure>
            <aside>
              <small>Response evidence</small>
              <strong>SLO burn and post-deployment errors share a service graph.</strong>
              <dl><div><dt>Target</dt><dd>checkout-api</dd></div><div><dt>Change</dt><dd>revision 1842</dd></div><div><dt>Evidence freshness</dt><dd>47 seconds</dd></div></dl>
            </aside>
          </div>
        </section>`,
    }),
    slide({
      index: 3,
      state: "CURRENT",
      chapter: "Detection and impact assessment",
      title: "Assess customer impact with the service graph",
      lead: "Correlation is not treated as causation. Services, resources, recent changes, and SLOs are compared using evidence from the same point in time.",
      layout: "sre-impact",
      source: sourceList("constitution", "operator"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-impact-view" aria-label="Example service impact analysis">
          <div class="sre-impact-legend"><span class="critical">Impact confirmed</span><span class="warning">Risk increased</span><span>Healthy</span><b>Example topology</b></div>
          <figure class="sre-service-map">
            <article class="node customer"><small>Customer journey</small><strong>Payment</strong><span>Success -8.4 pp</span></article>
            <i class="map-link customer-link" aria-hidden="true"></i>
            <article class="node service"><small>Service</small><strong>checkout-api</strong><span>SLO burn 6.2x</span></article>
            <i class="map-link service-link" aria-hidden="true"></i>
            <article class="node dependency"><small>Dependency</small><strong>payment-api</strong><span>p95 1.8s</span></article>
            <i class="map-link data-link" aria-hidden="true"></i>
            <article class="node change"><small>Recent change</small><strong>revision 1842</strong><span>Deployed 12 min ago</span></article>
            <article class="node healthy"><small>Comparison</small><strong>catalog-api</strong><span>Healthy range</span></article>
            <article class="node data"><small>Data layer</small><strong>orders-db</strong><span>connection +41%</span></article>
            <i class="map-link vertical-link" aria-hidden="true"></i>
          </figure>
          <aside class="sre-impact-summary">
            <header><small>Impact summary</small><strong>Ready for operator assessment</strong></header>
            <div><span>Journeys</span><b>1 payment journey</b></div>
            <div><span>Direct impact</span><b>2 services</b></div>
            <div><span>Candidates</span><b>1 change</b></div>
            <div><span>Unconfirmed</span><b>Root cause</b></div>
          </aside>
        </section>`,
    }),
    slide({
      index: 4,
      state: "DECISION",
      chapter: "Detection and impact assessment",
      title: "Combine rules, validated cases, prediction, and LLM analysis",
      lead: "Organizational response procedures provide the default path, with evidence-grounded AI analysis added for new ambiguity.",
      layout: "sre-decision",
      source: sourceList("constitution", "observability"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-decision-system" aria-label="AIOps decision system">
          <div class="sre-decision-inputs">
            <article><small>DETECT</small><strong>Statistical prediction</strong><span>Anomalies / capacity / SLO burn</span></article>
            <article><small>T0</small><strong>Operational rules</strong><span>Thresholds / policies / procedures</span></article>
            <article><small>T1</small><strong>Validated reuse</strong><span>Same symptom, scope, and outcome</span></article>
            <article><small>T2</small><strong>Grounded reasoning</strong><span>New relationships / residual ambiguity</span></article>
          </div>
          <div class="sre-decision-core">
            <small>EXAMPLE DECISION CASE</small>
            <strong>Review rollback of revision 1842</strong>
            <div><span>Evidence completeness</span><b>Satisfied</b></div>
            <div><span>Impact scope</span><b>2 services</b></div>
            <div><span>Current authority</span><b>Human approval</b></div>
            <div><span>Recovery plan</span><b>Validated</b></div>
          </div>
          <div class="sre-decision-output">
            <article class="selected"><small>RECOMMEND</small><strong>Deployment rollback</strong><span>Prior healthy revision + validation path</span></article>
            <article><small>ALTERNATIVE</small><strong>Traffic limiting</strong><span>Reduce impact if rollback fails</span></article>
            <article><small>HOLD</small><strong>Database change</strong><span>No execution: causal evidence is insufficient</span></article>
          </div>
          <footer><span>AI expands candidates.</span><b>Policy and authority gate execution.</b><span>Operators review evidence and options.</span></footer>
        </section>`,
    }),
    slide({
      index: 5,
      state: "DECISION",
      chapter: "Controlled recovery and failover",
      title: "Compare recovery options, not just speed",
      lead: "Compare expected effect, risk, RTO, and reversibility. FDAI proposes a validated path for the current failure and recovery objective.",
      layout: "sre-options",
      source: sourceList("recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-option-board" aria-label="Example recovery option comparison">
          <header><span>Example Incident / checkout-api</span><strong>Target: Restore the payment SLO within 15 minutes</strong><b>Awaiting operator decision</b></header>
          <div class="sre-option-grid">
            <article class="recommended">
              <small>Recommended</small><strong>Deployment rollback</strong><p>Return to revision 1841</p>
              <dl><div><dt>Recovery</dt><dd>6 minutes</dd></div><div><dt>Scope</dt><dd>2 services</dd></div><div><dt>Rehearsal</dt><dd>Recent success</dd></div></dl>
            </article>
            <article>
              <small>Limit impact</small><strong>Traffic limiting</strong><p>Reduce payment retry rate</p>
              <dl><div><dt>Recovery</dt><dd>4 minutes</dd></div><div><dt>Scope</dt><dd>Customer delay</dd></div><div><dt>Resolution</dt><dd>No</dd></div></dl>
            </article>
            <article>
              <small>Failover</small><strong>Switch to secondary</strong><p>Use a validated alternate region</p>
              <dl><div><dt>Recovery</dt><dd>12 minutes</dd></div><div><dt>RPO</dt><dd>5 minutes</dd></div><div><dt>Approvals</dt><dd>2 people</dd></div></dl>
            </article>
            <article class="blocked">
              <small>Excluded from execution</small><strong>Direct database edit</strong><p>No validated procedure</p>
              <dl><div><dt>Evidence</dt><dd>Insufficient</dd></div><div><dt>Reversibility</dt><dd>Unvalidated</dd></div><div><dt>Outcome</dt><dd>Excluded</dd></div></dl>
            </article>
          </div>
          <footer><span>Selection rationale</span><strong>Post-deployment symptoms + prior healthy revision + recent rollback exercise evidence</strong><b>Dry-run the current plan before execution</b></footer>
        </section>`,
    }),
    slide({
      index: 6,
      state: "BOUNDARY",
      chapter: "Controlled recovery and failover",
      title: "Separate roles and identities to retain control during emergencies",
      lead: "No single agent holds every authority, and human approval remains separate from the executor identity.",
      layout: "sre-authority",
      source: sourceList("operator", "recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-authority-map" aria-label="Separation of SRE response authority">
          <div class="sre-agent-lane">
            <article><small>OBSERVE</small><strong>Heimdall (observation and prediction) agent</strong><span>Publish signal and impact evidence</span></article><i></i>
            <article><small>DECIDE</small><strong>Forseti (decision) agent</strong><span>Determine eligible recovery options</span></article><i></i>
            <article class="human"><small>AUTHORIZE</small><strong>Operator + Var (approval relay) agent</strong><span>Approve the exact plan and scope</span></article><i></i>
            <article><small>ACT</small><strong>Thor (execution) agent</strong><span>Dispatch approved actions only</span></article><i></i>
            <article><small>RECOVER</small><strong>Vidar (recovery) agent</strong><span>Control the recovery plan after failure</span></article>
          </div>
          <div class="sre-safeguards">
            <header><small>Execution controls</small><strong>7 safeguards before execution</strong></header>
            <ol><li>Stop condition</li><li>Tested rollback</li><li>Blast-radius limit</li><li>Successful dry run</li><li>Logical-target lock</li><li>Stable idempotency key</li><li>Two-phase audit</li></ol>
            <footer><span>Saga (audit) agent</span><b>Connect intent -> approval -> execution -> effect -> closure in an append-only record</b></footer>
          </div>
        </section>`,
    }),
    slide({
      index: 7,
      state: "OPERATE",
      chapter: "Controlled recovery and failover",
      title: "Manage failover as one plan from transition through return",
      lead: "Manage traffic transition, data integrity, and failback under the same recovery objective rather than stopping after traffic moves to a secondary system.",
      layout: "sre-failover",
      source: sourceList("recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-failover-plan" aria-label="Example failover plan">
          <div class="sre-failover-architecture">
            <header><span>Example recovery plan</span><strong>Payment service regional failover</strong><b>Awaiting approval</b></header>
            <figure>
              <div class="traffic"><small>User traffic</small><strong>100%</strong></div>
              <i class="failover-link inbound" aria-hidden="true"></i>
              <i class="failover-link inbound-primary" aria-hidden="true"></i>
              <i class="failover-link inbound-secondary" aria-hidden="true"></i>
              <article class="primary"><small>PRIMARY / unhealthy</small><strong>Region A</strong><span>Error rate 18.2%</span></article>
              <i class="failover-link primary-link" aria-hidden="true"></i>
              <article class="secondary"><small>SECONDARY / ready</small><strong>Region B</strong><span>Replication lag 42 seconds</span></article>
              <i class="failover-link secondary-link" aria-hidden="true"></i>
              <article class="gate"><small>TRAFFIC GATE</small><strong>0% -> 10% -> 50% -> 100%</strong><span>Verify the SLO at each stage</span></article>
            </figure>
          </div>
          <aside class="sre-recovery-contract">
            <header><small>Recovery objectives</small><strong>Boundaries agreed before execution</strong></header>
            <div><span>RTO target</span><b>15 minutes</b></div>
            <div><span>RPO target</span><b>5 minutes</b></div>
            <div><span>Stop condition</span><b>Error rate &gt; 2%</b></div>
            <div><span>Data check</span><b>Order integrity</b></div>
            <div><span>Failback</span><b>Separate approval</b></div>
            <footer>On breach, stop transitions and use the approved recovery path.</footer>
          </aside>
        </section>`,
    }),
    slide({
      index: 8,
      state: "VALIDATED",
      chapter: "Controlled recovery and failover",
      title: "Verify service recovery through an independent observation path",
      lead: "Closure requires independent telemetry to confirm SLOs, error rate, latency, data integrity, and side effects outside the execution system.",
      layout: "sre-verification",
      source: sourceList("recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-verification-board" aria-label="Example service recovery verification">
          <header><span>Example effect observation / 10 minutes</span><strong>Verify effect of rollback-1842</strong><b>Validation passed</b></header>
          <div class="sre-chart-grid">
            <figure><figcaption><span>Error rate</span><b>18.2% -> 0.7%</b></figcaption><svg viewBox="0 0 300 110"><path class="axis" d="M8 95 H292"/><path class="before" d="M8 20 L60 25 L110 18 L155 70"/><path class="after" d="M155 70 C190 88 230 87 292 90"/></svg><small>Target &lt; 1%</small></figure>
            <figure><figcaption><span>p95 latency</span><b>1.8s -> 320ms</b></figcaption><svg viewBox="0 0 300 110"><path class="axis" d="M8 95 H292"/><path class="before" d="M8 28 L70 18 L120 30 L155 72"/><path class="after" d="M155 72 C200 84 240 81 292 86"/></svg><small>Target &lt; 500ms</small></figure>
            <figure><figcaption><span>Order integrity</span><b>100%</b></figcaption><div class="sre-donut" style="--donut-value:100"><i></i></div><small>0 mismatches</small></figure>
          </div>
          <div class="sre-verification-ledger">
            <article><small>Execution</small><strong>Action dispatch succeeded</strong><span>Not sufficient for operational success</span></article>
            <i></i>
            <article><small>Observation</small><strong>SLO and data verified</strong><span>Evidence source separate from the executor</span></article>
            <i></i>
            <article class="closed"><small>Outcome</small><strong>Service recovery confirmed</strong><span>Audit recorded and Incident closed</span></article>
          </div>
        </section>`,
    }),
    slide({
      index: 9,
      state: "METRIC",
      chapter: "MTTR and operational outcomes",
      title: "Break down MTTR by response stage to identify bottlenecks",
      lead: "Decomposing the full time from detection to resolution distinguishes automation opportunities from stages that require human judgment.",
      layout: "sre-mttr",
      source: sourceList("metrics", "operator"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-mttr-view" aria-label="Example MTTR stage analysis">
          <header><span>Example Incident / resolved</span><strong>Total 18 minutes 42 seconds</strong><b>Detection -> resolution</b></header>
          <div class="sre-mttr-timeline">
            <article style="--segment:12"><small>00:00</small><strong>Detection</strong><span>2m 11s</span></article>
            <article style="--segment:18"><small>02:11</small><strong>Correlation / impact</strong><span>3m 24s</span></article>
            <article class="bottleneck" style="--segment:35"><small>05:35</small><strong>Decision / approval</strong><span>6m 36s</span></article>
            <article style="--segment:20"><small>12:11</small><strong>Execution</strong><span>3m 47s</span></article>
            <article style="--segment:15"><small>15:58</small><strong>Effect verification</strong><span>2m 44s</span></article>
          </div>
          <div class="sre-mttr-summary">
            <article><small>Median</small><strong>21m 08s</strong><span>Typical response time</span></article>
            <article><small>p90</small><strong>54m 12s</strong><span>Slow-response boundary</span></article>
            <article><small>Unresolved</small><strong>3</strong><span>Incidents, not counted as 0 seconds</span></article>
            <aside><small>Primary bottleneck</small><strong>Approval wait 6m 36s</strong><p>Reduce wait time with a prepared evidence package and exact links without lowering approval quality.</p></aside>
          </div>
        </section>`,
    }),
    slide({
      index: 10,
      state: "NEXT",
      chapter: "MTTR and operational outcomes",
      title: "Review adoption results as measurable SRE outcomes",
      lead: "Compare the current baseline and FDAI-assisted results using the same evidence for one repeatable Incident scenario, then decide whether to expand.",
      layout: "sre-outcomes",
      source: sourceList("metrics", "operator", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-outcome-contract" aria-label="SRE adoption outcomes and deliverables">
          <div class="sre-outcome-scorecard">
            <header><small>Measured outcomes</small><strong>Outcomes to review at contract completion</strong></header>
            <article><span>MTTR</span><b>Median / p90</b><small>Change from baseline</small></article>
            <article><span>Recurrence</span><b>Same-symptom count</b><small>Observation window specified</small></article>
            <article><span>Human review</span><b>Touches per 100 cases</b><small>Approvals and manual recovery</small></article>
            <article><span>Automated resolution</span><b>Verified completion rate</b><small>Closures without rollback only</small></article>
            <article><span>SLO protection</span><b>Violation duration</b><small>Error budget impact</small></article>
            <article><span>Effect verification</span><b>Independent verification rate</b><small>0 unverified successes</small></article>
          </div>
          <div class="sre-delivery-path">
            <header><small>Delivery path</small><strong>Validate, then expand</strong></header>
            <ol><li><small>01</small><strong>Baseline</strong><span>Procedure + time</span></li><li><small>02</small><strong>Shadow mode</strong><span>Decision quality</span></li><li><small>03</small><strong>Controlled execution</strong><span>Approved small scope</span></li><li><small>04</small><strong>Outcome review</strong><span>Expand / hold / reduce</span></li></ol>
            <aside><strong>Select 1 initial validation scenario</strong><p>Example: errors after deployment</p><b>Deliverables: baseline + integration design + recovery plan + operational evidence + outcome report</b></aside>
          </div>
        </section>`,
    }),
  ];
}
