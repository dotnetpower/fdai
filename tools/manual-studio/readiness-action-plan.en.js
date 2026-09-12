/** Chapter 5: turn an assessment into owned evidence work, never automatic authority. */
import { entry, record, slide } from "./readiness-slide-kit.en.js";
import { agendaRing, icon } from "./readiness-diagrams.en.js";

export const workshopAgenda = [
  { minutes: 15, activity: "Align on the task and scope", output: "Confirm the users, goal, and exclusions in one sentence" },
  { minutes: 20, activity: "Review available evidence", output: "Compare source, revision, time, and access conditions" },
  { minutes: 25, activity: "Assess each capability", output: "Separate current level, confidence, and unassessed items" },
  { minutes: 20, activity: "Assign gaps and owners", output: "Agree on exit criteria, owners, dependencies, and review dates" },
  { minutes: 10, activity: "Record the next decision", output: "Separate what can be assessed now from what remains on hold" },
];

/** Build owned next steps; the displayed assessment cannot approve any operation. */
export function buildReadinessActionPlan() {
  return [
    slide({
      id: "gap-register", chapter: 5, visual: "gaps", state: "EXAMPLE",
      title: "Give every gap an owner and observable exit criteria",
      lead: "Track the six unverified items and model-use conditions in one improvement register. The dates are proposals for agreement.",
      body: `<div class="rm-closure-lanes"><header><span>Gap to resolve</span><span>Owner and proposed timing</span><span>Evidence of completion</span></header>${[
        ["context", "3 unmapped items", "Service and platform", "Week 2", "Reviewed targets and relationships with source revisions"],
        ["shield", "2 inaccessible items", "Data and access owners", "Week 2", "Reviewed authorization and verified effective server-side access"],
        ["clock", "1 stale item", "Collection and platform", "Week 2", "New observation and freshness-check results"],
        ["document", "No basis for model use", "Data and security", "Week 3", "Approval of purpose, classification, region, retention, and transfer conditions"],
      ].map(([symbol, gap, owner, week, exit]) => `<article><div>${icon(symbol)}<h3>${gap}</h3></div><div><strong>${owner}</strong><span>${week} / proposed</span></div><p>${exit}</p></article>`).join("")}</div><p class="rm-full-note">Keep items open until the same 20-item scope is reassessed. Submitted documents alone do not complete an item.</p>`,
      takeaway: "Close gaps with verified results, not document submission. Record the next owner and date for every open item.",
      evidence: ["constitution", "governance", "ontology"],
    }),
    slide({
      id: "three-boundaries", chapter: 5, visual: "boundaries", state: "STATUS",
      title: "Separate implementation, readiness, and action approval",
      lead: "Design documents and tests do not prove data-use approval, production quality, or execution authority for a deployment.",
      body: `<div class="rm-boundary-columns"><section>${icon("document")}${entry("Shared implementation", "Code and contracts exist", "Evidence checks and input minimization are implemented, not proof of production outcomes.")}</section><section>${icon("data")}${entry("Environment readiness", "Live evidence is required", "Each deployment needs privacy and retention approval. Full production-cohort evidence is still outstanding.")}</section><section>${icon("shield")}${entry("Action approval", "Separate controls apply", "Reads need access, scope, evidence, and audit. Changes also need policy authority and safeguards.")}</section></div>
        <div class="rm-safeguard-section"><strong>Seven safeguards required before a state change</strong><ol class="rm-safeguards"><li>Stop condition</li><li>Tested rollback</li><li>Blast-radius limit</li><li>Successful dry-run</li><li>Logical-target lock</li><li>Stable idempotency key</li><li>Intent-before-effect and terminal audit</li></ol></div>`,
      takeaway: "Dispatch acceptance is not success. An observer independent of the executor must verify the expected effect.",
      evidence: ["constitution", "governance", "metrics"],
    }),
    slide({
      id: "thirty-days", chapter: 5, visual: "roadmap", state: "PROPOSAL",
      title: "Use the first 30 days to build evidence for the next decision",
      lead: "This is an example of review checkpoints, not a guaranteed completion schedule. Do not advance conditions that fail a gate.",
      body: `<div class="rm-workstream-calendar"><header><span>Accountable workstream</span>${[1, 2, 3, 4].map(week => `<strong>Week ${week}</strong>`).join("")}</header>${[
        ["Scope and baseline", "Service owner", "Agree goals, exclusions,\nand ownership"],
        ["Data and context", "Data and platform", "Check gaps and access\nin the full scope"],
        ["AI evaluation", "AI and operations", "Compare quality and holds\non fixed cases"],
        ["Independent review", "Service and security", "Record open gaps\nand the next decision"],
      ].map(([title, owner, output], index) => `<div class="rm-calendar-row"><div><h3>${title}</h3><small>${owner}</small></div>${[0, 1, 2, 3].map(week => `<div class="rm-calendar-cell${index === week ? " is-planned" : ""}" data-rm-week="${week + 1}"${index === week ? ` data-rm-checkpoint="${index + 1}"` : ""}>${index === week ? `<p>${output}</p>` : '<i aria-hidden="true"></i>'}</div>`).join("")}</div>`).join("")}</div><p class="rm-calendar-caption">Shaded cells are proposed work weeks, not progress. Advance only after prerequisite evidence.</p>`,
      takeaway: "Do not promote because a date has passed. Reduce scope or hold when evidence is insufficient.",
      evidence: ["constitution", "metrics", "governance"],
    }),
    slide({
      id: "workshop", chapter: 5, visual: "workshop", state: "PROPOSAL",
      title: "Focus the 90-minute workshop on agreed outputs, not a grade",
      lead: "Service, data, AI evaluation, and security owners review the same evidence. Missing material remains unassessed.",
      body: `<aside class="rm-workshop-clock">${agendaRing(workshopAgenda)}<h3>Prepare before the meeting</h3><p>Bring questions, procedures, sources, quality records, use conditions, and owners.</p></aside>
        <ol class="rm-agenda">${workshopAgenda.map((item, index) => `<li data-rm-agenda="${index + 1}"><span>${item.minutes} min</span><div><h3>${item.activity}</h3><p>${item.output}</p></div></li>`).join("")}</ol>`,
      takeaway: "Record the task definition, evidence list, capability assessments, gap owners, and next review date.",
      evidence: ["constitution", "governance"],
    }),
    slide({
      id: "next-decision", chapter: 5, visual: "next", state: "PROPOSAL",
      title: "Decide the scope of the first validation, not the model",
      lead: "The goal is not a high score. Agree on who will produce which evidence and what the next decision will be.",
      body: `<section class="rm-final-brief"><small>${icon("target")}NEXT DECISION / REVIEW REQUEST</small><h3>Review the read-only pilot<br>and improvement plan.</h3>
        ${record([["One task", "A repeatable change-impact review"], ["Owners", "Service, data, evaluation, and security"], ["Next review", "Baseline, gaps, exit criteria, and date"]])}</section>
        <section class="rm-next-outcomes"><div>${icon("check")}${entry("Proceed to review", "Start with evidence-ready scope", "Review an observation plan within existing authority and approved data use.")}</div><div>${icon("cycle")}${entry("Improve and reassess", "Invest in blocking gaps first", "Improve evidence and ownership, then reassess the same scope.")}</div><div>${icon("target")}${entry("Redefine the scope", "Change work that does not fit", "Choose another starting point if value is low or validation is infeasible.")}</div></section>`,
      takeaway: "Readiness clarifies the next action. Maturity builds the ability to repeat that decision.",
      evidence: ["constitution", "metrics"],
    }),
  ];
}
