# Homepage editorial and visual review

This review guides the homepage refinement requested on 2026-09-13. It builds on
the corrected theme/accessibility source at `9da85fdc2`, not the older primary
checkout. It changes presentation and orientation copy, never runtime authority.

> The current design and results are in **Premium composition revision** and
> **Premium verification** below. Earlier sections retain the review history;
> their framed-paper composition is no longer the active design.

## Critique

The Korean desktop landing measured approximately 7,625px tall at 1440x900.
The page used a near-black backdrop even when the reader selected the light
theme. The earlier contrast repair made controls readable but did not address
the sustained visual weight or the information architecture.

| Finding | Reader cost | Decision |
| --- | --- | --- |
| Text and controls directly over a dark backdrop | Long-form reading needs stable contrast and a genuinely lighter reading surface. | Preserve the authored nebula and its motion. Put text on theme-aware paper and blue-gray surfaces instead of removing the artwork. |
| Hero starts with a 15-agent organization | Readers must understand implementation before recognizing their own task. | Lead with evidence-to-action cloud operations; explain accountability later. |
| Story arc, control loop, impact list, and agent cards repeat concepts | Scanning requires a long scroll without a clear progression. | Use four sections: outcomes, method, safety, and next steps. |
| Tier percentages are design targets, not measured results | Large numeric graphics invite a performance claim despite the disclaimer. | Remove percentages from the homepage. Keep the authoritative goals and reference documents linked. |
| Full action explorer and engineering phases dominate the end | Technical detail interrupts the first-visit orientation. | Link to the existing ontology, agents, architecture, and roadmap documents. Do not remove those documents. |
| The same three CTA links repeat | Roadmap and repository links compete with understanding and onboarding. | Two hero actions: Get started and How it works. End with purpose-specific reading paths. |

## Initial editorial design (superseded)

The first screen has a short, left-aligned headline and a compact conceptual
flow opposite it. The flow explicitly represents a model of the process, not
live telemetry or an approval. Use one accent family, neutral full borders,
readable secondary text, and generous spacing instead of glows or nested cards.

1. **What it helps with:** Three linked outcomes for Change Safety, Resilience,
   and Cost Governance. No stage labels or invented benefit percentages.
2. **How it works:** Observe with context, decide with rules first, then act
   within authority and verify independently. Decision tier never grants authority.
3. **How control is preserved:** Observation before promotion, applicable human
   approval or standing authorization, separate agent responsibilities, and
   independent effect verification. A native disclosure retains all seven safeguards.
4. **Where to begin:** Product orientation, a bounded pilot, and technical
   architecture. Azure is the implemented target; deployment is not permission
   to enable changes. Reference detail remains one link away.

English and Korean carry the same meaning and section order. Korean should read
as natural product documentation rather than English technical terms with Korean
particles. Keep fixed names and identifiers unchanged when they are needed.

## Design critique and revision

- **Corrected after user feedback:** Removing the nebula exceeded the request.
  The user requested brighter, clearer content, not deletion of the authored
  background. The original shader, stars, colors, intensity, speed, and full-page
  behavior are preserved; stable content surfaces solve contrast independently.
- **Rejected:** Replace implementation detail with promises such as "proven safe",
  "no more incidents", or "only approve the risky few". The scope and evidence
  must support each decision; uncertainty can require a hold or human review.
- **Revised:** Keep the seven safeguards in an accessible disclosure rather than
  deleting safety detail in the name of brevity. Opening it is a tested state.
- **Revised:** Preserve the previous button, mobile selector, keyboard, and
  diagram accessibility fixes. Change tests for the intentionally redesigned
  home; keep existing article/search/diagram coverage.
- **Revised:** Serve this task's source from its own worktree. Do not copy it
  into the clean primary checkout or overwrite the pending publication worktree.

## Sources and validation plan

The content derives from the existing [product orientation](../docs/user-guide/get-started.md),
[deterministic decision model](../docs/user-guide/concepts/deterministic-first.md),
[observation and promotion model](../docs/user-guide/concepts/shadow-then-enforce.md),
and the Constitution's approval, safeguard, and independent verification rules.

Review desktop at 1440x900 first, then 993x641, 390x844, and 320x844. Cover both
languages and themes, automatic theme changes, hover and keyboard focus,
disclosure open/closed, section and document navigation, 200% text enlargement,
forced colors, reduced motion, and no-JavaScript reading. Use source checks,
WCAG A/AA automated scans, explicit contrast measurements, and reviewed images.
Keep generated routes and production `/fdai/` links valid.

