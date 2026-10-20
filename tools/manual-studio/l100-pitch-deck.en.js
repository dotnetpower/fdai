import { pitchSlide, resourceGraph } from "./l100-pitch-kit.js";

const slide = data => pitchSlide("en", data);

export const l100PitchDeckSlides = [
  slide({
    id: "cover", chapter: "INTRODUCTION", kind: "cover", cover: true,
    title: "From operational signals<br><em>to verified outcomes</em>",
    lead: "Connect organizational rules with current state to reduce repeat work.<br>People set goals and authority. FDAI checks the actual effect of each task.",
    visual: `<div class="lp-cover-composition">
      <div class="lp-cover-message"><span class="lp-kicker">FDAI / AUTONOMOUS CLOUD OPERATIONS</span><strong>From gathering information<br>to safe decisions and action</strong><p>Resilience · Change Safety · Cost Governance</p></div>
      <figure class="lp-cover-photo"><img src="assets/l100-pitch-deck.jpeg" alt=""><figcaption>Rules first · Evidence grounded · Effect verified</figcaption></figure>
    </div>`,
    takeaway: "Developed and validated internally by Microsoft Korea CSU. FDAI is not an official Microsoft product or Azure service.",
    sources: ["constitution"],
  }),
  slide({
    id: "challenge", chapter: "01 / THE OPERATOR'S QUESTION", kind: "timeline", example: true,
    title: "Operators gather and reconcile scattered information",
    lead: "An error surge means checking logs, recent changes, service relations, and approval state across tools.",
    visual: `<blockquote class="lp-question">"API errors are rising. Check whether the latest deployment or the database<br>is responsible, and tell me what would allow a rollback."</blockquote>
      <ol class="lp-event-line"><li><b>Signal</b><span>Error logs and metrics</span></li><li><b>Context</b><span>Changes and dependencies</span></li><li><b>Decision</b><span>Impact and action conditions</span></li><li><b>Verification</b><span>Actual post-action state</span></li></ol>`,
    takeaway: "FDAI connects repeatable checks and decisions across existing tools rather than replacing those tools.",
    sources: ["constitution", "execution"],
  }),
  slide({
    id: "domains", chapter: "02 / FDAI'S ROLE", kind: "operating-map",
    title: "Connect resilience, change safety, and cost governance",
    lead: "FDAI is a control plane that coordinates operational decisions and action, using Site Reliability Engineering (SRE) as its operating model.",
    visual: `<dl class="lp-domain-list">
      <div><dt><span>01 / RESILIENCE</span><strong>Recover safely</strong></dt><dd>Detect problems and check that the service recovers after a recovery action.</dd></div>
      <div><dt><span>02 / CHANGE SAFETY</span><strong>Control change</strong></dt><dd>Review impact, approval conditions, and a recovery path together.</dd></div>
      <div><dt><span>03 / COST GOVERNANCE</span><strong>Manage cost</strong></dt><dd>Review cost and capacity without sacrificing service objectives.</dd></div>
    </dl><p class="lp-context-note">Connect existing observation, Git, and cloud tools. Agree on support and update ownership before adoption.</p>`,
    takeaway: "The goal is less repetitive human work while preserving safety and accountability, not automation for its own sake.",
    sources: ["constitution", "deployment"],
  }),
  slide({
    id: "knowledge", chapter: "03 / DISTINCT INFORMATION SOURCES", kind: "evidence-layers",
    title: "Documented intent is not the same as observed state",
    lead: "FDAI retains sources and reference times, distinguishing what each item can support.",
    visual: `<div class="lp-evidence-layers">
      <section><span class="lp-kicker">DESIGN INTENT</span><h3>Documents and guides</h3><p>Extract claims about objects and relations.<br>A change proposal needs review; it is not a current fact.</p></section>
      <section><span class="lp-kicker">CURRENT FACTS</span><h3>Inventory and observations</h3><p>Read resources and state; verify relations.<br>Check source, time, and missing information.</p></section>
      <section><span class="lp-kicker">PRIOR EXPERIENCE</span><h3>Investigations and cases</h3><p>Refer to earlier hypotheses and outcomes.<br>Check applicability to this target and situation.</p></section>
    </div>`,
    takeaway: "A document proposal or model-generated explanation is not a fact observed in the environment.",
    sources: ["documents", "graph"],
  }),
  slide({
    id: "ontology", chapter: "04 / SHARED MEANING", kind: "relationship", example: true,
    title: "An operating ontology gives targets and relations meaning",
    lead: "Define what an object is and what it depends on. Keep a type declaration distinct from an individual resource.",
    visual: resourceGraph("en"),
    takeaway: "A dependency identifies a possible impact path. Its existence alone does not establish the cause of an incident.",
    sources: ["ontology", "causality"],
  }),
  slide({
    id: "target", chapter: "05 / FROM QUESTION TO EXACT TARGET", kind: "verified-flow", example: true,
    title: "A similar name is not enough to select a target",
    lead: "Interpret the question, then verify the exact identity against current objects the principal is authorized to read.",
    visual: `<div class="lp-flow">
      <section data-lp-node="intent"><span class="lp-kicker">INTERPRET INTENT</span><h3>"Investigate API errors"</h3><p>Goal · target · time · constraints</p></section>
      <i class="lp-link" data-lp-from="intent" data-lp-to="plan" aria-hidden="true"></i>
      <section data-lp-node="plan"><span class="lp-kicker">VERIFY THE PLAN</span><h3>Allowed reads only</h3><p>Type · arguments · role · scope</p></section>
      <i class="lp-link" data-lp-from="plan" data-lp-to="object" aria-hidden="true"></i>
      <section data-lp-node="object"><span class="lp-kicker">READ CURRENT OBJECTS</span><h3>Exact target</h3><p>Identity · source · freshness</p></section>
    </div><p class="lp-context-note">Ask for clarification when names or scope are ambiguous. Candidate rank is neither fact verification nor action approval.</p>`,
    takeaway: "Language conveys intent. It does not expand access or execution authority.",
    sources: ["ontology", "constitution"],
  }),
  slide({
    id: "time", chapter: "06 / ONE TIME WINDOW", kind: "incident-timeline", example: true,
    title: "Compare changes and impact around the deployment",
    lead: "Use the same target and time window. Current topology cannot prove past relations when historical evidence is missing.",
    visual: `<div class="lp-time-board"><div class="lp-time-head"><span>Record to check</span><span>Before deployment</span><span>Deployment point</span><span>Error window</span></div>
      <div><strong>Change history</strong><span>Previous revision</span><span class="lp-focus">New revision</span><span>Target and config</span></div>
      <div><strong>API observations</strong><span>Baseline state</span><span>Request records</span><span class="lp-focus">Errors and latency</span></div>
      <div><strong>DB observations</strong><span>Baseline state</span><span>Find latency onset</span><span>Check persistence</span></div>
    </div>`,
    takeaway: "Temporal proximity alone does not make the deployment the cause. Missing evidence remains explicit.",
    sources: ["graph", "causality"],
  }),
  slide({
    id: "hypotheses", chapter: "07 / COMPETING HYPOTHESES", kind: "hypothesis-board", example: true,
    title: "Compare hypotheses before naming a cause",
    lead: "Find supporting and refuting evidence, then identify the next observation that distinguishes the hypotheses.",
    visual: `<table class="lp-table lp-hypotheses"><thead><tr><th>Possible cause</th><th>Evidence to inspect</th><th>Still unknown</th></tr></thead><tbody>
      <tr><th>Deployment regression</th><td>Changed target and error onset</td><td>Does the change explain the symptom?</td></tr>
      <tr><th>Database latency</th><td>Timing of DB latency and API requests</td><td>Did latency precede the errors?</td></tr>
      <tr><th>Shared dependency</th><td>Services using the same dependency</td><td>Are other services affected?</td></tr>
    </tbody></table><div class="lp-answer"><span class="lp-kicker">EXAMPLE ANSWER</span><p>"Current evidence does not establish the cause.<br>I will compare the deployment target with the onset of database latency."</p></div>`,
    takeaway: "Finding a related case is not the same as establishing the cause of this incident.",
    sources: ["causality"],
  }),
  slide({
    id: "tiers", chapter: "08 / PROPORTIONATE DECISION EFFORT", kind: "tier-comparison",
    title: "Apply rules first; reason only as far as needed",
    lead: "T0, T1, and T2 describe decision effort. At every tier, a model proposal alone cannot authorize execution.",
    visual: `<dl class="lp-tier-list">
      <div><dt>T0</dt><dd><h3>Rules and policy</h3><p>No model. The same verified inputs, policy version, and context produce the same decision.</p></dd></div>
      <div><dt>T1</dt><dd><h3>Verified reuse and lightweight judgment</h3><p>Use cases, patterns, and lightweight models. Deterministically verify proposed targets and intent.</p></dd></div>
      <div><dt>T2</dt><dd><h3>Deeper reasoning for residual ambiguity</h3><p>Ground reasoning in evidence, with distinct-model cross-checks and independent verification.</p></dd></div>
    </dl>`,
    takeaway: "Use the least effort sufficient for a decision. Reacquire evidence or hold judgment when support is insufficient.",
    sources: ["llm", "execution"],
  }),
  slide({
    id: "agents", chapter: "09 / SEPARATE RESPONSIBILITIES", kind: "ownership",
    title: "Agents own distinct roles and collaborate through events",
    lead: "The fixed 15-agent organization assigns accountability. These are role groups, not the complete organization chart.",
    visual: `<div class="lp-ownership"><div class="lp-event-bus"><span class="lp-kicker">SHARED COLLABORATION PATH</span><h3>Schema-validated events</h3><p>Owner · target · evidence · time</p></div>
      <dl><div><dt>Observe and retain</dt><dd>Check signals and relations; supply verified context.</dd></div><div><dt>Decide and explain</dt><dd>Review rules and risk; communicate the decision basis.</dd></div><div><dt>Approval and execution</dt><dd>Check valid human approval. The executor uses a separate identity.</dd></div><div><dt>Verify, recover, audit</dt><dd>Observe effects independently; retain outcomes and recovery history.</dd></div></dl>
    </div>`,
    takeaway: "An agent does not approve its own proposal. Shared knowledge is not shared execution authority.",
    sources: ["agents", "constitution"],
  }),
  slide({
    id: "authority", chapter: "10 / BEFORE EXECUTION", kind: "safeguards",
    title: "Execution requires authority and all safety conditions",
    lead: "Establishing a cause does not authorize an action. Check the approval and seven safeguards for each registered action.",
    visual: `<div class="lp-authority-band"><strong>Proposal</strong><span>Not authority</span><strong>Valid approval</strong><span>Recheck safeguards</span><strong>Isolated executor</strong></div>
      <ol class="lp-safeguards"><li>Machine-evaluable stop condition</li><li>Tested rollback or recovery</li><li>Impact scope and limit</li><li>Successful dry run</li><li>Exact logical-target lock</li><li>Stable deduplication key</li><li>Audit before and after effects</li></ol>`,
    takeaway: "Do not execute when a condition fails. FDAI can still diagnose the missing evidence and readiness requirements.",
    sources: ["constitution", "execution"],
  }),
  slide({
    id: "effect", chapter: "11 / ACTUAL TASK EFFECT", kind: "effect-verification", example: true,
    title: "Verify recovery, not just an accepted command",
    lead: "An accepted rollback request is not completion. Compare expected effects using an observation independent of the execution channel.",
    visual: `<div class="lp-effect-stages"><section><span class="lp-kicker">BEFORE ACTION</span><h3>Pin the baseline</h3><p>Exact target and revision<br>Error state and expected recovery</p></section><section><span class="lp-kicker">AUTHORIZED ACTION</span><h3>Perform the rollback</h3><p>Execution receipt and audit<br>Acceptance is not effect evidence</p></section><section><span class="lp-kicker">SEPARATE OBSERVATION</span><h3>Compare actual state</h3><p>Window, source, completeness<br>Check the expected recovery</p></section></div>
      <div class="lp-outcomes"><p><b>Recovery verified</b>Complete only when the expected effect is observed.</p><p><b>Recovery unverified</b>Do not report success. Follow the registered recovery contract or request human review.</p></div>`,
    takeaway: "Recovery does not automatically establish the cause. Retain causal-hypothesis verification separately.",
    sources: ["constitution", "causality"],
  }),
  slide({
    id: "status", chapter: "12 / IMPLEMENTATION AND VALIDATION", kind: "status-comparison",
    title: "Separate implemented, enabled, and live-validated",
    lead: "Code alone does not prove default availability or operational quality. Repository reference date: 2026-10-20.",
    visual: `<table class="lp-table lp-status"><thead><tr><th>Capability</th><th>Observed status</th><th>Check before adoption</th></tr></thead><tbody>
      <tr><th>Typed reads and plan checks</th><td>Implementation foundation exists</td><td>Actual data, roles, and source bindings</td></tr>
      <tr><th>Vector-ranked instance candidates</th><td>Disabled in the standard answer path</td><td>Separate activation and validation</td></tr>
      <tr><th>Document-derived relations</th><td>Change proposals for review</td><td>Active-graph admission integration</td></tr>
      <tr><th>Causal analysis and action effects</th><td>No live validation claimed</td><td>Validate the exact deployment scope</td></tr>
    </tbody></table><p class="lp-context-note">Natural-language interpretation differs from vector candidate search. This deck is not a live-validation report.</p>`,
    takeaway: "Check evidence and readiness per capability. Enabled configuration never grants execution authority.",
    sources: ["ontology", "indexRuntime", "documents", "causality"],
  }),
  slide({
    id: "azure", chapter: "13 / AZURE DEPLOYMENT BOUNDARIES", kind: "deployment",
    title: "Check Azure components and data-processing boundaries",
    lead: "Deploy in the customer's Azure subscription. Check each service's region, network, and identity.",
    visual: `<div class="lp-azure-boundary"><span class="lp-kicker">CUSTOMER-SELECTED AZURE SUBSCRIPTION / BASELINE</span>
      <dl><div><dt>Runtime services</dt><dd>Azure Kubernetes Service<br>Core · Operator · Ingestion · Worker · Executor</dd></div><div><dt>Events and state</dt><dd>Event Hubs · PostgreSQL<br>Events, service-owned state, and audit</dd></div><div><dt>Identity and observation</dt><dd>Key Vault · Managed Identity<br>Log Analytics · Application Insights</dd></div></dl>
    </div><p class="lp-context-note"><b>Optional scope</b> Configure Console, models, document processing, private connectivity, and Teams as needed. Console requires the applicable Entra ID authentication setup.</p>`,
    takeaway: "Deployment inside a subscription does not guarantee residency for every connection. Review processing locations for models, documents, Git, and other services.",
    sources: ["deployment", "constitution"],
  }),
  slide({
    id: "adoption", chapter: "14 / THE FIRST VALIDATION DECISION", kind: "adoption-worksheet", example: true,
    title: "Define the first observation scope and its owners",
    lead: "Start in observation mode without applying changes. Agree on exit criteria; completing observation does not authorize execution.",
    visual: `<div class="lp-worksheet"><div class="lp-sheet-heading"><span class="lp-kicker">FIRST VALIDATION SCOPE / EXAMPLE WORKSHEET</span><strong>Investigate API errors and inspect decision evidence</strong></div>
      <dl><div><dt>Target and exclusions</dt><dd>Owners define services, time windows, and excluded targets.</dd></div><div><dt>Owners and roles</dt><dd>Name the operational owner, approver, and reviewer.</dd></div><div><dt>Baseline and window</dt><dd>Agree on the current process and measurement period.</dd></div><div><dt>Safety and exit</dt><dd>No changes applied. Review evidence, hold reasons, and the next decision date.</dd></div></dl>
    </div>`,
    takeaway: "Continue observing, improve evidence, adjust scope, or review execution eligibility. Promotion and approval remain separate.",
    sources: ["constitution", "deployment"],
  }),
];
