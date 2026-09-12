---
title: UI/UX quality rubric
rubric_version: "1.0.0"
---
# UI/UX quality rubric

Use this rubric to make FDAI Console and static mock reviews repeatable. It defines 50 observable
criteria, a shared scoring scale, and evidence requirements so that visual polish doesn't hide
interaction, accessibility, or information-quality defects.

> A score describes the declared review scope, not the entire product. Even 100 points isn't a
> WCAG certification, proof of user satisfaction, or permission to publish, deploy, or execute.
> The Constitution, product contracts, and shared design tokens remain authoritative.

## What this covers

The rubric has ten areas with five criteria each. Criteria have equal weight; critical conditions
use mandatory gates instead of extra points. Version `1.0.0` is an initial review standard, not a
scientifically calibrated measure of usability.

| Area | IDs | Focus |
|------|-----|-------|
| Purpose and information architecture | UX-01 to UX-05 | What users need to understand and do |
| Layout and hierarchy | UX-06 to UX-10 | Grouping, density, first-screen priorities |
| Typography and language | UX-11 to UX-15 | Readable, consistent text and values |
| Color and visual restraint | UX-16 to UX-20 | Contrast, meaning, quiet presentation |
| Component consistency | UX-21 to UX-25 | Reusable controls, lists, overlays |
| Interaction and recovery | UX-26 to UX-30 | Working flows, feedback, safe actions |
| Data and visualization | UX-31 to UX-35 | Accurate interpretation and evidence |
| Accessible operation | UX-36 to UX-40 | Keyboard, semantics, alternatives, targets |
| Responsive and adaptive behavior | UX-41 to UX-45 | Reflow, enlargement, content extremes, preferences |
| Verification and delivery discipline | UX-46 to UX-50 | State coverage, performance, parity, regression |

## Select the scope before editing

1. Record the exact route or component, mock or production venue, intended task, data mode,
   supported languages, browser, viewport, navigation state, and required interaction states.
2. Start with these twelve core checks: `UX-01`, `UX-02`, `UX-06`, `UX-08`, `UX-11`, `UX-16`,
   `UX-26`, `UX-36`, `UX-37`, `UX-41`, `UX-46`, and `UX-50`. Add every relevant gate and the
   criteria affected by the change. A new route or full redesign normally selects all 50.
3. Record unselected IDs and why they are outside this change. Shared tokens or shell changes
   widen the scope to representative affected consumers, not automatically to the whole product.
4. For a selected criterion, use `N/A` only when its feature genuinely doesn't exist in scope,
   such as form validation on a screen without inputs. Record a reason before scoring.
5. An existing but untested feature is `U`, not `N/A`. Missing infrastructure, authentication, or
   a required human check is an evidence gap. Don't shrink the scope after a failure.

For a dashboard, agree which information should fit the first screen and at which desktop viewport
and navigation state. Don't apply a no-scroll rule to every detail page, mobile viewport, or enlarged
text view. Preserve readability and access to secondary information.

## Score and decide

### Rating scale

| Rating | Meaning |
|---------|---------|
| 0 | Broken, misleading, inaccessible, or absent where required |
| 1 | Major defects obstruct the declared task |
| 2 | Usable, but meaningful inconsistency or friction remains |
| 3 | Sound implementation with a small, explicitly recorded refinement remaining |
| 4 | Meets the criterion throughout the declared scope with supporting evidence and no known defect |
| U | Applicable, but the evidence needed to score it is missing |
| N/A | Selected, but genuinely inapplicable; rationale recorded |

Scores are integers. A screenshot alone can't prove a working request, keyboard behavior, or
screen-reader output. A zero-finding automated scan can't supply the visual or interaction ratings.
For a 3, name the remaining refinement; for a 4, point to evidence rather than writing "looks good."

Let `A` be the number of selected criteria excluding `N/A`, and `E` the number with ratings 0 to 4:

```text
coverage_percent = 100 * E / A
score = 100 * sum(ratings) / (4 * A), only when A > 0 and E == A
```

If `A == 0`, report `not-applicable`, not a passing score. If `E < A`, report the coverage and
missing evidence but leave the final score unset. Unselected items don't enter either denominator.
Report each area's applicable count and mean as well; don't compare different scopes as if their
totals measured the same work.

### Gates and acceptance

`G` marks a gate in the tables below. Every applicable gate needs a rating of 4. In addition,
every other applicable criterion needs at least 3, coverage needs to be 100%, and the unrounded
total needs to be at least 90 before the scoped review can pass.