The review selects the applicable core UI rubric checks plus content hierarchy,
language, contrast, focus, semantics, reflow, preferences, and evidence. Live
operations, numeric performance, and destructive-action controls are outside
this static orientation page. A passing automated scan is not a screen-reader
certification; report the exact verified scope without a product-wide score.

## Initial editorial verification (before nebula restoration)

- **Homepage scenarios:** 20 scenarios per viewport across desktop, constrained
  desktop, mobile, and 320px reflow. Both languages, both themes, automatic
  switching, button states, native section links, disclosure, and no-JavaScript
  reading were exercised. Final affected enlargement and image checks were
  rerun after wrapping fixes; passing unrelated evidence was reused.
- **Final result:** All 80 homepage scenarios passed against the final source,
  including at least 4.5:1 button text contrast and 3:1 control-boundary and focus
  contrast. Sixteen focused content, safety, navigation, and publication tests
  and the UI TypeScript check also passed.
- **Measured density:** Korean desktop home is approximately 3,276px tall at
  1440x900, down from approximately 7,625px. Four primary sections replace the
  repeated story, percentage chart, catalog, and engineering-phase content.
- **Visual review:** Full-page images cover English and Korean in light/dark at
  all four sizes. The default and expanded safety disclosure survive 200% text
  enlargement with user spacing overrides. No unintended document overflow was
  observed in the checked states.
- **Safety and meaning:** The home retains all seven safeguards, explicit human
  authority, distinct responsibilities, and independent effect verification.
  The flow is labeled conceptual; no result or benefit percentage is presented.
- **Build boundary:** The production `/fdai/` build and publication-link check
  preserve 148 routes and 108 existing diagram embeds. No canonical article or
  diagram source was changed.
- **Active preview:** Port 4321 now serves `feat/docs-home-editorial` directly.
  The shared browser confirmed the new Korean headline, four sections, zero
  document overflow, no nebula canvas, and distinct light/dark surface colors.
  Primary `main` and the prior publication worktree were left unchanged.

This is a local Chromium review, not a cross-browser or screen-reader
certification. It does not change or claim runtime functionality, field
performance, publication, or deployment. The earlier theme-repair record remains
historical; its always-dark homepage description is superseded by this design.

## Nebula restoration

The original `NebulaBackground` component is mounted again without changing its
source. The canvas retains intensity `1`, speed `1`, full opacity, and full-page
placement. The revised four-section content stays intact. The hero copy, article
body, buttons, and footer use stable light/dark surfaces for readability.

The source regression now requires the original component and parameters.
Browser coverage checks actual WebGL draw calls and pixels, continuing frames
with normal motion, and a still frame under reduced motion. Production-preview
checks remain separate from development-toolbar markup.

Restoration verification passed 88 browser scenarios: 22 each at 1440x900,
993x641, 390x844, and 320x844. The focused content/safety tests, UI type check,
and 148-route build check passed. The original nebula source has no diff.
Viewport capture with normal motion confirmed visible clouds and stars, not
only an attached canvas. Full-page captures under reduced motion can clear the
original canvas when capture changes viewport size; they are not used as proof
that the artwork is rendered.

## Premium composition revision

The operator rejected the boxed restoration as visually weak and explicitly
requested a complete premium redesign while retaining the nebula. This revision
supersedes the paper-panel composition, not the preserved artwork or safety copy.

- **Visual cause:** Opaque hero and body panels compete with the nebula. Repeated
  rounded cards flatten the hierarchy and make the artwork look attached after
  the layout rather than integral to it.
- **Chosen direction:** Full-bleed cosmic hero, large unboxed typography, a compact
  header, broad negative space, and a short first-screen action hierarchy. Keep
  the original nebula at full intensity, speed, and opacity. A soft-edged local
  scrim protects text only; it is not a new background or global dimming layer.
- **Reading sequence:** Three unboxed operational columns, a four-stop conceptual
  evidence-to-outcome diagram, distinct accountability statements with the native
  seven-safeguard disclosure, and three deliberate starting paths. No invented
  product metrics, fake live status, or oversized mock interfaces.
