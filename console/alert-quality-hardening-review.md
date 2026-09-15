# Alert quality browser review

This review records the isolated Console UI checks for alert-noise hardening round 12.
The browser imports the real route and shell with a test-only identity module response and
intercepted synthetic API records. It is not Browser Entra or provider validation.

## Scope and evidence

- Route: `/alert-quality`; Live presentation of explicit test fixtures, English and Korean.
- Navigation: default collapsed rail; evidence and retained-plan disclosures both expanded.
- Browser: Chromium; desktop 1440x900 first, then 993x641 and 390x844.
- Inputs: route-local report/Settings fixtures and signed-in test principal, no actual credentials.
- [Browser scenarios](tests/e2e/alert-quality.spec.ts): 12 passed after the request-history extension;
  271 Console tests and TypeScript passed. The later baseline metadata addition rechecked desktop
  history and Korean expanded geometry across all three viewports.
- DOM checks: document and main have no horizontal overflow; standalone route controls are at
  least 44px high. The existing inline title breadcrumb is excluded from that standalone target
  requirement, not hidden or changed.
- Interaction: keyboard submits routing once; suppression and threshold forms send one exact
  treatment; Settings sends one revision-bound PUT; ambiguous POST and conflicting PUT never retry.
- State: missing/expired reports allow reassessment but not proposals; anonymous mode sends no
  alert reads or writes; loading has a semantic skeleton with reduced motion.
- Request history: exact baseline and canonical Process links are visible in recorded details.
  A deliberate exact-original-key terminal read can reconcile a previously uncertain request;
  a general evidence refresh or an unconfirmed result cannot. No POST is resent.
- Local screenshot names: `alert-quality-en-desktop.png` and `alert-quality-ko-{1440,993,390}.png`
  in the runner's temporary output. Inspected images contain synthetic references only.
  The main scroll container means a full-page capture can show only its opening viewport. Dedicated
  `alert-history-*` captures scroll the actual baseline into view; neither image proves unvisited
  content or a complete keyboard/assistive-technology matrix.

## Rubric assessment

All 50 criteria are selected for this new route. A local behavioral pass is not a complete rubric
score. `U` means evidence is still needed, not an inapplicable feature or a passing assertion.

| Criteria | Rating | Evidence or remaining verification |
|----------|--------|------------------------------------|
| UX-01, UX-04, UX-05, UX-08, UX-14, UX-18, UX-19, UX-20 | 4 | Reviewed bilingual screenshots, exact route/authority/source labels and neutral surfaces. |
| UX-10, UX-13, UX-24, UX-26, UX-27, UX-28, UX-29, UX-30, UX-33, UX-34, UX-38, UX-40, UX-43, UX-45 | 4 | Exercised forms, evidence disclosures, error states, geometry, labeled native controls and reduced-motion skeletons. |
| UX-02, UX-03, UX-06, UX-07, UX-11, UX-12, UX-15, UX-16, UX-17, UX-21, UX-22, UX-23, UX-25, UX-31, UX-32, UX-35, UX-36, UX-37, UX-39, UX-41, UX-42, UX-44, UX-46, UX-47, UX-48, UX-49, UX-50 | U | Full contrast, all-keyboard navigation, assistive technology, 320px/200% text, content extremes and authenticated full-stack verification remain unmeasured. |
| UX-09 | N/A | This is a scrollable evidence/task route, not a dashboard with an agreed first-screen metric budget. |

Evidence coverage is 22/49 applicable criteria (44.90%); no final quality score is assigned.
Overall rubric disposition: `needs-infrastructure` for standard authenticated full-stack evidence;
assistive-technology validation additionally needs a human. Test scenarios themselves passed, but
that does not close these broader evidence gaps or imply operational readiness.
