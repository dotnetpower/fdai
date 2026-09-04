---
name: console-ui-ux
description: "Design, implement, review, or refine FDAI Console routes and static UI mocks. Use for Console web UI, frontend UX, visual hierarchy, premium polish, typography, navigation, cards, panels, tables, responsive layout, accessibility, screenshots, Playwright visual checks, overflow, or design mock parity."
argument-hint: "Describe the Console route, component, mock, or visual problem"
---

# FDAI Console UI/UX

Build quiet, precise operational interfaces for FDAI Console and its static design mocks. Premium
quality comes from reduction, alignment, and trustworthy state presentation rather than decoration.

## When to Use

Load this skill when work touches:

- Console routes, shells, navigation, cards, panels, tables, filters, drawers, or Command Deck UI.
- Static pages under `mocks/ui/` or the repository-root design mock index.
- Typography, spacing, hierarchy, responsive behavior, accessibility, or visual consistency.
- Browser screenshots, frontend critique, visual regression, overflow, clipping, or interaction polish.

Do not use this skill for backend-only behavior with no operator-facing presentation.

## Sources of Truth

Read the applicable repository instructions before editing. In particular:

- `.github/instructions/app-shape.instructions.md` owns Console topology and visual boundaries.
- `ui/calm-slate-tokens.css` owns shared foundation and semantic typography tokens.
- `ui/calm-slate-primitives.css` owns presentation primitives shared by Console and mocks.
- `console/src/styles.css` owns production Console composition.
- `mocks/ui/assets/calm-slate.css` owns static mock composition over shared tokens.

Existing product behavior and the active design system win over examples in this skill.

## Product Direction

FDAI Console is a work-focused operational surface, not a marketing site. Optimize for repeated
scanning, comparison, evidence review, and bounded action. The interface should feel calm even when
the underlying system is busy.

Use these principles:

1. **Reduce simultaneous signals.** One element should own the primary message in each region.
2. **Keep authority visible.** Separate measured, unavailable, pending, failed, and synthetic state.
3. **Prefer hierarchy over containers.** Spacing, alignment, type, and rules should organize most
   pages. Cards are for repeated items or genuinely bounded tools.
4. **Use color locally.** Color belongs on the status datum, not the container edge or every menu row.
5. **Make the actual viewport the design surface.** Validate the Console route or mock shell users
   really open, including nested iframe width where applicable.

## Workflow

### 0. Complete Desktop First

Treat desktop and responsive validation as sequential gates, not one simultaneous edit loop.

1. Establish the desktop baseline at `1440x900`, or the collaborator's actual desktop viewport.
2. Finish desktop functionality, hierarchy, geometry, pointer hit targets, overflow, and clipping
  before opening a constrained desktop or mobile viewport. A known desktop defect blocks
  responsive validation.
3. Run the narrowest focused check and capture the desktop screenshot and measurements. The
  desktop gate passes only when the actual route, representative data states, and primary
  interactions are correct.
4. After desktop passes, validate constrained desktop at about `993x641`, then mobile at
  `390x844`. Responsive fixes must preserve the accepted desktop baseline; rerun the cheapest
  desktop geometry check after a responsive edit.

Do not inspect or tune mobile in parallel with an unresolved desktop layout. The only exception is
an explicitly mobile-only request when the desktop baseline is already known to pass.

### 1. Locate the Actual Surface

- Identify the real route, shell, and owning stylesheet before changing pixels.
- For production Console work, reuse the standard `http://localhost:5273` full-stack page.
- For static mocks, distinguish the repository-root `http://127.0.0.1:5373/` master index from
  `mocks/ui/index.html` and direct mock pages. They are separate navigation surfaces.
- Capture one before screenshot and measure viewport, container width, overflow, and active state.

### 2. State a Falsifiable Visual Hypothesis

Name one local cause and one cheap check. Examples:

- "Always-expanded groups create navigation noise; collapsing inactive groups should reduce the
  sidebar scroll height while preserving the active route."
- "The specimen remains two-column inside a narrow iframe; an earlier container-driven breakpoint
  should remove crowding without changing semantic type metrics."

Make the smallest edit that lets the check discriminate, then validate before widening scope.

### 3. Establish Hierarchy

Order visual emphasis as follows unless the route has a stronger domain need:

1. Page identity and current operational state.
2. Primary measured value, decision, or work item.
3. Supporting evidence and comparison.
4. Metadata, provenance, and technical annotation.

Do not give headings, badges, borders, code chips, and helper copy equal contrast. When everything
speaks loudly, the page reads as unfinished.

### 4. Implement with Shared Roles

- Reuse semantic typography roles before adding a literal `font-size`.
- Reuse existing components and tokens before creating a local variant.
- Keep data contracts and machine values unchanged while improving presentation.
- Preserve narrowest drill-down destinations for data-bearing cards.
- Keep loading skeletons, unavailable states, errors, and empty states visually distinct.

### 5. Validate in the Browser

Run focused tests first, then inspect the live surface in this order:

1. Desktop: `1440x900` or the collaborator's actual desktop viewport. Complete this gate before
  continuing.
2. Constrained desktop: about `993x641` when using the shared VS Code browser.
3. Mobile: `390x844` for routes and mocks expected to support narrow screens.

