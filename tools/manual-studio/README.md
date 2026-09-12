# Manual Studio

Manual Studio presents FDAI reference decks on a fixed 1536x864 canvas. The viewer scales the whole
slide for the available screen; the presentation is a static explanation, not an operational
control or a source of execution authority.

## Share a manual

Each catalog entry has a stable page named `<manual-id>.html`. Share that page in Microsoft Teams
instead of the query-based library URL. The static artifact generates crawler-readable Open Graph
and Twitter metadata from `catalog.json`, including the manual title, description, canonical URL,
and absolute cover-image URL. Opening the page still launches the selected manual at slide 1.

The local server renders the same metadata. Azure publishing supplies the deployed Manual Studio
base URL to the artifact builder, so no deployment hostname is stored in the repository. When you
add or rename a manual, regenerate the static artifact and confirm that its share page contains no
template tokens and that the cover image returns an image content type without authentication.

## Choose the interface language

Use **EN** or **한국어** in the top bar to change the Manual Studio interface. The selection updates
the Console preview, guide library, journey stages, guide titles, catalog descriptions, cover
labels, dates, navigation labels, and viewer controls. Manual Studio preserves the selected locale
in the current URL and in browser storage, so manual and slide links keep the same interface
language.

The selector also chooses the locale-specific slide source for every catalog manual. English and
Korean titles, leads, visual labels, explanatory text, and accessibility labels are maintained as
separate repository content. Manual Studio does not send slide content to a runtime translation
service.

## Use Case and Value Prioritization workshop

The 25-slide L200 workshop helps portfolio sponsors, service owners, and platform or operations
leaders choose one recurring operational decision for a bounded observation-mode validation. It
separates evidence and safety eligibility from value comparison, keeps unknown evidence out of
numeric scores, and ends with a decision brief, evidence map, and 30-day observation plan.

| File | Responsibility |
|------|----------------|
| [value-prioritization.js](value-prioritization.js) | Sparse title slide and complete deck assembly. |
| [value-prioritization-slide-kit.js](value-prioritization-slide-kit.js) | Shared slide metadata, source labels, chapters, and decision takeaway structure. |
| [value-prioritization-foundations.js](value-prioritization-foundations.js) | Slides 2-7: decision unit, domains, candidate brief, and baseline. |
| [value-prioritization-eligibility.js](value-prioritization-eligibility.js) | Slides 8-12: evidence, time, topology, precedence, and seven safeguards. |
| [value-prioritization-value.js](value-prioritization-value.js) | Slides 13-17: value measures, guard metrics, repeatability, tiers, and authority. |
| [value-prioritization-portfolio.js](value-prioritization-portfolio.js) | Slides 18-22: selection logic, uncertainty, worked comparison, horizons, and decision record. |
| [value-prioritization-action.js](value-prioritization-action.js) | Slides 23-25: observation, independent review, first 30 days, and final commitment. |
| [value-prioritization.css](value-prioritization.css), [value-prioritization-visuals.css](value-prioritization-visuals.css), and [value-prioritization-portfolio.css](value-prioritization-portfolio.css) | Presentation typography, title treatment, and deck-specific visual systems. |
| [test/value-prioritization.test.mjs](test/value-prioritization.test.mjs) and [test/value-prioritization-critique.test.mjs](test/value-prioritization-critique.test.mjs) | Content, authority, measurement, and 23-round critique contracts. |
| [test/value-prioritization-visual.mjs](test/value-prioritization-visual.mjs) | Local desktop, tablet, mobile, fullscreen, and PDF geometry validation. |

The examples in the deck are illustrative and are labeled as non-operational evidence. Portfolio
selection starts observation only. It never grants approval, promotion, or execution authority.

## FDAI Target Architecture review

The 25-slide L200 architecture review helps architects, platform owners, security reviewers, and
operations leaders decide whether to conditionally accept the Azure target-architecture baseline.
It separates design acceptance from production approval and enforce-mode authority. Five chapters
progress from an L0 reference view and C4 system context through runtime topology, decision and
execution boundaries, and the Azure deployment baseline. All 24 body slides use named architecture
nodes, directional connections, system or trust boundaries, and explicit implementation states.

