/** Chapters 1-2: frame one decision, then establish minimum usable evidence. */
import { entry, path, record, slide } from "./readiness-slide-kit.en.js";
import { convergence, dimensionMap, edge, icon } from "./readiness-diagrams.en.js";

/** Frame the first decision and its data requirements in thirteen teaching slides. */
export function buildReadinessFoundations() {
  return [
    slide({
      id: "demo-gap", chapter: 1, visual: "contrast", state: "GUIDE",
      title: "A good demo does not mean the system is ready for operations",
      lead: "Generating an answer and meeting the conditions to rely on it at work are different capabilities.",
      body: `<article class="rm-demo">${icon("ai")}<small>DEMONSTRATION</small><h3>It can answer a question</h3><blockquote>Summarize the impact<br>of this change.</blockquote><div class="rm-graph rm-demo-output"><span data-rm-node="input">Input</span>${edge("input", "generation")}<span data-rm-node="generation">Generate</span>${edge("generation", "answer")}<span data-rm-node="answer">Answer</span></div><p>Producing an answer does not mean<br>it is ready for operational use.</p></article>
        <section class="rm-operating-record"><small>OPERATION</small><h3>Can it handle gaps and exceptions?</h3>
          <div class="rm-proof-checks">${[
            ["target", "Target", "Verify the exact target and revision, not only its name"],
            ["data", "Evidence", "Expose missing, delayed, and inaccessible evidence"],
            ["people", "Accountability", "Define hold criteria and the person who takes over"],
            ["check", "Outcome", "Confirm the actual effect through a separate observation"],
          ].map(([symbol, label, detail]) => `<article>${icon(symbol)}<div><h3>${label}</h3><p>${detail}</p></div></article>`).join("")}</div></section>`,
      takeaway: "Adoption starts with the decision to delegate and the evidence to verify, not with model selection.",
      evidence: ["constitution"],
    }),
    slide({
      id: "two-lenses", chapter: 1, visual: "lenses", state: "PROPOSAL",
      title: "Readiness tests this decision; maturity tests the ability to repeat it",
      lead: "Assess both whether one pilot can run and whether the organization can sustain its quality.",
      body: `<section class="rm-lens-panel"><small>READINESS / THIS DECISION</small><h3>A snapshot of the current scope</h3><div class="rm-snapshot-visual">${icon("target")}<strong>NOW</strong><span>target / evidence / reviewer</span></div><p>Review evidence and failure handling for this scope,<br>then record a proceed or hold recommendation.</p></section>
        <section class="rm-lens-panel"><small>MATURITY / ABILITY TO REPEAT</small><h3>Quality sustained through change</h3><div class="rm-graph rm-repeat-visual">${["Assess", "Validate", "Handover"].map((label, index) => `<span data-rm-node="review-${index}">${icon(["search", "check", "people"][index])}<b>${label}</b></span>${index < 2 ? edge(`review-${index}`, `review-${index + 1}`) : ""}`).join("")}</div><p>Can the process repeat as people and data change,<br>and can results drive improvement?</p></section>
        <div class="rm-lens-summary"><span>Reassess readiness when scope changes</span><span>Transfer evidence when ownership changes</span></div>`,
      takeaway: "Readiness and maturity inform review. Access and execution authority require separate verification.",
      evidence: ["constitution", "governance"],
    }),
    slide({
      id: "six-dimensions", chapter: 1, visual: "dimensions", state: "PROPOSAL",
      title: "Connect six capabilities to one operational decision",
      lead: "Do not score technology, data, and people separately. Connect the evidence needed to perform the same work.",
      body: dimensionMap([
        ["01 / VALUE", "Value and scope", "Define the decision to improve and what remains out of scope", "target"],
        ["02 / DATA", "Data quality and management", "Verify quality with source contracts and gap checks", "data"],
        ["03 / CONTEXT", "Meaning and service context", "Connect target, relationships, goals, and owner", "context"],
        ["04 / AI", "AI evaluation and change", "Evaluate correct answers and correct abstentions", "ai"],
        ["05 / PEOPLE", "People and operations", "Assign exception response and handover accountability", "people"],
        ["06 / GOVERNANCE", "Controls and safe change", "Separate conditions of use from access and execution authority", "shield"],
      ]),
      takeaway: "Find the specific gaps blocking the selected work instead of calculating a composite score.",
      evidence: ["constitution", "governance", "llm"],
    }),
    slide({
      id: "decision-charter", chapter: 1, visual: "charter", state: "EXAMPLE",
      title: "First, define the work to delegate in one sentence",
      lead: "Example: Help an operator reviewing an API change see impact evidence and unverified scope in one view.",
      body: `<div class="rm-charter-heading"><small>DECISION CHARTER / WORKED EXAMPLE</small><h3>${icon("target")}Pre-change impact review briefing</h3><span class="rm-pill">Read-only pilot proposal</span></div>
        ${record([["User and timing", "Service operator / before the change review meeting"], ["Target scope", "Selected API workload and 20 related resources"], ["Required inputs", "Change diff, current relationships, goals, and owners"], ["Minimum collection", "Only decision-critical fields and source references"], ["Outcome to verify", "Time to find evidence and detection of omissions"], ["Out of scope", "Change approval, resource modification, and confirmed causation"]], "rm-record-grid")}`,
      takeaway: "Define the target and purpose first to avoid collecting unnecessary data.",
      evidence: ["constitution", "ontology", "governance"],
    }),
    slide({
      id: "pilot-selection", chapter: 1, visual: "selection", state: "PROPOSAL",
      title: "The first task should be small, repeatable, and reviewable",
      lead: "Any of the three operating areas can be a starting point. Expected value does not override gaps in data or authority.",
      body: `<div class="rm-option-board">${[
        ["change", "CHANGE SAFETY", "Impact briefing", "Change diff, service relationships, and protected goals", "Automated approval and deployment execution"],
        ["shield", "RESILIENCE", "Incident evidence summary", "Observations, timestamps, and prior response for the same event", "Confirming causation from correlation alone"],
        ["cost", "COST", "Review candidate explanation", "Cost window, utilization, and reliability constraints", "Reporting projected savings as realized savings"],
      ].map(([symbol, label, title, need, excluded]) => `<article>${icon(symbol)}<small>${label}</small><h3>${title}</h3><div><span>Secure first</span><p>${need}</p></div><div class="rm-not-in-scope"><span>Exclude from the first validation</span><p>${excluded}</p></div></article>`).join("")}</div>
        <div class="rm-question-strip"><b>Shared questions</b><span>Does a current procedure exist?</span><span>Is the effect evaluated separately?</span><span>Can a person take over?</span></div>`,
      takeaway: "A read-only pilot still requires access. State changes require a separate safety review.",
      evidence: ["constitution", "metrics"],
    }),
    slide({
      id: "evidence-supply", chapter: 2, visual: "supply", state: "GUIDE",
      title: "Each data source answers a different question",
      lead: "Connect observations, changes, documents, and goals while distinguishing what each one proves.",
      body: convergence([
        ["OBSERVATION", "What is visible now?", "State, metrics, traces, and observation scope", "data"],
        ["CHANGE", "What will be different?", "Difference between current state and the pinned plan revision", "change"],
        ["KNOWLEDGE", "How has this been reviewed?", "Valid runbooks, procedures, and evidence-backed cases", "document"],
        ["GOAL", "What must be protected?", "Service goals, constraints, and current owner", "target"],
      ], ["BOUNDED EVIDENCE", "Evidence bundle for one decision", "Verify target, relationships, time, and source together\nDocument != current observation != permission to use\nRecord gaps as unverified instead of guessing", "context"]),
      takeaway: "Connect the minimum evidence supporting each claim instead of maximizing collection volume.",
      evidence: ["ontology", "governance"],
    }),
    slide({
      id: "data-contract", chapter: 2, visual: "data-contract", state: "EXAMPLE",
      title: "Give every source a contract for purpose, time, and accountability",
      lead: "Example: Define the conditions for using asset relationship data in a change impact briefing.",
      body: `<header class="rm-document-heading"><div><small>SOURCE CONTRACT / WORKED EXAMPLE</small><h3>${icon("document")}Current relationship data for an API workload</h3></div><span class="rm-pill">Not a live operating configuration</span></header>
        ${record([["Purpose and fields", "Impact review / target reference, relationship, and source time"], ["Source and revision", "Approved asset inventory / pinned at assessment time"], ["Owner and scope", "Platform owner / 20 selected resources"], ["Time basis", "Reference time and source-specific freshness policy"], ["Quality failures", "Record unmapped, inaccessible, and delayed items separately"], ["Access and retention", "Authorized reviewers / approved retention and deletion policy"]], "rm-record-grid")}`,
      takeaway: "A successful source connection does not establish readiness. Define how contract violations are handled.",
      evidence: ["governance", "constitution"],
    }),
    slide({
      id: "quality-tests", chapter: 2, visual: "quality", state: "PROPOSAL",
      title: "Explain quality through defect-finding checks, not a favorable score",
      lead: "Test decision-critical fields first, and retain failed items in the denominator and review record.",
      body: `<div class="rm-quality-lab">${[
        ["completeness", "Completeness", "Compare expected targets with observed scope", "Do not treat omissions as normal", '<b></b><b></b><b></b><b></b><b></b><b class="is-missing"></b>'],
        ["accuracy", "Accuracy", "Compare exact identifiers with the source", "Hold the decision if the target differs", '<span>Target A</span><i>≠</i><span>Target B</span>'],
        ["freshness", "Freshness", "Compare source time with its validity window", "Exclude expired evidence", `${icon("clock")}<span>observed / expires / arrived</span>`],
        ["consistency", "Consistency", "Check for conflicts in units, states, and relationships", "Do not average away conflicts", '<span>Claim A</span><i>≠</i><span>Claim B</span>'],
        ["uniqueness", "Uniqueness", "Distinguish repeated collection of the same event", "Do not count duplicates as new samples", '<span>Event A</span><i>=</i><span>Event A</span>'],
        ["lineage", "Lineage", "Reproduce the source, revision, and transformation path", "Record broken paths as unverified", `${icon("link")}<span>source / transform / citation</span>`],
      ].map(([kind, title, check, failure, motif]) => `<article><div class="rm-quality-motif rm-motif-${kind}" aria-hidden="true">${motif}</div><h3>${title}</h3><p>${check}</p><span class="rm-failure-rule">${failure}</span></article>`).join("")}</div>`,
      takeaway: "Agree quality criteria for each task. Do not invent a universal pass rate.",
      evidence: ["constitution", "governance", "metrics"],
    }),
    slide({
      id: "coverage", chapter: 2, visual: "coverage", state: "EXAMPLE",
      title: "Keep the six unseen resources in the assessment",
      lead: "Example: Of the 20 selected resources, 14 have verified current relationships.",
      body: `<div class="rm-coverage-head"><div><small>CURRENT RELATIONSHIPS</small><strong>14 <span>/ 20</span></strong></div><div class="rm-resource-waffle" role="img" aria-label="Preserves the status of all 20 resources: 14 verified, 3 unmapped, 2 inaccessible, and 1 delayed.">${Array.from({ length: 20 }, (_, index) => `<span data-rm-unit="${index < 14 ? "verified" : index < 17 ? "gap" : index < 19 ? "restricted" : "stale"}" aria-hidden="true">${index < 14 ? "✓" : index < 17 ? "?" : index < 19 ? "×" : "!"}</span>`).join("")}</div><p>Reference time: 10:00 UTC<br>Pinned scope: 20 resources / 0 excluded<br>Verified: target, relationship, and freshness confirmed</p></div>
        <div class="rm-coverage-bar"><div class="rm-coverage-strip" data-rm-total="20" role="img" aria-label="Example: 14 verified, 3 unmapped, 2 inaccessible, and 1 with stale evidence. 20 total.">
          <span class="is-verified" data-rm-count="14" style="width:70%">14</span><span class="is-gap" data-rm-count="3" style="width:15%">3</span><span class="is-restricted" data-rm-count="2" style="width:10%">2</span><span class="is-stale" data-rm-count="1" style="width:5%">1</span></div>
          <div class="rm-coverage-legend"><span>Verified: 14</span><span>Unmapped: 3</span><span>Inaccessible: 2</span><span>Delayed: 1</span></div></div>
        <div class="rm-coverage-equation"><strong>70%</strong><p>14 / 20 = 70%<br>Do not count only the verified 14 as the denominator and report 100%.</p><b>Six unverified resources<br>limit the complete impact decision.</b></div>`,
      takeaway: "This is example relationship coverage, not a maturity score or pilot approval threshold.",
      evidence: ["constitution", "metrics"],
    }),
    slide({
      id: "time", chapter: 2, visual: "time", state: "EXAMPLE",
      title: "Recently collected information may already describe stale facts",
      lead: "The example policy permits reuse in a current decision for only 5 minutes after observation.",
      body: `<div class="rm-time-chart"><div class="rm-time-window" data-rm-duration="10"><div class="rm-valid-window" data-rm-duration="5" style="width:50%"><strong>5 minutes valid for a decision</strong></div><div class="rm-expired-window" style="width:50%"><strong>After expiry / cannot be reused as current evidence</strong></div></div>
        <div class="rm-time-axis" data-rm-total-minutes="10">${[
          [0, "09:50 UTC", "Observed event"], [5, "09:55 UTC", "Freshness expires"], [8, "09:58 UTC", "Arrives at FDAI"], [10, "10:00 UTC", "Decision time"],
        ].map(([minute, time, label]) => `<div class="rm-time-marker" data-rm-minute="${minute}" style="left:${minute * 10}%"><i aria-hidden="true"></i><div><strong>${time}</strong><span>${label}</span></div></div>`).join("")}</div>
        <div class="rm-time-explanation">${entry("TIMELINE USES ACTUAL INTERVALS / EXAMPLE", "A recent collection can carry an expired fact", "Arriving 8 minutes later does not extend the 5-minute validity window.")}${entry("RESPONSE AT DECISION TIME", "Observe again or hold the current decision", "Retain event time, recorded time, and validity window so the decision can be reproduced.")}</div></div>`,
      takeaway: "Store late evidence as a separate revision. Do not overwrite the evidence behind a past decision.",
      evidence: ["constitution", "ontology"],
    }),
    slide({
      id: "semantic-spine", chapter: 2, visual: "semantic", state: "EXAMPLE",
      title: "Connect resources to service meaning and accountability",
      lead: "To understand the example API change, identify how the exact resource connects to its workload and service.",
      body: path([
        ["BusinessService", "Order service", "Basis for protected goals and service accountability", "people"],
        ["Workload", "API workload", "Unit of change review and operational handover", "context"],
        ["Resource", "Runtime resource", "Observed target and source revision", "data"],
      ], ["implementation relationship<small>implemented_by</small>", "runtime location<small>workload_runs_on</small>"])
        + `<div class="rm-semantic-notes">${entry("CONNECTIONS THAT COMPLETE CONTEXT", "Goals and owners", "Verify approved service goals and current ownership as separate evidence.")}${entry("INTERPRETATION LIMIT", "A relationship is not causation or authority", "Leave a missing connection unmapped. Do not infer one from a similar name.")}</div>`,
      takeaway: "Ontology aligns the meaning of targets and relationships. Verify current state and access separately.",
      evidence: ["ontology", "constitution"],
    }),
    slide({
      id: "knowledge", chapter: 2, visual: "knowledge", state: "EXAMPLE",
      title: "A retrieved document is not automatically evidence for an answer",
      lead: "Retrieval-augmented generation (RAG) connects retrieved material to answer generation. Access and citation support still require verification.",
      body: path([
        ["01 / ACCESS SCOPE", "Authorized documents only", "Verify read permission and source conditions first", "shield"],
        ["02 / RETRIEVAL", "Find relevant passages", "Search and rank only within the authorized set", "search"],
        ["03 / VALIDATION", "Compare with the claim", "Verify that target, revision, and passage support the claim", "compare"],
        ["04 / ANSWER", "Evidence and limits", "Cite only supported claims and disclose unverified areas", "document"],
      ]) + `<div class="rm-retrieval-review"><span class="rm-review-old">${icon("hold")}Prior revision: exclude from current impact evidence</span><span>${icon("check")}Current material: cite only for the relevant claim</span></div>`,
      takeaway: "Explain missing or conflicting documents. Do not replace absent evidence with a retrieval score.",
      evidence: ["ingestion", "llm"],
    }),
    slide({
      id: "data-lifecycle", chapter: 2, visual: "lifecycle", state: "CONTRACT",
      title: "Prepare for data from ingestion through deletion",
      lead: "Source access, retention, and deletion conditions must extend to text, summaries, and embeddings, the numeric representations used for retrieval.",
      body: `<div class="rm-lifecycle-track">${[
        ["data", "Classify and collect", "Minimum fields required for the purpose", "owner / classification / collection purpose"],
        ["shield", "Send to model", "Region, retention, and training-use conditions", "de-identification / approved processor"],
        ["search", "Retrieve and share", "User and source access boundaries", "compare permissions for documents and derived material"],
        ["cycle", "Retain and delete", "Deletion and legal-hold processing path", "confirm completion for source / chunk / embedding"],
      ].map(([symbol, title, check, proof], index) => `<article>${icon(symbol)}<small>0${index + 1}</small><h3>${title}</h3><p>${check}</p><span>${proof}</span></article>`).join("")}</div>
        <div class="rm-inheritance-band"><strong>Preserve source conditions</strong><span>Source text</span><i aria-hidden="true">/</i><span>Summary / citation chunk</span><i aria-hidden="true">/</i><span>Embedding</span></div>
        <p class="rm-full-note">Hold transfer when classification or model-use approval is unverified. Do not send inputs that cannot be sufficiently de-identified.</p>`,
      takeaway: "Retention periods and model terms are not universal. Accountable owners must approve them for each deployment.",
      evidence: ["governance", "ingestion"],
    }),
  ];
}
