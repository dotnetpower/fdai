/** Chapter 4: proposed qualitative rubric, not an automated score or authority registry. */
import { slide, table } from "./readiness-slide-kit.en.js";
import { icon, maturityPosition } from "./readiness-diagrams.en.js";

export const maturityLevels = [
  ["M1", "Ad hoc", "Relies on individual experience", "Observed work examples"],
  ["M2", "Defined", "Owners and criteria are agreed", "Documents and confirmation records"],
  ["M3", "Repeatable", "Repeats the same procedure", "Repeated execution records"],
  ["M4", "Evidence-validated", "Proves the agreed quality", "Measurements and independent review"],
  ["M5", "Continuously improving", "Detects change and revalidates", "Regression, improvement, and restoration history"],
];

export const illustrativeProfile = [
  { dimension: "Value and scope", level: "M2", evidence: "Work and reviewer documented", next: "Measure the current baseline for the same work" },
  { dimension: "Data quality and governance", level: "M3", evidence: "Repeated checks cover all 20 items", next: "Resolve unmapped, inaccessible, and delayed items" },
  { dimension: "Meaning and service context", level: "M2", evidence: "Mapping agreed; six items unverified", next: "Verify relationships and sources across the full scope" },
  { dimension: "AI evaluation and change", level: "M2", evidence: "Criteria agreed; no comparison results", next: "Evaluate abstention and citation with a fixed case set" },
  { dimension: "People and operating procedures", level: "M3", evidence: "Repeated review and handoff records", next: "Measure exception handling and review burden" },
  { dimension: "Controls and safe change", level: null, evidence: "Model-use approval evidence missing", next: "Review authority and data-use conditions separately" },
];