| Total, after all gates and floors pass | Interpretation |
|---------------------------------------|----------------|
| 95 to 100 | Polished within the evaluated scope |
| 90 to below 95 | Ready for review, with listed minor refinements |
| Below 90 | Refine before calling the scoped work complete |

Use `passed`, `failed`, `needs-human`, or `needs-infrastructure` for an applicable review's disposition.
A known gate failure remains a failure even when the total is high. Missing required evidence
can't produce `passed`; name every blocker and choose the disposition matching the next blocking step.
These are local UI review outcomes, not release authorization.

**Calculation examples, not evaluations of the current dashboard:**

- 40 applicable criteria with 148 points give 92.5. A gate rated 3 still prevents a pass.
- 38 evaluated criteria out of 40 applicable give 95% coverage, not a final quality score.
- Fifty criteria rated 4 give 100 only for the recorded routes, states, and evidence.

## The 50 criteria

Evidence codes: `M` = measured DOM, geometry, timing, or computed styles; `V` = visual comparison
with a written rationale; `I` = exercised keyboard, pointer, or task interaction; `T` = focused
test or contract inspection; `H` = a human usability or assistive-technology check when required.
List what was actually used; a suggested method below doesn't prove that the check ran.

### 1. Purpose and information architecture

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-01 | Clear page purpose | The title and first content identify the task, target, and expected result without relying on internal implementation names. | - | V, I |
| UX-02 | Decision priority | The most important measured condition or next decision is encountered before supporting detail; urgency has an evidence-based reason. | - | V, I |
| UX-03 | Progressive disclosure | Default and expanded states each have coherent headings, grouping, reading order, and usable controls; secondary content isn't a dumping ground. | - | V, I |
| UX-04 | Orientation | Current route, navigation group, filters, and selection are identifiable, with a predictable way back or to the next relevant level. | - | I, T |
| UX-05 | Task-oriented language | Labels and help describe the user's next step consistently; jargon is explained and technical identifiers stay in supporting details. | - | V, I |

### 2. Layout and hierarchy

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-06 | Alignment | Titles, content edges, repeated values, and actions follow a small shared grid rather than accidental offsets. | - | M, V |
| UX-07 | Spacing rhythm | Shared spacing roles distinguish within-group and between-group gaps; compact dashboard exceptions are deliberate and still readable. | - | M, V |
| UX-08 | Meaningful containers | Cards bound real data or action units. Titles and metadata use hierarchy and spacing; decorative nested cards or whole-section boxes are absent. | - | V, T |
| UX-09 | First-screen priorities | A dashboard's agreed essential summary fits the declared default desktop viewport and navigation state without hiding information or shrinking text to force a fit. | - | M, V |
| UX-10 | No obstructed content | Navigation, sticky elements, overlays, and content don't accidentally cover text or controls; no unintended horizontal overflow or clipping occurs. | G | M, I |

### 3. Typography and language

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-11 | Semantic type roles | Page, section, panel, body, label, and caption roles use shared tokens with a visibly ordered hierarchy. | - | M, V, T |
| UX-12 | Comfortable reading | Primary content uses readable body or compact roles, not tiny captions; line height and contrast remain comfortable in the actual viewport. | - | M, V |
| UX-13 | Text measure and wrapping | Paragraphs have a readable measure; headings, long identifiers, and multiline labels wrap without hiding required meaning. | - | M, V |
| UX-14 | Value formatting | Numbers align consistently; units, denominators, precision, dates, and time zones are explicit and appropriate to the evidence. | - | V, T |
| UX-15 | Language consistency | Supported English and Korean text reads naturally, preserves identifiers and product names, and uses the correct language metadata and fallback. | - | V, T, H |

### 4. Color and visual restraint

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-16 | Text contrast | Applicable text meets WCAG AA: 4.5:1 normally, or 3:1 for large text (24 CSS px regular or 14 pt bold); relevant backgrounds and states are tested. | G | M |
| UX-17 | Non-text contrast | Required control boundaries, focus or selection indicators, and meaningful graphics meet applicable 3:1 contrast; decorative and disabled exceptions are identified, not assumed. | G | M, V |
| UX-18 | Semantic palette | Accent and status colors use shared meanings consistently across routes, states, and themes; color doesn't imply unsupported certainty. | - | V, T |
| UX-19 | Restrained surfaces | Whitespace, typography, and alignment carry structure; ornamental gradients, elevation effects, colored rails, and competing accents don't distract from the task. | - | V |
| UX-20 | Meaning beyond color | Status, selection, errors, and chart distinctions remain understandable through text, shape, patterns, or equivalent labels without color alone. | G | V, I |

