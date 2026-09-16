# Human Report Lines and Approval Routing implementation ledger

This ledger tracks the source implementation, focused verification, hardening, and operational
evidence for document-derived human report lines and their use in selected approval routes.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Reporting-edge contracts and lifecycle | implemented | `current change`; 414 focused Python tests | Immutable cases, revision-fenced graph activation, expiry, conflict, and supersession are implemented. |
| Governed organization-document extraction | implemented | `current change`; worker and ingestion API tests in the focused run | The admitted document path emits cited candidates and abstains on ambiguous or unsupported layouts. |
| Identity comparison, confirmation, and Owner review | implemented | `current change`; Core and fixed-agent workflow tests | Endpoint confirmation and independent Owner review stay separate and produce no `ActionRun`. |
| Current graph projection and Console | implemented | `current change`; 32 Console tests, production build, and two Playwright scenarios | Principal-filtered cases and graph views support batch submission and responsive review. |
| Requester consent and HIL routing | implemented | `current change`; HIL, runtime, Operator, and Playwright tests | Consent is action- and route-bound; delivery and resolution revalidate the current route and policy. |
| Shadow rollout and operational evidence | not-started | Design owner | No live route, promotion, or tenant evidence is claimed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-16 | in-progress | Adopted the design and implementation ledger without reconstructing prior report-line behavior. | `current change`; canonical design and dependency-ordered plan | Implement and verify every bounded source slice, then record critique and delivery evidence. |
| 2026-09-16 | implemented | Added document-derived reporting edges, endpoint confirmation, independent Owner review, current-graph routing, requester contact consent, Operator projections, and Console workflows. | 414 focused Python tests; strict mypy on 57 changed modules; Ruff; 32 Console tests; Console typecheck and production build; two focused Playwright scenarios; localization, design-route, document-size, stewardship, and pantheon-layout gates | Complete the recorded critique rounds and retain protected delivery evidence. |

### Remaining work

- [x] Implement the source and focused tests for every scope row.
- [ ] Record at least ten distinct critique and hardening rounds with no unresolved finding above Low.
- [ ] Retain protected exact-head CI and merge evidence for the delivered change.
- [ ] Keep live directory, notification, and promotion evidence separate until a deployment supplies it.