- **Theme boundary:** The cosmic hero has coherent light ink in both themes.
  Subsequent full-width reading bands respect light/dark preference and have no
  outer rounded frame. Article pages and their existing header remain unchanged.
- **Critique and revision:** Reject merely replacing white panels with dark glass
  cards; it preserves the same weak composition. Reject adding decorative 3D
  objects or extra animations that compete with the authored nebula. Reuse native
  controls and the original canvas rather than replacing its implementation.
- **Acceptance:** At 1440x900 the first screen shows a large uninterrupted nebula
  region, the primary action, and no boxed hero copy. Validate actual viewport
  images before responsive work. Then check 993x641, 390x844, and 320x844,
  both locales/themes, keyboard flow, expanded safeguards, 200% enlargement,
  forced colors, and reduced motion. Text and control contrast remain measured.

The revised rubric scope includes the existing core checks and all applicable
layout, typography, theme, semantics, focus, reflow, preferences, and evidence
gates. Quantitative data, live workflows, destructive actions, and product forms
do not exist on this static homepage. Missing assistive-technology evidence will
remain explicit, not a claimed full certification.

## Premium verification

The local production build covers 120 distinct browser scenarios, 30 at each of
1440x900, 993x641, 390x844, and 320x844. Focused reruns resolved every observed
failure and cover the changed inputs; reruns are not counted as new scenarios.
Both languages, light/dark/automatic theme behavior, search results and empty
results, keyboard navigation, native disclosure, article-header fallback,
200% text and spacing, forced colors, no-JavaScript reading, and original WebGL
motion are included. Five focused homepage content/safety checks and the UI
TypeScript check passed. The build check retains 148 routes and 108 diagrams.

| Viewport | English page height | Korean page height | Primary action bottom, English / Korean | Document overflow |
| --- | --- | --- | --- | --- |
| 1440x900 | 4254px | 4061px | 705px / 688px | 0px |
| 993x641 | 3971px | 3743px | 598px / 583px | 0px |
| 390x844 | 6251px | 5641px | 613px / 575px | 0px |
| 320x844 | 6975px | 6185px | 684px / 582px | 0px |

These are default, collapsed, local Chromium measurements, not performance
metrics. The longer reading page is an intentional tradeoff for larger type,
full-width bands, and clear section spacing. The first action stays on screen.

- **Visual review:** Reviewed actual nebula viewport images, desktop reading
  bands, an expanded safety disclosure, and narrow English/Korean reading
  crops. Hero and operational columns have no opaque panel, rounded outer
  frame, or card shadow. No new artwork or animation library was added.
- **Artwork preservation:** The original nebula source has no diff. Canvas
  parameters and opacity remain `1`. Instrumented tests observe actual draw
  calls and pixel output, continued motion when allowed, and a still frame
  when reduced motion is selected. The test instrumentation is not product code.
- **Contrast:** Normal text and all action states meet the checked 4.5:1
  threshold. Required action boundaries and focus indicators meet 3:1. The
  local hero backdrop is composited over white as a worst-case shader pixel;
  text remains inside its protected center at normal and 200% text sizes.
- **Corrections from evidence:** Removed reduced opacity from section numbers;
  made the header wrap in document flow when text is enlarged; restricted the
  wide Korean theme label to desktop; and let the local text backdrop grow
  vertically with long copy. A zero document-overflow measurement alone did
  not catch an off-screen fixed header, so controls now have explicit bounds
  assertions. Normal mobile headers retain one row with 44px controls.
- **Scope:** All new presentation is home-scoped. The original article, search,
  diagram, locale, and production-base-path contracts remain exercised. Source
  changes stay in this task worktree; no commit, publication, or deployment is
  part of this review.

Private screenshots and the scoped rubric are under `.fdai/homepage-premium/`.
The full rubric score is intentionally unset: manual assistive-technology review
and an agreed, measured responsiveness budget are not available. Local Chromium
evidence does not claim Safari/Firefox parity, user preference, field performance,
or accessibility certification.

The final task-owned development preview runs on port 4321 from
`feat/docs-home-editorial`. English and Korean return HTTP 200. The shared Korean
browser page confirms the new header, transparent hero copy, four sections,
full-opacity original canvas, and zero document overflow. Its native reduced-motion
preference was preserved. The temporary launch entry was removed after readiness;
the primary and previous publication worktrees retain no site or task-file changes.