### 5. Component consistency

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-21 | Shared primitives | Existing components, tokens, and interaction patterns are reused; a necessary variation has a documented purpose rather than a copied local fork. | - | T, V |
| UX-22 | Complete component states | Applicable default, hover, focus, selected, disabled, loading, and error states are coherent and don't introduce unexpected layout movement. | - | M, I |
| UX-23 | Clear affordance | Links navigate, buttons act, and disclosure controls expand; clickable areas and disabled reasons are discoverable without relying on hover. | - | V, I |
| UX-24 | Lists and tables | Labels and values align; headers, sorting, filtering, pagination, and selection describe the displayed data when those features exist. | - | M, I, T |
| UX-25 | Overlay consistency | Dialogs, drawers, menus, and tooltips use appropriate placement, dismissal, ownership, and focus behavior; no nested or ambiguous interaction surfaces remain. | - | I, T |

### 6. Interaction and recovery

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-26 | Primary task works | The scoped task reaches its intended observable result through the real route. A labeled mock interaction is recorded as mock evidence, not backend success. | G | I, T |
| UX-27 | Form guidance | Where inputs exist, requirements and validation are understandable, errors identify the affected field and correction, and useful input survives failure. | - | I, T |
| UX-28 | Honest feedback | Loading, queued, submitted, completed, and effect-verified states are distinct where applicable; feedback doesn't claim success before the authoritative result. | - | I, T |
| UX-29 | Recoverable failures | Applicable retry, cancel, back, reconnect, or undo paths are bounded and predictable; they preserve context and don't duplicate a state-changing request. | - | I, T |
| UX-30 | Authority and harmful actions | UI controls preserve server authorization, current human approval, identity separation, and destructive-action safeguards; no styling or client state bypasses them. | G | I, T |

### 7. Data and visualization

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-31 | Appropriate encoding | Use numbers for lookup, tables for exact comparison, and charts for a genuine pattern; decoration doesn't replace or distort the message. | - | V, I |
| UX-32 | Quantitative fidelity | Axes, areas, scales, intervals, baselines, totals, and rounding agree with the source values and don't exaggerate differences. | G | M, T |
| UX-33 | Honest data states | Zero, missing, unknown, stale, partial, failed, and simulated data remain distinguishable; unavailable evidence is never rendered as a measured zero or healthy result. | G | I, T |
| UX-34 | Provenance and scope | Source, time window, freshness, completeness, and relevant scope can be inspected; the evidence actually supports the visible claim. | G | I, T |
| UX-35 | Useful drill-downs | Data-bearing summaries lead to the narrowest relevant detail, retaining applicable filters, time, scope, and return context; links aren't placeholders. | - | I, T |

### 8. Accessible operation

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-36 | Keyboard completeness | Every scoped task works by keyboard with logical order and no trap; no essential action depends on pointer-only behavior. | G | I |
| UX-37 | Focus management | Focus is visible and not obscured; opening, closing, navigation, and errors move or restore it predictably without an unexpected focus steal. | G | M, I |
| UX-38 | Programmatic semantics | Landmarks, heading order, names, roles, values, labels, and native elements expose the actual structure; custom ARIA doesn't contradict behavior. | G | M, I, T |
| UX-39 | Equivalent information | Charts, icons, images, status changes, and errors have appropriate text alternatives or announcements; required assistive-technology checks use the declared browser/tool pair. | G | I, T, H |
| UX-40 | Targets and input alternatives | Targets are at least 24 by 24 CSS px or meet a recorded WCAG 2.2 AA exception, including permitted spacing; standalone mobile controls meet the 44 by 44 CSS px project target. Essential gestures have a simple alternative. | G | M, I |

### 9. Responsive and adaptive behavior

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-41 | Reflow | Content remains usable at 320 CSS px without unintended two-dimensional scrolling; a genuinely two-dimensional table or visualization has a bounded, justified exception. | G | M, I |
| UX-42 | Text enlargement and spacing | Required information and controls survive 200% text enlargement and user spacing overrides: line height 1.5, paragraph spacing 2em, letter spacing .12em, word spacing .16em. | G | M, I |
| UX-43 | Real container behavior | Desktop, constrained, and mobile composition follows actual container pressure, including master-shell iframes and navigation-open states, not only a standalone page. | - | M, V |
| UX-44 | Content extremes | Empty, single, many, and long-content fixtures, including Korean and opaque IDs where supported, don't break layout or make actions unreachable. | - | M, I, T |
| UX-45 | User preferences | Reduced motion and forced colors preserve meaning and operation; supported themes are consistent, and motion never introduces hazardous flashing. | - | M, I |