| File | Responsibility |
|------|----------------|
| [target-architecture-plan.md](target-architecture-plan.md) | Audience, review decision, 25-slide architecture story, consistency rules, evidence map, and validation plan. |
| [target-architecture.js](target-architecture.js) | Sparse title slide and complete deck assembly. |
| [target-architecture-slide-kit.js](target-architecture-slide-kit.js) | Chapter, state, source, takeaway, and evidence metadata. |
| [target-architecture-diagram-kit.js](target-architecture-diagram-kit.js) | Measurable architecture nodes, typed directional links, labeled boundaries, and non-color-only legends. |
| [target-architecture-review.js](target-architecture-review.js) | Slides 2-5: L0 reference view, C4 context, layers, and the closed control loop. |
| [target-architecture-runtime.js](target-architecture-runtime.js) | Slides 6-10: five services, service channels, Core components, 15 agents, and data ownership. |
| [target-architecture-decision.js](target-architecture-decision.js) | Slides 11-15: evidence admission, semantic and temporal architecture, tier routing, and Unified RiskGate. |
| [target-architecture-execution.js](target-architecture-execution.js) | Slides 16-20: dispatch, Isolated Executor, trust zones, effect closure, and safe degradation. |
| [target-architecture-deployment.js](target-architecture-deployment.js) | Slides 21-25: ports and adapters, Azure deployment and network flows, release paths, and the ARB decision. |
| [target-architecture.css](target-architecture.css), [target-architecture-visuals.css](target-architecture-visuals.css), and [target-architecture-deployment.css](target-architecture-deployment.css) | Presentation typography, sparse cover, and deck-specific visual systems. |
| [test/target-architecture.test.mjs](test/target-architecture.test.mjs) and [test/target-architecture-critique.test.mjs](test/target-architecture-critique.test.mjs) | Structure, authority, implementation state, digest, and 30-round architecture critique contracts. |
| [test/target-architecture-visual.mjs](test/target-architecture-visual.mjs) | Local desktop, tablet, mobile, fullscreen, print, connector, contrast, and PDF validation. |
| [test/target-architecture-text-geometry.mjs](test/target-architecture-text-geometry.mjs) | Nested clipping, painted edge-label overlap, container overflow, and deliberately broken browser fixtures. |

The architecture decision records a baseline only. It does not deploy a revision, approve
production, promote a capability, or grant an execution identity. The production gate remains
blocked until its named owners provide exact evidence for the reviewed deployment.

The visual runner first proves that its checker rejects the original 112px RiskGate boundary and
scaled clipping fixtures. It waits for slide animations before measuring, includes visually painted
`aria-hidden` labels, and checks every ancestor that can clip text. Review each full-size desktop
image before using the generated contact sheets to compare the deck. Recheck the shared browser
when its font environment differs from local Chromium; geometry success in one is not proof of
readability in the other.

## Readiness and maturity workshop

The 32-slide L200 readiness manual covers five chapters: decision scope, data readiness, AI
evaluation and operation, evidence-based maturity, and the next 30 days. It uses one explicitly
fictional change-review case throughout, including a source contract, complete coverage
denominator, qualitative capability profile, review memo, and owned gap register.

The M1-M5 rubric is a workshop proposal, not a certification, an automated assessment, or an
execution-authority scale. Unassessed controls stay visible. Current-workflow diagnostics, FDAI
reference-system comparisons, and independent operational effects remain separate measurements.

| File | Responsibility |
|------|----------------|
| [readiness-maturity-plan.md](readiness-maturity-plan.md) | Audience, decision, 32-slide storyboard, critique, source map, and validation scope. |
| [readiness-maturity.js](readiness-maturity.js) | Cover and complete deck assembly. |
| [readiness-slide-kit.js](readiness-slide-kit.js) | Static slide structure, evidence metadata, records, tables, and measurable connected nodes. |
| [readiness-foundations.js](readiness-foundations.js) | Slides 2-14: decision scope and minimum usable data. |
| [readiness-ai.js](readiness-ai.js) | Slides 15-21: AI evaluation, fair comparisons, economics, and change management. |
| [readiness-maturity-model.js](readiness-maturity-model.js) | Slides 22-27: proposed rubric, assessment confidence, and the illustrative review. |
| [readiness-action-plan.js](readiness-action-plan.js) | Slides 28-32: owned gaps, separate authority boundaries, improvement plan, and workshop. |
| [readiness-maturity.css](readiness-maturity.css) and [readiness-visuals.css](readiness-visuals.css) | Deck-scoped ivory layouts, presentation typography, diagrams, and proportional charts. |
| [readiness-diagrams.js](readiness-diagrams.js) and [readiness-diagrams.css](readiness-diagrams.css) | Named graph nodes and edges, categorical maturity positions, exact agenda proportions, and the refined visual grammar. |

The cover is typography-only: a subject and one-line subtitle, without an image, agenda, cards,
or teaching diagram. Its density contract is executable in the readiness content tests. Body
slides use source convergence, a six-perspective map, a proportional freshness timeline, paired
evaluation paths, a version-review cycle, and a proposed workstream calendar. Maturity uses one
discrete marker per assessed dimension, never a continuous score or a radar area. Unassessed
dimensions have no numeric position.

The content contracts are in [test/readiness-maturity.test.mjs](test/readiness-maturity.test.mjs).
The local-only [rendering check](test/readiness-visual.mjs) accepts an absolute artifact directory
outside the repository and optional comma-separated modes: `desktop`, `tablet`, `mobile`,
`fullscreen`, and `print`. Reuse the local Manual Studio server on port 5474 and the installed
Console Playwright dependency. Complete desktop inspection before the responsive modes.

The rendering check navigates the actual viewer, checks text ranges, regions, contrast, body font
size, horizontal and vertical connector endpoints, bar and time proportions, category positions,
and agenda arc lengths, and exports a PDF with print CSS. Inspect full-size
images and contact sheets, then check the PDF page count and every MediaBox separately. The
versioned readiness review in [validation-evidence.json](validation-evidence.json) covers the new
32-slide deck; the older 25-slide hardening records and the initial 32-slide editorial review
remain historical evidence for their exact snapshots.

