import { slide, entry, flow, table, sources as s } from "./ontology-slide-kit.en.js";

function agentPort(role, name, description) {
  return `<article class="oe-agent-port" data-agent="${name}"><small>${role}</small><strong>${name}</strong><p>${description}</p><i class="oe-bus-connector" aria-hidden="true"></i></article>`;
}

/** Slides 29-40: bounded questions, agent responsibility, effects, and adoption. */
export function operationSlides() {
  return [
    slide({
      state: "ILLUSTRATIVE", chapter: "28 / A BOUNDED QUESTION", layout: "objectset-worked",
      title: "ObjectSet makes the question's scope and limits explicit",
      lead: "Example: Which data services does this Workload depend on? Fields fix the target, relationship, depth, and limit.",
      body: `<div class="oe-bounded-query"><figure class="oe-query-diagram"><figcaption><span>depends_on / outgoing / depth 1</span><span>Inside dashed line: returned targets</span></figcaption>
        <svg class="oe-inline-diagram" viewBox="0 0 780 314" role="img" aria-label="Example query: Traversing the depends_on relationship one level from the Workload root returns Database and Cache. The dashed line marks the returned scope.">
          <defs><marker id="oe-query-direction" viewBox="0 0 8 8" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L8 4L0 8Z"/></marker></defs>
          <rect class="oe-query-scope" x="456" y="1" width="316" height="312" rx="12"/>
          <path class="oe-query-edge" data-diagram-edge="database" data-from="root" data-to="database" d="M250 133H372V64H494"/>
          <path class="oe-query-edge" data-diagram-edge="cache" data-from="root" data-to="cache" d="M250 181H372V250H494"/>
          <g class="oe-query-node"><rect data-diagram-node="root" x="18" y="109" width="232" height="96" rx="6"/><text class="oe-diagram-label" x="134" y="150" text-anchor="middle">Workload</text><text class="oe-diagram-detail" x="134" y="182" text-anchor="middle">Root / ObjectRef</text></g>
          <g class="oe-query-node"><rect data-diagram-node="database" x="494" y="18" width="244" height="92" rx="6"/><text class="oe-diagram-label" x="616" y="59" text-anchor="middle">Database</text><text class="oe-diagram-detail" x="616" y="89" text-anchor="middle">Returned target</text></g>
          <g class="oe-query-node"><rect data-diagram-node="cache" x="494" y="204" width="244" height="92" rx="6"/><text class="oe-diagram-label" x="616" y="245" text-anchor="middle">Cache</text><text class="oe-diagram-detail" x="616" y="275" text-anchor="middle">Returned target</text></g>
        </svg></figure><aside class="oe-bounded-receipt"><small>Illustrative query receipt</small><strong>2<span> targets</span></strong><dl><div><dt>Return limit</dt><dd>Up to 100</dd></div><div><dt>Time and interpretation</dt><dd>Current cutoff / exact release</dd></div><div><dt>Query completeness</dt><dd>Not truncated</dd></div></dl><p>Read evidence only.<br>No execution authority.</p></aside></div>`,
      takeaway: "ObjectSet results are scoped read evidence. The presence of returned objects does not establish cause or execution eligibility.",
      evidence: [s.platform, s.structural],
    }),
    slide({
      state: "ILLUSTRATIVE", chapter: "29 / COMPLETENESS", layout: "completeness-tree",
      title: "Check completeness before claiming there are no results",
      lead: "An empty result supports absence only when the requested scope was checked completely. For truncated results, inspect the reason first.",
      body: `${table(["Query result state", "Meaning", "Next action"], [
        ["Not truncated", "Requested scope completed", "If 0, assess absence within that scope"],
        ["RESULT_LIMIT", "Return count limit reached", "Adjust the permitted limit or split the query"],
        ["CANDIDATE_LIMIT", "Only some pre-filter candidates checked", "Narrow the conditions and query again"],
        ["TRAVERSAL_LIMIT", "Only part of the relationship graph checked", "Narrow the root, depth, and scope"],
      ])}<div class="oe-receipt-line"><code>ObjectSetMaterialization</code><span>truncated + truncation_reason</span><small>Truncation markers in the actual contract</small></div>`,
      takeaway: "Even a complete query cannot prove absence if the observation source is incomplete. Check both scope and source evidence.",
      evidence: [s.platform, s.constitution],
    }),
    slide({
      state: "CURRENT", chapter: "30 / ACCOUNTABLE AGENTS", layout: "agent-swimlane",
      title: "Agents share meaning and collaborate through distinct responsibilities",
      lead: "This conceptual view shows key roles. Agents publish and subscribe to validated events instead of calling one another directly.",
      body: `<div class="oe-agent-system oe-pubsub-map" role="group" aria-label="Key agents connect independently to the event bus. The layout does not represent direct agent calls or execution order."><div class="oe-pubsub-top">${agentPort("Collection", "Huginn", "Publishes changes and correlations")}${agentPort("Context", "Muninn", "Supplies snapshots and expert evidence")}${agentPort("Decision", "Forseti", "Assembles required evidence and decides")}</div>
        <div class="oe-pubsub-bus" data-diagram-bus><strong>Event bus</strong><span>Schema-validated publish and subscribe / pub/sub</span></div>
        <div class="oe-pubsub-bottom">${agentPort("Human approval", "Var", "Validates required approvals")}${agentPort("Execution", "Thor", "Executes eligible actions only")}${agentPort("Independent observation", "Heimdall", "Confirms actual effects")}${agentPort("Audit", "Saga", "Records evidence and action lineage")}</div></div>`,
      takeaway: "Placement is not execution order. Approval, execution, and observation remain separate, with no direct calls, shared mutable state, or self-approval.",
      evidence: [s.agentLoop, s.constitution],
    }),
    slide({
      state: "BOUNDARY", chapter: "31 / MEANING IS NOT PERMISSION", layout: "authority-wall",
      title: "Accurate meaning does not create execution authority",
      lead: "After semantic validation, policy, risk, required human approval, and execution safeguards still apply independently.",
      body: `<div class="oe-split oe-narrow-left"><blockquote class="oe-statement"><small>Boundary that cannot be crossed</small><strong>Meaning<br><em>!=</em><br>Authority</strong></blockquote>
        <div class="oe-stack">${entry("Policy and risk", "Is this action eligible now?", "Review allowed actions, blast radius, and recoverability.")}${entry("Human approval", "Is the required approval valid?", "Validate role, quorum, and expiry while keeping approver and executor separate.")}${entry("Execution", "Are all seven safeguards satisfied?", "Stop condition, tested rollback, blast-radius limit, successful dry-run, target lock, idempotency key, and 2-phase audit")}</div></div>`,
      takeaway: "Only the Thor agent executes eligible actions. Command acceptance is not success; the Heimdall agent must observe the effect independently.",
      evidence: [s.constitution, s.platform, s.action],
    }),
    slide({
      state: "CURRENT", chapter: "32 / ACTION AND EFFECT", layout: "effect-lifecycle",
      title: "Record selection, execution attempt, and actual effect separately",
      lead: "Making a decision, sending a command, and confirming the intended effect are distinct facts.",
      body: `${flow([["Decision / Forseti", "Selected alternative", "DecisionCase reviews<br>ActionOption"], ["Execution / Thor", "Execution attempt", "Record ActionRun from an<br>eligible MutationPlan"], ["Observation / Heimdall", "Actual effect", "Compare ExpectedEffect<br>with ObservedOutcome"]])}
        <div class="oe-effect-records"><span><code>ActionOption</code> expects <code>ExpectedEffect</code></span><span><code>ActionRun</code> resulted_in <code>ObservedOutcome</code></span></div>`,
      takeaway: "Do not collapse execution failure, effect mismatch, or unavailable observation into success. Recovery proposals return through policy and approval.",
      evidence: [s.ontology, s.platform, s.action],
    }),
    slide({
      state: "CURRENT", chapter: "33 / INDEPENDENT VERIFICATION", layout: "reconciliation-loop",
      title: "Effect verification needs states beyond success",
      lead: "An authoritative observer independent of the executor compares expected and actual effects. Insufficient evidence remains distinct from closure.",
      body: `<div class="oe-reconciliation-split"><div class="oe-closed-outcomes"><small>Three states that close the comparison</small><ol><li data-result-state="MATCHED" data-closure="terminal"><div><code>MATCHED</code><strong>Expected scope confirmed</strong></div><p>Confirm effect and<br>record closure evidence</p></li><li data-result-state="MISMATCHED" data-closure="terminal"><div><code>MISMATCHED</code><strong>Expected and actual differ</strong></div><p>Propose recovery review<br>without execution authority</p></li><li data-result-state="TIMED_OUT" data-closure="terminal"><div><code>TIMED_OUT</code><strong>Observation window closed</strong></div><p>Review recovery<br>without claiming success</p></li></ol></div>
        <aside class="oe-open-outcome" data-result-state="UNSCORABLE" data-closure="pending"><small>Insufficient observation evidence / open</small><strong>Decision on hold</strong><code>UNSCORABLE</code><p>Record this attempt only,<br>then await new trusted evidence.</p><span>Re-evaluate when new observations arrive</span></aside></div>`,
      takeaway: "API or broker acceptance is not effect evidence. A recovery request is a proposal and does not automatically approve another execution.",
      evidence: [s.platform, s.constitution],
    }),
    slide({
      state: "ILLUSTRATIVE", chapter: "34 / CHANGE SAFETY", layout: "scenario-change",
      title: "Assess change impact through service relationships",
      lead: "Example: Change the database tier for a payment workload. What is affected, and which objectives must remain protected?",
      body: `<div class="oe-change-graph" role="img" aria-label="A service is implemented by a workload, and the workload depends on a database"><div class="oe-relation-node"><small>Business scope</small><strong>BusinessService</strong></div><div class="oe-labeled-edge"><span>implemented_by</span><i class="oe-edge" aria-hidden="true"></i></div><div class="oe-relation-node"><small>Operational unit</small><strong>Workload</strong></div><div class="oe-labeled-edge"><span>depends_on</span><i class="oe-edge" aria-hidden="true"></i></div><div class="oe-relation-node"><small>Example change target</small><strong>Database</strong></div></div>
        <div class="oe-three">${entry("Objective", "What must be protected?", "SLO, recovery objective, and allowed change window")}${entry("Evidence", "Is it still current?", "Current topology, change revision, and backup evidence")}${entry("Safety", "Can failure be reversed?", "Recovery plan, successful dry-run, and required approvals")}</div>`,
      takeaway: "Bind the exact change and evidence to the DecisionCase. Do not execute with stale evidence or a failed dry-run.",
      evidence: [s.agentLoop, s.ontology, s.action],
    }),
    slide({
      state: "ILLUSTRATIVE", chapter: "35 / INCIDENT ANALYSIS", layout: "scenario-incident",
      title: "Anomalies at the same time do not prove the same cause",
      lead: "Example: API latency and DB throttling appear after deployment. Sequence narrows candidates but does not establish cause.",
      body: `<ol class="oe-incident-timeline"><li><time>10:01</time><strong>Deployment</strong></li><li><time>10:04</time><strong>API latency</strong></li><li><time>10:05</time><strong>DB throttle</strong></li><li><time>10:09</time><strong>Additional observation</strong></li></ol>
        ${table(["Cause candidate", "Observation that distinguishes the hypothesis"], [
          ["H1 / Deployment regression", "Latency difference between prior and current revisions under the same load"],
          ["H2 / DB capacity limit", "Effective time for saturation, quota metrics, and throttling"],
          ["H3 / Storage latency", "Storage observations and request traces from the same interval"],
        ])}`,
      takeaway: "Forseti compares hypotheses using evidence from Heimdall. If distinguishing evidence is insufficient or conflicting, the cause is unknown.",
      evidence: [s.ontology, s.platform, s.constitution],
    }),
    slide({
      state: "ILLUSTRATIVE", chapter: "36 / COST GOVERNANCE", layout: "scenario-cost",
      title: "Compare savings and SLO protection in one decision",
      lead: "Example: Downsize an underused VM by one tier. Evaluate capacity headroom and recoverability alongside cost.",
      body: `<div class="oe-cost-options"><article><small>OPTION A</small><strong>Keep current size</strong><p>Preserve current cost and<br>capacity headroom as the no-action baseline</p></article><article><small>OPTION B</small><strong>Downsize one tier</strong><p>Expect savings, but<br>capacity headroom may decrease</p></article></div>
        <div class="oe-three oe-cost-criteria">${entry("Cost objective", "Will savings materialize?", "Compare CostObjective with observed cost")}${entry("Service objective", "Will the SLO remain protected?", "Confirm under the same load and observation window")}${entry("Recovery objective", "Can problems be reversed?", "Tested recovery and limited blast radius")}</div>`,
      takeaway: "Review cost and capacity evidence from the Njord and Freyr agents. Propose in shadow mode first, and hold when objectives conflict or evidence is insufficient.",
      evidence: [s.ontology, s.constitution, s.action],
    }),
    slide({
      state: "BOUNDARY", chapter: "37 / LEARNING WITHOUT SELF-PROMOTION", layout: "learning-flywheel",
      title: "Learning creates proposals; review determines adoption",
      lead: "Reading documents and operational outcomes does not immediately change the active ontology or execution authority.",
      body: `<div class="oe-learning-paths"><div><small>Extract meaning from documents</small>${flow([["Input", "Document", "Object, relationship, and property candidates"], ["Proposal", "Semantic change", "OntologyChangeProposal"], ["Separate review", "OntologyRelease", "Check sources, conflicts, and compatibility"]])}</div><div><small>Learn from sealed operational cases</small>${flow([["Input", "Operational case set", "Success, failure, hold, and recovery"], ["Proposal", "Inactive rule", "RuleCandidate"], ["Separate review", "Rule catalog", "Check replay and shadow-mode evidence"]])}</div></div>`,
      takeaway: "Learning proposals from Norns and rule reviews from Mimir remain separate from execution promotion. Learning never raises execution authority automatically.",
      evidence: [s.distillation, s.learning, s.constitution],
    }),
    slide({
      state: "GAP", chapter: "38 / IMPLEMENTATION AND EVIDENCE", layout: "status-roadmap",
      title: "Implementation and operational proof are different stages",
      lead: "When reading current design records, assess code presence, validation scope, and operational evidence separately.",
      body: table(["Evidence level", "Current scope and remaining proof", "Does not mean"], [
        ["Implemented foundation", "Exact release, type contracts, and bounded query", "Operational proof across every target and path"],
        ["Validation in progress", "End-to-end evidence for provider binding, history, and effect reconciliation", "Some passing tests mean complete delivery"],
        ["Separate design and delivery scope", "Action knowledge resolver, storage, and current operational receipts", "A design document makes the capability available"],
      ]) + `<div class="oe-inline-note"><strong>Deployment decisions require operational evidence for the exact revision.</strong><p>Validate hold, failure, and recovery scenarios as well as success.</p></div>`,
      takeaway: "Do not present partial implementation or limited validation as production completion of the full platform. Verify current status in each owning document and evidence record.",
      evidence: [s.platform, s.structural, s.behavior],
    }),
    slide({
      state: "DECISION", chapter: "39 / START WITH ONE QUESTION", layout: "adoption-checklist",
      title: "Start by validating one question end to end",
      lead: "Keep the scope small. Confirm that the answer can be replayed from the same meaning and evidence before expanding.",
      body: `<div class="oe-split"><blockquote class="oe-statement"><small>Example first question</small><strong>Which service objectives<br>does this change<br>affect?</strong></blockquote><ol class="oe-adoption-steps"><li><b>01</b><div><strong>Agree on scope</strong><p>Define exact targets, relationships, and sources with the service owner.</p></div></li><li><b>02</b><div><strong>Bind the evidence</strong><p>Record revision, cutoff, completeness, and acceptable unknowns.</p></div></li><li><b>03</b><div><strong>Verify by replay</strong><p>Compare expected answers with actual evidence and check for false authority claims.</p></div></li></ol></div>`,
      takeaway: "With sufficient evidence, expand the next question in shadow mode. Otherwise, strengthen the evidence; stop expansion when a safety boundary is violated.",
      evidence: [s.ontology, s.platform, s.constitution],
    }),
  ];
}