### 10. Verification and delivery discipline

| ID | Criterion | Full-score condition | Gate | Evidence |
|----|-----------|----------------------|------|----------|
| UX-46 | State coverage | The declared matrix includes applicable collapsed, expanded, loading, empty, error, stale, denied, and success states; hidden states aren't treated as covered by the default screenshot. | - | I, T |
| UX-47 | Responsiveness budget | A task-specific feedback and rendering budget is agreed before measurement and met without input loss or disruptive layout shifts; lab samples aren't claimed as field percentiles. | - | M, I |
| UX-48 | Truthful parity claims | Mock, isolated test, and authenticated production-like evidence are distinguished. A successful health endpoint or static rendering isn't claimed as a working authenticated screen. | G | I, T |
| UX-49 | Reviewable evidence | The result links exact inputs, scenario assertions, measurements, visual comparisons, and limitations; retained artifacts are checked for sensitive data. | - | M, V, T |
| UX-50 | Repeatability and regression | Baseline and revised results use the same rubric, scope, states, and conditions; relevant regressions are tested and previously passed evidence is reused only when its inputs remain valid. | - | T, V |

## Use the rubric during UI work

1. **Before editing:** Select scope and criteria, record applicability, capture a baseline, and
   state the most important defect that the next change should falsify.
2. **During implementation:** Finish desktop structure and operation before responsive tuning.
   Evaluate both the default and any changed expanded, overlay, error, or permission state.
3. **Before completion:** Run the smallest relevant checks, inspect the actual surface, then score
   the selected criteria. Fix gates first, then criteria below 3, then the largest remaining task friction.
4. **Report:** Include scope, coverage, score or missing-score reason, gates, remaining refinements,
   and evidence. Keep mock implementation, production validation, and publication separate.

Don't treat all 50 criteria as 50 new test commands. Existing contract tests, browser measurements,
and one carefully selected scenario can support several criteria. Conversely, one screenshot doesn't
automatically support every visual rating or any hidden state.

Scoring doesn't authorize live Azure or model calls, credential export, or wider validation.
Use existing local evidence first and report a blocker instead of weakening authentication or
silencing a failing check.

### Review record template

Keep detailed records in a private session artifact or the existing ignored visual-review directory.
Only scrubbed summaries belong in source control.

```yaml
rubric_version: "1.0.0"
surface: "<exact route or component>"
venue: "static-mock"
task: "<observable user goal>"
source_inputs: "<revision or task-owned diff and relevant configuration>"
conditions: "<browser, viewport, navigation state, language, theme, data mode>"
states: ["default", "expanded"]
selected_ids: ["UX-03", "UX-46"]
selection_note: "Illustrative excerpt; a real review includes the core set and relevant gates."
not_selected: "<IDs and scope reasons>"
na: []
ratings:
  - id: "UX-03"
    state: "U"
    score: null
    evidence: []
    finding: "Expanded state has not been inspected."
    next_step: "<check, owner, and expected result>"
summary:
  applicable: null
  evaluated: null
  coverage_percent: null
  score: null
  gates: "not-yet-verified"
  disposition: "needs-human"
  limitations: []
```

For each rated item, record a 0-to-4 integer and the actual evidence. For `U`, keep the score null
and name the missing check. An `N/A` entry needs its reason. A review record should account for every
selected ID; this template is intentionally incomplete and isn't a completed assessment.

## Calibrate without gaming the score

Use the first three different UI tasks to compare ratings between reviewers. Discuss differences
of two or more points using the same screenshots and interactions; don't simply average them away.
For judgment-heavy items, record the comparison and the concrete reason for the rating.

Keep IDs stable. Version changes to criterion meaning, gates, scale, or thresholds; don't silently
change weights or exclusions to improve a score. If the scope changes, retain the old result and
start a revised record. A reviewer can request a refinement even when the numeric floor passes.

## Related docs

| To review | Reference |
|-----------|-----------|
| Console and mock workflow | [Console UI/UX skill](../../.github/skills/console-ui-ux/SKILL.md) |
| Shared typography and controls | [Tokens](../../ui/calm-slate-tokens.css) and [primitives](../../ui/calm-slate-primitives.css) |
| Topology and authority boundaries | [App shape](../../.github/instructions/app-shape.instructions.md) |
| Targeted validation and result reuse | [Coding conventions](../../.github/instructions/coding-conventions.instructions.md#testing) |
| Accessibility criteria and exceptions | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) |

Use the WCAG source for complete requirements and exceptions. This practical rubric groups checks
for UI delivery and doesn't enumerate every WCAG success criterion or replace user research.