/** Explain the proposed rubric and its explicitly fictional evidence-based assessment. */
export function buildReadinessMaturityModel() {
  return [
    slide({
      id: "maturity-ladder", chapter: 4, visual: "maturity", state: "PROPOSAL",
      title: "Maturity is repeatable capability, not the amount of automation",
      lead: "M1-M5 is a proposed model for this workshop. It is not an accredited rating or an FDAI execution-authority scale.",
      body: `<ol class="rm-maturity-steps">${maturityLevels.map(([code, title, meaning, evidence], index) => `<li style="--step:${index}"><div class="rm-maturity-stage"><small>${code}</small>${icon(["people", "document", "cycle", "check", "context"][index])}</div><h3>${title}</h3><p>${meaning}</p><span>${evidence}</span></li>`).join("")}</ol>
        <div class="rm-maturity-boundary"><strong>Criteria to agree first</strong><p>Work scope, measurement window, required sample, acceptable error, evidence validity period, and accountable reviewer</p></div>`,
      takeaway: "No evidence means unassessed. M levels are separate from decision tiers and execution modes.",
      evidence: ["constitution", "metrics"],
    }),
    slide({
      id: "data-rubric", chapter: 4, visual: "rubric", state: "PROPOSAL",
      title: "Data maturity progresses from documentation to repeatable validation",
      lead: "These middle-level examples need a window and sample agreed for the selected work's risk and variability.",
      body: table(["Capability", "M2 / Defined", "M3 / Repeatable", "M4 / Evidence-validated"], [
        ["Value and scope", "Define goals, owner, and exclusions", "Repeat the same work baseline", "Review value and side effects in one unit"],
        ["Data quality and governance", "Assign source contracts, criteria, and owners", "Track gaps and delays in the same scope", "Prove quality, deletion, and access controls"],
        ["Meaning and service context", "Agree target, relationship, and goal meanings", "Track mapping changes and unclassified items", "Validate relationships, time, and sources per question"],
      ], "rm-rubric-table") + `<p class="rm-full-note">At M5, detect new data and relationship changes, then maintain reassessment, improvement, and restoration records.</p>`,
      takeaway: "Do not reuse one document as evidence for every capability. Link evidence directly to each assessment item.",
      evidence: ["governance", "ontology", "metrics"],
    }),
    slide({
      id: "operating-rubric", chapter: 4, visual: "rubric", state: "PROPOSAL",
      title: "AI and operating maturity advance with evaluation and accountability",
      lead: "Assess the ability to detect errors, transfer work to people, and review changes rather than experience using a model.",
      body: table(["Capability", "M2 / Defined", "M3 / Repeatable", "M4 / Evidence-validated"], [
        ["AI evaluation and change management", "Define expected answers, abstention, and failure criteria", "Run regression evaluations with fixed cases and versions", "Prove quality, cost, and latency through independent review"],
        ["People and operating procedures", "Assign work, exceptions, and backup owners", "Repeat review, handoff, and incident response", "Measure and improve workload and missed handoffs"],
        ["Controls and safe change", "Define data-use and authority boundaries", "Check access, approval, audit, and recovery", "Prove controls and effect observation in the target environment"],
      ], "rm-rubric-table") + `<div class="rm-role-example"><strong>Example roles</strong><p>AI owner: restore the model-version record. Operations owner: review reproduction of the same case.</p></div>`,
      takeaway: "Documentation, repeated execution, and validation are different states. A maturity level does not replace approval.",
      evidence: ["llm", "governance", "constitution"],
    }),
    slide({
      id: "assessment-confidence", chapter: 4, visual: "confidence", state: "PROPOSAL",
      title: "Record the current level and confidence in its assessment together",
      lead: "Distinguish self-assessment from observed evidence. This distinction expresses diagnostic confidence, not execution eligibility.",
      body: `<div class="rm-confidence-list">${[
        ["people", "Explanation only", "Interview and self-assessment", "Treat it as a hypothesis pending validation and request actual cases."],
        ["document", "Evidence reviewed", "Owner- and revision-identified records", "Compare the document with the current scope."],
        ["cycle", "Repetition confirmed", "Execution records and reproduction results", "Check whether the same procedure holds across different owners."],
        ["check", "Independent review", "Measurements and independent confirmation", "Review the window, sample, failures, and exclusion reasons together."],
      ].map(([symbol, label, title, detail]) => `<article class="rm-entry"><small>${icon(symbol)}${label}</small><h3>${title}</h3><p>${detail}</p></article>`).join("")}</div>
        <aside class="rm-unknown"><h3>Leave it unassessed</h3><p><strong>No evidence</strong><br>Record the request and owner</p><p><strong>Conflicting evidence</strong><br>Keep both claims and the re-review reason</p><p><strong>Not applicable</strong><br>Record scope rationale and reviewer confirmation</p></aside>`,
      takeaway: "Do not choose a score first and fit evidence to it. Reassess stale findings when new evidence arrives.",
      evidence: ["constitution", "metrics"],
    }),
    slide({
      id: "profile", chapter: 4, visual: "profile", state: "EXAMPLE",
      title: "Read the gaps that block the work instead of an average score",
      lead: "Illustrative team assessment: 70% relationship coverage is not a maturity score.",
      body: `<div class="rm-profile-caption"><span>Current assessment / empty marks indicate other categories</span><span>M1-M5 are ordinal categories; spacing does not represent a numeric difference.</span></div>` + table(["Capability", '<span class="rm-category-scale">' + [1, 2, 3, 4, 5].map(value => `<b>M${value}</b>`).join("") + '</span>', "Evidence provided / example"], illustrativeProfile.map(item => [
        item.dimension,
        maturityPosition(item.level),
        item.evidence,
      ]), "rm-profile-table"),
      takeaway: "Repeatable checks can still find relationship gaps. Never average away an unassessed control.",
      evidence: ["constitution", "governance"],
    }),
    slide({
      id: "decision-memo", chapter: 4, visual: "memo", state: "EXAMPLE",
      title: "End the assessment with a scoped review recommendation and rationale",
      lead: "Illustrative conclusion: Hold the full-impact briefing pilot and propose a permitted data-quality investigation first.",
      body: `<aside class="rm-memo-verdict">${icon("hold")}<small>ASSESSMENT MEMO / EXAMPLE</small><h3>Recommendation to hold the pilot</h3><p>Six of 20 relationships remain unverified, and there is no evidence approving model use.</p><span>Final review: Service owner<br>Data use: Data and security owners</span></aside>
        <div class="rm-decision-branches"><article class="rm-investigate">${icon("search")}<div><small>Scope to propose now</small><h3>Investigate permitted evidence</h3><p>Within read access, diagnose 3 unmapped, 2 inaccessible, and 1 delayed item.</p></div></article><article class="rm-defer">${icon("hold")}<div><small>Scope to hold</small><h3>Hold impact and action decisions</h3><p>Model transfer, final impact determination, change approval, and execution</p></div></article><div class="rm-revisit">${icon("cycle")}<p>Reassess the same 20-item scope after collecting the missing evidence</p></div></div>`,
      takeaway: "This is a review recommendation. Neither 14 confirmed items nor a high M level grants authority.",
      evidence: ["constitution", "governance"],
    }),
  ];
}
