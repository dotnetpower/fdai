export const executiveBriefingSlides = [
  {
    eyebrow: "FDAI / EXECUTIVE BRIEFING",
    brandLogo: "assets/microsoft-logo.png",
    deckTitle: "FDAI Executive Briefing",
    overline: "Forward Deployed Agents",
    showDate: true,
    title: "<span class=\"executive-title-line\">Agents <em>operate autonomously.</em></span><span class=\"executive-title-line\">People <em>decide and stay accountable.</em></span>",
    lead: "FDAI connects operational signals with organizational procedures to handle repeatable work.<strong>People set goals and boundaries, approve consequential decisions, and remain accountable for outcomes.</strong>",
    layout: "cover deck-executive-briefing",
    content: `
      <figure class="cover-photo">
        <img src="assets/executive-briefing.jpeg" alt="Abstract shapes moving through a connected flow">
      </figure>`,
  },
  {
    eyebrow: "01 / EXECUTIVE DECISION",
    title: "Connect existing tools to transform the operating model",
    lead: "FDAI connects the observability, ticketing, and execution tools already in use. It carries operational signals through decisions and approvals, then verifies the actual effect.",
    layout: "executive-choice",
    content: `
      <div class="executive-model-visual">
        <div class="executive-model-shift">
          <article class="executive-model-panel" data-state="AS-IS">
            <small>Current / tool-centered</small>
            <strong>People connect decisions<br>across tools</strong>
            <div class="executive-model-route"><span>Signal</span><i></i><span>Person</span><i></i><span>Ticket</span></div>
            <p>Operators repeatedly gather context and connect approvals with outcomes themselves.</p>
          </article>
          <div class="executive-model-pivot">
            <small>OPERATING MODEL SHIFT</small>
            <span aria-hidden="true">-&gt;</span>
            <strong>Assign repeatable<br>decisions to agents</strong>
          </div>
          <article class="executive-model-panel target" data-state="TO-BE">
            <small>Target / operating-model-centered</small>
            <strong>Agents run operations<br>while people set boundaries</strong>
            <div class="executive-model-route detailed" role="img" aria-label="Detect cloud changes, make evidence-based decisions and approvals, execute safely, and verify operational effects">
              <span><strong>Detect change</strong><small>State / events</small></span><i></i>
              <span><strong>Decide / approve</strong><small>Evidence / policy</small></span><i></i>
              <span><strong>Execute / verify</strong><small>Action / effect</small></span>
            </div>
            <p>Agents connect repeatable flows, while people decide consequential approvals and exceptions.</p>
          </article>
        </div>
        <div class="executive-shift-principles">
          <span><b>01</b><strong>Use existing tools</strong><small>Connect observability, ticketing, and execution systems</small></span>
          <span><b>02</b><strong>Focus human judgment</strong><small>Concentrate on goals, approvals, and exceptions</small></span>
          <span><b>03</b><strong>Complete with effect</strong><small>Verify independently after execution</small></span>
        </div>
      </div>`,
  },
  {
    eyebrow: "02 / FDAI AT A GLANCE",
    title: "15 agents share accountability across one operational flow",
    lead: "Even as cloud complexity grows, observation, understanding, decisions, execution, and verification stay connected in one flow.",
    layout: "executive-blueprint",
    content: `
      <div class="executive-blueprint-layout">
        <figure class="executive-blueprint-core">
          <img src="assets/target-architecture.jpeg" alt="">
          <figcaption>
            <small>EVIDENCE-GOVERNED CONTROL PLANE</small>
            <strong>Digital operations team</strong>
            <span>Autonomous for repeatable work, accountable for consequential decisions</span>
          </figcaption>
        </figure>
        <div class="executive-closed-loop" role="img" aria-label="A closed loop that observes cloud changes, interprets meaning through the ontology, decides through rules and policies, executes within authority, and independently verifies effects">
          <div><b>01</b><strong>Observe</strong><small>State / change / anomaly</small></div><i></i>
          <div><b>02</b><strong>Understand</strong><small>Ontology / relationships / time</small></div><i></i>
          <div><b>03</b><strong>Decide</strong><small>Rules / policy / evidence</small></div><i></i>
          <div><b>04</b><strong>Execute</strong><small>Authority / safeguards</small></div><i></i>
          <div><b>05</b><strong>Verify</strong><small>Actual effect / audit</small></div>
        </div>
        <div class="executive-blueprint-foundations">
          <span><b>15</b><strong>Agents with separated responsibilities</strong><small>No single principal owns decision, approval, and execution</small></span>
          <span><b>1</b><strong>Shared operating ontology</strong><small>Interpret targets, relationships, and evidence consistently</small></span>
          <span><b>T0-T2</b><strong>Lowest sufficient decision Tier</strong><small>Apply rules, reuse, and evidence-grounded reasoning progressively</small></span>
        </div>
      </div>
      <p class="executive-bottom-line">FDAI applies established operating rules and standard procedures first. For new situations, it connects current evidence and presents options for operator judgment.</p>`,
  },
  {
    eyebrow: "03 / AGENT ORGANIZATION",
    title: "The operating ontology creates shared context, and agents process work by role",
    lead: "The ontology connects the meaning of targets, relationships, time, and evidence. Each agent collaborates through schema-validated events.",
    layout: "executive-pantheon",
    content: `
      <div class="executive-pantheon-layout">
        <aside class="executive-ontology-core">
          <small>SHARED SEMANTIC READ MODEL</small>
          <strong>Operating ontology</strong>
          <p>Connects resources, services, goals, dependencies, evidence, and permitted actions in one semantic system.</p>
          <div><span>Targets</span><span>Relationships</span><span>Time</span><span>Evidence</span><span>Authority boundary</span></div>
          <b>Meaning does not grant authority</b>
        </aside>
        <section class="executive-agent-groups" aria-label="FDAI's fixed pantheon of 15 agents">
          <article class="governance">
            <header><span>GOVERNANCE STAFF</span><b>5</b></header>
            <div>
              <span><b>Odin</b><small>Goal alignment</small></span><span><b>Saga</b><small>Audit</small></span>
              <span><b>Mimir</b><small>Rule stewardship</small></span><span><b>Muninn</b><small>Memory</small></span>
              <span><b>Norns</b><small>Learning candidates</small></span>
            </div>
          </article>
          <article class="pipeline">
            <header><span>CONTROL PIPELINE</span><b>7</b></header>
            <div>
              <span><b>Huginn</b><small>Event intake</small></span><span><b>Heimdall</b><small>Observe / predict</small></span>
              <span><b>Forseti</b><small>Decision</small></span><span><b>Var</b><small>Approval delivery</small></span>
              <span><b>Thor</b><small>Execution</small></span><span><b>Vidar</b><small>Recovery</small></span>
              <span><b>Bragi</b><small>Converse / explain</small></span>
            </div>
          </article>
          <article class="specialists">
            <header><span>DOMAIN SPECIALISTS</span><b>3</b></header>
            <div>
              <span><b>Njord</b><small>Cost</small></span><span><b>Freyr</b><small>Capacity</small></span>
              <span><b>Loki</b><small>Resilience experiments</small></span>
            </div>
          </article>
        </section>
      </div>
      <div class="executive-event-fabric"><span>AGENT</span><i></i><strong>Typed events / schema validation / single owner / replayable audit</strong><i></i><span>AGENT</span><b>NO DIRECT CALLS</b></div>`,
  },
  {
    eyebrow: "04 / SOVEREIGN OPERATIONS",
    title: "Control data location, access paths, identity, and AI usage",
    lead: "FDAI can operate within customer-approved regions, private connectivity, identities, and model boundaries.",
    layout: "executive-sovereign",
    content: `
      <div class="executive-sovereign-layout">
        <figure class="executive-sovereign-art">
          <img src="assets/operating-model.jpeg" alt="">
          <figcaption><small>SOVEREIGN-BY-DESIGN</small><strong>Customers decide<br>where data resides<br>and who may use it</strong><span>Fix data, connectivity, identity, and AI usage boundaries in policy</span></figcaption>
        </figure>
        <section class="executive-sovereign-boundary">
          <header><span>SOVEREIGN OPERATING ENVELOPE</span><strong>Customer policy defines the operating boundary</strong><small>Only validated deployment conditions apply to live operations</small></header>
          <div class="executive-sovereign-controls">
            <article><b>01</b><strong>Storage location</strong><span>Operational data and audit records remain only in customer-approved regions and stores.</span></article>
            <article><b>02</b><strong>Access path</strong><span>Collection, processing, and model calls use approved private connectivity.</span></article>
            <article><b>03</b><strong>Access control</strong><span>Managed Identity and least privilege govern access, while customers manage encryption keys.</span></article>
            <article><b>04</b><strong>AI operations</strong><span>Rules, prediction, learning, and LLM reasoning operate within approved region and model boundaries.</span></article>
          </div>
          <div class="executive-sovereign-assurances" aria-label="Core assurances for sovereign operations">
            <span><b>DATA RESIDENCY</b><strong>Customers determine data location</strong></span>
            <span><b>ACCESS CONTROL</b><strong>Customers control access and keys</strong></span>
            <span><b>BOUNDED AUTHORITY</b><strong>Operational authority applies only within validated scope</strong></span>
          </div>
        </section>
      </div>
      <p class="executive-bottom-line">This is FDAI's target deployment model. After assessing readiness, adoption can begin with scopes where data movement, isolation, and recovery are validated.</p>`,
  },
  {
    eyebrow: "05 / DETERMINISTIC SCALE",
    title: "Operate at the lowest Tier sufficient for each decision as scale grows",
    lead: "FDAI progressively applies rules, validated reuse, prediction, and LLM reasoning through one AIOps path.",
    layout: "executive-rules",
    content: `
      <div class="executive-rules-layout">
        <section class="executive-tier-stack" aria-label="Decision stages consisting of T0 rules and policies, T1 validated reuse, and T2 bounded reasoning">
          <header><small>EVENT VOLUME</small><strong>Cloud operations events</strong><span>State / change / anomaly / cost / capacity</span></header>
          <div class="t0"><b>T0</b><strong>Rule and policy catalog</strong><span>Repeatable majority / identical input produces identical decisions</span></div>
          <div class="t1"><b>T1</b><strong>Validated resolution reuse</strong><span>Only when past events, evidence, and outcomes all match</span></div>
          <div class="t2"><b>T2</b><strong>Bounded evidence-grounded reasoning</strong><span>Novel and ambiguous minority / rechecked by verifier and policy</span></div>
        </section>
        <section class="executive-decision-outcomes">
          <header><small>RISK + AUTHORITY GATE</small><strong>Decisions follow three paths</strong></header>
          <article class="automatic"><b>Automatic handling</b><span>Low impact / complete evidence / promoted capability</span></article>
          <article class="human"><b>Human decision</b><span>Consequential impact / policy-required approval / goal conflict</span></article>
          <article class="hold"><b>Hold / deny</b><span>Insufficient evidence / stale context / failed verification / no authority</span></article>
          <p><strong>Approval requests are operational load.</strong> FDAI first rechecks, applies rules, and safely narrows scope, escalating only matters that require a person.</p>
        </section>
      </div>
      <div class="executive-rule-principle"><span>Human role</span><strong>Not approving every ticket, but owning goals, policies, and exceptions</strong><b>NO APPROVAL SPAM</b></div>`,
  },
  {
    eyebrow: "06 / HANDOVER AND LEARNING",
    title: "Turn repeatable responses into reviewable knowledge",
    lead: "FDAI preserves cases, runbooks, decision evidence, and actual outcomes together. Only reviewed knowledge is reused in later responses.",
    layout: "executive-handover",
    content: `
      <div class="executive-handover-layout">
        <figure>
          <img src="assets/pilot-production.jpeg" alt="Operations leaders collaborating at a laptop">
          <figcaption><small>HUMAN-TO-AGENT HANDOVER</small><strong>Work and<br>decision evidence</strong></figcaption>
        </figure>
        <section class="executive-knowledge-path">
          <article><b>01</b><small>CAPTURE</small><strong>Human-resolved case</strong><span>Preserve the runbook, evidence, decision, and actual outcome as one case</span></article>
          <i></i>
          <article><b>02</b><small>PROPOSE</small><strong>Unvalidated knowledge candidate</strong><span>Norns (learning candidate proposer) agent proposes a candidate</span></article>
          <i></i>
          <article><b>03</b><small>REVIEW</small><strong>Rule quality review</strong><span>Mimir (rule reviewer) agent and a person review the evidence</span></article>
          <i></i>
          <article><b>04</b><small>REUSE</small><strong>Rule or validated reuse</strong><span>Resolve the same event faster at T0 or T1 thereafter</span></article>
        </section>
      </div>
      <aside class="executive-forecast-lane"><small>FORECAST</small><strong>History + time + dependencies</strong><i></i><span>Anticipate capacity, certificate, budget, and recovery risks.</span><b>Insufficient evidence: hold and report outcomes and proposals to the operator.</b></aside>`,
  },
  {
    eyebrow: "07 / ADOPTION DECISION TREE",
    title: "Four readiness areas define the starting scope and improvement plan",
    lead: "Assess IaC, operational data, standard procedures, and execution safeguards together. Start ready areas in observation mode and turn the rest into an action plan.",
    layout: "executive-readiness",
    content: `
      <div class="executive-readiness-tree" role="img" aria-label="A flow that checks IaC, trusted operational data, standard procedures and completion criteria, and execution safeguards to define the observation-mode starting scope and readiness plan">
        <article><small>CONDITION 01</small><strong>Can the change path be<br>reviewed and reproduced?</strong><span>IaC or GitOps baseline</span><b>Ready / next condition</b><em>Preparation needed<br>Plan IaC transition with FDAI</em></article>
        <i></i>
        <article><small>CONDITION 02</small><strong>Can state, relationships, and<br>observability data be trusted?</strong><span>Scope, time, source, completeness</span><b>Ready / next condition</b><em>Preparation needed<br>Assess observability and ontology</em></article>
        <i></i>
        <article><small>CONDITION 03</small><strong>Are procedures and<br>completion criteria clear?</strong><span>Runbook, owner, measurement</span><b>Ready / next condition</b><em>Preparation needed<br>Establish procedures and baseline</em></article>
        <i></i>
        <article><small>CONDITION 04</small><strong>Can execution authority and<br>recovery paths be validated?</strong><span>Authority, dry run, recovery, audit</span><b>Ready / review observation mode</b><em>Preparation needed<br>Design execution safeguards</em></article>
        <i></i>
        <div class="executive-ready-outcome"><small>STARTING POINT</small><strong>Observation-mode starting scope</strong><span>Build a pilot plan after operator review</span></div>
      </div>
      <div class="executive-readiness-no-go">
        <strong>FDAI can also assess unready areas and create an improvement plan</strong>
        <span>Review actual changes only within scopes where required safeguards are validated.</span>
        <b>DIAGNOSE / PREPARE / VALIDATE</b>
      </div>`,
  },
  {
    eyebrow: "08 / EVIDENCE-LED ADOPTION",
    title: "Start one validation scenario in observation mode",
    lead: "Select one repeatable operational decision with a measurable effect. Compare FDAI's decision with current operational outcomes without making an actual change.",
    layout: "executive-adoption",
    content: `
      <div class="executive-pilot-criteria">
        <span><b>01</b><strong>IaC scope</strong><small>Change path is reviewable and reproducible</small></span>
        <span><b>02</b><strong>Repeatable event</strong><small>A current runbook and owner exist</small></span>
        <span><b>03</b><strong>Measurable effect</strong><small>Execution outcome can be observed independently</small></span>
        <span><b>04</b><strong>Safe recovery</strong><small>Stop, rollback, and blast radius are explicit</small></span>
      </div>
      <div class="executive-adoption-path">
        <article><span>01</span><small>REGISTER</small><strong>Scope, owner, safeguards</strong><p>Define the scenario and authority ceiling.</p></article><i></i>
        <article><span>02</span><small>OBSERVE</small><strong>Decision</strong><p>Compare with actual human decisions.</p></article><i></i>
        <article><span>03</span><small>COMPARE</small><strong>Quality / safety comparison</strong><p>Measure accuracy and review load against the same event set.</p></article><i></i>
        <article><span>04</span><small>REVIEW</small><strong>Operator promotion review</strong><p>Review observation evidence and decide whether to execute.</p></article><i></i>
        <article class="enforce"><span>05</span><small>BOUNDED ENFORCEMENT</small><strong>Execute only approved scope</strong><p>Return immediately to observation mode on regression.</p></article>
      </div>
      <div class="executive-measures"><span>Decision accuracy</span><span>Human review rate</span><span>Policy violation count</span><span>Recovery procedure validation rate</span><span>Effect confirmation rate through independent observation</span></div>`,
  },
  {
    eyebrow: "09 / NEXT DECISION",
    title: "Start today by defining the first validation scope, not approving adoption",
    lead: "Review the first scenario's current baseline, data, authority, and execution safeguards together to build evidence for the next investment decision.",
    layout: "executive-decision",
    content: `
      <div class="executive-decision-layout">
        <div class="executive-decision-list">
          <div><span>01</span><strong>Name the sponsor and R&R</strong><p>Assign accountability for value, risk, data, and operational outcomes.</p></div>
          <div><span>02</span><strong>Select 1 validation scenario</strong><p>Choose a repeatable operational decision whose current effect can be measured.</p></div>
          <div><span>03</span><strong>Run a readiness and baseline workshop</strong><p>Review current time, review load, quality, and recovery paths together.</p></div>
        </div>
        <figure class="executive-decision-visual console-sign-in">
          <img src="assets/fdai-console-sign-in.png" alt="FDAI Console Entra ID sign-in screen centered against a space background">
          <figcaption class="console-sign-in-invitation"><strong>Begin the adoption review</strong></figcaption>
        </figure>
      </div>`,
  },
];
