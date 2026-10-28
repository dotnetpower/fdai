# Console Web Notifications implementation ledger

This ledger tracks delivery of
[Console Web Notifications](../../roadmap/interfaces/console-web-notifications.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Incident-independent Finding attention | implemented | `console/src/findings.ts`; `finding-attention.tsx`; `finding-notifications.tsx`; `/findings` Reader projection; focused tests and `console/tests/e2e/findings.spec.ts` | Foreground attention and evidence details remain separate from hidden-page OS delivery. New/reopened/escalated/recovered versions use stable per-principal deduplication; unavailable and Sample content never become live evidence. |
| Personal channel selection | implemented | `console/src/routes/settings-system.tsx`; `console/src/components/browser-notification-control.tsx`; focused Settings tests | Settings is canonical and the header is a synchronized shortcut. Selection is scoped to the authenticated principal and current browser profile. |
| Browser capability and leadership | implemented | `console/src/browser-notifications.ts`; `console/src/browser-notification-transport.ts`; `console/src/hooks/browser-stream-leader.ts`; focused capability and leadership tests | Secure context, Notifications, Web Locks, and a verified worker or page-session receiver are required. Session delivery is explicitly labeled, and failures remain visible. |
| Delivery ledger and acknowledgement | implemented | `console/src/browser-notifications.ts`; `console/public/notification-sw.js`; focused ledger and worker tests | Display and click acknowledgement are separate, token-bound, bounded, browser-local, and serialized across same-origin tabs. Cross-account click recovery locates exactly one originating ledger. |
| Presentation and localization | implemented | paired component and Settings catalogs; Console build; authenticated browser checks | Header and Settings states remain synchronized, localized, and responsive at the scoped viewports and 200% text. |
| Correlation evidence navigation | implemented | `console/src/browser-notifications.test.ts`; `console/src/notification-service-worker.test.ts`; `console/tests/e2e/incidents-intervention.spec.ts` | Runtime alerts open Audit without assuming Incident membership or inheriting Sample mode. Legacy Live Incident selections offer localized audit recovery. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-28 | implemented | Added current-Finding polling, visible-page attention, paginated evidence details and hidden-page notifications without requiring an Incident. Retained existing browser claims, verified transport, delivery limits, account isolation and closed click targets. Kept Finding code and catalogs lazy without relaxing the initial bundle budget. | `current change`; `npm --prefix console run typecheck` passed; 54 focused Finding/notification/settings tests and 32 owning worker/route tests passed; `npm --prefix console run build` passed (148760 initial gzip bytes, limit 150000); seven isolated browser scenarios passed, including English/Korean 1440/993/390 px Finding and structured-policy layouts, background delivery, reload deduplication and severity escalation. | Fixtures prove local behavior, not live cloud detection, a human-confirmed operational OS alert, a Core delivery receipt or closed-browser Push. |
| 2026-10-28 | implemented | Added a labeled page-session receiver after bounded worker failure, gated by explicit selection and a real native notification `show` event. Kept principal selection, claim fencing, generic bodies, closed scoped click targets, and acknowledgement fragments unchanged. Receiver readiness stays pending until verified, survives a same-tab reload without another connection probe, and can be retried while the selection remains checked. Native display tags are bounded SHA-256-derived keys; canonical event tags and tokens are unchanged. Focus does not restart a failed receiver. | `current change`; transport, ledger, worker, and catalog tests (48 passed); Console typecheck passed; English/Korean activation, restoration, retry, deselection and 1440/993/390 px browser checks (2 passed). The shared Console at `localhost:5273` displayed a connection notification and a 133-character diagnostic event through its bounded native display key, without transient user activation and while hidden; one notification leader and the selected receiver remained healthy during the bounded observation. | Native display was observed through the browser API, not a human-confirmed operational alert or Core delivery receipt. Closed-page delivery is not added. |
| 2026-09-15 | implemented | Replaced the assumed Incident notification destination with correlated Audit evidence, retained scoped legacy click handling, and added localized recovery from missing Live Incident selections. | `current change`; #1038; focused notification, service-worker, data-mode, Incident, and catalog tests; seven focused desktop browser scenarios; Console typecheck. | Operating-system notification display and click confirmation remains a human validation step. |
| 2026-09-14 | implemented | Serialized every delivery-ledger mutation across tabs, retained the latest delivery status when re-enabling, and made component-catalog calls explicit. | `current change`; focused browser-notification and catalog-usage regression tests plus Console build. | Retain human-confirmed operating-system notification evidence before claiming live desktop validation. |
| 2026-09-14 | implemented | Restricted notification-click navigation to controlled clients inside the registered Console scope. | `current change`; focused unrelated-same-origin window regression test. | No known out-of-scope same-origin navigation remains. |
| 2026-09-14 | implemented | Added explicit `console-web` selection, local delivery and click receipts, bounded recovery, cross-tab synchronization, token fencing, and responsive bilingual presentation. | `current change`; focused tests, build, bundle gate, localization checks, browser measurements, and code review. | Retain human-confirmed operating-system notification evidence before claiming live desktop validation. |
| 2026-09-14 | implemented | Added Settings > Integrations as the canonical personal selection surface and resolved final review findings around listener timing, account changes, same-document state, and selection-versus-health semantics. | `current change`; focused regression tests and final independent review. | Add another personal channel only after a verified principal endpoint and matching delivery path exist. |

### Remaining work

- [x] Verify Finding attention, evidence navigation, Sample-to-Live isolation, background delivery,
  reload deduplication and escalation with the scoped browser scenarios recorded above.

- [x] Verify bounded worker failure, explicit session display proof, long-tag mapping, original
  event and claim preservation, reload, focus, retry and deselection with the 2026-10-28 focused
  tests and bounded shared-browser diagnostics recorded above.
- [ ] Capture a human-confirmed Windows or macOS notification display and click receipt from the
  canonical Console origin.
- [ ] Add closed-browser Web Push only after a separately approved authenticated service,
  encrypted subscription storage, revocation, CSRF protection, and server-side delivery audit
  exist.
