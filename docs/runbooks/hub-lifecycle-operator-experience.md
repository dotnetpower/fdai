---
title: Hub Operator Experience Improvements
---
# Hub Operator Experience Improvements

Use this backlog when designing the next Release Hub and Lifecycle Hub operator journey.
It identifies avoidable manual work without removing the independent trust, customer approval
and installation-local execution boundaries.

> **Scope:** Process and source-based design review, not a complete visual or accessibility audit.
> Proposed behavior below is not a shipped feature or deployment authorization.
> Private target identifiers and operational evidence stay in customer-controlled records.

## What this covers

The recurring journey should be publish, review, admit, stage, plan, execute, observe and recover.
The operator should see what is complete, what is blocked, who owns the next step and where to act.
A screen that looks complete should not hide an engineering console, file transfer or absent Agent.

P1 items block a dependable guided rehearsal. P2 items reduce recurring operational effort.
These priorities describe the operator journey, not a vulnerability severity assessment.

## Improvements for the next design

| ID / priority | Friction or risk | Proposed interaction | Observable acceptance |
|---------------|------------------|----------------------|-----------------------|
| UXH-01 / P1 | Identity, enrollment, ownership, configuration, artifacts and Agent state are split across pages and tools | One installation readiness journey with a responsible role and a next-action link for each prerequisite | An operator can locate every failed prerequisite without private scripts; unknown state is not a green check |
| UXH-02 / P1 | A generic data-loading error does not identify authentication, API permission, DNS, ingress or backend failure | Typed error panels with safe diagnostics and distinct recovery actions | Session expiry, API 401/403, unavailable API and timeout tests each show the correct action; no token, key, DSN or receipt is displayed |
| UXH-03 / P1 | An ingress denial can occur before the application loads; it is easily mistaken for missing application roles | Separate network reachability guidance from identity/role diagnosis; record approved source ranges privately | A blocked source never leads to a role-expansion recommendation; an out-of-band diagnostic path works when the SPA cannot load |
| UXH-04 / P1 | A cached login can fail silently during token renewal | A clear session-expired state and explicit sign-in recovery, preserving read context | An interaction-required failure offers sign-in; uncertain writes require readback before retry and are never replayed automatically |
| UXH-05 / P1 | Similar Hub screens and image packaging can hide which product/build is serving | Persistent product identity, role and immutable build information, backed by build-time target checks | Release and Lifecycle UI assets are verified separately; wrong-product packaging fails before publication |
| UXH-06 / P1 | Catalog revision/digest move through a person, and download metadata can be confused with independent trust | A reviewed public handoff with revision, pin, expiry, publisher and recipient; display independent-source comparison separately | Values transfer without retyping; missing/mismatched independent approval still blocks import; a downloaded pin never approves itself |
| UXH-07 / P1 | Catalog availability is easily confused with signed input delivery or mirrored images | Separate catalog accepted, signatures verified, artifacts available, input staged and fresh report states | A Plan cannot be labelled ready merely because the catalog was imported; each missing transport has an owner and actionable reason |
| UXH-08 / P1 | Installation/configuration key custody and native proof steps need engineering help | A supported setup flow that signs inside the installation and exports only public handoff material | Existing identity keys stay in place; operator acceptance remains separate; no key extraction or trust reset is needed to resume |
| UXH-09 / P1 | An installation row or healthy cluster does not show whether an Agent actually runs | Show last Agent contact, finite Job or resident scheduling mode, PVC readiness and next eligible run | The UI distinguishes an idle/stopped Agent from healthy workload state and from an unavailable report |
| UXH-10 / P1 | Persistent environment lifetime, daily execution windows and Plan expiry look like one time limit | Three explicit settings/status groups: environment retention, execution schedule and current Plan validity | Keeping AKS on never implies unlimited Plan authority; local time, zone and next eligible window are understandable without manual UTC arithmetic |
| UXH-11 / P1 | A terminal or expired Plan may still look like an executable open Plan | Distinguish stored Plan history, terminal outcome and current dispatch eligibility | Terminal/expired Plans are not offered as executable; schedule changes explain the exact blocking condition without bypassing backend guards |
| UXH-12 / P1 | Rollback, release recall, suppression and installed health are independent but appear as one failed status | A failure/recovery timeline with current workload, original failure, recall propagation, hold expiry and next responsible actor | Successful template recovery does not hide failure; suppression lift needs explicit approval; recall and audit remain intact |
| UXH-13 / P1 | Application-neutral labels can overstate what the renderer supports | Show supported execution contract, workload kinds, schema constraints and unmet prerequisites before binding or apply | Changing `product` cannot turn a two-HTTP-component test into full FDAI readiness; unsupported topology is explicitly blocked |
| UXH-14 / P2 | Configuration inventory can look signed even when only a digest or enrollment-created row exists | Distinguish stored metadata, independently signed package, approved revision and active consumption | `Not recorded`, unavailable and verified-empty remain distinct; no signed badge is derived from row existence |
| UXH-15 / P2 | Disabled future menus create uncertainty about permissions and product completeness | Label unavailable capability with its reason and alternative supported procedure, not an inert generic tooltip | Users can distinguish unimplemented, unconfigured and forbidden without trying additional roles |
| UXH-16 / P2 | Operators repeat engineering work after a browser, terminal or Job interruption | Durable resumable setup tasks with exact input digests, last observed result and a safe next command | Resume reads the existing outcome first; accepted enrollment, native creation and publication are not duplicated |
| UXH-17 / P2 | Cleanup is remembered separately from what should remain running and billable | A retention summary for workload, Agent Jobs, cluster, identities and temporary permissions | Finite tests have UID-fenced cleanup and independent absence evidence; retained resources show an owner and cost acknowledgement |
| UXH-18 / P2 | Vendor/customer/setup-owner handoffs rely on chat and have no acknowledgement | Durable tasks and role-specific notifications with a link to exact pending work | Each blocked step has an acknowledged owner; notifications contain public metadata only and never approve or execute work |

