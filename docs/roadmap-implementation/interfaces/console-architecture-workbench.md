# Console Architecture Workbench implementation ledger

This ledger records the current implementation state and reviewable evidence for the focused
Architecture workbench owner.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Geometry-less Landscape and Resource focus | implemented | `architecture-{landscape-layout,boundaries,map-layout}.*`; focused Console tests | Returned containment produces finite generated geometry, an 8-scope Landscape, and a direct-first 36-record focus without using API coordinates. |
| Network and Impact presentation | implemented | `architecture-network-focus.ts`; shared topology SVG; Blast Radius integration; focused model and browser tests | Network overview is bounded to 2 VNet, 4 Subnet, and 4 related role records separately from complete path evidence. Found paths and inferred Impact Subnet membership remain visible without changing source semantics. |
| Reviewed icon asset loading | implemented | `architecture-network-icon-urls.ts`; `architecture-network-icons.ts`; `vite.config.ts`; focused icon and browser tests; Console typecheck and production build | Interactive graphs resolve static icon URLs without eager Vite URL modules. Raw SVG content remains available only to the self-contained export path, and loopback development serves reviewed assets only from within the repository root. |
| Accessibility and responsive operation | implemented | bilingual catalogs; topology SVG; synthetic Playwright at four widths; six independent review passes | Visible summary counts match accessible names. Mobile targets, keyboard navigation, Fit, full screen, reduced motion, and forced colors retain the read-only task. |
| Architecture action visibility | implemented | `console/src/architecture-entry-points.test.ts`; focused shell, route, and browser tests; Console typecheck | Architecture remains registered and available through contextual Resource drill-downs and direct URLs, while Governance and every other Console screen omit dedicated Architecture-labeled actions. |
| Exact-source post-fix evidence | in-progress | authenticated standard-5273 failure baseline; isolated 5274 SSO and access-boundary attempt | The failure baseline is exact-source. Post-fix exact-source rendering requires the merged revision on the standard 5273 origin; no alternate-origin CORS or authentication control was weakened. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-17 | implemented | Kept reviewed shared icons available in the loopback Vite server after splitting URL-only resolution from raw export sources. | `current change`; focused Vite config test; focused Ontology browser test verified every rendered icon request returned HTTP 200. | No remaining local-development asset-boundary work for this slice. |
| 2026-09-17 | implemented | Split reviewed network icon URLs from raw export sources and removed eager Vite URL-module imports from Ontology Instances. | `current change`; focused Vitest (`125 passed`); Console typecheck; production build; transformed icon module inspection (`72` eager SVG proxy requests reduced to `0`) | Retain exact-source post-merge timing evidence on the standard 5273 origin before claiming runtime validation. |
| 2026-09-17 | implemented | Removed the remaining dedicated Architecture actions from Live, Onboarding, Rules, and Impact scope while preserving contextual Resource drill-downs. | `current change`; `console/src/architecture-entry-points.test.ts`; focused Vitest (`50 passed`); Playwright (`1 passed`); Console typecheck; production build and entry budget (`448441` raw / `140937` gzip, 67 lazy imports) | No work remains for cross-screen Architecture action visibility. Exact-source Architecture rendering remains separately in progress. |
| 2026-09-17 | implemented | Removed the Architecture entry from Governance Explorer while preserving the registered panel and direct route. | `current change`; `console/src/components/navigation-shell.tsx`; focused Vitest (`37 passed`); Playwright (`1 passed`); Console typecheck | No work remains for menu visibility. Exact-source Architecture rendering remains separately in progress. |
| 2026-09-15 | implemented | Reduced the post-merge live Landscape and Network overview density after direct standard-5273 review found 9 px Landscape summary text and a 28% Network Fit. | `current change`; standard-5273 measurements; dense 500-record model and browser fixtures; focused Vitest (`190 passed`); typecheck; production build and entry budget (`482790` raw / `149959` gzip, 63 lazy imports); Playwright (`6 passed`); Landscape Fit `100%`, Network Fit `62%`, unique positions, fitted scroll bounds, and zero document overflow; five independent reviews ended with no Medium-or-higher or Low finding. | Retain the reduced limits on the merged standard-5273 route before changing exact-source evidence to `validated`. |
| 2026-09-15 | implemented | Corrected the live geometry-less inventory regression and completed 22 focused critique-and-hardening rounds. | `current change`; geometry-less 500-record tests; focused Vitest (`185 passed`); typecheck; build and entry budget (`482762` raw / `149952` gzip, 63 lazy imports); synthetic Playwright (`5 passed`); six independent reviews ended with no Medium-or-higher or Low finding. | Retain post-merge exact-source rendering on the standard 5273 origin before changing the evidence row to `validated`. |

### Remaining work

- [ ] Open the merged revision on the authenticated standard `http://localhost:5273/architecture`
  route and retain measured finite geometry, bounded displayed counts, nonzero boundaries, unique
  positions, and responsive desktop/mobile evidence.
