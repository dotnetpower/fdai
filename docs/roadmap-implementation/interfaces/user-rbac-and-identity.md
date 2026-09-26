# User RBAC and Entra Identity implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Runtime capability checks, `RoleEnforcer.no_self_approval`, and
> risk-gate quorum are implemented. CI now joins exact-head GitHub PR, commit, review, and Check Run
> facts to an Entra principal bundle emitted by a configured trusted verifier App. Missing trusted
> attestation fails closed. Runtime callbacks require justification and current Entra authority.
> Deploying that App, recording the human OID trailer at draft creation, and the complete
> `@aw-approvers` CODEOWNERS layout remain open.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Human and workload identity separation for activity observation | implemented | `fdai_operator_service/activity_projection.py`; `test_activity_projection.py`; the authenticated observation contract in this document | Durable current-state activity carries only a hashed correlation reference, while the Reader bearer gate and the relay workload credential remain separate and no activity row gains executor authority. |
| Reader interactive conversation boundary | implemented | `services/operator-service/src/fdai_operator_service/family_authorization.py`; `services/operator-service/tests/test_operator_workload_auth.py`; focused authorization checks | Human Reader principals may submit `chat.stream` with their exact Reader scope. Legacy exchange, background, mutation, approval, and execution operations retain their higher role floors. |
| Break-Glass activation request boundary | implemented | `services/operator-service/src/fdai_operator_service/families/iam/break_glass.py`; `capabilities.py`; `services/operator-service/tests/test_operator_break_glass_activation.py` | `POST /system/break-glass/activation` requires the BreakGlass-only `activate-break-glass` capability, a non-empty incident id and reason, and a future offset-aware expiry inside a bounded maximum. It records an audit-only projection and grants no HIL approval or executor identity. The durable activation store, TTL enforcement, and sign-in alerting remain deployment work. |
| Human approval callback identity | implemented | `families/iam/hil_callback.py`; `hil_callback_authority.py`; `hil_decision_outbox.py`; `postgres_iam.py`; focused callback, persistence, Kafka, workflow, and canary tests | Teams uses a separate team/channel audience and mapped current Entra authority. Slack can operate independently with complete workspace mapping. BreakGlass retains its existing global behavior but remains unable to approve. |
| Slack signed actor handoff | in-progress | `families/iam/slack_handoff.py`; `console/src/routes/hil-queue.tsx`; focused Operator/Console and synthetic desktop checks | Signed Slack click mints a short-lived nonce digest tied to original action, workspace, sender, mapping revision, and expiry. A decision requires a fresh signed Entra API-token `auth_time`; missing claims fail closed. The authenticated provider journey and actual Slack posting are unverified. |
| Local Browser Entra session resilience | implemented | `console/src/auth-session.ts`; `console/src/auth.ts`; focused Console auth tests (`10 passed`) and typecheck | MSAL Browser v4 uses encrypted `localStorage` only on loopback origins and keeps deployed origins on `sessionStorage`. One coalesced refresh runs at startup, every 30 minutes, and after focus, visibility, or network recovery. Entra can still require interactive authentication. |
| Console IAM projection recovery | implemented | `console/src/routes/settings-iam.tsx`; shared retry state; focused Console unit and Playwright checks | A failed initial Identity and access projection remains visible and can repeat the same authorized read without reloading the console, changing the verified principal, or granting capability. |
| Owner-scoped document OCR policy | implemented | IAM capability checks, document OCR settings routes, PostgreSQL adapter, and focused Operator tests | Only Owner can save the revisioned provider policy or request its protected plan. The capability grants no apply, provider mutation, approval, or executor authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-26 | in-progress | Added service-owned Slack interaction verification and one-use handoff to the existing audited HIL decision service. | `current change`; `slack_handoff.py`, `hil-queue.tsx`, focused IAM and Console tests. | Retain fresh Entra optional-claim, PostgreSQL race, authenticated browser, and real Slack click evidence before #943 criterion 3 is closed. |
| 2026-09-15 | implemented | Added bounded retry for an initial Console IAM projection failure while preserving the verified principal and authorization boundary. | `current change`; `settings-iam.tsx`; focused Console unit, browser, typecheck, and production build checks. | Obtain required pushed-head CI and protected merge evidence with the Console resilience batch. |
| 2026-09-15 | implemented | Allowed human Reader principals to submit the interactive semantic stream while retaining Contributor or higher for legacy exchange, background, mutation, approval, and execution operations. | `current change`; `family_authorization.py`; `test_operator_workload_auth.py`; focused authorization checks. | No live Entra or Browser runtime evidence is claimed; retain it separately if required. |
| 2026-09-04 | implemented | Reused the Owner-only `manage-model-bindings` capability for revisioned document OCR policy and protected-plan requests without widening BreakGlass or other human roles. | `current change`; IAM routes, manifest, PostgreSQL adapter, and focused Operator tests. | Retain a deployed authorization-denial and Owner plan-request receipt. |
| 2026-08-13 | implemented | Adopted the implementation ledger without reconstructing earlier provenance and recorded the bounded identity carried by durable current-state activity. | Current source plus `test_activity_projection.py`; the focused persistence and projection suites passed. | Add the separately designed production Break-Glass activation boundary. |
| 2026-08-15 | implemented | Added the `POST /system/break-glass/activation` request boundary with a BreakGlass-only capability, incident id, reason, bounded future expiry, and an audit-only projection. | `current change`; `services/operator-service/src/fdai_operator_service/families/iam/break_glass.py`; `pytest services/operator-service/tests` (308 passed, 1 skipped). | Bind a durable activation store, TTL enforcement, and sign-in alerting in a deployment. |
| 2026-08-21 | implemented | Added a loopback-only durable MSAL cache and one lifecycle-owned proactive refresh loop without changing deployed token storage or API verification. | `current change`; `console/src/auth-session.ts`; `console/src/auth.ts`; `console/src/app.tsx`; focused auth tests passed 10 cases and Console typecheck passed. An unretained loopback Browser check restored a second tab with no MSAL `sessionStorage` entry and observed one successful startup refresh. | Retain a governed Browser receipt across a webview recreation or overnight suspension before claiming runtime validation. |
| 2026-08-31 | implemented | Replaced callback-supplied authority and added stable signed decision time, first-timestamp audit idempotency, proposal-first recovery, durable Kafka publication, bounded workflow callback context, and independent Teams team/channel audience. | `current change`; focused Operator IAM, PostgreSQL, Kafka, composition, workflow, and local canary checks. | Retain governed deployed Teams OBO and broker-acceptance receipts without storing a token or tenant value. |

### Remaining work

- [ ] Confirm a signed API access-token `auth_time` from fresh Entra login after a Slack click and a real PostgreSQL one-use receipt with current mapping and no-self-approval; retain authenticated Console and Slack delivery evidence for #943 criterion 3.
- [x] The production Break-Glass activation endpoint exists, requires an incident id, a reason, and a bounded future expiry, records the activation audit evidence, and grants no runtime HIL approval or executor identity, proven by `services/operator-service/tests/test_operator_break_glass_activation.py`.
- [ ] Bind a durable activation store, TTL enforcement, and sign-in alerting in a deployment, and retain one governed activation receipt.
- [ ] Retain one governed loopback Browser receipt across a webview recreation or overnight suspension without exposing cached authentication artifacts. A Conditional Access or MFA challenge remains an interactive authentication boundary.
