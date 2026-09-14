# Console Web Notifications implementation ledger

This ledger tracks delivery of
[Console Web Notifications](../../roadmap/interfaces/console-web-notifications.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Personal channel selection | implemented | `console/src/routes/settings-system.tsx`; `console/src/components/browser-notification-control.tsx`; focused Settings tests | Settings is canonical and the header is a synchronized shortcut. Selection is scoped to the authenticated principal and current browser profile. |
| Browser capability and leadership | implemented | `console/src/browser-notifications.ts`; `console/src/hooks/browser-stream-leader.ts`; focused capability and leadership tests | Secure context, Notifications, Service Worker, and Web Locks are required. Worker and leader failures remain explicit. |
| Delivery ledger and acknowledgement | implemented | `console/src/browser-notifications.ts`; `console/public/notification-sw.js`; focused ledger and worker tests | Display and click acknowledgement are separate, token-bound, bounded, and browser-local. Cross-account click recovery locates exactly one originating ledger. |
| Presentation and localization | implemented | paired component and Settings catalogs; Console build; authenticated browser checks | Header and Settings states remain synchronized, localized, and responsive at the scoped viewports and 200% text. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | implemented | Restricted notification-click navigation to controlled clients inside the registered Console scope. | `current change`; focused unrelated-same-origin window regression test. | No known out-of-scope same-origin navigation remains. |
| 2026-09-14 | implemented | Added explicit `console-web` selection, local delivery and click receipts, bounded recovery, cross-tab synchronization, token fencing, and responsive bilingual presentation. | `current change`; focused tests, build, bundle gate, localization checks, browser measurements, and code review. | Retain human-confirmed operating-system notification evidence before claiming live desktop validation. |
| 2026-09-14 | implemented | Added Settings > Integrations as the canonical personal selection surface and resolved final review findings around listener timing, account changes, same-document state, and selection-versus-health semantics. | `current change`; focused regression tests and final independent review. | Add another personal channel only after a verified principal endpoint and matching delivery path exist. |

### Remaining work

- [ ] Capture a human-confirmed Windows or macOS notification display and click receipt from the
  canonical Console origin.
- [ ] Add closed-browser Web Push only after a separately approved authenticated service,
  encrypted subscription storage, revocation, CSRF protection, and server-side delivery audit
  exist.
