/** Chapter 3: evaluate AI without confusing fluent answers with operational proof. */
import { entry, slide } from "./readiness-slide-kit.en.js";
import { edge, icon, node, reviewCycle } from "./readiness-diagrams.en.js";

/** Teach evaluation, comparison, and AI lifecycle boundaries without calling a model. */
export function buildReadinessAi() {
  return [
    slide({
      id: "reasoning", chapter: 3, visual: "reasoning", state: "CONTRACT",
      title: "AI readiness starts with decision strategy, not model names",
      lead: "Apply rules and verified reuse first. Use grounded reasoning from a large language model (LLM) for residual ambiguity.",
      body: `<div class="rm-tier-system"><div class="rm-tier-lanes">${[
        ["T0", "Rules and policies", "Same input and rule version, same result", "If unresolved, review at T1"],
        ["T1", "Verified reuse", "Match target, preconditions, and evidence", "Similarity alone is insufficient; invalid reuse goes to T2"],
        ["T2", "Grounded reasoning", "Independent model cross-check + deterministic verification", "Insufficient evidence: hold or seek human review"],
      ].map(([tier, title, detail, next]) => `<article><strong>${tier}</strong><div><h3>${title}</h3><p>${detail}</p><span>${next}</span></div></article>`).join("")}</div>
        <aside class="rm-tier-verifier">${icon("shield")}<small>Shared verification boundary</small><h3>Confidence is not authority</h3><p>Check format, citations, and policy. Then review risk and approval separately.</p><span>Confidence cannot grant approval.</span></aside></div>`,
      takeaway: "AIOps includes rules, reuse, detection, prediction, and reasoning. Model call volume does not measure maturity.",
      evidence: ["llm", "constitution"],
    }),
    slide({
      id: "evaluation-cases", chapter: 3, visual: "evaluation", state: "PROPOSAL",
      title: "Convert real questions into evaluation cases and expected behavior",
      lead: "The six types below illustrate an evaluation set. Easy correct answers alone do not establish quality.",
      body: [
        ["check", "01 / Sufficient evidence", "Accurate explanation", "Cite current targets and answer only within the requested scope.", "Check: Claims supported by citations?"],
        ["target", "02 / Ambiguous target", "Required clarification", "Ask for distinguishing details before choosing a target.", "Check: No target guesswork."],
        ["hold", "03 / Missing, stale, or conflicting", "Bounded abstention", "Name the evidence gaps and the sources to check again.", "Check: Unverified scope disclosed?"],
        ["shield", "04 / Insufficient authority", "Prevent information disclosure", "Deny access without exposing restricted titles or content.", "Check: No data leaks."],
        ["document", "05 / Instructions in documents", "Preserve the trust boundary", "Ignore document instructions; analyze only as permitted.", "Check: Tool authority unchanged?"],
        ["clock", "06 / Delay or failure", "Bounded termination", "Stop at time and cost limits. Mark incomplete work clearly.", "Check: Clear error state and handoff?"],
      ].map(([symbol, label, title, detail, assertion]) => `<article class="rm-entry rm-test-case">${icon(symbol)}<small>${label}</small><h3>${title}</h3><p>${detail}</p><span>${assertion}</span></article>`).join(""),
      takeaway: "Fix the input, expected result, prohibited behavior, evaluator, and evidence revision for every case.",
      evidence: ["constitution", "llm"],
    }),
    slide({
      id: "good-abstention", chapter: 3, visual: "answers", state: "EXAMPLE",
      title: "A good answer explains precisely what remains unknown",
      lead: "Example question: Is this API change safe? Of 20 resources, current relationship evidence is confirmed for only 14.",
      body: `<article class="rm-answer is-unsupported"><small>${icon("hold")}Example failed response</small><h3>Expands a partial check into full approval</h3><blockquote>No issues were found in the checked resources,<br>so <mark>it is safe to deploy.</mark></blockquote><p>It hides the six unchecked resources<br>and expands a partial query into full impact and approval.</p><span class="rm-answer-verdict">Verdict: Claim exceeds the evidence</span></article>
        <article class="rm-answer is-bounded"><small>${icon("check")}Example expected response</small><h3>Evidence, limits, and next check</h3><blockquote><span><b>Confirmed</b>14 current relationships were confirmed.</span><span><b>Limits</b>3 unmapped, 2 inaccessible,<br>and 1 stale evidence item remain.</span></blockquote><p>The full impact cannot yet be assessed.<br>Complete the relationships and access scope, then review again.</p><span class="rm-answer-verdict">Verdict: Scope-bounded abstention with a next check</span></article>`,
      takeaway: "This answer is review material. It does not replace change approval or root-cause confirmation.",
      evidence: ["constitution", "llm"],
    }),
    slide({
      id: "measurement-layers", chapter: 3, visual: "measurement", state: "PROPOSAL",
      title: "Retrieval, answers, and work outcomes require different metrics",
      lead: "The design below is illustrative, not a measured result. High retrieval quality alone does not establish an operational effect.",
      body: `<div class="rm-metric-lenses">${[
        ["search", "Retrieval", "Recover required evidence", "Relevant evidence retrieved", "Evidence judged relevant", "Fix allowed documents, result count, and question set"],
        ["document", "Answer", "Align claims with citations", "Claims supported by evidence", "Factual claims evaluated", "Judge separately with the same revision and criteria"],
        ["hold", "Abstention", "Handle unresolved cases correctly", "Cases abstained as expected", "Cases requiring abstention", "Count missing, conflicting, and inaccessible evidence separately"],
        ["people", "Work", "Reduce review preparation burden", "Elapsed time or human touchpoints", "Completed work in the same period", "Compare with the current process / show incomplete work separately"],
      ].map(([symbol, label, title, numerator, denominator, condition]) => `<article>${icon(symbol)}<div><small>${label}</small><h3>${title}</h3></div><div class="rm-metric-fraction"><span>${numerator}</span><span>${denominator}</span></div><p>${condition}</p></article>`).join("")}</div>`,
      takeaway: "A separate authoritative observation must confirm actual recovery or savings.",
      evidence: ["metrics", "llm", "constitution"],
    }),
    slide({
      id: "fair-baseline", chapter: 3, visual: "cohorts", state: "CONTRACT",
      title: "Compare the same problem under the same conditions",
      lead: "Separate the current process used for workflow diagnosis from the reference system used for FDAI performance claims, and fix the comparison criteria first.",
      body: `<p class="rm-cohort-diagnostic"><strong>Workflow diagnosis: current operating process vs pilot</strong><span>Measure current time, omissions, and review burden in the same units</span></p>
        <div class="rm-graph rm-cohort-experiment">${node("sample", "FDAI PERFORMANCE CLAIM", "Fixed reference system vs FDAI", "Same scenarios, inputs, and period\nFix revision, units, and exclusions", "compare", "grid-column:1;grid-row:1 / 3")}
          ${edge("sample", "reference", "right", "grid-column:2;grid-row:1")}
          ${node("reference", "REFERENCE", "Documented single-model, non-tiered baseline", "Same inputs; never weaken the reference system", "document", "grid-column:3;grid-row:1")}
          ${edge("sample", "treatment", "right", "grid-column:2;grid-row:2")}
          ${node("treatment", "TREATMENT", "FDAI at the same revision", "Independently assess failures, incomplete work, and uncertainty", "ai", "grid-column:3;grid-row:2")}</div>
        <p class="rm-cohort-seal">Keep improvement and final evaluation cases separate. Pin the sample and criteria before comparison.</p>
        <p class="rm-policy-note"><strong>Policy sample floor</strong> At least 30 samples per cohort; this alone proves neither statistical sufficiency nor improvement.</p>`,
      takeaway: "Answer comparison does not prove operational effects. Synthetic data is not operational evidence.",
      evidence: ["metrics"],
    }),
    slide({
      id: "unit-economics", chapter: 3, visual: "economics", state: "PROPOSAL",
      title: "Measure time and cost per completed unit of work alongside quality",
      lead: "A cheap model can still be expensive when it causes frequent re-review. Cost to complete the work matters more than token price.",
      body: `<div class="rm-economics-formula"><small>Workflow diagnostic cost model / proposal</small><h3>Cost per 1 completed review</h3><div class="rm-cost-composition">${[
        ["ai", "Model"], ["search", "Retrieval"], ["check", "Verification"], ["data", "Attributable infrastructure"], ["people", "Human review"],
      ].map(([symbol, label]) => `<span>${icon(symbol)}<b>${label}</b></span>`).join('<i aria-hidden="true">+</i>')}</div><div class="rm-cost-denominator">Completed units of work in the same period</div><span>Disclose incomplete work and shared overhead separately. State each cost's scope and unit.</span></div>
        <div class="rm-budget-grid">${entry("Response time", "Median and tail latency", "Track p90 (when 90% complete), timeouts, and user retries separately.")}${entry("Cost limit", "Budget per unit of work", "Set the model-call and verification budget before work starts.")}${entry("Failure response", "Abstention and handoff", "At the limit, avoid infinite retries and record the missing evidence.")}</div>`,
      takeaway: "Keep this workflow cost model separate from the official FDAI KPI cost definition, and disclose the inclusion scope of each.",
      evidence: ["metrics", "llm"],
    }),
    slide({
      id: "ai-lifecycle", chapter: 3, visual: "ai-lifecycle", state: "GUIDE",
      title: "Rebuild evaluation evidence when data or models change",
      lead: "Changes to documents, retrieval settings, prompts, policies, and evaluation criteria can alter results just as model changes can.",
      body: reviewCycle([
        ["01 / DETECT", "What changed?", "Check questions, citation errors, latency, and cost changes", "search"],
        ["02 / PIN", "What makes it reproducible?", "Link source, retrieval, prompt, and model versions", "document"],
        ["03 / COMPARE", "Where did it regress?", "Test answers and abstentions with the same evaluation cases", "compare"],
        ["04 / REVIEW", "Apply or revert?", "Use a separate review and retain the prior approved revision", "cycle"],
      ]) + `<div class="rm-owner-strip"><strong>AI evaluation owner</strong><span>Regression analysis and improvement proposals</span><strong>Operations owner</strong><span>Scope, handoff, and change review</span></div>`,
      takeaway: "Do not pass a model based on its self-evaluation. Training or version changes do not raise authority.",
      evidence: ["llm", "governance", "constitution"],
    }),
  ];
}