## Ontology deck files

| File | Responsibility |
|------|----------------|
| [ontology-foundation.js](ontology-foundation.js) | Preserves the approved title page and assembles the forty-slide deck. |
| [ontology-slide-kit.js](ontology-slide-kit.js) | Shared slide structure, short citations, tables, and connected diagrams. |
| [ontology-story-foundations.js](ontology-story-foundations.js) | Slides 2-14: motivation, history, and the operating definition. |
| [ontology-story-contracts.js](ontology-story-contracts.js) | Slides 15-28: identity, time, evidence, and semantic boundaries. |
| [ontology-story-operations.js](ontology-story-operations.js) | Slides 29-40: bounded queries, agents, effects, scenarios, and adoption. |
| [ontology-editorial.css](ontology-editorial.css) | Restrained ivory layouts and typography for the 39 body slides only. |
| [ontology-foundation.css](ontology-foundation.css) | Existing base styles, retained for the approved cover's rendering compatibility. |
| [ontology-opening.css](ontology-opening.css) | Slide 1 only: title, short subtitle, and decorative artwork. |
| [manual-content.js](manual-content.js) | Registers the ontology deck alongside other manuals. |
| [catalog.json](catalog.json) | Catalog identity, level, duration, and slide count. |
| [validation-evidence.json](validation-evidence.json) | Recorded validation history; a scoped review does not revalidate earlier deck revisions. |

## Refine one slide at a time

Keep the opening stylesheet scoped to `.manual-slide.slide-ontology-cover` and loaded after the
shared styles in both viewer entry points. The opening's content-density contract is in
[test/prototype.test.mjs](test/prototype.test.mjs). Explanations, agendas, and instructional diagrams
belong in the body slides. The cover's unlabeled architectural SVG is decorative, hidden from
assistive technology, and independent of external images or fonts.

Body slides use one central visual and one takeaway instead of stacking several boxed summaries.
History retains its chronology and qualifications; examples stay labeled. Meaning, observed state,
policy, approval, execution, and independent effects remain distinct. ObjectSet examples name the
actual `truncated` and `truncation_reason` fields rather than invented receipt flags.

Interpretation branches show alternative meanings, not resource relationships. Query graphs label
their scope and direction; the agent diagram connects independent roles to an event bus rather than
to each other. Comparison closure stays separate from an unscorable hold. These distinctions are
covered by [test/ontology-diagrams.test.mjs](test/ontology-diagrams.test.mjs).

Preserve presentation-size text rather than shrinking it to resolve crowding. Check the actual
browser viewport, text bounds, contrast, connector endpoints, and neighboring content regions.
A hidden shared browser can report a zero-size viewport; that is not responsive-validation evidence.
Use a local Chromium context for repeatable dimensions and inspect a full-size screenshot as well.

## Validation

Run `npm --prefix tools/manual-studio run check` from the repository root. The opening contracts in
[test/prototype.test.mjs](test/prototype.test.mjs) protect its content boundaries and stylesheet scope.
When adding a runtime-loaded asset, update the
[static artifact allowlist](../../scripts/deployment/azure/build_manual_studio_artifact.py) and its
[integration test](../../tests/integration/scripts/test_build_manual_studio_artifact.py).

Store screenshots and PDFs outside the repository. Record only performed checks, their slide scope,
and the tested content revision; retain older evidence as history rather than silently relabeling it.

### English presentation layout

[english-layout.css](english-layout.css) contains the English-only typography and layout corrections.
It loads after the shared styles in both viewers. Keep primary text at presentation size; shorten
display copy or rebalance the content regions instead of hiding overflow or shrinking the text.

Use [test/english-visual.mjs](test/english-visual.mjs) with an absolute artifact directory outside the
checkout. Its optional arguments select comma-separated modes (`desktop`, `tablet`, `mobile`,
`fullscreen`, `print`) and manual IDs. Review desktop captures before the smaller viewports and PDF
output. The runner waits for fonts and animations, requires painted text, and checks clipping,
overlap, card bounds, cover-image occlusion, and measured connectors. Its fixtures deliberately
break these conditions to prove the checks detect them.

Review the actual shared browser as well as the local Chromium output: fallback font metrics can
change wrapping. PDF contact sheets help compare slides, but inspect corrected pages at full size
and verify each book's page count and 16:9 MediaBoxes. The append-only English layout review in
[validation-evidence.json](validation-evidence.json) records the tested scope and source digests;
it does not grant human approval or remove a manual's `DRAFT` mark.

## Related guidance

| To learn about | Read |
|----------------|------|
| Presentation and evidence standards | [Manual Studio guide](../../.github/skills/manual-studio/SKILL.md) |
| Meaning and authority boundaries | [FDAI Constitution](../../docs/roadmap/architecture/fdai-constitution.md) |
| The operating meaning model | [Operating ontology](../../docs/roadmap/architecture/operating-ontology.md) |
