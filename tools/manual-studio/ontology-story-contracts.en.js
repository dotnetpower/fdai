import { slide, entry, flow, table, sources as s } from "./ontology-slide-kit.en.js";

/** Slides 15-28: identity, time, evidence, and the semantic boundary. */
export function contractSlides() {
  return [
    slide({
      state: "ILLUSTRATIVE", chapter: "14 / PRIMITIVES", layout: "primitive-map",
      title: "Distinguish types from real objects",
      lead: "Separate classes, instances, properties, and relationships to validate each part of a question.",
      body: `<div class="oe-split"><aside class="oe-specimen"><small>Illustrative observation</small><strong>Resource<br>vm-01</strong><code>power_state = running</code><p>NIC-01 attached_to VM-01</p></aside>
        ${table(["Element", "Meaning to validate"], [
          ["Type / ResourceType", "Which properties and meanings are allowed"],
          ["Instance / Resource", "Which real object it identifies"],
          ["Property / power_state", "Whether the value type, unit, and range are valid"],
          ["Relationship / attached_to", "Whether its direction and endpoint types are valid"],
        ])}</div>`,
      takeaway: "A type declaration is not current state. Link identity, properties, and relationships to observations with time and provenance.",
      evidence: [s.ontology, s.structural],
    }),
    slide({
      state: "BOUNDARY", chapter: "15 / RELATIONSHIP DIRECTION", layout: "relation-compass",
      title: "Relationship direction does not imply cause",
      lead: "Storage direction, traversal direction, effective time, and causality carry distinct meanings on the same edge.",
      body: `<div class="oe-split oe-narrow-left"><div class="oe-vertical-relation" role="img" aria-label="Storage direction: Workload depends_on Database"><div class="oe-relation-node"><strong>Workload</strong></div><div class="oe-vertical-edge"><span>depends_on</span><i aria-hidden="true"></i></div><div class="oe-relation-node"><strong>Database</strong></div></div>
        ${table(["Aspect", "Interpretation"], [
          ["Storage", "Record from the dependent object toward the required object"],
          ["Traversal", "Choose outgoing or incoming when reading"],
          ["Time", "Preserve the interval when the relationship was valid with evidence"],
          ["Causality", "Do not infer cause from connection alone"],
        ])}</div>`,
      takeaway: "Reverse traversal does not change the stored edge. Distinguish correlation from causation with separate evidence.",
      evidence: [s.structural, s.metamodel],
    }),
    slide({
      state: "CURRENT", chapter: "16 / STABLE IDENTITY", layout: "identity-anchor",
      title: "Identity persists when a name changes",
      lead: "Preserve display names, object identifiers, and the ontology version used for interpretation separately.",
      body: `<div class="oe-identity"><div class="oe-name-change"><div><small>Example display name / yesterday</small><strong>payments-vm-01</strong></div><span aria-hidden="true">-&gt;</span><div><small>Example display name / today</small><strong>checkout-worker-a</strong></div></div>
        <div class="oe-identity-anchor"><small>Same object referenced by both names</small><strong>ObjectRef</strong><span>Exact provider identity + type_ref</span></div>
        <div class="oe-two">${entry("When provider identity differs", "Same name does not mean same object", "Check for a new object or a reviewed mapping.")}${entry("When semantic versions differ", "Recheck the exact release", "Stop interpretation and review compatibility on mismatch.")}</div></div>`,
      takeaway: "Replay requires both the object's ObjectRef and the OntologyRelease digest used for interpretation.",
      evidence: [s.ontology, s.platform],
    }),
    slide({
      state: "BOUNDARY", chapter: "17 / STATE AUTHORITY", layout: "authority-lanes",
      title: "Observation, interpretation, intent, and execution are different facts",
      lead: "States for the same object are not interchangeable when their authoritative sources and purposes differ.",
      body: table(["State domain", "What it describes", "Evidence owner"], [
        ["OBSERVED / observation", "Current power state reported by the provider", "External authoritative observation source"],
        ["DERIVED / interpretation", "A degraded assessment or capacity forecast", "Versioned function and input evidence"],
        ["DESIRED / intent", "Target state for SLO, budget, or policy", "Approved operating intent and configuration"],
        ["EXECUTION / execution", "Plan, command dispatch, and execution result", "Process and execution audit record"],
      ]),
      takeaway: "Command acceptance is not a recovery observation. Independent re-observation is required to establish the effect as an observed fact.",
      evidence: [s.ontology, s.metamodel, s.constitution],
    }),
    slide({
      state: "CURRENT", chapter: "18 / TIME & PROVENANCE", layout: "time-ribbon",
      title: "Arriving information may no longer be valid",
      lead: "Event, effective, recorded, and freshness times are not four sequential points. They answer four evidence questions.",
        body: `<div class="oe-time-reading">${table(["Time meaning", "Question to ask"], [
        ["event_time", "When did it happen?"], ["effective_time", "During which interval is it valid?"],
        ["recorded_time", "When was it accepted and recorded?"], ["fresh_until", "Until when can it be reused?"],
        ])}<figure class="oe-freshness-chart"><figcaption>Observation arriving after freshness expires / example</figcaption>
          <svg class="oe-inline-diagram" viewBox="0 0 760 260" role="img" aria-label="Evidence for an event at 10:00 expires at 10:05 and is recorded at 10:06. It cannot be reused when it arrives.">
            <path class="oe-fresh-window" d="M44 124H544"/><path class="oe-expired-window" d="M544 124H728"/>
            <text class="oe-diagram-detail" x="294" y="98" text-anchor="middle">Reusable interval</text>
            <circle class="oe-diagram-dot" cx="44" cy="124" r="5"/>
            <text class="oe-diagram-label" x="44" y="185">10:00</text><text class="oe-diagram-detail" x="44" y="218">Event occurs</text>
            <path class="oe-expiry-marker" d="M544 77V149"/>
            <text class="oe-diagram-label" x="544" y="30" text-anchor="middle">10:05</text><text class="oe-diagram-detail" x="544" y="62" text-anchor="middle">Freshness expires</text>
            <path class="oe-arrival-marker" d="M644 124V180"/><rect class="oe-diagram-dot" x="639" y="119" width="10" height="10"/>
            <text class="oe-diagram-label" x="644" y="209" text-anchor="middle">10:06</text><text class="oe-diagram-detail" x="644" y="242" text-anchor="middle">Observation recorded</text>
          </svg><p>The evidence is expired when it arrives.<br>Confirm current state with a new observation.</p>
        </figure></div>`,
      takeaway: "Preserve source, revision, completeness, and conflicts with time. Late evidence is a new revision and does not overwrite a past decision.",
      evidence: [s.ontology, s.governance, s.constitution],
    }),
    slide({
      state: "BOUNDARY", chapter: "19 / WORKING WITH UNKNOWN", layout: "unknown-spectrum",
      title: "An unknown result must guide the next action",
      lead: "Classifying what is missing enables bounded recovery and verification instead of speculation.",
      body: `<div class="oe-definition-grid">${entry("UNKNOWN SERVICE", "The service connection is unverified", "Request an approved mapping between the service and workload.")}${entry("UNCLASSIFIED", "The type classification is not reviewed", "Send the raw type and evidence for classification review.")}${entry("UNAVAILABLE", "The authoritative source cannot be read", "Recollect within the deadline or route to human review.")}${entry("INCOMPLETE", "Only part of the requested scope was observed", "Narrow the query or collect complete observation evidence.")}</div>`,
      takeaway: "When recovery succeeds, reassess with new evidence. Otherwise, hold, make no change, record the audit, and do not raise authority.",
      evidence: [s.ontology, s.platform],
    }),
    slide({
      state: "CURRENT", chapter: "20 / VERSIONED MEANING", layout: "release-rings",
      title: "Changing meaning requires a new release",
      lead: "Replay past decisions with their original meaning, and distinguish new declarations by exact version and digest.",
      body: `<div class="oe-release-pair"><div><small>Replay a past decision</small><strong>Release A</strong><span>Preserve A's declarations and digest</span></div><div><small>Apply to a new decision</small><strong>Release B</strong><span>New declarations and compatibility verdict</span></div></div>
        ${table(["Compatibility", "Condition for use"], [["COMPATIBLE", "Existing consumers can read the change"], ["MIGRATION REQUIRED", "Use after explicit transformation and evidence verification"], ["INCOMPATIBLE", "Do not accept automatically; keep A and B paths separate"]])}`,
      takeaway: "A new release does not change the meaning of past records. Do not rewrite past decisions with the latest value.",
      evidence: [s.platform, s.structural],
    }),
    slide({
      state: "ILLUSTRATIVE", chapter: "21 / AN UNGROUNDED REQUEST", layout: "failure-cascade",
      title: "Where does a plausible restart proposal fail?",
      lead: "Example request: The payment service is slow. Restart it. Action cannot begin without four checks.",
      body: `<div class="oe-four">${entry("01 / Wrong target", "Verify identity", "Check exact type and ObjectRef, not just a name.")}${entry("02 / Stale document", "Verify evidence", "Check effective time, source, and release for this decision.")}${entry("03 / Unapproved request", "Verify eligibility", "Check policy, risk, and required approval separately.")}${entry("04 / Acceptance-only success", "Verify the effect", "Heimdall, the independent observer, confirms the effect.")}</div>`,
      takeaway: "If any check lacks evidence, stop without change and explain the identity, observation, or approval required next.",
      evidence: [s.llm, s.constitution, s.ontology],
    }),
    slide({
      state: "BOUNDARY", chapter: "22 / THE LIMIT OF RETRIEVAL", layout: "rag-sieve",
      title: "A relevant document is not automatically a current fact",
      lead: "RAG finds candidate material. Identity, effective time, access scope, and completeness still require validation.",
      body: `<div class="oe-retrieval-caption"><small>Example question</small><strong>What is this Workload's recovery procedure?</strong></div>
        <div class="oe-document-strip"><article><small>Relevant document / A</small><strong>Runbook</strong><p>Same name but<br>different ObjectRef</p><span>Exclude from evidence for this object</span></article><article><small>Relevant document / B</small><strong>Incident</strong><p>Exact object but<br>previous release</p><span>Recheck current applicability</span></article><article><small>Relevant document / C</small><strong>Policy</strong><p>Current document but<br>covers only part of the scope</p><span>Mark as partial evidence and supplement</span></article></div>`,
      takeaway: "Relevance and authority are different. Without sufficient current evidence, hold the decision and explain what is missing.",
      evidence: [s.llm, s.governance, s.platform],
    }),
    slide({
      state: "BOUNDARY", chapter: "23 / SIMILARITY IS NOT IDENTITY", layout: "similarity-map",
      title: "Vector proximity does not establish identity",
      lead: "Embeddings help rank candidates. They do not prove object identity or cause.",
      body: `<div class="oe-split"><div class="oe-similarity" role="img" aria-label="Illustrative similarity map. Timeout and latency are nearby expressions, but this does not prove a shared object or cause."><small>Similarity concept / not measured data</small><svg viewBox="0 0 560 300" aria-hidden="true"><ellipse cx="224" cy="132" rx="170" ry="94"/><circle cx="130" cy="106" r="6"/><text x="147" y="114">timeout</text><circle cx="235" cy="164" r="6"/><text x="252" y="172">latency</text><circle cx="412" cy="247" r="6"/><text x="302" y="285">throttle</text></svg></div>
        <div class="oe-stack">${entry("Candidate retrieval", "Find similar expressions", "High relevance still leaves the object and cause unverified.")}${entry("Semantic verification", "Resolve the exact object and relationship", "Validate ObjectRef, LinkType direction, and release.")}${entry("Decision boundary", "Verify current evidence and eligibility", "Check freshness, completeness, policy, and required approval separately.")}</div></div>`,
      takeaway: "Similarity helps order review. It does not replace causal assessment or execution authority.",
      evidence: [s.llm, s.behavior, s.constitution],
    }),
    slide({
      state: "PRINCIPLE", chapter: "24 / GROUNDED INTERPRETATION", layout: "grounding-bridge",
      title: "Generate broad candidates, then verify meaning narrowly",
      lead: "Natural-language interpretation can become planning input, but it is not an execution command.",
      body: `${flow([["Generate", "Interpretation candidates", "Find possible meanings with<br>words, embeddings, and models"], ["Verify meaning", "Verified plan", "Bind to the exact release and<br>resolved terms"], ["Decision path", "Policy, risk, and approval", "Review action eligibility through<br>the standard decision path"]])}
        <div class="oe-outcomes"><span><b>Eligible</b> Review the next gate</span><span><b>Insufficient evidence</b> Hold and recollect</span><span><b>T2 mismatch</b> Human review</span><span><b>Policy violation</b> Block without change</span></div>`,
      takeaway: "Eligibility does not guarantee execution. Required approval, all seven safeguards, and independent effect verification still apply.",
      evidence: [s.platform, s.constitution, s.agentLoop],
    }),
    slide({
      state: "CURRENT", chapter: "25 / PROOF-CARRYING PLAN", layout: "proof-chain",
      title: "A semantically verified plan has no execution authority",
      lead: "Every term and argument needs grounding before a candidate can become a verified plan.",
      body: `<div class="oe-proof"><div class="oe-proof-names"><div><small>Candidate</small><code>SemanticInterpretationCandidate</code></div><div><small>After resolving every term</small><code>VerifiedSemanticPlan</code></div></div>
        ${table(["Allowed semantic evidence", "What it verifies"], [["EXACT_CATALOG", "Exact declaration in the active release"], ["PROMOTED_SURFACE", "Semantic expression promoted after review"], ["OPERATOR_CONFIRMATION", "Authenticated operator confirmation of target and scope"]])}</div>`,
      takeaway: "Do not create the plan if any term remains unresolved. VerifiedSemanticPlan.execution_authority is always false.",
      evidence: [s.platform, s.agentLoop],
    }),
    slide({
      state: "FOUNDATION", chapter: "26 / THE OPERATING SPINE", layout: "operating-spine",
      title: "Connect technical events to service operating outcomes",
      lead: "Read the target, objective, options, execution attempt, and actual effect through one semantic model.",
      body: `<ol class="oe-spine"><li><b>01</b><div><strong>What are we operating?</strong><code>BusinessService / Workload / Resource</code></div><p>Fix the scope of services and real resources</p></li><li><b>02</b><div><strong>What are we protecting?</strong><code>Objective / Change</code></div><p>Connect SLO, recovery, cost objectives, and changes</p></li><li><b>03</b><div><strong>Which options are available?</strong><code>DecisionCase / ActionOption</code></div><p>Compare alternatives with the no-action baseline</p></li><li><b>04</b><div><strong>What actually changed?</strong><code>ActionRun / ObservedOutcome</code></div><p>Separate the execution attempt from independent observation</p></li></ol>`,
      takeaway: "Stop where an intermediate object or relationship remains unresolved. Do not infer facts or authority for the next stage.",
      evidence: [s.ontology, s.platform],
    }),
    slide({
      state: "FOUNDATION", chapter: "27 / DECLARATION AND OBSERVATION", layout: "dual-wheel",
      title: "Distinguish question types from declaration types",
      lead: "Not all five operator questions become release declarations. State and context are evidence-bound outputs.",
      body: `${table(["Operator question", "Answer form", "Basis to preserve"], [
        ["Object / Relationship / Action", "ObjectType / LinkType / ActionType", "Declaration version and release"],
        ["State / Context", "State fact / context snapshot", "Time, source, and completeness"],
        ["Shared capabilities and operations", "InterfaceType / FunctionType", "query / derive / validate / plan"],
      ])}<div class="oe-inline-note"><strong>Declarations describe meaning; observations describe current state.</strong><p>Do not create StateType and ContextType as new declaration kinds.</p></div>`,
      takeaway: "Separate release declarations from runtime outputs to replay both the meaning of a past decision and its evidence at the time.",
      evidence: [s.metamodel, s.platform],
    }),
  ];
}
