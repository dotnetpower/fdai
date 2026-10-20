const source = (...paths) =>
  `<small class="l100-source" title="${paths.join(" · ")}">Sources: ${paths.join(" · ")}</small>`;

export const l100PitchDeckSlides = [
  {
    eyebrow: "MICROSOFT KOREA CSU · INTERNAL DEVELOPMENT",
    brandLogo: "assets/microsoft-logo.png",
    deckTitle: "FDAI L100 Pitch Deck",
    title: "From operational signals<br><em>to verified outcomes</em>",
    lead: `FDAI performs repeatable operational tasks based on organizational operating rules and information about the current state. People define the goals and execution authority, and FDAI verifies task outcomes through separate observation.
      <span class="l100-pitch-disclaimer">FDAI is not an official Microsoft product or Azure service. It is a solution being developed and validated internally by Microsoft Korea CSU.</span>`,
    layout: "cover deck-l100-pitch",
    content: `<figure class="l100-pitch-photo"><img src="assets/l100-pitch-deck.jpeg" alt="Pink and blue data particles flowing along several paths"><figcaption><span>RESILIENCE</span><span>CHANGE SAFETY</span><span>COST GOVERNANCE</span></figcaption></figure>`,
  },
  {
    eyebrow: "01 / PRODUCT IDENTITY",
    title: "FDAI connects operational signals to decisions, execution, and outcome verification",
    lead: "It is an autonomous cloud operations control plane that handles repeatable work using organizational operating rules and current state.",
    layout: "l100-pitch-body slide-l100-identity",
    content: `<section class="l100-visual l100-identity" aria-label="What FDAI is and is not">
      <article class="is"><span>WHAT FDAI DOES</span><strong>Connect operational signals<br>to verifiable outcomes</strong><div><b>Connect current state with service relationships</b><b>Apply organizational rules and policy first</b><b>Execute approved work and verify the actual effect</b></div></article>
      <article class="is-not"><span>PRODUCT STATUS</span><strong>An internal solution developed<br>by Microsoft Korea CSU</strong><div><b>Not an official Microsoft product or Azure service</b><b>Not covered by Microsoft product support or SLA</b><b>Support and update responsibilities are agreed before adoption</b></div></article>
      <p>People define the goals and execution authority, and FDAI acts only within the permitted scope</p>
    </section>${source("docs/roadmap/architecture/fdai-constitution.md")}`,
  },
  {
    eyebrow: "02 / OPERATING CHALLENGE",
    title: "Operational response slows while scattered information is connected into one decision",
    lead: "Operators must find logs and metrics, recent changes, service relationships, operating policies, and approval status across multiple tools, then evaluate them together.",
    layout: "l100-pitch-body slide-l100-challenge",
    content: `<section class="l100-visual l100-challenge" aria-label="Five stages operators connect manually">
      <article><b>01</b><strong>Signal</strong><span>Logs · metrics · alerts</span></article><i></i><article><b>02</b><strong>Impact</strong><span>Relations · SLO · deployment</span></article><i></i><article><b>03</b><strong>Decision</strong><span>Procedure · risk · approval</span></article><i></i><article><b>04</b><strong>Execution</strong><span>Change · recovery · rollback</span></article><i></i><article><b>05</b><strong>Verification</strong><span>State · recurrence · audit</span></article><div class="human"><span>OPERATOR</span><strong>Operators reconnect context at every handoff</strong></div>
    </section>${source("docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
  {
    eyebrow: "03 / CONNECTED OPERATIONS",
    title: "FDAI connects repeatable work across existing tools without replacing them",
    lead: "Each system remains authoritative for its own data, and FDAI uses only information the deployment is allowed to access.",
    layout: "l100-pitch-body slide-l100-connected",
    content: `<section class="l100-visual l100-connected" aria-label="Flow from sources through FDAI to outcomes">
      <article class="sources"><small>AUTHORITATIVE SOURCES</small><strong>Operational information</strong><span>Azure state</span><span>Logs and metrics</span><span>Service relations</span><span>Rules and Git changes</span></article><i></i>
      <article class="control"><small>FDAI CONTROL PLANE</small><strong>Connect decisions and work</strong><span>Identify target</span><span>Evaluate rules</span><span>Build plan</span><span>Check authority</span></article><i></i>
      <article class="outcomes"><small>GOVERNED OUTCOMES</small><strong>Operational outcome</strong><span>Proposal</span><span>Human approval</span><span>Permitted execution</span><span>Verification and recovery</span></article>
      <p>FDAI Console does not change customer resources. Only the isolated Executor performs approved work.</p>
    </section>${source(".github/instructions/app-shape.instructions.md", "docs/roadmap/deployment/deployment.md")}`,
  },
  {
    eyebrow: "04 / OPERATING DOMAINS",
    title: "One SRE operating model connects resilience, change safety, and cost governance",
    lead: "All three domains share the same service objectives, operational evidence, and authority boundaries.",
    layout: "l100-pitch-body slide-l100-domains",
    content: `<section class="l100-visual l100-domains" aria-label="Three FDAI operating domains"><div class="sre-core"><small>OPERATING MODEL</small><strong>SRE</strong><span>Objectives · risk · evidence · effects</span></div><article class="resilience"><b>01</b><strong>RESILIENCE</strong><span>Detect · recover · verify</span></article><article class="change"><b>02</b><strong>CHANGE SAFETY</strong><span>Impact · approve · roll back</span></article><article class="cost"><b>03</b><strong>COST GOVERNANCE</strong><span>Cost · capacity · safe optimization</span></article><p>FDAI's goal is not automation itself. It is less repetitive human intervention without losing safety or accountability.</p></section>${source("docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
  {
    eyebrow: "05 / A TYPICAL OPERATING QUESTION",
    title: "One operating question requires multiple authoritative sources and an execution-authority check",
    lead: "An error-rate increase alone cannot determine whether it is safe to roll back the latest deployment.",
    layout: "l100-pitch-body slide-l100-question",
    content: `<section class="l100-visual l100-question" aria-label="An operating question about rolling back a deployment"><div class="question-icon" aria-hidden="true">?</div><blockquote>Service errors have surged.<br>Should we roll back the latest deployment?</blockquote><div class="question-sources"><span>Service relations</span><span>Change history</span><span>Operating rules</span><span>Execution authority</span></div><p>Target, relation, time, evidence, authority, and expected effect must agree.</p></section>${source("docs/roadmap/decisioning/execution-model.md")}`,
  },
  {
    eyebrow: "06 / QUESTION DECOMPOSITION",
    title: "FDAI decomposes an operating question into target, relation, time, evidence, authority, and expected effect",
    lead: "Natural language conveys intent, but it never creates execution authority.",
    layout: "l100-pitch-body slide-l100-decomposition",
    content: `<section class="l100-visual l100-decomposition" aria-label="Operating question decomposed into six decision dimensions">
      <div class="callout target"><b>Target</b><span>Which service and revision?</span></div><div class="callout relation"><b>Relation</b><span>Which services are affected?</span></div><div class="callout time"><b>Time</b><span>When did errors begin?</span></div>
      <p class="annotated"><mark>Service</mark> <mark>errors have surged</mark>.<br>Should we <mark>roll back</mark> the <mark>latest deployment</mark>?</p>
      <div class="callout evidence"><b>Evidence</b><span>Are observations current?</span></div><div class="callout authority"><b>Authority</b><span>Is rollback registered and approved?</span></div><div class="callout effect"><b>Expected effect</b><span>Which metric must recover?</span></div><p class="example-note">Illustrative example, not an actual customer outcome.</p>
    </section>${source("docs/roadmap/architecture/fdai-constitution.md", "docs/roadmap/decisioning/execution-model.md")}`,
  },
  {
    eyebrow: "07 / FDAI OPERATING ENGINE",
    title: "FDAI connects an operating question to a grounded decision and verified work",
    lead: "Every stage checks the evidence and authority established by the previous stage and stops when a required condition is not met.",
    layout: "l100-pitch-body slide-l100-engine",
    content: `<section class="l100-visual l100-engine-v2" aria-label="FDAI operating engine that grounds an operating question, decides, authorizes, executes, and independently verifies the effect">
      <div class="engine-sources"><span>Operating ontology</span><span>Current observations</span><span>Rule Catalog</span><span>Verified cases</span></div>
      <div class="engine-grounding" aria-hidden="true"><i></i><b>GROUNDED CONTEXT</b><i></i></div>
      <div class="engine-flow">
        <article class="engine-input"><small>INPUT</small><strong>Error surge</strong><span>Roll back the latest deployment?</span></article>
        <i class="engine-arrow" aria-hidden="true"></i>
        <div class="engine-core">
          <header><small>FDAI OPERATING ENGINE</small><strong>Pin evidence and authority at every stage</strong></header>
          <ol>
            <li><b>01</b><strong>Ground</strong><span>Target · relation · time</span></li>
            <li><b>02</b><strong>Decide</strong><span>Rule · tier · risk</span></li>
            <li><b>03</b><strong>Authorize</strong><span>Approval · scope · safeguards</span></li>
            <li><b>04</b><strong>Execute</strong><span>Lock · idempotency · audit</span></li>
          </ol>
        </div>
        <i class="engine-arrow" aria-hidden="true"></i>
        <article class="engine-output"><small>GOVERNED OUTCOME</small><strong>Authorized rollback</strong><span>or hold · deny · human review</span></article>
      </div>
      <div class="engine-verification"><strong>Independent effect verification</strong><span>Pre-action baseline</span><i></i><span>Separate observation</span><i></i><span>Error rate recovered</span><i></i><b>Complete or roll back</b></div>
    </section>${source("docs/roadmap/architecture/fdai-constitution.md", "docs/roadmap/agents/agent-pantheon.md")}`,
  },
  {
    eyebrow: "08 / SEMANTIC OPERATING CONTEXT",
    title: "Semantic search connects a question to typed targets and relations in the operating ontology",
    lead: "Agents use those structured targets and relations to retrieve only the operational information they need.",
    layout: "l100-pitch-body slide-l100-semantic",
    content: `<section class="l100-visual l100-semantic-v2" aria-label="Agents map an operating question into typed semantic search, bind it to ontology, rules, and cases, and receive bounded context, decisions, and action contracts">
      <article class="semantic-agents"><small>ACCOUNTABLE</small><b>15</b><strong>AGENTS</strong><span>Ask · observe · decide · execute</span></article>
      <i class="semantic-arrow" aria-hidden="true"></i>
      <div class="semantic-mapper"><small>SEMANTIC SEARCH</small><strong>Map language to types</strong><div><span>Intent</span><span>Target</span><span>Relation</span><span>Time</span><span>Evidence</span><span>ActionType</span></div></div>
      <i class="semantic-arrow" aria-hidden="true"></i>
      <div class="semantic-knowledge"><div class="ontology-hub"><small>SHARED MEANING</small><strong>Operating ontology</strong><span>Resource · service · objective · dependency</span></div><div class="knowledge-pair"><span>Rule Catalog</span><span>Verified cases</span></div></div>
      <i class="semantic-arrow" aria-hidden="true"></i>
      <div class="semantic-outputs"><article><small>CONTEXT</small><strong>Current state</strong><span>Relation · time · freshness</span></article><article><small>DECISION</small><strong>Permitted scope</strong><span>Rule · risk · approval</span></article><article><small>ACTION</small><strong>Action contract</strong><span>Effect · recovery · verification</span></article></div>
      <p>Semantic search structures meaning. The ontology never creates authority.</p>
    </section>${source("docs/roadmap/architecture/operating-ontology-platform.md", "docs/roadmap/agents/agent-pantheon.md")}`,
  },
  {
    eyebrow: "09 / DECISION EFFORT",
    title: "FDAI selects T0, T1, or T2 based on the judgment required",
    lead: "It uses the lowest tier sufficient for a decision to reduce cost and latency.",
    layout: "l100-pitch-body slide-l100-tier-selector",
    content: `<section class="l100-visual l100-tier-selector" aria-label="T0, T1, and T2 decision effort"><aside><strong>Decision<br>Reasoning<br>Effort</strong><p>Start with deterministic rules. Use AI only for residual ambiguity.</p></aside><div class="levels"><article class="t0"><b>T0</b><strong>Rules and policy</strong><span>Lowest cost · predictable · no model</span></article><article class="t1"><b>T1</b><strong>Verified reuse</strong><span>Similar case · low cost · evidence match</span></article><article class="t2"><b>T2</b><strong>Grounded reasoning</strong><span>Novel case · multiple models · deterministic verification</span></article></div><p>A model response never authorizes execution. Tier shares are targets to measure, not current results.</p></section>${source("docs/roadmap/architecture/llm-strategy.md", "docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
  {
    eyebrow: "10 / DETERMINISTIC OPERATION",
    title: "Repeatable situations run deterministically without using an LLM",
    lead: "The same structured event and policy receive the same decision.",
    layout: "l100-pitch-body slide-l100-deterministic",
    content: `<section class="l100-visual l100-deterministic" aria-label="T0 deterministic decision flow"><div class="intent"><small>STRUCTURED EVENT</small><strong>Error threshold exceeded</strong><span>Target · revision · time · metric</span></div><div class="definitions"><small>GOVERNED DEFINITIONS</small><article><b>Rule</b><span>Decision condition</span></article><article><b>Policy</b><span>Risk and approval</span></article><article><b>ActionType</b><span>Work and safeguards</span></article></div><i></i><div class="engine"><small>T0</small><strong>Deterministic engine</strong><span>Schema · policy · dry run</span></div><i></i><div class="receipt"><small>TYPED OUTCOME</small><strong>Same input = same decision</strong><span>Verdict · ceiling · audit receipt</span></div><p>Missing evidence never becomes a guess. FDAI holds, denies, or moves to the next tier.</p></section>${source("docs/roadmap/decisioning/execution-model.md", "docs/roadmap/architecture/llm-strategy.md")}`,
  },
  {
    eyebrow: "11 / AGENT KNOWLEDGE BASE",
    title: "Agents query policy, ontology, and verified cases through one knowledge base",
    lead: "The knowledge base fixes each operating domain's retrieval scope, information sources, and synthesis behavior.",
    layout: "l100-pitch-body slide-l100-knowledge",
    content: `<section class="l100-visual l100-knowledge" aria-label="Agent knowledge base structure"><aside><small>KNOWLEDGE DOMAIN</small><strong>One governed entry point</strong><span>Retrieval scope</span><span>Knowledge sources</span><span>Synthesis behavior</span><span>Grounding and citations</span></aside><div class="kb"><header><strong>AGENT KNOWLEDGE BASE</strong></header><div class="sources"><article><b>INDEXED</b><span>Rule Catalog</span><span>Case history</span><span>Document index</span></article><article><b>FEDERATED</b><span>Operating ontology</span><span>Current observations</span><span>Authoritative sources</span></article></div><div class="indexes"><span>Vector index</span><span>Lexical index</span><span>Typed query</span></div><div class="guard"><b>Policy · source · freshness · authority</b></div></div><div class="agent-output"><strong>AGENTS</strong><span>Retrieve only what is needed</span></div><p>Retrieved knowledge informs a decision. It never grants approval or execution authority.</p></section>${source("docs/roadmap/architecture/operating-ontology-platform.md", "docs/roadmap/rules-and-detection/prediction-learning-and-case-history.md")}`,
  },
  {
    eyebrow: "12 / OPERATING ONTOLOGY",
    title: "The operating ontology connects resources, services, objectives, and actions",
    lead: "Agents query typed operating relationships instead of comparing strings alone.",
    layout: "l100-pitch-body slide-l100-ontology-graph",
    content: `<section class="l100-visual l100-ontology-graph-v2" aria-label="Operating ontology graph connecting change, service, resource, evidence, SLO, ActionType, and expected effect">
      <aside><small>SEMANTIC QUERY</small><strong>Did the latest deployment<br>contribute to the<br>error surge?</strong><span>Bind target and time as typed scope</span></aside>
      <i class="ontology-query-arrow" aria-hidden="true"></i>
      <svg class="l100-ontology-svg" viewBox="0 0 920 350" role="img" aria-label="Change affects Service. Service depends on Resource and is measured by SLO. Resource is observed by Evidence. ActionType targets Resource and expects an Expected Effect.">
        <defs><marker id="ontology-arrow-en" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>
        <g class="ontology-links" marker-end="url(#ontology-arrow-en)"><path d="M 190 92 H 300"></path><path d="M 490 92 H 590"></path><path d="M 700 122 V 135 H 797 V 145"></path><path d="M 300 115 C 250 160 230 258 190 258"></path><path d="M 395 230 C 450 175 540 150 590 105"></path><path d="M 490 258 H 590"></path></g>
        <foreignObject class="ontology-edge-label" x="200" y="50" width="90" height="28"><div xmlns="http://www.w3.org/1999/xhtml">affects</div></foreignObject><foreignObject class="ontology-edge-label" x="490" y="50" width="110" height="28"><div xmlns="http://www.w3.org/1999/xhtml">depends on</div></foreignObject><foreignObject class="ontology-edge-label" x="735" y="92" width="135" height="28"><div xmlns="http://www.w3.org/1999/xhtml">observed by</div></foreignObject><foreignObject class="ontology-edge-label" x="172" y="165" width="118" height="28"><div xmlns="http://www.w3.org/1999/xhtml">measured by</div></foreignObject><foreignObject class="ontology-edge-label" x="440" y="138" width="90" height="28"><div xmlns="http://www.w3.org/1999/xhtml">targets</div></foreignObject><foreignObject class="ontology-edge-label" x="500" y="218" width="80" height="28"><div xmlns="http://www.w3.org/1999/xhtml">expects</div></foreignObject>
        <foreignObject class="ontology-node change-node" x="40" y="62" width="150" height="60"><div xmlns="http://www.w3.org/1999/xhtml">Change</div></foreignObject><foreignObject class="ontology-node service-node" x="300" y="62" width="190" height="60"><div xmlns="http://www.w3.org/1999/xhtml">Service</div></foreignObject><foreignObject class="ontology-node resource-node" x="590" y="62" width="140" height="60"><div xmlns="http://www.w3.org/1999/xhtml">Resource</div></foreignObject><foreignObject class="ontology-node evidence-node" x="700" y="145" width="194" height="55"><div xmlns="http://www.w3.org/1999/xhtml">Evidence</div></foreignObject><foreignObject class="ontology-node slo-node" x="40" y="230" width="150" height="55"><div xmlns="http://www.w3.org/1999/xhtml">SLO</div></foreignObject><foreignObject class="ontology-node action-node" x="300" y="230" width="190" height="55"><div xmlns="http://www.w3.org/1999/xhtml">ActionType</div></foreignObject><foreignObject class="ontology-node effect-node" x="590" y="230" width="230" height="55"><div xmlns="http://www.w3.org/1999/xhtml">Expected Effect</div></foreignObject>
        <foreignObject class="ontology-legend observed" x="55" y="305" width="160" height="34"><div xmlns="http://www.w3.org/1999/xhtml"><i></i><span>Observed state</span></div></foreignObject><foreignObject class="ontology-legend governed" x="215" y="305" width="160" height="34"><div xmlns="http://www.w3.org/1999/xhtml"><i></i><span>Policy and action</span></div></foreignObject><foreignObject class="ontology-legend desired" x="375" y="305" width="180" height="34"><div xmlns="http://www.w3.org/1999/xhtml"><i></i><span>Objective and effect</span></div></foreignObject>
      </svg>
      <p>FDAI checks direction, effective time, source, and freshness. The ontology never grants authority.</p>
    </section>${source("docs/roadmap/architecture/operating-ontology-platform.md", "docs/roadmap/architecture/fdai-constitution.md")}`,
  },
  {
    eyebrow: "13 / AZURE DEPLOYMENT",
    title: "FDAI deploys its operations control plane inside the customer's Azure subscription",
    lead: "Operational data, network paths, service identities, and audit records stay within the Azure region and policy boundary selected by the customer.",
    layout: "l100-pitch-body slide-l100-azure",
    content: `<section class="l100-visual l100-azure" aria-label="Core and optional Azure resources used by FDAI"><header><small>CUSTOMER AZURE SUBSCRIPTION</small><strong>An Azure boundary owned and controlled by the customer</strong></header><div class="layers"><article><small>COMPUTE</small><strong>Azure Kubernetes Service</strong><span>Core · Operator · Ingestion · Worker · Executor</span></article><article><small>CONTROL DATA</small><strong>Event Hubs + PostgreSQL</strong><span>Events · state · audit · KPIs · pgvector</span></article><article><small>TRUST + OBSERVABILITY</small><strong>Key Vault + Managed Identity</strong><span>ACR · Log Analytics · Application Insights · VNet</span></article></div><div class="optional"><small>OPTIONAL</small><span>Static Web Apps + Entra ID</span><span>Azure OpenAI + Foundry</span><span>ADLS Gen2 + Document Intelligence</span><span>Blob Storage</span><span>Private Endpoints</span><span>Teams or Bot</span></div><p>These are Azure services used by FDAI. FDAI itself is not an official Microsoft product or Azure service.</p></section>${source("docs/roadmap/deployment/deploy-and-onboard.md", "docs/roadmap/deployment/deployment.md")}`,
  },
  {
    eyebrow: "14 / ADOPTION DECISION",
    title: "Choose the first validation workflow and accountable owners",
    lead: "The first step does not approve adoption or autonomous execution. It aligns on the problem and exit criteria for shadow validation.",
    layout: "l100-pitch-body slide-l100-adoption",
    content: `<section class="l100-visual l100-adoption" aria-label="FDAI readiness and first validation path"><ol><li><b>01</b><strong>Scope</strong><span>Workflow · target · exclusions</span></li><li><b>02</b><strong>Owners</strong><span>Service · operations · approval · review</span></li><li><b>03</b><strong>Evidence</strong><span>Inventory · observations · changes · policy</span></li><li><b>04</b><strong>Baseline</strong><span>Window · success · guard metrics</span></li><li><b>05</b><strong>Azure</strong><span>Region · quota · network · cost</span></li><li><b>06</b><strong>Exit criteria</strong><span>Shadow result · review date</span></li></ol><div class="path"><span>Align scope</span><i></i><span>Azure preflight</span><i></i><span>Deploy</span><i></i><span>Shadow mode</span><i></i><span>Compare baseline</span><i></i><span>Review promotion</span></div><aside><small>FIRST DELIVERABLE</small><strong>One-page validation charter</strong><span>Owners · baseline · sources · exclusions · exit criteria</span></aside><p>FDAI is an internal Microsoft Korea CSU solution, not an official Microsoft product or Azure service.</p></section>${source("docs/roadmap/deployment/deploy-and-onboard.md", "docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
];
