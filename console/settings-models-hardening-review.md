# Settings Models Hardening Review

This review records the 2026-07-19 critique and hardening pass for
`/settings/models`. It covers T2 model governance, data integrity, responsive
layout, accessibility, and operator clarity. Findings are based on code review,
the live local projection, and browser checks at 1440 x 900, 944 x 664, and
390 x 844.

## Evidence

- At 944 px, the capability table measured 599 px of content inside a 562 px
  wrapper. The last columns were available only through a buried horizontal
  scroll.
- The document and `main` both scrolled. At 1440 x 900, `body.scrollHeight` was
  1818 while `main` was a separate 807 px scroll container.
- The Explorer subtitle measured 244 px of content in a 183 px box and was
  truncated.
- The API reported six T2 capabilities, but `t2.reasoner.secondary` and
  `t2.reasoner.escalated` were approval-only. Endpoint inventory and routing
  telemetry were empty.
- The original contract hard-coded `t2_selection_scope=system-governed` and
  exposed no T2 candidate set or selection workflow.

## Detected issues

| # | Severity | Finding | Disposition |
|---|----------|---------|-------------|
| 1 | Critical | T2 had no selectable primary or secondary controls. | Fixed with the T2 policy draft builder. |
| 2 | Critical | The API exposed no safe T2 candidate set. | Fixed by projecting sanitized registry publisher/family preferences. |
| 3 | Critical | A single-model selector would violate the mixed-model quality gate. | Fixed by requiring a primary and secondary pair. |
| 4 | Critical | No UI rule enforced distinct publishers. | Fixed in decoder helpers and the copy action. |
| 5 | High | The system-governed label gave no path to propose a change. | Fixed with a catalog-as-code draft workflow. |
| 6 | High | Runtime mutation and governance intent were not visibly separated. | Fixed with a PR-artifact-only boundary notice. |
| 7 | High | Current and proposed T2 assignments were not shown separately. | Fixed with active primary/secondary facts above the draft controls. |
| 8 | High | T2 quorum readiness was not visible. | Fixed with quorum-ready or approval-required status. |
| 9 | High | Registry absence would otherwise render an unexplained empty selector. | Fixed with disabled unavailable options and an empty-pair message. |
| 10 | High | A frontend deployed before its backend would fail the entire page on a missing T2 policy field. | Fixed with a version-skew fallback to an unavailable builder. |
| 11 | High | The six-column capability table overflowed by 37 px at the observed viewport. | Fixed with responsive row layout below 1100 px. |
| 12 | High | The document and `main` produced nested vertical scrollbars. | Fixed by constraining `.shell` to one viewport and keeping `main` as the scroll owner. |
| 13 | High | `.data-table-wrap` used `overflow:auto` on both axes without a vertical bound. | Fixed for Models with horizontal-only overflow on wide layouts. |
| 14 | High | Horizontal table scroll was discoverable only at the table bottom. | Fixed by removing horizontal scrolling on common narrow layouts. |
| 15 | High | Mobile table cells lost their column meaning when headers were visually hidden. | Fixed with explicit `mobileLabel` cell metadata. |
| 16 | Medium | Four lifecycle facts were placed in a three-column grid. | Fixed with a four-column desktop grid and one-column mobile layout. |
| 17 | Medium | The Explorer subtitle was truncated by 61 px. | Fixed with wrapped two-line-capable text. |
| 18 | Medium | Section headings and status pills competed for width. | Fixed with shrink-safe copy and stacked mobile headers. |
| 19 | Medium | Long model, capability, and binding identifiers forced table expansion. | Fixed with bounded wrapping inside Models tables. |
| 20 | Medium | Long fallback text had no height or overflow boundary. | Fixed with a bounded scrollable fallback region. |
| 21 | Medium | T2 select controls had no stable dimensions. | Fixed with full-width, minimum-height controls in a constrained grid. |
| 22 | Medium | Primary and secondary controls did not stack on mobile. | Fixed with a one-column layout below 760 px. |
| 23 | Medium | A generated policy artifact had no bounded preview area. | Fixed with a focusable, wrapped, scrollable preview. |
| 24 | Medium | The T2 role controls had no labels because the controls did not exist. | Fixed with explicit `for` and `id` associations. |
| 25 | Medium | The draft preview had no accessible name. | Fixed with an `aria-label` and keyboard focus. |
| 26 | Medium | Clipboard denial would have failed silently. | Fixed with an inline alert and manual-copy fallback. |
| 27 | Medium | Successful copy had no feedback. | Fixed with a persistent `Draft copied` button state until the selection changes. |
| 28 | Medium | Empty candidate arrays would produce blank native selects. | Fixed with an explicit unavailable option. |
| 29 | Medium | Invalid or incomplete pairs had no blocking state. | Fixed by disabling copy and showing pair validation status. |
| 30 | Medium | Mobile rows had no scan-friendly key/value alignment. | Fixed with a stable label/value grid per row. |
| 31 | Medium | The UI used the raw HIL acronym in lifecycle summary text. | Fixed with the human-facing `approval-only` label. |
| 32 | Medium | Capability copy said T2 could not be personalized but did not explain governance drafts. | Fixed with proposal-oriented copy. |
| 33 | Medium | The generated YAML could be mistaken for a complete registry replacement. | Fixed with a merge-only comment that preserves SKU and capacity. |
| 34 | Medium | Production could expose no candidates even though the image ships the registry. | Fixed by wiring the sibling `/app/rule-catalog/llm-registry.yaml` when present. |
| 35 | Medium | Candidate metadata could have been sourced from narrator deployments, collapsing T1 and T2 semantics. | Fixed by using only the T2 registry capabilities. |
| 36 | Medium | Endpoint and credential details could leak if raw registry or bindings were returned. | Fixed by projecting publisher and family only. |
| 37 | Low | Raw capability status values such as `hil-only` remain visible in the evidence table. | Follow-up: localize display labels while preserving machine values. |
| 38 | Low | Narrator preference can be saved when unchanged. | Follow-up: add dirty-state detection. |
| 39 | Low | Narrator preference conflicts still surface as a generic route error. | Follow-up: add the same reload-and-review flow used by web search. |
| 40 | Low | Empty routing and endpoint sections explain absence but do not link to provisioning evidence. | Follow-up: add contextual links when those routes expose grounded records. |

## Result

The page now supports a real operator choice without bypassing FDAI's safety
model. The choice produces a validated governance fragment; it does not mutate
the running control plane. Applying it still requires a reviewed catalog PR,
resolver regeneration of `resolved-models.json`, and deployment. The quality
gate continues to require two models from distinct publishers.

The hardening also removes document-level overflow, preserves one vertical
scroll owner, converts dense tables to labeled rows on narrow screens, and
keeps all new copy in English/Korean catalog parity.
