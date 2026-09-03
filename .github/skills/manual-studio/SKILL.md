---
name: manual-studio
description: "Create, edit, review, or validate FDAI Manual Studio books and slides. Always use for tools/manual-studio/** content, catalog, visuals, typography, album art, presentation copy, PDF output, or deployment packaging. Applies PowerPoint-style readability, Microsoft Learn-inspired language, FDAI semantic accuracy, visual storytelling, responsive validation, and evidence requirements."
argument-hint: "Describe the Manual Studio book, slide, visual, or presentation problem"
---

# FDAI Manual Studio

Create Manual Studio books as presentation-ready alternatives to PowerPoint. Every deck should help
an executive, operator, or technical decision-maker understand the problem, see how FDAI works,
evaluate the controls, and decide what to do next without reading source code or roadmap documents.

This skill is mandatory for every change under `tools/manual-studio/**`. The
`manual-studio` route in `scripts/lib/design-routes.json` loads it automatically.

## Sources of Truth

Use repository artifacts before presentation conventions:

- `tools/manual-studio/catalog.json` owns the book catalog, journey stage, level, status, slide count,
  cover, duration, and description.
- `tools/manual-studio/manual-content.js` owns shared deck registration and general builders.
- A substantial book should use its own `tools/manual-studio/<book-id>.js` and
  `tools/manual-studio/<book-id>.css`.
- `tools/manual-studio/assets/provenance.json` owns published image provenance.
- `tools/manual-studio/validation-evidence.json` records completed hardening and rendering evidence.
- FDAI roadmap documents own product behavior, implementation status, authority, and metrics.

Presentation polish never overrides the FDAI Constitution, current implementation status, or
evidence. A slide may simplify a concept, but it must not invent a capability, customer result,
operating metric, authorization, or deployment state.

## Required Workflow

### 1. Define the Decision

Before writing, state:

- Who is viewing the deck.
- What decision they should be able to make.
- What concern or operating problem brings them to the deck.
- Which journey stage and level fit the content.
- Which roadmap documents prove each product claim.

If the audience or decision is unclear, the deck is not ready for layout work.

### 2. Give Every Slide One Job

Classify each slide as one of:

- Problem context.
- Product value.
- Operating workflow.
- Architecture or relationship explanation.
- Decision or option comparison.
- Safety or authority boundary.
- Measurement or operational outcome.
- Adoption readiness.
- Call to action.

One slide should answer one primary question. Split a slide that tries to explain value,
implementation, safety, and next steps at the same time.

### 3. Design the Story Before the Components

A complete product story normally follows this progression:

1. Why the current operating experience is difficult.
2. What outcome FDAI enables.
3. How signals and evidence become a decision.
4. How authority, execution, recovery, and verification remain controlled.
5. How the result is measured.
6. What the reader can start with.

Do not repeat the same claim in different card layouts. Each slide must add a new decision,
relationship, boundary, metric, or action.

### 4. Write the Full Proposition

Draft important statements as:

`actor + action + evidence or constraint + result`

Example:

`FDAI는 같은 장애 구간의 신호를 서비스 관계와 시간 근거로 연결해 운영자가 대응 우선순위를 판단할 수 있도록 합니다.`

Only shorten the sentence after the actor, constraint, and result remain clear.

### 5. Build the Visual Around the Meaning

Choose a visual form from the concept, not from the previous slide:

- Signal volume or compression: funnel, bar sequence, or operational dashboard.
- Service impact: connected topology or dependency graph.
- Decision logic: evidence stack, decision case, or option board.
- Responsibility: swimlane or authority handoff.
- Recovery: primary/secondary architecture and bounded transition.
- Effect verification: before/after chart plus authoritative outcome.
- Time: incident timeline or waterfall.
- Metrics: scorecard with unit, window, baseline, and decision purpose.
- Adoption: phased path with explicit entry and exit evidence.

Cards are one option, not the default. Three or more consecutive card or flow slides require a
redesign.

## PowerPoint Substitute Standard

Manual Studio is projected, presented in meetings, exported to PDF, and reviewed on shared screens.
Treat the 16:9 reference page as `16in x 9in`, or `1536 x 864` CSS pixels at 96 dpi.

