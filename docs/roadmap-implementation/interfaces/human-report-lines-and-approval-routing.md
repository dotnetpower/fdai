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
| 2026-09-17 | implemented | Included the optional acceptance-recovery loader in the Core wheel without changing report-line dependencies, contact consent or approval policy. | `current change`; four Core wheel checks and six acceptance composition cases passed. | No report-line source or authority changed; live rollout remains separate. |
| 2026-09-17 | implemented | Kept registered anomaly preparation and current approval readback separate from human requesters, reporting subjects, contact consent and approval eligibility. | `current change`; 291 focused agent/runtime/layout/commerce tests passed. | No report-line behavior or authority changed; existing live rollout remains separate. |
| 2026-09-16 | implemented | Scoped the requester contact-consent scan to current `awaiting_contact_consent` records before its completeness check, so terminal approval history cannot make the optional Console panel unavailable. | `current change`; `postgres_report_line_contacts.py`; `test_postgres_report_line_contacts.py`; 9 focused Operator tests; strict mypy on the changed source and test; Ruff | Retain protected CI and merge evidence. Live rollout remains separately authorized. |
| 2026-09-16 | implemented | Added the dedicated inventory-manifest helper to the explicit Core wheel inventory without creating a report-line dependency. | `current change`; focused Core wheel payload test and design-impact gate | No human-report-line behavior changed. |
| 2026-09-16 | implemented | Kept the shared inventory invalidation cursor outside report-line state, approval evidence, routing, and authority. | `current change`; design-impact gate and focused Operator inventory-state tests | No human-report-line behavior changed. |
| 2026-09-16 | in-progress | Adopted the design and implementation ledger without reconstructing prior report-line behavior. | `current change`; canonical design and dependency-ordered plan | Implement and verify every bounded source slice, then record critique and delivery evidence. |
| 2026-09-16 | implemented | Added document-derived reporting edges, endpoint confirmation, independent Owner review, current-graph routing, requester contact consent, Operator projections, and Console workflows. | 414 focused Python tests; strict mypy on 57 changed modules; Ruff; 32 Console tests; Console typecheck and production build; two focused Playwright scenarios; localization, design-route, document-size, stewardship, and pantheon-layout gates | Complete the recorded critique rounds and retain protected delivery evidence. |
| 2026-09-16 | implemented | Completed 22 critique and hardening rounds. Independent Core and HIL residual reviews at `38f85b819` reported only Low-or-lower findings. | Commits and focused evidence in the hardening table; delivery tracked by [#1159](https://github.com/dotnetpower/fdai/issues/1159) | Record protected PR, CI, and merge evidence on #1159 after publication. |
| 2026-09-16 | implemented | Reconciled the final hardened implementation and local evidence without claiming live deployment validation. | 439 focused Python tests; strict mypy on 58 changed modules; Ruff on 78 Python files; 34 Console tests; Console typecheck and production build; two focused Playwright scenarios; localization, design-route, document-size, stewardship, and pantheon-layout gates | Collect live directory, notification, and promotion evidence only in a separately authorized deployment. |
| 2026-09-16 | implemented | Corrected hardening commit references after rebasing and integrating the latest protected base; the earlier pre-rebase hash remains historical evidence only. | Rebased hashes in the hardening table; focused validation is required again before publication. | Retain the new focused results and protected PR evidence on #1159. |
| 2026-09-16 | implemented | Revalidated the complete feature after integrating the latest protected base. | 439 focused Python tests; strict mypy on 58 source modules; Ruff on 78 Python files; 34 Console tests; Console typecheck and production build; two Playwright scenarios; full translation, catalog, design-route, document-size, roadmap-ledger, and stewardship gates | Publish the exact local head and retain protected CI and merge evidence on #1159. |
| 2026-09-16 | implemented | Reconciled repository route, service-test, wheel, transport-version, and generated question-bank inventories exposed by protected regression shards. | 56 focused inventory and generation tests passed; official `build_question_bank.py` output; PR #1164 CI diagnosis | Retain the next exact-head protected CI result on #1159. |
| 2026-09-16 | implemented | Regenerated the semantic intent coverage derived from the updated question bank. | Official `build_semantic_intent_coverage.py` output and focused artifact parity test | Retain the next exact-head protected CI result on #1159. |

#### Hardening evidence

| Round | Severity | Result | Evidence |
|-------|----------|--------|----------|
| 1 | High | Avoided sending organization documents to a grounded interpreter when deterministic extraction already produced an edge. | `826290220`; worker tests |
| 2 | Medium | Pinned contact-command time to immutable consent evidence so HTTP retries remain identical. | `3d89e8ae2`; Operator and contract tests |
| 3 | Medium | Rejected report-line and contact projections that claim approval or execution authority. | `fc6322715`; Console decoder tests |
| 4 | High | Converted invalid, cyclic, and depth-bounded paths to audited route-unavailable outcomes. | `4e1007fc9`; Core routing tests |
| 5 | Medium | Rejected unsupported report-line quorum at policy construction. | `71b6f58fe`; policy tests |
| 6 | Critical | Removed the accidental 32-edge organization limit with linear whole-graph cycle detection. | `348b993bd`; 40-edge regression |
| 7 | Critical | Fenced endpoint decisions before graph activation with the resumable `activation_pending` state. | `49cace6b3`; deterministic interleaving test |
| 8 | High | Terminalized unanswered and late contact consent as audited no-ops. | `534a21894`; coordinator and reaper tests |
| 9 | High | Replaced whole-graph freshness coupling with path-scoped revisions. | `2ef258f8e`; unrelated-change regression |
| 10 | High | Removed quadratic historical validation from approval reads. | `909eac438`; read-path regression |
| 11 | Medium | Required exact principal, ActionType, and target-scope approval policy. | `dd389f325`; runtime policy tests |
| 12 | Medium | Made completed confirmation and Owner-review transitions replay-safe. | `a20cfc8c0`; lifecycle and agent tests |
| 13 | Medium | Bounded relationship validity and future scheduling to 366 days. | `e3ff2d526`; lifecycle boundary tests |
| 14 | Medium | Revalidated stored confirmer identity as an exact relationship endpoint. | `b8d07c99a`; model tamper test |
| 15 | Medium | Added route, path, and graph evidence to terminal approval audits. | `a91fb7b7c`; HIL audit assertions |
| 16 | Low | Covered escalation-time role, ActionType, scope, path, and second-rung revalidation. | `ec382dea7`; runtime and ladder tests |
| 17 | Medium | Labeled undispatched consent expiry as a lifecycle transition, not autonomy enforcement. | `33826b7ce`; audit-mode assertion |
| 18 | Medium | Converged consent responses that race a terminal expiry instead of returning an internal error. | `c294c4103`; injected CAS-race test |
| 19 | Medium | Restored router and coordinator coverage for a route with no eligible ancestor. | `21c18a5ab`; no-park/no-delivery assertions |
| 20 | High | Added structural precheck and a durable conflict exit for graph activation failures. | `071b41ed9`; deterministic conflict test |
| 21 | Medium | Compacted expired and superseded aggregate entries while retaining immutable case and audit evidence. | `418c84efd`; expiry and supersession tests |
| 22 | High | Retracted the exact graph edge when a competing terminal case state won the ACTIVE CAS. | `fd7200d3c`; deterministic compensation race test |

### Remaining work

- [x] Implement the source and focused tests for every scope row.
- [x] Record at least ten distinct critique and hardening rounds with no unresolved finding above Low.
- [x] Track protected delivery evidence on [#1159](https://github.com/dotnetpower/fdai/issues/1159).
- [ ] In a separately authorized deployment, record live directory, notification, and promotion evidence without inferring it from source tests.