## Status of delivered items

- UXH-01/02/04/05/07/09/10/11/12/13/14/15, customer and vendor readiness/recovery increment
  (#2532 / #2534 / #2535): Release Hub adds transactional stage promotion
  (`POST /v1/releases/{id}/promote`), active capability-recall blocker visibility, and one-click
  reviewed confirmation prefill without manual string transcription. Lifecycle Hub adds typed
  error recovery in `AsyncBoundary`, a unified Update Readiness & Next-Step panel, three-horizon
  time summaries (environment anchor, daily schedule, and Plan validity), a Failure/Hold/Recovery
  timeline, an enabled Configuration tab distinguishing stored metadata from verified package
  signatures, working Commands and hash-chained Audit screens, and EN/KO workspace switching.
- UXH-02/04/16, bounded recovery: catalog errors distinguish expired sessions, denied access,
  conflicts, readiness and timeouts without displaying arbitrary server diagnostics. After a
  failed or uncertain write, the dialog closes and the UI reads authoritative catalog state
  before offering a new confirmation. Failed reads disable mutations. Successful HTTP responses
  are not shown as confirmed changes unless readback contains the exact revision, action,
  target, destination and reason event. Reload never replays a write.
- UXH-06: for development catalogs, signed export, pull-only polling, Rego policy adoption and the
  **Updates** screen remove revision and digest transcription. The legacy pin flow remains for
  unsigned and offline exports. Production TUF roles are still design.
- UXH-08: `fdai-lifecycle-hub sign-enrollment` and the bound-installation selection remove file
  path and ID transcription. `fdai-lifecycle-agent enroll` removes the carried file: the Agent
  derives Entities and reported state from its cluster and submits a pending request, and the
  operator compares the key id out of band and accepts. Native proof handoff, configuration-key
  custody and a live Agent submission to an operating Hub remain open.

### Vendor increment boundary

Stencil implementation is deferred. This increment improves the existing single FDAI Release
workspace; it adds no feature catalog, variants, Stencil grants, licensing, or build orchestrator.
The design hypothesis is that one next step plus native evidence disclosures reduces competing
actions while preserving audit and exact-target confirmation.

The critique is that a browser can confuse channel membership with passed promotion gates, and
an accepted request with an observed change. The revised implementation labels membership as
recorded state, leaves missing gate results explicitly unavailable, and verifies the attributed
event on readback. The existing server-side promotion evaluator and its source-membership,
labels, canary, soak, timeout and recall checks are unchanged. Manual channel curation is not
renamed or presented as gated promotion.

The catalog API does not expose promotion-run receipts or durable build/publication job status.
Those are still open under #2532, together with transcription-free publication/promotion,
session recovery across real sign-in, and complete UXH-16/18 durable task handoff. No new required
approval step is introduced, and no completion of these outcomes is claimed.

Focused checks for this increment:

```bash
npm --prefix lifecycle/release-hub/ui test
npm --prefix lifecycle/release-hub/ui run typecheck
npm --prefix lifecycle/release-hub/ui run build
```

The actual Release Hub route is checked with synthetic catalog responses, not a live vendor
publication. Desktop precedes constrained/mobile measurements. Authentication-provider recovery
and genuine durable-job resume still require their own evidence. See the
[implementation ledger](../roadmap-implementation/deployment/lifecycle-releases-and-channels.md)
for the delivered boundary and remaining work; this increment is not a whole-product UX score.

## Reuse what already works

Execution-settings and application-binding forms already generate UUIDs, current Settings digests
and exact confirmation text. Preserve those patterns instead of asking operators to calculate
machine values. Keep refresh/readback distinct from writes.

Likewise, keep **Refresh catalog**, **Renew catalog freshness**, **Approve exact pin** and
**Import approved catalog** separate. They do different work. A guided flow can connect them
without making an import or a download authorize itself.

## Separate automation from approval

| Automate the mechanics | Preserve the decision |
|------------------------|-----------------------|
| Generate public setup records and compare independently obtained fingerprints | Accept the installation identity and native ownership scope |
| Transfer signed inputs, verify exact bytes and stage atomically | Establish signing trust and approve customer configuration |
| Mirror and verify approved immutable images | Approve registry boundary and source eligibility |
| Explain blockers and generate request UUID/digest/confirmation fields | Confirm the attributed operation and exact impact |
| Schedule bounded Agent work and collect independent readback | Approve runtime scope, maintenance windows and exceptional recovery |
| Produce cleanup/retention records and notifications | Decide resource lifetime and suppression lift |

Do not solve these problems by disabling TLS or authentication, opening all source IPs, granting
administrator/Graph permissions, auto-accepting downloaded keys/pins, resetting durable identity,
or treating a healthy Pod as proof of operational success.

## Verification scope for the next design

Source references for the current interaction gaps:

- [Shared Hub authentication](../../lifecycle/hub/ui/src/auth.ts): silent token acquisition and
  generic failure presentation. This identifies a recovery-design gap; it does not establish
  the cause of every observed data-loading failure.
- [Data-loading boundary](../../lifecycle/hub/ui/src/components/async-boundary.tsx):
  one generic title and retry action.
- [Installation detail](../../lifecycle/hub/ui/src/routes/installation.tsx):
  separate constraint, Entity, schedule and application panels; Configuration remains unavailable.
- [Navigation](../../lifecycle/hub/ui/src/components/nav.tsx): planned surfaces are still inert.
- [Operator guide](hub-lifecycle-operator-guide.md): setup, input transport and finite Agent
  scheduling are not a single shipped installer.

Use the [UI/UX rubric](../reference/ui-ux-quality-rubric.md) for the actual redesign. This backlog
selects information, state clarity and recovery concerns, not a scored visual review.
Desktop geometry, keyboard use, constrained/mobile layouts, live sign-in recovery and real
customer task completion remain unmeasured here.

Before claiming a redesign complete, validate the relevant English/Korean routes, loading,
unavailable, denied, expired, uncertain-write, rollback and resumed states. Record each scenario
as `passed`, `failed`, `needs-human` or `needs-infrastructure`; untested states do not pass.
Start with desktop, then verify responsive changes where applicable.

## Next steps

| To learn about | Read |
|---------------|------|
| Supported operator steps today | [Hub operator guide](hub-lifecycle-operator-guide.md) |
| Application-neutral runtime extension | [Application runtime bundles](../roadmap/deployment/lifecycle-runtime-bundles.md) |
| Configuration trust and custody | [Configuration key onboarding](lifecycle-configuration-key-onboarding.md) |
| Authoritative lifecycle boundaries | [Hub-managed lifecycle](../roadmap/deployment/hub-managed-lifecycle.md) |
