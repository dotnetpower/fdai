# Documentation site UI/UX review

This review records the theme and usability fixes verified locally on
2026-09-13. It covers the GitHub Pages documentation site, not the Console or
Manual Studio, and does not claim publication or deployment.

## Scope

- **Pages:** English and Korean home, Get Started, SRE, architecture, diagram
  gallery, roadmap, and the long operator-console reference.
- **Themes:** Light, dark, and system preference. The landing retains its dark
  brand background; documentation articles and search respect the reader's theme.
- **Viewports:** 1440x900, 993x641, 390x844, and 320x844, tested in that order.
- **States:** Default, hover, keyboard focus, selected action, expanded menu,
  search results and empty results, 200% text enlargement with spacing overrides,
  forced colors, reduced motion, and reading without JavaScript.

## Findings and completed plan

| Priority | Finding | Change | Verification |
| --- | --- | --- | --- |
| P0 | Light-theme secondary hero links had 1.13:1 text contrast on the dark landing. Partial color overrides also affected notes, action details, and the footer. | Added a complete landing-only palette and explicit default, hover, and focus colors. Kept the article and search palettes separate. | Both themes pass scoped contrast checks; all six hero/footer actions exceed 4.5:1 in tested states, including the brightest bounded decorative backdrop. |
| P1 | Get Started card text reached only 3.15:1 in light mode; dark documentation-card descriptions reached 4.48:1. | Replaced translucent hard-coded card surfaces with theme tokens, increased readable text roles, and aligned grid children. | Both themes pass the affected contrast checks. |
| P1 | Landing step numbers, colored chart labels, and a gradient sample approval had insufficient or unreliable contrast. | Used readable text colors, bounded backdrop brightness, and solid contrasting fills. | Text checks and 3:1 chart-fill/track checks pass. |
| P1 | Header overrides also styled search-dialog buttons. | Restricted overrides to the search opener and restored a readable search placeholder. | Search opens, returns results, reports no results, restores focus, and navigates to the correct localized document. |
| P1 | The mobile landing hid both theme and language controls; the Korean desktop theme label was truncated. | Kept the native selectors accessible in a compact mobile layout and allocated space for the full Korean label. | Theme switching, locale navigation, and measured selected-label fit pass. |
| P1 | Mobile search, menu, and diagram controls were 32-40px high; the menu button retained a false expanded state. | Used 44px standalone targets and synchronized the actual button's expanded attribute with the existing menu implementation. | Target geometry, Enter/Escape, menu visibility, and focus restoration pass. |
| P1 | The enhanced SVG exposed buttons inside an image role. Unselected node text was faded even though it remained actionable. | Changed only the enhanced SVG to a labeled group and retained readable node labels. The downloadable image is unchanged. | Nested-interactive checks, arrow-key navigation, selection, closing details, and focus restoration pass. |
| P1 | Enlarged long identifiers and minimum grid tracks caused horizontal overflow. At 320px, English hero words split mid-word at normal text size. | Bounded flex/grid children, allowed appropriate wrapping, used a smaller minimum headline size, and gave enlarged headers real layout space. | No document overflow at the four declared widths, including enlarged text; word-range checks pass for default headlines. |
| P2 | Starlight paragraph margins displaced children inside the action explorer. | Isolated component spacing from prose rules. | Reviewed final component screenshots and keyboard selection checks. |
| P2 | Wide tables lacked an explicit keyboard scroll stop. Static illustrations resembled live approval controls. | Made only overflowing tables focusable and labeled both illustrations as examples. The approval illustration now states a request instead of presenting an action. | Keyboard table scrolling, visible example labels, and no-JavaScript reading checks pass. |

## Validation evidence

| Check | Result |
| --- | --- |
| Browser regression matrix | 200 distinct scenarios passed: 50 per viewport. |
| Final visual refinements | 40 affected scenarios rechecked after headline, theme-label, and explorer-spacing changes; unchanged evidence reused. |
| Focused source and viewer checks | 27 passed. |
| UI test types and browser helper syntax | Passed. |
| Diagram viewer TypeScript | Passed. |
| Production build and artifact validation | Passed: 148 routes, 148 publication records, 108 diagram embeds, no Mermaid runtime containers. |
| Active development preview | Task-owned source and generated viewer compared with the tested worktree; representative pages captured locally. |

Browser tests use the production `/fdai/` base path and a real generated
Pagefind index. Development mode intentionally displays Starlight's search
availability notice instead of an index. The [site README](README.md#theme-and-interaction-checks)
describes how to rerun the checks.

Detailed measurements and screenshots remain in ignored local review artifacts.
The captures contain only the public documentation surface and no customer data.

## Limits and follow-up

- **Representative coverage:** The browser matrix covers shared templates and
  interactions, not every paragraph on all 148 routes. Link and artifact checks
  cover all generated routes.
- **Accessibility evidence:** Automated WCAG A/AA checks, DOM semantics,
  measured contrast, keyboard checks, and screenshots do not replace a human
  screen-reader review. SVG text and background combinations that axe reports
  as incomplete were not counted as automated passes.
- **Browser scope:** Chromium was tested locally. No Safari, Firefox, physical
  touch device, or assistive-technology certification is claimed.
- **Quality score:** No aggregate rubric score is reported because a complete
  assistive-technology review remains unmeasured. No confirmed defect in the
  declared executable scenarios remains open.
- **Delivery:** These are local implementation and validation results. No
  commit, push, GitHub Actions run, or GitHub Pages deployment was requested.

## Related files

| Purpose | File |
| --- | --- |
| Theme surfaces and focus | [theme-surfaces.css](src/styles/theme-surfaces.css) |
| Responsive controls and reflow | [responsive.css](src/styles/responsive.css) |
| Browser regression configuration | [playwright.config.ts](playwright.config.ts) |
| Shared documentation UI checks | [theme-accessibility.spec.ts](test/ui/theme-accessibility.spec.ts) |
| Adaptive behavior checks | [adaptive-controls.spec.ts](test/ui/adaptive-controls.spec.ts) |
| Contrast and progressive fallback | [contrast.spec.ts](test/ui/contrast.spec.ts) |
| Navigation, search, and diagram checks | [interactions.spec.ts](test/ui/interactions.spec.ts) |
