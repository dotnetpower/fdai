---
title: Human-Agent Assignment Implementation Plan
---
# Human-Agent Assignment Implementation Plan

This plan turns the human-agent assignment and knowledge-handover design into dependency-ordered
work packages. Each package uses a task branch and isolated worktree, then enters `main` through
a reviewed pull request. It names the owning modules, compatibility path, API and event contracts, focused
tests, Azure permissions, rollout controls, and evidence required before IAM writes are enabled.

> **Authority boundary:** FDAI Console submits a domain-typed case. It never receives Graph
> write permission or Thor's identity. Ownership merge, human approval, IAM apply, and knowledge
> promotion remain independently verifiable effects.
## Delivery shape

Implementation is split into nine focused work packages. Packages 1 through 4 target a
complete observation-only workflow. Package 5 is the first provider mutation and stays in
observation mode until separately promoted. Packages 6 through 8 add approval continuity and
knowledge capture without raising IAM authority. Package 9 currently reports bounded observation
evidence, not operational readiness. Bounded source requirements and [12 distinct final critique rounds](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation)
after remaining source implementation are complete with no unresolved confirmed Medium/High source finding.
Source delivery completed through [PR #1014](https://github.com/dotnetpower/fdai/pull/1014): reviewed head `8c1d9977c`, protected squash `953a17de4`, successful exact-head CI `34925881557` and post-merge CI `34926168342`. The [#1017 local UI review](../../internals/handover-ui-evidence-20260915.md) retains a real assistive-technology gap; live operational evidence remains separate.

![Delivery shape. The main stages are Package 1 duty schema, Package 2 assignment core, Package 3 API and console, Package 4 ownership coordination, Package 5 IAM provisioner, Package 6 approval supervisor, Package 7 handover goals, Package 8 knowledge lifecycle, Package 9 production rollout.](../../diagrams/generated/fdai-roadmap-interfaces-human-agent-assignment-implementation-plan-01.en.svg)

## Current baseline and gaps

| Area | Current source | Remaining review or external evidence |
|------|-------|------------------------|
| Directory | `HumanIdentityDirectory`, exact Entra subject lookup, App Role roster, allowlisted membership adapter | External: current deployed identity, provider credentials, permission and promotion evidence |
| Access | Shared SDK, exact Core material/HIL/preparation, isolated Graph dispatch, subject/group lock, durable intent/result, independent Heimdall observation, atomic closure, and fresh approved inverse | External: live credentials, permissions, current approvals, Graph/lock/recovery drills, and independent promotion under open #458; only the legacy Core adapter always refuses enforce |
| Ownership | Stewardship v2 plus ownership-only scoped-duty `1.2.0` cases, current group/schedule readers, two-Owner review, immutable artifacts, current merge observations, and H10 Console route | External: governed GitHub App and deployed lifecycle/coverage evidence; no IAM, ACL, or authorization grant |
| Approval | `HilResumeCoordinator`, bounded ladder receipts, current-source forecast timing, reminders, load control, and shadow non-response observation | External: current rung identities, delivery, measured timing cohorts, drills, and promotion |
| Conversation | Current Operator and Core goal/reviewer/admission/retrieval bindings, six-slot acceptance, observed-group Reader ACL checks, and durable subject-wide budget | External: current deployed identity, source ACL, and pilot/cohort evidence |
| Documents | Governed ingestion, deterministic chunks, goal observation `1.1.0`, immutable typed Rule/ontology compilation, independent review, and Mimir retention/scrubbing | External: provider conformance, deployed source/hold policy, latency and cohorts; unsupported prose is held, not semantic success |
| Console | Actual Mapping reviews H10 workspace, Current owners, document checklist/review controls, and Owner-only readiness read | #1017 accounts for all 50 UI IDs and passes local keyboard, long/expanded and responsive checks. Required real screen-reader evidence remains `needs-human`, without a final score; live convergence/pilot evidence remains open and readiness stays `shadow`, `operationally_ready=false` |

## Contract decisions before coding

### Proactive ownership handover conversation

The current Operator conversation slice uses the reviewed ownership projection as the
server-side assignment authority. The Operator service creates one safe-to-retry (idempotent)
invitation for a signed-in accountable user and binds it to a fixed Pantheon agent, goal, session,
and ownership revision. Browser-provided agent names remain no-authority routing hints; every
decision and evidence transition is resolved independently from server-owned state.

The slice follows these rules:

- `GET /handover/goals/invitation` verifies the signed-in subject against the current ownership
  projection before returning or creating an invitation.
- One session receives at most one invitation. A principal receives at most two new invitations in
  one ISO week. Retries return the existing invitation.
- An invitation never blocks Console access. Current ownership, active identity, incident/approval
  suppression, and goal eligibility are rechecked before a handover turn is reserved.
- A handover conversation sends the goal identity with every turn. The server verifies principal,
  goal, agent, and durable conversation session before injecting the mapped agent address. This
  routing does not grant action, approval, or evidence authority.
- Web files enter the document-ingestion gateway first. Before goal evidence becomes reviewable, the
  Operator service re-reads the exact document version and verifies uploader, admitted state,
  active availability, immutable `doc:<document_id>:<version_id>` citation, and source digest.
- Goal transitions use revision fencing and the six shared explicit slots in `handover_checklist`
  `1.0.0`. An unslotted legacy document proves no completeness. Legacy `accepted` or
  `ready_for_review` records that lack current requirements project as `blocked` without rewriting
  history. Each slot needs admitted evidence or its own reasoned exemption.
- Acceptance binds an independent Owner and, by the high-impact default, a distinct current backup
  to the exact checklist digest. The first and prior reviewers' current directory roles and backup
  duties are rechecked. Reader-only backup review requires current observed role-group membership
  and the exact document ACL; a duty, role label, or direct App Role supplies no inferred grant.
  Missing or partial group evidence holds. Neither review grants execution authority.
- Every goal command, including an exact retry, revalidates the goal subject's active accountable
  mapping and exact ownership revision before mutation. Missing identity or ownership evidence
  holds the command. A removed mapping leaves permitted prior evidence readable but not mutable.
- A retry binds the complete command payload, normalized actor, operation, and expected revision.
  Reusing that identity with changed evidence or a different reason is a conflict, not success.
- Operator's durable subject-wide budget admits one active session, three unique turn identities,
  five non-sliding minutes, and two actual sessions per ISO week. Exact retries retain the original
  deadline but are held if ownership is invalidated, the user is busy, or the goal is stale,
  accepted, or otherwise ineligible. The semantic deadline is capped by the session window;
  ordinary Console conversations are unaffected.
- Same-person, same-scope, same-current-ownership-revision evidence can be explicitly reused across
  current agents after a source recheck. Reviews are never copied; the target needs new acceptance.
- Core binds `GoalEvidenceAdmission` and `GoalReviewerEligibility` through its current source and
  reviewer readers. Actual knowledge-owner consumption invokes the bound goal service, and the
  authenticated governed-document function uses the bound standalone search. Admission precedes
  content access; missing identity, source, reviewer, or ACL evidence holds without borrowing
  Operator authority or granting raw document-table reads.

This slice does not promote IAM mutation or infer a new owner from conversation text. Ownership
changes still require the reviewed pull-request flow, and provider-side mutation remains on its
independent promotion axis.

### Ownership schema migration

Stewardship schema v2 adds `duty: primary | backup | escalation` to accountable steward entries.
`responsibility` remains `accountable | informed`; an informed entry has no duty. The migration is
additive and follows this compatibility window:

1. The v2 loader reads v1 and derives the first accountable subject as `primary` and later
   accountable subjects as `backup`, but emits `duty_derived` and `backup_missing` findings.
2. `scripts/governance/migrate-stewardship-v2.py` renders a reviewable v2 candidate and never edits
   the live file in place.
3. New assignment cases always emit v2. Existing v1 deployments continue in observation mode.
4. Enforce mode requires v2, one live primary, and one distinct live backup or escalation subject.

This keeps `config/agent-stewardship.yaml` as the ownership source of truth instead of creating a
second mutable duty graph.

### Assignment state

Add `services/core-control-plane/src/fdai/core/human_assignment/` with pure models, transition validation, coverage checks, and
a coordinator over the existing `StateStore`. Revisioned cases use atomic `state_kv` plus the
audit hash chain. The connected lifecycle also requires service-owned migrations for immutable
receipts, namespace guards, restricted source reads, semantic packages, and Executor evidence;
the original no-migration case prototype is not the current release boundary.

| State key | Contents |
|-----------|----------|
| `human_assignment:case:<case_id>` | Immutable intent, revision, requester, target, role, duties, goals, and effect receipts |
| `human_assignment:decision:<case_id>` | Independent review decision and quorum evidence |
| `human_assignment:active:<subject_hash>:<agent>:<scope_hash>` | Current converged assignment projection without names or usernames |
| `handover_goal:<goal_id>` | Goal revision, required evidence slots, fatigue state, and review status |

Package 2 writes only the case key. It embeds append-only review receipts in the revisioned case
snapshot so quorum evidence and lifecycle state advance in one atomic CAS. Operator derives the
displayed assignment projection from that authority; it is not a second approval store.

Grant transitions are `draft -> pending_review -> approved -> ownership_pr_open ->
ownership_merged -> iam_applying -> active`. Removal has a new independently reviewed intent and
reverses the effect order: `approved -> iam_applying -> iam_revoked -> ownership_pr_open -> revoked`.
Compare-and-set (CAS) checks reject stale commands and hold the pinned original case before effects.
`rejected`, `degraded`, and `superseded` remain terminal or held outcomes.

### Commands, events, and actions

The Operator API may create a case but can't apply its effects. Machine collaboration uses validated
events and existing control-loop ingress.

Assignment transport carries only an immutable Operator proposal reference, canonical digest,
operation, and acceptance time. The consumer resolves the exact namespace-owned source record;
neither a payload role nor the transport identity substitutes for that authenticated receipt.
Missing, expired, mismatched, or unauthorized evidence produces an audited hold. A verified
transport intake is only `awaiting_agent_review`, never an approved or active assignment. The
case-changing consumer requires Forseti validation, Var's independent review where applicable,
and Saga's sealed result before coordinating an ownership proposal. Unavailable agent bindings
remain visible and never fall back to applying the Operator's presentation state.

The shared database is not a shared authority boundary: an insert-only Operator receipt table
preserves the authenticated command in the same transaction as its outbox proposal. Core reads
that table but cannot write it; only Core may write assignment cases and command results. Old
unsealed proposals cannot acquire authority through a migration backfill. Huginn normalizes a
content-free notice, Forseti validates it, Var rechecks an independent human review, Saga seals
each decision, and Muninn materializes only that sealed command. Review-only ownership artifact
delivery uses the existing idempotent PR publisher after the sealed case result; it never merges
the PR, applies a duty map, grants access, or substitutes for Thor's action path.

Goal observation `1.1.0` binds a content-free digest to exact source-read checks. Core cannot write
Operator goals. The bounded worker rotates pages and source priority, retains failed pages, and
publishes mechanical `knowledge.handover.source_observed.v1` notices, not agent decisions. An
observed goal never admits a document or promotes a candidate. A Core-only boolean SQL function
checks the current document uploader, digest, availability, governed state, index, and retention
without granting document `SELECT`. These local checks do not prove live directory, cohort, or
source state in a deployment. Core owns shared-table guards and immutable receipt schema;
Operator owns its dependent insert/read grant. Rollback refuses to delete retained receipts.

Multiplexing semantic request and result logical topics over one physical Event Hub does not merge
human principals, roles, approvals, or assignment revisions. The authenticated principal remains in
the versioned request, and physical-topic RBAC grants transport access only, never assignment or
execution authority. Deadline-bound semantic replay can emit only a typed hold; it cannot create or
advance an assignment case. Type-stable JSONB persistence changes no principal or assignment state.

| Contract | Purpose |
|----------|---------|
| `POST /iam/assignment-cases` | Owner submits an immutable assignment intent and idempotency key |
| `GET /iam/assignments` | Joined role, duty, coverage, case, and handover projection |
| `GET /iam/assignment-cases/{case_id}` | Effect receipts, audit references, and failure state |
| `human.assignment.requested` | Forseti validation and Var review intake |
| `human.assignment.ownership_merged` | Signed webhook proves the exact stewardship revision merged |
| `human.assignment.iam_apply_requested` | Legacy shadow-only intake after prerequisites converge; replay never upgrades its authority |
| `human.assignment.activated` | Independent membership observation and atomic closure precede Core's matching ownership/IAM transition |
| `handover.goal.requested` | Mapped agent publishes one bounded knowledge need |
| `knowledge.evidence.proposed` | Admitted answer or document span is available for review |
| `knowledge.handover.source_observed.v1` | Mechanical source-check notice; each accountable consumer makes its own decision |
| `GET /handover/readiness` | Owner-only bounded observation report, never operational approval |

Add shadow-default `ops.apply-human-access` and `ops.revoke-human-access`
ActionTypes. Their pantheon bindings remain Forseti judge, Var approver, Thor executor, Vidar
recovery, and Saga auditor. No role binding is configurable.

## Dependency-ordered work package sequence

### Package 1 - Operational ownership v2 and coverage

**Changes:** Extend `core/stewardship/model.py`, `resolver.py`, `coverage.py`, `escalation.py`, the
config checker, and both ownership design docs. Add the migration renderer and fixtures. Keep v1
read compatibility and preserve all 15 agent names.

**Tests:** Resolver tests for v1 derivation and v2 fail-fast behavior; coverage properties proving
primary and backup resolve to distinct normalized people; group expansion failure doesn't prove
two-person coverage; migration output round-trips through the v2 loader.

**Exit:** Existing v1 config loads with findings, a generated v2 candidate is deterministic, and
v2 rejects missing primary, missing backup or escalation, cycles, duplicate duties, and stale-only
coverage.

### Package 2 - Assignment case core

**Status:** Implemented. The core remains observation-only; its runtime adapter consumes only
audit-sealed commands and stores exact command receipts in the same case CAS and audit transaction.

**Changes:** Add `core/human_assignment/model.py`, `transitions.py`, `coverage.py`, `service.py`, and
`__init__.py`. Reuse `StateStore.write_state_with_audit_if_absent` and revisioned writes. Add
content-free audit kinds for request, review, effect receipt, activation, degradation, and
supersession.

**Tests:** State-transition table, idempotent replay, conflicting key, stale revision, normalized
no-self-approval, elevated-role quorum, partial-effect recovery, and property tests that no state
skips review or ownership merge.

**Exit:** A case can be created, reviewed, replayed, and projected without I/O outside `StateStore`;
no transition can mark it active without both ownership and IAM receipts.

### Package 3 - Observation-only API and Assignments tab

**Status:** Implemented. The Operator API and browser receive no human-access provisioner or Graph
write capability. Missing directory, role, and handover evidence remains explicitly unavailable.

**Changes:** The independent Operator service owns `families/iam/assignments.py` and its IAM routes.
Extend app config with the case service and ownership projection, not a provisioner. Add
`settings-iam-assignments.tsx`, model and command types, the fifth IAM tab, English/Korean catalog
keys, skeleton loading, filters, editor, validation summary, and evidence drawer.

**Tests:** Owner-only search and submit, exact subject revalidation, body and pagination bounds,
stale revision, unavailable directory, Preact reducer and decoder tests, keyboard tabs,
localization parity, accessibility, and production build.

**Exit:** An Owner can search one active subject, compose role plus duties plus goals, and create an
observation-only case. The UI clearly states that no Entra membership changed.

### Package 4 - Ownership PR coordination

**Status:** The immutable request outbox, Core receipt reader, fixed-agent validation/review/seal
chain, approved-case draft publisher, and signed-merge consumer are connected in source. Local
tests cover separate stores and real PostgreSQL service roles, transactional audit failure,
replay, lease fencing, a single draft PR, and exact merge correlation. GitHub App installation,
current deployed bindings, and provider drills remain separate evidence gates.

**Changes:** Add a `StewardshipGovernanceService` that accepts an approved case and renders one v2
overlay. Persist case id, PR receipt, and canonical candidate digest in proposal state. The signed
GitHub merge path records the ownership effect receipt on the case only when PR ref and rendered
content digest match.

**Tests:** Additive merge, removal rejection without replacement, remote PR replay, webhook
signature, wrong repository or digest, duplicate delivery, case supersession, notification, and
atomic audit receipt.

**Exit:** One approved case opens at most one draft PR; only the matching reviewed merge advances
the case; IAM remains untouched.

### Package 5 - Governed Entra membership apply

**Status:** Source-connected, including the shared SDK, Core material/HIL/preparation, isolated
Graph execution, independent observation, shared atomic post-release closure, and fresh approved
inverse. The legacy Core adapter still refuses enforce. The actual isolated path supports enforce
only when independently promoted and currently authorized; no live promotion is established here.

**Changes:** [Shared membership contracts](../../../packages/service-contracts/src/fdai_service_contracts/human_access.py),
[Core runtime binding](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py),
[isolated executor](../../../services/isolated-executor/src/fdai_executor_service/human_access.py), and
[closure reconciliation](../../../services/core-control-plane/src/fdai/delivery/human_access_closure.py)
preserve these boundaries:

1. **Original material:** Forseti retains exact catalog Action bytes, case/replacement and role-map
  digests, and current promotion before human approval. Core has no mutation identity; Operator
  and ingestion never receive a Graph writer. The grant's matching ownership merge comes first.
2. **Approval and preparation:** Var uses existing HIL slots with the original non-sliding
  five-minute window. Reader/Contributor access requires one current eligible Owner;
  Approver/Owner access requires two distinct current eligible Owners, excluding requester and
  target. Existing role/ActionType approval policy and risk/quorum ceilings still apply. Original
  case reviews are not execution approval. Muninn records preparation `r -> r+1` while the approved
  `expected_revision=r`, Action, and expiry remain unchanged.
3. **Dispatch and effect:** Thor alone dispatches through all seven shared safeguards. Grant,
  revoke, and inverse use the same normalized subject/group lock across cases. Current source,
  approval, kill/degradation state, role/action policy, and promotion are rechecked at dispatch
  boundaries. Executor-owned durable pre-state/intent precede one Graph mutation; acknowledged
  result follows it. Independent Heimdall observation, Forseti judgment, Saga seal, and shared
  atomic post-release closure precede Muninn's case effect. Acknowledgement alone is not success.
4. **Fresh inverse:** Existing ActionTypes use `recovery_of` with exact original owned pre-state,
  immutable intent/result, current demand, and unchanged target lineage. Vidar proposes and
  finishes on its owned topics; Var requires fresh independent Owner approval and the existing
  ActionType whitelist; Thor alone dispatches. Independent inverse readback and closure are
  mandatory. Core remains `degraded`; duties, goals, approval, and promotion are not restored.
  `ALREADY_APPLIED`, unknown ownership, unacknowledged dispatch, or intervening attempts cannot
  authorize an inverse or automatic mutation retry. A script reference alone proves no rollback.

The same source/configuration and authority checks apply in every venue. Credentials, endpoints,
and provider scope are venue-owned; local authority cutover is forbidden and shadow never mutates.
Legacy `iam_apply_requested` remains shadow-only even after another path is promoted.

**Removal ordering:** Immutable `revocation` transport `1.1.0` pins original and replacement
revisions and requires fresh removal review. Core holds the original by CAS. The sequence remains
`approved -> iam_applying -> iam_revoked -> ownership_pr_open -> revoked`: independent IAM removal
precedes the review-only old-duty PR, and its exact signed merge closes the hold without another
grant. Rendering rechecks pinned active replacements and actual duties. Other active or uncertain
grant demand preserves membership. This normal removal is distinct from the exact recovery inverse.

For user membership, Microsoft Graph documents `GroupMember.ReadWrite.All` as the least privileged
application permission for `POST /groups/{group-id}/members/$ref`. Use a dedicated managed identity,
exclude role-assignable groups, and hard-allowlist only configured FDAI role group object ids. An
application permission is tenant-wide, so the code allowlist is a compensating control, not a
directory permission boundary. Active-user inspection also needs `User.Read.All`. A selected
deployment needs a separate security assessment to determine whether an
administrative-unit-scoped Groups Administrator or custom role, plus required read permission, can
replace the broad application permission for the target tenant. Don't combine both and claim that
the administrative unit narrows an already tenant-wide application permission.

**Tests:** The recorded execution selection passed 132 and the separate real-SQL/fixed-agent
selection passed 21. They cover current approval/preparation, owned inverse, shared lock/closure,
service-role isolation, original bytes, and uncertain-dispatch refusal. Provider HTTP and Owner
observations are synthetic; overlapping counts are not summed.

**Exit:** Source requirements are complete. Live credentials/permissions, zero-target-mismatch
shadow evidence, non-production add/verify/remove/restore drills, and independent promotion remain
external requirements under open [#458](https://github.com/dotnetpower/fdai/issues/458).

### Package 6 - Human non-response supervisor

The runtime loads the reviewed escalation catalog. Catalog audience groups require explicit
audience-to-human resolution; positional guesses from a stewardship list are prohibited. Bound
windows and urgency inputs are snapshotted with the immutable request. Missing selection or
audience resolution preserves the existing conservative ladder and records the unavailable
catalog reason, never invented urgency. Enforce dispatch requires an injected current-role and
active-identity verifier; an absent verifier cannot default to eligible. Shadow observation
remains non-dispatching and cannot import standing-authority execution.
The existing Heimdall evaluator now retains breach ETA and prediction-band confidence in its
transactional publication. An exact Core-role episode/outbox read binds them to the approval's
target and correlation before catalog timing can shorten a window. Missing, stale, closed, or
mismatched evidence keeps conservative timing; request-supplied numbers and `R²` are not proof.

**Status:** Implemented as a periodic shadow worker. Coordinator parks snapshot the bounded ladder
and delivery receipt, and terminal decisions use one CAS winner. Production promotion remains
unbound. A terminal claim may retry bounded delivery-state revision changes only while the parked
action, action hash, and request fingerprint remain unchanged.

**Changes:** Add `core/hil_resume/escalation_supervisor.py`. On parking, snapshot the ordered
primary, backup, escalation, and maintainer rungs with role eligibility, delivery deadline, action
hash, and overall deadline. A scheduled runtime tick claims due transitions with CAS, dispatches
the unchanged request to the next rung, and appends one Saga audit per hop.

**Tests:** Delivery failure versus human silence, immediate unavailable response, primary timeout,
late decision, concurrent ticks, rejection terminality, role loss, schedule outage fallback,
overall expiry, restart replay, and no-op without standing authority.

**Exit:** Shadow metrics match historical approval timing before rung dispatch is enabled. Enforce
mode never changes the action hash, accepts two decisions, or turns exhaustion into execution.

### Package 7 - Proactive knowledge transfer goals

**Status:** Operator and Core source paths are implemented: source-bound commands, checklist
`1.0.0`, independent Owner/backup acceptance, and the durable one-session/three-turn/five-minute/
two-per-ISO-week budget. Legacy incomplete records project as blocked without rewriting history.
Core's current goal/reviewer/admission/retrieval bindings are consumed by actual source and search
paths. Reader-only backup review requires observed current role-group membership and the exact
document ACL. Missing or partial evidence holds; deployed source and pilot evidence remain open.

**Changes:** Goal and document commands share six explicit slots, current ownership and reviewer
checks, retry payload fencing, and source revalidation. Same-person/scope/revision reuse across
current agents copies evidence references, never reviews. Standalone retrieval requires current
admission. Sign-in and ordinary conversations remain independent of handover completion.

**Tests:** Explicit slots and exemptions, legacy blocked projections, first/prior reviewer role
loss, current-source holds, exact retries, durable subject-wide budgets, busy/stale/accepted holds,
evidence reuse without review copying, and document-route interaction and accessibility.

**Exit:** Current Core bindings and focused source/SQL evidence are complete. Retain governed
Reader-backup and pilot evidence separately. No goal path changes IAM, ACLs, or autonomy.

### Package 8 - Evidence, source checks, and inert semantic packages

**Status:** Source-connected. Norns compiles exact typed Rules and ontology candidates into private
immutable packages; Mimir independently rereads current sources before content, recompiles without
model calls, and maintains retention on its existing subscription. Worker notices remain mechanical,
and Saga receipts contain no document text. Actual SQL checks prove local service isolation, not
deployed source freshness. Typed compilation does not prove unsupported prose Rule fidelity.

**Changes:** The accountable chain is Huginn -> Forseti -> Saga -> Muninn `StateSnapshot` -> Saga ->
Norns (existing consensus, publication gate, and rate limit) -> Mimir independent package review -> Saga.
Forseti, Muninn, Norns, and Mimir independently read the source and use owner-local CAS; no shared
mutable stage grants authority. Same-source-revision withdrawal is monotonic. A five-minute recheck and tracked
latest source identity handle deletion and restart. Explicit same-document conflicting digests go
from Forseti to Odin for clarification, without selecting a winner. The existing
`publish_knowledge_conflict` helper is only a proposal primitive, not general contradiction detection.

Mimir checks at most 25 packages per notice, rotates retained identities, and retires monotonically
on withdrawal, drift, or the stricter original/current expiry. Known legal hold keeps inaccessible
bytes; unknown hold or unavailable source never permits erasure. Explicit current no-hold evidence
is required to scrub content while preserving immutable claim, digest, receipt, and audit. Neither
hold release nor replay resurrects a retired package or restarts extraction under the same identity.

**Tests:** Exact observation/digest reads, actual SQL isolation and boolean source checks,
independent stage replay/CAS, deletion/restart withdrawal, explicit digest conflicts, deterministic
chunk lineage, and inert outputs. The recorded compiler/actual-SQL selection passed 37; separate
contract, envelope, runtime, and owner checks passed 40 on their recorded inputs; the later
retention/policy/compiler/SQL/agent selection passed 60. Results overlap and are not summed.

**Exit:** Bounded compilation/review/retention source requirements are complete. Provider conformance,
deployed source/hold policy, latency, and cohorts remain external. Review packages activate no
catalog or graph, grant no ACL, and supply no promotion or IAM authority.

### Package 9 - Production rollout and operations

**Status:** Capability axes and bounded shadow reconciliation are implemented, not a completed
production rollout. `human_access.enabled` applies at restart; the kill switch only lowers
eligibility. The existing worker pages at `human_access.reconciliation_interval_seconds`, isolates
invalid records, and retains failed pages. It produces recovery observations without provider calls.

**Changes:** The same reconciliation now records sampled counts, total, invalid count, partial-scan
status, alert observations, explicit source gaps, and external blockers. The mean effect-receipt
interval uses only cases with two effects and is `null` when none qualify; it is not whole-product
latency. Owner-only `GET /handover/readiness` exposes the report for ten minutes. Future-dated or
malformed reports are unavailable. The report always stays `shadow` and not operationally ready;
it dispatches no alerts, checks no provider, writes no recovery action, and performs no promotion.
The completed source-gap inventory is empty (`source_gaps=[]`); `operationally_ready=false` and all
external blockers remain. Reporting is separate from the gated execution/recovery worker.

**Tests:** Bounded scan/restart behavior, sampled/total/invalid/partial reporting, two-effect or null
intervals, explicit blockers, Owner authorization, expiry, future timestamps, and malformed input.

**Exit:** Retain governed identity, IAM, GitHub, notification, rollback, restart, and recovery drills
plus cohort evidence. Alert dispatch, provider checks,
recovery writes, and promotion are not delivered by this reporting slice.

### Package 10 - Human report lines and approval routing

**Status:** Implemented in source and disabled by default. Deployment evidence and promotion remain
open.

**Changes:** Add an independent `human_reporting` lifecycle with immutable document candidates,
edge confirmation, independent Owner review, acyclic current-graph projection, requester contact
consent, and nearest eligible ancestor routing. Reuse governed document ingestion, the existing
assignment transport, HIL queue, non-response supervisor, and principal-to-ActionType policy.
The Operator API and Console expose only bounded proposals and projections. They gain no execution
identity, and neither a report line nor contact consent grants approval authority.

The initial runtime opt-in accepts quorum `1`. Higher-quorum actions remain on their existing
workflow or human-access approval path. `FDAI_REPORT_LINE_APPROVAL_ROUTES_JSON` selects exact
ActionTypes, while an empty value preserves existing approval routing.
`FDAI_REPORT_LINE_APPROVER_SCOPES_JSON` independently constrains each selected principal and
ActionType to exact target scopes.

**Tests:** Contract digest and tamper checks, extraction and directory-conflict holds, edge
transition and graph-cycle properties, independent reviewer checks, current-route eligibility,
contact-consent expiry and replay, durable Operator transport, HIL dispatch and stale-route
rejection, Console decoding and interaction contracts, and bilingual catalog parity.

**Exit:** Source behavior and focused checks pass, at least ten distinct critique and hardening
rounds leave no unresolved finding above Low, and protected CI merges the exact reviewed head.
Live Graph, notification, and promotion evidence remain deployment-owned.

## Current-change evidence and remaining scope

The [final integrated record](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation) documents 12 distinct rounds after all remaining source implementation.
No unresolved confirmed Medium/High source finding remains. Earlier checkpoint results stay historical;
the earlier source selections below overlap and are not summed. #1014 is delivered; #1017's local
UI follow-up and #458's operational evidence remain separate outcomes.

| Review slice | Recorded final source-review evidence |
|--------------|---------------------------------------|
| Goal, revocation, replacement, Operator, Reader, and catalog | 145 focused checks passed |
| Real SQL, fixed agents, and owning migration inventory | 92 checks passed; provider HTTP and Owner observations were synthetic |
| Runtime mode, observer, and readiness | 33 checks passed |
| Semantic compilation, retention, and Core runtime | 61 checks passed |
| HIL, bootstrap, layout, and document parity | 136 checks passed |
| Execution source typing | 19 modules passed strict typing |
| Task source static checks | 227 Python files passed lint/format; 149 source modules passed import/module-doc scanning; existing LOC ratchets unchanged |
| Delivered documentation checkpoint | #1014 completed reviewed EN/KO synchronization, canonical catalog generation and normal hooks; exact-head and post-merge CI passed |
| Current local Console follow-up | #1017: 28 distinct synthetic browser scenarios, 127 focused unit checks and TypeScript pass; all 50 rubric IDs recorded, with real assistive-technology evidence missing and no final score |

All existing bounded source requirements are complete against that evidence:

- [x] **H10:** [Scoped request processing](../../../services/core-control-plane/src/fdai/core/human_assignment/scoped_duty_requests.py)
  and the actual [Console workspace](../../../console/src/routes/scoped-duty-workspace.tsx) connect
  current scope/group/schedule review, merge observation, and projection. Future-only declarations
  stay draft; HTTP202 stays `awaiting_core` until manual GET. No personal IAM or ACL is inferred.
- [x] **Alternate Core goals:** [Core bindings](../../../services/core-control-plane/src/fdai/runtime/core_handover.py)
  connect current goal/reviewer/admission and standalone retrieval to actual consumers.
- [x] **Reader backup source:** [Reviewer eligibility](../../../services/operator-service/src/fdai_operator_service/families/iam/handover_review_eligibility.py)
  joins current observed groups to exact document ACL without a new grant.
- [x] **Semantic candidates:** [Semantic binding](../../../services/core-control-plane/src/fdai/runtime/handover_semantics.py),
  [retention policy](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/handover_retention.py),
  and [private SQL packages](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_handover_semantics.py)
  preserve typed fidelity, locators, current source-before-content review, and monotonic retirement.
- [x] **Urgency source:** [Forecast verification](../../../services/core-control-plane/src/fdai/core/hil_resume/forecast_urgency.py)
  binds actual production/approval sources; measured cohorts remain external.
- [x] **Execution source wiring:** [Runtime](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py),
  [isolated execution](../../../services/isolated-executor/src/fdai_executor_service/human_access.py),
  [inverse](../../../services/core-control-plane/src/fdai/runtime/human_access_recovery.py), and
  [atomic closure](../../../services/core-control-plane/src/fdai/delivery/human_access_closure.py)
  connect exact HIL/preparation, shared membership lock, durable intent/result, and independent effects.

- [x] **Final source critique:** Completed 12 distinct integrated rounds after remaining source
  implementation; the [final record](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation) has no unresolved confirmed Medium/High source finding.
- [x] **#946 publication:** Reviewed translations, generation, normal hooks and [PR #1014](https://github.com/dotnetpower/fdai/pull/1014) delivery completed; exact-head CI `34925881557` and post-merge CI `34926168342` passed.
- [x] **Local UI evidence:** [#1017 evidence](../../internals/handover-ui-evidence-20260915.md) accounts for all 50 IDs and records keyboard, pending/error recovery, long/expanded states, two languages and responsive measurements.
- [ ] **Assistive technology:** Retain real EN/KO status, error and disclosure announcements from NVDA with supported Chrome or a declared equivalent. Until then the scoped rubric is `needs-human`, not a final numerical score or WCAG claim.
**Follow-up delivery:** [#1017](https://github.com/dotnetpower/fdai/issues/1017) tracks this change's normal hooks and protected exact-head CI/merge; #1014's successful delivery does not attest this new diff.

External blockers remain separate: [#458](https://github.com/dotnetpower/fdai/issues/458) remains open
for live credentials/permissions, current identity and approval, Graph/GitHub App, independent IAM-effect and
target-lock drills, and promotion. Teams evidence remains under
[#942](https://github.com/dotnetpower/fdai/issues/942) and
[#944](https://github.com/dotnetpower/fdai/issues/944), document evidence under
[#424](https://github.com/dotnetpower/fdai/issues/424), and deployment evidence under
[#803](https://github.com/dotnetpower/fdai/issues/803), alongside the required cohorts. Local SQL
checks do not verify live directory, cohort, or document-source state in those deployments.
Use the [standalone deployment coordinator](../deployment/installable-deployment-cli.md) and managed
host for an explicitly selected signed release, current exact plan, independent approval and
readback. GitHub Actions is not a tenant-deployment transport. The [prerequisite matrix](../../internals/handover-ui-evidence-20260915.md#delivery-and-operational-boundary)
names current identity, App installation, ChatOps, source/ACL/hold, inverse-drill and cohort evidence;
source implementation or issue closure never supplies those approvals.

## Focused verification by slice

| Slice | Narrow command before commit |
|-------|------------------------------|
| Stewardship v2 | `uv run pytest -q --no-cov services/core-control-plane/tests/core/stewardship` plus `bash scripts/governance/check-stewardship.sh` |
| Assignment core | `uv run pytest -q --no-cov services/core-control-plane/tests/core/human_assignment` |
| IAM API | `uv run pytest -q --no-cov services/operator-service/tests/test_operator_iam_family.py services/operator-service/tests/test_operator_service_postgres.py services/operator-service/tests/test_handover_runtime.py` |
| Console | `npm --prefix console test -- --run src/routes/settings-iam.test.ts src/routes/settings-iam-assignments.test.tsx` |
| Ownership governance | `uv run pytest -q --no-cov services/core-control-plane/tests/core/human_assignment/test_ownership_coordination.py services/core-control-plane/tests/runtime/test_stewardship_governance.py services/core-control-plane/tests/runtime/test_stewardship_merge_effects.py` |
| HIL supervisor | `uv run pytest -q --no-cov services/core-control-plane/tests/core/hil_resume` |
| Knowledge lifecycle | `uv run pytest -q --no-cov services/core-control-plane/tests/core/document_ingestion services/core-control-plane/tests/delivery/document_index services/core-control-plane/tests/delivery/ingestion_gateway` |

Each package also runs Ruff and strict mypy only for touched Python paths before its focused
commit. The centralized Integration Validator owns diff-scoped integration and repository-wide
validation receipts.

## Rollout evidence and stop conditions

| Stage | Required evidence | Stop or demote when |
|-------|-------------------|---------------------|
| Assignment observation | 30 days or 100 cases; zero invalid subject and coverage escapes | Any case projects the wrong subject, role, agent, or scope |
| IAM observation | Exact planned group and subject match on every case | Any target mismatch or unredacted provider response |
| IAM non-production enforce | 20 add/remove cycles; 100% convergence; rollback drill | Any wrong membership, unverifiable receipt, or rollback failure |
| Escalation observation | Historical timing replay plus 50 live pending approvals | Duplicate decision, changed action hash, or unauthorized rung |
| Handover pilot | 20 mapped users; opt-out and completion measured | Budget breach, sign-in blocking, or uncited accepted goal |
| Knowledge pilot | ACL, deletion, citation, and conflict suites green | Cross-ACL retrieval or promoted unreviewed candidate |

Release guard metrics are assignment activation latency, ownership-to-IAM convergence latency,
coverage defects, approval response by rung, exhausted approvals, handover invitations per user,
goal completion and opt-out, citation coverage, ACL denials, and rollback success. IAM and
escalation kill switches are independent.

## Definition of complete

These operational release criteria remain open; the source checklist above does not close them.

- [ ] Owner search returns the exact live Entra subject and existing FDAI role and duties.
- [ ] Stewardship v2 enforces one primary and one distinct backup or escalation target.
- [ ] One immutable case correlates independent review, ownership PR, IAM receipt, and audit.
- [ ] The Operator API and browser never receive membership-write credentials.
- [ ] Grants follow reviewed ownership merge; removal requires fresh independent review and a
  recorded independent IAM removal before the old-duty PR. Thor changes only allowlisted groups.
- [ ] Unanswered approvals advance by durable deadlines and exhaust to audited no-op.
- [ ] Login-triggered handover respects fatigue limits and never blocks access.
- [ ] Accepted goals cite admitted, ACL-preserving evidence and reviewed candidates only.
- [ ] Restart, duplicate delivery, outage, revoke, rollback, and demotion drills pass.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/human-agent-assignment-implementation-plan.md) |
| Target behavior and administrator experience | [Human-agent assignment and knowledge handover](human-agent-assignment-and-knowledge-handover.md) |
| Current human RBAC and access-request contract | [User RBAC and Entra identity](user-rbac-and-identity.md) |
| Ownership schema and governance lifecycle | [Agent operational ownership and handover](agent-stewardship-and-handover.md) |
| Pending approval supervision | [Escalation and standing authority](../decisioning/escalation-and-standing-authority.md) |
| Agent-owned document path | [Document ingestion agent ownership](document-ingestion-agent-ownership.md) |