Check computed styles and geometry, not only screenshots. A screenshot can hide overflow or an
inactive control outside the crop.

Classify an explicit UI scenario as exactly one of:

- `passed`: every declared assertion was exercised and supported by evidence.
- `failed`: at least one exercised assertion did not hold.
- `needs-human`: the remaining step requires a human action that automation must not perform.
- `needs-infrastructure`: the harness cannot exercise the assertion with the available local setup.

Skipped or unexercised steps never count as `passed`. Record the local evidence location and whether
it was checked for sensitive or customer-identifying content. Screenshots, traces, and videos remain
optional unless the request or owning test contract requires them.

## Navigation

- Keep a single dominant active cue: quiet surface tint plus a complete border or outline.
- Avoid decorative status dots on every item. Show a color marker only when it carries meaning.
- Collapse inactive groups when a rail contains more content than one viewport. Keep native button
  semantics and `aria-expanded` on group controls.
- Prefer a rail near `240-248px` for a dense desktop tool unless the established Console shell owns
  another tested width.
- Expose one dominant content scroll. Secondary rails may scroll, but their scrollbar should not
  compete visually when idle.
- Keep file paths, diagnostics, and implementation labels out of the primary header. Move them to
  technical details, a tooltip, or a copy action.
- Use the real FDAI brand asset. Do not invent placeholder initials when a committed logo exists.

## Typography

Use the shared semantic roles in `ui/calm-slate-tokens.css`:

| Role | Intended use |
|------|--------------|
| Page title | Route or bounded workspace identity |
| Page subtitle | One-sentence route purpose |
| Lead | Deliberately prominent explanatory copy |
| Section title | Major content section |
| Panel title | Bounded panel or repeated item title |
| Body | Default readable prose and evidence explanation |
| Compact | Dense operational facts and row summaries |
| Label | Controls, keys, and short uppercase metadata |
| Caption | Chart axes and secondary technical annotation only |

Rules:

- Do not introduce arbitrary half-step sizes when a semantic role fits.
- Keep body text at a readable measure, usually `68-76ch`.
- Use caption text sparingly. Primary operational information should not be 11px.
- Test English, Korean, timestamps, and long machine identifiers together.
- Letter spacing stays `0` except an established compact label pattern that requires otherwise.

## Layout and Spacing

- Use an 8px spacing rhythm. Common section gaps are `44-56px`; common content gaps are `8-24px`.
- Align titles, descriptions, controls, and data to a small set of shared vertical lines.
- Give dense rows stable grid tracks so dynamic content cannot resize the layout unexpectedly.
- Increase spacing before adding a border, card, badge, or background.
- Do not nest cards. Do not turn full page sections into floating cards.
- Keep card radius at 8px or less unless an existing component contract says otherwise.
- Avoid colored top or left rails, decorative gradients, orbs, bokeh, and ornamental status bars.

## Color and Surfaces

- Start with neutral text, surface, and hairline tokens.
- Use one accent family for selection and links. Semantic colors are reserved for actual state.
- Reduce the number of colored elements before reducing saturation further.
- Use shadows only when elevation communicates interaction or stacking. Flat report sections should
  usually use spacing and hairlines.
- Never use color as the only status or selection cue.

## Responsive Behavior

- Choose breakpoints from container pressure, not device labels. An iframe may be narrow on a wide
  desktop.
- Switch a two-column specimen or form to one column before text becomes cramped.
- Long Korean copy and opaque identifiers must wrap without expanding the page.
- Controls must not overlap, clip labels, or shift layout when values change.
- Mobile interactive targets should be at least 44px where touch interaction is expected.

## Accessibility and Interaction

- Prefer native links, buttons, tables, headings, details, inputs, and lists.
- Every icon-only command needs an accessible name and a tooltip when its meaning is not obvious.
- Keep visible `:focus-visible` treatment on every interactive element.
- Disclosure controls expose `aria-expanded`; current navigation exposes `aria-current` or an
  equivalent active contract.
- Respect `prefers-reduced-motion`. Motion may confirm a change but must not encode status alone.
- Prevent nested interactive elements and whole-card links containing independent controls.

## Validation Checklist

Before reporting completion:

- [ ] The actual Console or master mock URL was opened, not a substitute shell.
- [ ] The desktop functional and visual gate passed before constrained or mobile validation began.
- [ ] The accepted desktop baseline still passes after responsive edits.
- [ ] Focused component or contract tests pass.
- [ ] Console TypeScript changes pass `npm --prefix console run typecheck`.
- [ ] Production-impacting Console CSS passes `npm --prefix console run build`.
- [ ] Desktop, constrained desktop, and applicable mobile screenshots were reviewed.
- [ ] `scrollWidth <= clientWidth` for the document and primary content region.
- [ ] Active navigation, disclosure state, loading, unavailable, error, and empty states remain clear.
- [ ] Long English, Korean, timestamp, and identifier samples fit without overlap.
- [ ] Reduced-motion and keyboard focus behavior remain usable.
- [ ] Shared tokens or docs were updated when the visual contract changed.
- [ ] Explicit scenarios report `passed`, `failed`, `needs-human`, or `needs-infrastructure`.

Report measured outcomes. Do not claim runtime or visual validation from source inspection alone.