[Microsoft PowerPoint accessibility guidance](https://support.microsoft.com/en-us/accessibility/powerpoint/make-your-powerpoint-presentations-accessible-to-people-with-disabilities)
recommends 18pt or larger text. Use that as the primary body floor, not as a target to shrink toward.

### Font Sizes

| Role | PowerPoint equivalent | CSS size on the 1536px reference page |
|------|-----------------------|----------------------------------------|
| Deck or section title | 30-36pt | 40-48px |
| Slide title | 28-32pt | 37-43px |
| Lead or subtitle | 18-22pt | 24-29px |
| Primary body and decision text | 18pt minimum | 24px minimum |
| KPI or key number | 28-40pt | 37-53px |
| Secondary label | 14-16pt | 19-21px |
| Technical evidence footer | 10-12pt | 13-16px |

Rules:

- Decision-critical text must never use the technical-footer size.
- Secondary labels may be below 18pt only when the slide remains understandable without reading
  them.
- Do not fix overflow by shrinking primary text below the floor. Shorten copy, reduce regions, or
  split the slide.
- Use a simple sans-serif stack. Keep weight, contrast, and line height sufficient for projection.
- Limit a title to two lines and a lead to two short lines at the reference size.
- A paragraph should not exceed three lines. Prefer a short statement plus a visual.
- Inspect the real slide at `1440x900` and in fullscreen. A contact sheet is for comparison, not for
  judging final readability.

CSS `clamp()` values must preserve these roles at the reference page. When browser previews scale a
fixed 16:9 slide down, preserve hierarchy rather than allowing labels to become larger than body
text.

### Layout and Density

- Reserve about 55-70% of the content region for the primary visual.
- Keep one dominant visual and one supporting evidence region.
- Use whitespace to separate ideas, not to compensate for missing content.
- Avoid empty cards with one short phrase in a large box.
- Align content to a small number of shared axes.
- Use color for state and comparison, not decoration.
- Never rely on color alone. Pair it with a label, line style, icon, or value.
- Keep corners, borders, shadows, and gradients quiet. Information hierarchy should lead.

### Connectors and Diagrams

- Nodes and connectors must share one coordinate system. Prefer CSS Grid for box-and-line diagrams.
- Do not combine percentage-positioned nodes with fixed SVG coordinates.
- A connector must touch the intended node boundary within 1 CSS pixel at the desktop reference
  viewport.
- Vertical branches need visible space between nodes so the connecting segment can be seen.
- Arrow direction, line style, and color must have a legend or an obvious semantic meaning.
- Validate the geometry with browser bounding boxes, not screenshots alone.

## Microsoft Learn-Inspired Language

Use the approachable, task-oriented style demonstrated by the
[Azure SRE Agent overview](https://learn.microsoft.com/ko-kr/azure/sre-agent/overview?tabs=task).
Follow the style, not the source wording.

### Structure the Explanation

Prefer this order:

1. Start with the reader's operating problem.
2. Explain what FDAI helps the reader accomplish.
3. Give a concrete example.
4. Explain how it works.
5. State configuration, authority, or evidence boundaries.
6. End with a clear next action.

Useful Korean patterns include:

- `~할 수 있습니다.`
- `~하도록 도와줍니다.`
- `예를 들어, ...`
- `다음과 같이 작동합니다.`
- `~하려면 다음을 확인하세요.`
- `구성된 권한과 정책 범위에서 ...`

Use active, polite Korean. Prefer short sentences and familiar verbs. Avoid noun clusters that read
like translated internal contracts.

### Before and After

Avoid:

`가장 낮은 충분한 판단`

Prefer:

`충분한 판단이 가능한 최소 Tier를 선택합니다.`

Avoid:

`FDAI는 숙련된 운영자처럼 검증된 규칙과 지식을 먼저 적용합니다.`

Prefer:

`FDAI는 조직에 축적된 운영 규칙과 표준 절차를 먼저 적용합니다. 새로운 상황에는 현재 근거를 연결해 운영자가 판단할 수 있는 선택지를 제시합니다.`

Avoid:

`불확실하면 보류 · 관찰 모드에서 정확도 검증 · 권한 자동 확대 없음`

Prefer:

`근거가 충분하지 않으면 판단을 보류합니다. 관찰 모드에서 결과를 비교하고 운영자에게 근거와 제안을 보고합니다.`

Avoid:

`하나라도 미충족이면 FDAI 도입 대상이 아닙니다.`

Prefer:

`준비되지 않은 영역은 FDAI로 현재 상태를 진단하고 실행 계획을 마련할 수 있습니다. 실행 권한은 필수 안전장치를 검증한 뒤 검토합니다.`

### Tone Rules

- Lead with what the reader can understand, decide, or do.
- Explain unfamiliar terms on first mention.
- Prefer `사람 승인`, `관찰 모드`, `영향 범위`, `실행 안전장치`, and `복구 작업` in display
  copy.
- Keep canonical terms in code, schema values, and technical correlation details.
- Avoid superlatives, fear language, courtroom tone, and unsupported promises.
- Use `현재 구현`, `예시`, `목표`, and `진행 중` explicitly. Do not make a target look live.
- A safety boundary can remain firm, but explain the useful next step after a hold or block.

## FDAI Product Meaning

Product copy must preserve these distinctions:

- AIOps includes rules, verified reuse, anomaly detection, prediction, learning, and LLM reasoning.
  It is broader than a model call.
- FDAI applies organizational rules and procedures first. Grounded reasoning handles residual
  ambiguity without making AI sound incidental.
- A finding is not automatically an Incident. An Incident is not automatically authority to act.
- Observation, promotion, execution, rollback, and effect verification are separate stages.
- Dispatch or API acceptance is not operational success. A separate authoritative observation must
  confirm the effect.
- Missing safeguards block execution, but FDAI can still diagnose readiness and propose a plan.
- Language never grants authority. No agent approves its own proposal.

### Named Agents

In Korean presentation copy, the first mention uses:

`Norns(학습 후보 제안 담당) 에이전트`

Later mentions use:

`Norns 에이전트`

Apply the same pattern to every Pantheon agent. Do not use a bare agent name as if every reader
already knows the role.

### Metrics

Every displayed metric needs:

- Unit.
- Measurement window.
- Baseline or comparison.
- Inclusion and exclusion rules.
- Decision purpose.

Illustrative values must be labeled `예시`. Never present synthetic values as customer or FDAI
operational results. Remove a metric if the deck cannot explain why it changes a decision.

## Book and Asset Rules

- Every book belongs to one journey stage and meets the catalog's minimum slide count for its level.
- A book has one coherent audience and decision. Split unrelated audiences into separate books.
- Album art must be unique across the catalog and relevant to the title.
- Use repository-owned, authorized, or generated assets only.
- Record every published asset in `assets/provenance.json`.
- Use an empty `alt` only for decorative artwork. Meaningful diagrams need a concise accessible name.
- A substantial book should have a dedicated module and stylesheet rather than expanding shared
  files indefinitely.
- Add new runtime-loaded JS and CSS files to the Azure Manual Studio artifact allowlist and its
  integration test.

## Validation

Complete desktop before responsive validation:

1. Render every slide at `1440x900`.
2. Review every slide at actual size and generate a contact sheet for repetition.
3. Verify text and component bounds programmatically.
4. Verify every diagram connector against node bounding boxes.
5. Render every slide at about `993x641`.
6. Render every slide at `390x844`.
7. Enter fullscreen through `slide-stage` and recheck all slides.
8. Export PDF and confirm page count equals `catalog.json` and every MediaBox is 16:9.
9. Update `validation-evidence.json` only for checks actually performed.

Required outcomes:

- No request failures.
- No text outside the slide.
- No horizontal document overflow.
- No clipped decision-critical text.
- No repeated album-art path.
- No duplicate slide title.
- No connector detached from its intended node.
- All example values are visibly labeled.

Run the focused gates:

```bash
node --check tools/manual-studio/<book-id>.js
npm --prefix tools/manual-studio run check
uv run pytest -q --no-cov tests/integration/scripts/test_build_manual_studio_artifact.py
bash scripts/quality/repository/check-punctuation.sh <changed-files>
python3 scripts/quality/localization/check-readable-hangul.py <changed-files>
python3 scripts/quality/architecture/check-design-routes.py
```

Store screenshots, contact sheets, and PDFs outside the repository in the session artifact folder.
Do not commit local validation output.
