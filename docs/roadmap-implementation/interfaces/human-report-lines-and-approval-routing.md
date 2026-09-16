# Human Report Lines and Approval Routing implementation ledger

This ledger tracks the source implementation, focused verification, hardening, and operational
evidence for document-derived human report lines and their use in selected approval routes.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Reporting-edge contracts and lifecycle | implemented | `current change`; 439 focused Python tests | Immutable cases, two-phase activation, exact-edge compensation, bounded retention, expiry, conflict, and supersession are implemented. |
| Governed organization-document extraction | implemented | `current change`; worker and ingestion API tests in the focused run | The admitted document path emits cited candidates, avoids unnecessary interpreter calls, and abstains on ambiguous or unsupported layouts. |
| Identity comparison, confirmation, and Owner review | implemented | `current change`; Core and fixed-agent workflow tests | Endpoint confirmation and independent Owner review stay separate, replay safely, and produce no `ActionRun`. |
| Current graph projection and Console | implemented | `current change`; 34 Console tests, production build, and two Playwright scenarios | Principal-filtered cases and graph views support batch submission, responsive review, and reject authority-bearing projections. |
| Requester consent and HIL routing | implemented | `current change`; HIL, runtime, Operator, and Playwright tests | Consent is action-, path-, and scope-bound; delivery, escalation, and resolution revalidate current authority. |
| Shadow rollout and operational evidence | not-started | Design owner | No live route, promotion, or tenant evidence is claimed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-16 | in-progress | Adopted the design and implementation ledger without reconstructing prior report-line behavior. | `current change`; canonical design and dependency-ordered plan | Implement and verify every bounded source slice, then record critique and delivery evidence. |
| 2026-09-16 | implemented | Added document-derived reporting edges, endpoint confirmation, independent Owner review, current-graph routing, requester contact consent, Operator projections, and Console workflows. | 414 focused Python tests; strict mypy on 57 changed modules; Ruff; 32 Console tests; Console typecheck and production build; two focused Playwright scenarios; localization, design-route, document-size, stewardship, and pantheon-layout gates | Complete the recorded critique rounds and retain protected delivery evidence. |
| 2026-09-16 | implemented | Completed 22 critique and hardening rounds. Independent Core and HIL residual reviews at `38f85b819` reported only Low-or-lower findings. | Commits and focused evidence in the hardening table; delivery tracked by [#1159](https://github.com/dotnetpower/fdai/issues/1159) | Record protected PR, CI, and merge evidence on #1159 after publication. |
| 2026-09-16 | implemented | Reconciled the final hardened implementation and local evidence without claiming live deployment validation. | 439 focused Python tests; strict mypy on 58 changed modules; Ruff on 78 Python files; 34 Console tests; Console typecheck and production build; two focused Playwright scenarios; localization, design-route, document-size, stewardship, and pantheon-layout gates | Collect live directory, notification, and promotion evidence only in a separately authorized deployment. |

#### Hardening evidence

| Round | Severity | Result | Evidence |
|-------|----------|--------|----------|
| 1 | High | Avoided sending organization documents to a grounded interpreter when deterministic extraction already produced an edge. | `01abca8da`; worker tests |
| 2 | Medium | Pinned contact-command time to immutable consent evidence so HTTP retries remain identical. | `3fbe75e42`; Operator and contract tests |
| 3 | Medium | Rejected report-line and contact projections that claim approval or execution authority. | `3f925f163`; Console decoder tests |
| 4 | High | Converted invalid, cyclic, and depth-bounded paths to audited route-unavailable outcomes. | `9a590a4d1`; Core routing tests |
| 5 | Medium | Rejected unsupported report-line quorum at policy construction. | `37826b6ee`; policy tests |
| 6 | Critical | Removed the accidental 32-edge organization limit with linear whole-graph cycle detection. | `db02fadcb`; 40-edge regression |
| 7 | Critical | Fenced endpoint decisions before graph activation with the resumable `activation_pending` state. | `e75ed106b`; deterministic interleaving test |
| 8 | High | Terminalized unanswered and late contact consent as audited no-ops. | `ad77123da`; coordinator and reaper tests |
| 9 | High | Replaced whole-graph freshness coupling with path-scoped revisions. | `b8b3846ea`; unrelated-change regression |
| 10 | High | Removed quadratic historical validation from approval reads. | `698e67d2a`; read-path regression |
| 11 | Medium | Required exact principal, ActionType, and target-scope approval policy. | `43d42fdaf`; runtime policy tests |
| 12 | Medium | Made completed confirmation and Owner-review transitions replay-safe. | `8eb19e8b7`; lifecycle and agent tests |
| 13 | Medium | Bounded relationship validity and future scheduling to 366 days. | `c3e133332`; lifecycle boundary tests |
| 14 | Medium | Revalidated stored confirmer identity as an exact relationship endpoint. | `e316f1d56`; model tamper test |
| 15 | Medium | Added route, path, and graph evidence to terminal approval audits. | `701f6330a`; HIL audit assertions |
| 16 | Low | Covered escalation-time role, ActionType, scope, path, and second-rung revalidation. | `8dc88fce7`; runtime and ladder tests |
| 17 | Medium | Labeled undispatched consent expiry as a lifecycle transition, not autonomy enforcement. | `21470c922`; audit-mode assertion |
| 18 | Medium | Converged consent responses that race a terminal expiry instead of returning an internal error. | `0791fc009`; injected CAS-race test |
| 19 | Medium | Restored router and coordinator coverage for a route with no eligible ancestor. | `91bd566c3`; no-park/no-delivery assertions |
| 20 | High | Added structural precheck and a durable conflict exit for graph activation failures. | `d83183800`; deterministic conflict test |
| 21 | Medium | Compacted expired and superseded aggregate entries while retaining immutable case and audit evidence. | `f458dda2f`; expiry and supersession tests |
| 22 | High | Retracted the exact graph edge when a competing terminal case state won the ACTIVE CAS. | `38f85b819`; deterministic compensation race test |

### Remaining work

- [x] Implement the source and focused tests for every scope row.
- [x] Record at least ten distinct critique and hardening rounds with no unresolved finding above Low.
- [x] Track protected delivery evidence on [#1159](https://github.com/dotnetpower/fdai/issues/1159).
- [ ] In a separately authorized deployment, record live directory, notification, and promotion evidence without inferring it from source tests.
