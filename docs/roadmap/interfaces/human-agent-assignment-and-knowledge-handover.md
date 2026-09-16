---
title: Human-Agent Assignment and Knowledge Transfer
---
# Human-Agent Assignment and Knowledge Transfer

This document defines the target administrator workflow for finding a person, assigning FDAI
access, mapping the person to agents, establishing approval coverage, and collecting operational
knowledge without overwhelming the person. It coordinates identity, operational ownership,
approval, conversation, and document ingestion while keeping each authority independent.

> **Safety boundary:** Mapping a person to an agent never grants an FDAI role. A combined
> administrator workflow may request both outcomes, but RBAC and operational ownership are still
> validated, approved, applied, and audited as separate axes.
> **Current scope:** The bounded source requirements and 12 distinct final integrated critique rounds
> after remaining implementation are complete at the [recorded checkpoint](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation), with no unresolved confirmed Medium/High source finding there.
> [PR #1014](https://github.com/dotnetpower/fdai/pull/1014) merged reviewed head `8c1d9977c` as `953a17de4` after exact-head [CI 34925881557](https://github.com/dotnetpower/fdai/actions/runs/34925881557) passed. Post-merge [CI 34926168342](https://github.com/dotnetpower/fdai/actions/runs/34926168342) also passed; #946 is complete.
> The [local UI follow-up](../../internals/handover-ui-evidence-20260915.md) records 28 distinct synthetic browser scenarios, 127 focused unit checks, and ten focused plus ten final integrated critique rounds under [#1017](https://github.com/dotnetpower/fdai/issues/1017).
> All 50 rubric IDs are accounted for, but required real screen-reader evidence is missing: `needs-human`, no final score or WCAG claim. Live operational evidence remains under #458.
> No deployment or promotion is enabled; readiness stays `shadow` with `operationally_ready=false`.

## Design at a glance

The target experience separates authority from operational oversight. `Settings > Identity and
access` owns exact directory identity, FDAI App Roles, and access requests. `Governance > Agent
oversight` owns the human dependency map, knowledge handover, action-specific approval routes,
and mapping reviews. An Owner proves scoped primary and backup coverage and submits one governed
assignment case. The case coordinates two effects:

1. A reviewed ownership pull request updates the agent handover map.
2. After the ownership change merges, Thor adds the person to an allowlisted Entra role group.
3. After both effects converge, the mapped agents can begin a bounded knowledge handover through
   Bragi, and uploaded evidence enters the existing agent-owned ingestion path.

![Design at a glance. The main stages are Owner searches Entra, Assignment case, Validate identity, role, coverage, and separation, Independent human review, Ownership draft PR, Reviewed merge, Allowlisted IAM group mutation, Convergence check, Bounded handover invitation, Governed documents and answers, Chunk, index, ontology candidates, and audit.](../../diagrams/generated/fdai-roadmap-interfaces-human-agent-assignment-and-knowledge-handover-01.en.svg)

## Current owners read model and Console

The additive Current owners record is joined by the Operator service from the reviewed declaration,
bounded identity-directory hints, and Owner-visible assignment cases. The browser validates and
renders that record but never joins those sources, treats a display name as authority, or hides a
missing binding, schema migration, identity check, or backup-coverage gap.
The aggregate route assembly applies this decorator to `/stewardship` for every production or
development composition, while unrelated operation projections pass through unchanged.
If assignment evidence is unavailable, the Current owners view keeps the reviewed ownership map
and marks only pending-change evidence unavailable.
A bounded assignment page is labeled partial whenever its total, cursor, or source truncation flag
shows that more cases exist.
The browser cross-checks Current owners agent order, maintainers, exact subjects, distinct
primary and backup counts, and summary totals against the validated stewardship map. Drift fails
the panel instead of selecting one version.
Current owners exposes an explicit refresh. It retains the last ready projection while the new read
is in flight and replaces it only with the next terminal ready, unavailable, or error state. The
mobile refresh control retains the shared 44 px touch target.
At container-constrained desktop and mobile widths, Current owners changes the wide comparison
table into labeled per-agent records. The responsive presentation preserves every field and does
not change scope or evidence.
Current owners localizes assignment lifecycle states and keeps the full source digest in disclosed
technical details instead of presenting machine values as primary operator copy.
The shared Console catalog retains the Current owners headings and coverage labels used before the
joined record is available. The assignment editor distinguishes an unobserved roster from a
filtered empty result and applies the standard primary and secondary button roles.

## Decisions and boundaries

- **One workflow, separate authorities:** `AssignmentCase` coordinates RBAC and ownership but
  doesn't collapse them into one permission model.
- **Group membership is the IAM write surface:** Routine registration adds or removes a person
  from one configured FDAI role group. It doesn't accept arbitrary group ids or direct role ids.
- **Ownership first, access last for grants:** A new user receives console access only after the
  reviewed ownership change merges. A failed IAM write leaves the user without new access and
  routes work to the already-required backup.
- **Explicit operational reporting:** The approval chain is an FDAI duty graph. A governed
  organization chart or Entra manager can propose a separate
  [human report line](human-report-lines-and-approval-routing.md), but one endpoint must confirm
  the edge and an independent Owner must review it. The relationship still grants no approval
  authority.
- **Timers determine non-response:** Presence, calendar, and out-of-office signals are advisory.
  Delivered, acknowledged, and decided timestamps are the authoritative escalation inputs.
- **Typed-event collaboration:** Agents don't call each other or share mutable interview state.
  Bragi is the only conversational renderer.
- **Knowledge is advisory first:** Answers and documents don't become authoritative policy or
  ontology facts without review and promotion.

Goal commands revalidate the goal subject's active accountable mapping and exact ownership source
revision, even for an otherwise identical retry. A removed, unavailable, or revised mapping holds
the command without hiding permitted prior evidence. Independent Owner acceptance remains distinct
from the goal subject. Retry identity binds the complete evidence or reason payload; a changed
payload is a conflict, and an older receipt without that binding requires refresh instead of an
assumed successful replay.

## Administrator experience

### Agent oversight workspace

The Governance surface provides an Agent oversight workspace. Keep the workspace dense and
agent-first rather than presenting a wizard or a person-first IAM editor. Identity and role
details are read-only projections from the IAM authority.

| Region | Contents |
|--------|----------|
| Overview | Provider availability, authority mode, maintainer floor, backup coverage, overload, and source freshness. |
| Human dependencies | Fixed Pantheon roles, Agent plus scope ownership, exact subjects, groups or schedules, effective dates, and fail-closed validation. |
| Knowledge handover | Agent-owned goal templates, evidence weights, ACL and source spans, staleness, fatigue budget, and sign-in invitations. |
| Approval routes | ActionType and scope, eligible roles, quorum, requester separation, delivery state, non-response TTLs, and standing authority. |
| Mapping reviews | Immutable case revision, current-to-proposed diff, independent reviewers, ownership PR, IAM convergence, rollback, and audit receipts. |

`GET /stewardship` version 2 preserves each accountable owner's `primary`, `backup`, or
`escalation` duty. Informed relationships omit duty. The browser treats a missing accountable
duty or an informed relationship with duty as a contract error instead of inferring operational
ownership from list order.

The browser searches through `GET /iam/directory/users`; it never receives Graph credentials. A
result exposes the stable provider subject id, active state, member or guest type, current FDAI App
Roles, existing agent mappings, and current coverage. Display name and username are recognition
hints, not authoritative identifiers.

### Coordinated assignment review

1. **Identity:** Resolve exactly one active directory subject, group, or configured schedule.
  Ambiguous free text remains a candidate and can't be submitted.
2. **Scope:** Bind operational ownership to Agent plus service, environment, and target scope.
3. **Ownership:** Assign accountable primary, backup, or escalation duties separately from an
  informed relationship. Informed entries have no duty.
4. **Approval coverage:** Evaluate ActionType-specific role eligibility, quorum, and requester,
  target, reviewer, and executor separation.
5. **Handover goals:** Start from the selected Agent's versioned goal templates and attach
  admitted documents, links, or explicit not-applicable decisions.
6. **Review:** Block submission on coverage defects and show intended effects, independent
  reviewers, rollback or forward repair, source freshness, and residual warnings.

The editor may save a private draft, but submission creates one immutable `AssignmentCase`. A
later intent change creates a superseding case instead of editing approved history.

**H10 ownership-only source path:** Exact user, group, and configured schedule declarations use
separate scoped-duty cases, not personal IAM assignments. Owner-only
`POST /handover/scoped-duty-cases` enters the existing immutable outbox and fixed-agent review
chain with transport `1.2.0`. Two distinct current Owners review the exact plan; the requester,
resolved targets, and static fallbacks cannot review it. Replays retain each command's original
state and revision even when a later review has already completed.

Core binds `FDAI_SCOPED_DUTY_CATALOG_PATH` to a private, bounded JSON catalog with
`schema_version: "1.0.0"`, exact `scopes`, and configured `shifts` (`rotation`, `primary_oid`,
`secondary_oid`, `start`, `until`). Its content-derived revision is reread after identity I/O.
Entra reads require complete active-person expansion; schedule lookup reuses `OnCallSchedule`.
Unknown scopes, ambiguous or incomplete groups, expired sources, and future-only intervals hold.
The declared static person is separately resolved when a schedule is unavailable.

After independent review, the existing draft publisher proposes one immutable file under
`config/scoped-duty-plans/` in the private deployment repository. A separate reader checks the
exact PR head's human review, human merge, and matching content at both the merge commit and current
default branch. Only then does `GET /handover/scoped-duties?agent_name=...&scope_ref=...` expose
current scope coverage. The observation expires within 60 seconds or sooner at a source or duty
boundary; configured reconciliation runs at most 30 seconds apart. Partial scans, overlapping
cases, changed artifacts, and unavailable sources are held, not merged with the global map.
`GET /handover/scoped-duties/catalog` separately reports catalog and artifact-delivery availability.
An explicit `supersedes_case_id` can replace only a reviewed case over the same agent/scopes.
Until the new artifact is independently observed as merged, it cannot displace the old observation.
After that observation, retained negative supersession prevents an outage from reviving old duties.

The actual `/agent-oversight/mapping-reviews` Console route now includes this ownership-only
workspace. Its six existing API calls support exact case navigation, explicit UTC intervals,
static schedule fallback, supersession, and manual refresh. HTTP202 remains `awaiting_core` until
an authoritative GET supplies the case; uncertain retries preserve the original request identity.
Field corrections link to their inputs, and add/remove or completed-request focus returns to a
usable control without stealing deliberate navigation. The [follow-up evidence](../../internals/handover-ui-evidence-20260915.md)
covers bilingual keyboard, long/expanded content, 320px reflow, actual 200% text, themes and pending
recovery. All API responses are synthetic; required screen-reader speech and live-scope evidence remain open.

Group expansion never creates personal grants, today's schedule proves no future coverage, and
the global v2 map stays unchanged. The workspace grants no IAM role, document ACL, or execution
authority. Live identity, GitHub evidence, operational adoption, and real assistive-technology checks
remain separate requirements. Checklist controls follow each server-advertised operation, preserve
the review revision, and reset private input and late replies when the client or goal changes.

## Assignment and duty model

### Composite assignment case

`AssignmentCase` is coordination state, not a new authorization source.

| Field | Purpose |
|-------|---------|
| `case_id` and `idempotency_key` | Retry and audit correlation. |
| `subject_ref` | Provider plus immutable Entra object id. |
| `requested_role` | Desired FDAI App Role and configured group slot. |
| `duty_bindings` | Agent, duty slot, scope, and effective dates. |
| `approval_routes` | Ordered eligible subjects or schedule references. |
| `handover_goal_refs` | Versioned goal templates selected for the person. |
| `requester`, `reviewers`, and `justification` | Separation of duties and attribution. |
| `effect_receipts` | Ownership PR and IAM provider receipts. |

Grant states are `draft -> pending_review -> approved -> ownership_pr_open -> ownership_merged ->
iam_applying -> active`. A separately reviewed `revocation` intent pins the original and replacement
revisions and follows `approved -> iam_applying -> iam_revoked -> ownership_pr_open -> revoked`.
`rejected`, `degraded`, and `superseded` remain terminal or held outcomes. Core goal mutation needs
an active, unheld assignment; current ownership and evidence checks still apply. Held or removed
assignments preserve permitted prior evidence, not mutation or acceptance authority.

### Minimum coverage

Every non-autonomous agent and governed operational scope needs:

- **Primary:** At least one `primary` accountable owner.
- **Backup:** At least one distinct `backup` owner or one explicit `escalation` target.
- **Approval eligibility:** At least two distinct live principals who can satisfy the minimum role
  for approval-bearing actions in that scope.
- **Platform fallback:** FDAI maintainers remain the final platform escalation, but they don't
  satisfy domain backup coverage unless explicitly assigned to that duty.

Coverage requires current resolution to distinct people; a primary and backup that resolve to one
person cannot prove it. An unresolved group may remain a notification target but proves no
two-person approval coverage. H10's current group/schedule resolution is connected to scoped
review, merge observation, projection, and the bounded Console workspace. Live coverage still
requires current deployment evidence. One person may own several agents, but overload remains visible.

### Operational reporting graph

Use an explicit, acyclic duty graph:

```text
HumanPrincipal -> occupies -> AgentDuty(primary|backup|escalation)
AgentDuty -> covers -> Agent + scope
AgentDuty -> escalates_to -> AgentDuty or schedule
AgentDuty -> requires_role -> FDAI App Role
```

The graph is deployment state and never enters the upstream catalog with real tenant values. It
has a configured maximum depth, no self-loop, effective dates, and one static fallback even when a
schedule adapter supplies the current on-call person.

## Governed IAM provisioning

The shared membership SDK, Core material and approval services, and isolated Graph adapter form
the implemented source path. Core plans and reads evidence without a mutation identity. Operator
accepts governed proposals and human decisions but, like the browser and ingestion services,
receives no Graph writer. The legacy Core `HumanAccessDirectApiExecutor` still refuses enforce;
the separate isolated path supports it only after current, independent promotion and all gates.

1. **Material:** After the grant's reviewed ownership merge, Forseti binds the original catalog
  `Action` to the exact case, person, allowlisted role group, current promotion, and target digest.
  A removal instead requires its new reviewed intent and current replacement coverage.
2. **Human approval:** Var parks existing human-in-the-loop (HIL) slots for that immutable material.
  Reader/Contributor access requires one current eligible Owner; Approver/Owner access requires
  two distinct current eligible Owners. The requester and target never count. Existing role,
  ActionType approval policy, risk/quorum ceilings, and the original non-sliding five-minute
  window apply. Original case reviews are not execution approval.
3. **Preparation:** After Saga seals the review, Muninn atomically records the exact material and
  case preparation from revision `r` to `r+1`. The approved `expected_revision=r`, Action bytes,
  and approval expiry remain unchanged. Restart cannot renew or rebind them.
4. **Dispatch:** Thor alone publishes through the shared seven-safeguard coordinator. Core and
  Executor use the same normalized subject/group lock across cases, grants, removals, and inverses.
  Current source, human approval, role/action policy, kill switch, degradation, and promotion are
  rechecked before publication and at their dispatch boundaries. The isolated Executor persists
  exact pre-state and intent before one Graph mutation, then an immutable acknowledged result.
5. **Effect:** A provider acknowledgement is not success. Independently attributed Heimdall
  observation, Forseti judgment, Saga sealing, and the existing atomic post-release closure precede
  Muninn's IAM effect. Only the required ownership and IAM effects can activate or revoke a case.
  A new user token may still be needed before the role claim appears.

The seven safeguards remain stop condition, tested rollback, bounded blast radius, successful
dry-run, logical-target lock, stable idempotency key, and two-phase audit. The isolated writer uses
a distinct dedicated identity and an immutable allowlist of four routine FDAI role groups. It
cannot create groups, grant BreakGlass, target arbitrary/dynamic/role-assignable groups, or borrow
cloud-resource execution permissions. Microsoft Graph membership mutation requires
`GroupMember.ReadWrite.All`; active-user inspection also requires `User.Read.All`. These are
external tenant permissions, and the code allowlist does not narrow their directory permission scope.

**Recovery is a new approval, not an automatic inverse.** Existing `ops.apply-human-access` and
`ops.revoke-human-access` ActionTypes use `recovery_of` to bind the exact original owned mutation,
pre-state, immutable intent/result, current demand, and target generation. Forseti judges; Vidar
proposes and finishes on its owned Rollback topic; Var requires fresh independent Owner slots and
the existing ActionType whitelist; Thor alone dispatches. Independent inverse observation and
shared atomic closure are required before rollback completion. The Core case stays `degraded`:
recovery restores no duties, goal authority, approval, or promotion. `ALREADY_APPLIED`, unknown
ownership, intervening attempts, and unacknowledged dispatch cannot authorize an inverse or an
automatic mutation retry. A reference string alone is not tested rollback evidence.

Every venue uses the same source/configuration and authority rules; only venue-owned credentials,
endpoints, and provider scope differ. Local authority cutover is forbidden, and shadow performs
no mutation. A legacy shadow notice never becomes enforce-capable through replay.

Revocation starts with pinned, current replacement coverage and a new removal review, not the
grant's old approval. Request and result transport `1.1.0` preserve that intent; legacy grant
compatibility never reinterprets removal as a grant. Core holds the exact original case through
compare-and-set (CAS) before effects and keeps the hold recoverable after restart. A hold is not
proof of removal or restoration.

The reverse effect order removes IAM access before opening a review-only old-duty PR. The PR
requires an independently recorded IAM removal receipt; only its exact signed merge reaches
`revoked` and closes the original hold without another grant request. Rendering rechecks pinned
replacement revisions and current duties, not an inferred promotion of a backup. Other active or
uncertain grants retain their membership. The API permits an inactive exact person only as a
removal target. Execution approval, target locking, independent observation, and recovery are now
source-connected. Live credentials, permissions, Graph effects, lock/recovery drills, and promotion
remain external gates; [#458](https://github.com/dotnetpower/fdai/issues/458) remains open.

## Approval non-response and escalation

Channel fallback and human escalation remain separate. Channel fallback retries delivery to the
same rung. The approval supervisor advances to another authorized person after non-response.

Each pending approval stores `delivered_at`, `ack_deadline`, `decision_deadline`, the overall
deadline, current rung, attempted subjects, action hash, minimum role, requester, target, impact,
urgency, and schedule resolution receipt.

The default progression is primary -> backup -> escalation duty -> maintainer. A declared
unavailable or delegate response advances immediately. A rejection is terminal and doesn't mean
"ask someone else until approved." The next rung receives the unchanged action hash and remaining
deadline. The first valid decision wins through a compare-and-set claim; late decisions are audited
and ignored.

If all rungs expire, the action ends as an audited no-op. Standing authorization, when separately
configured, may re-enter the normal risk gate, but absence never creates automatic authority.

## Proactive knowledge transfer

### Session trigger

After an `active` assignment's user signs in, Huginn emits a content-free session-start event. The
handover lifecycle loads incomplete goals. Mapped agents publish their knowledge gaps, Odin
deduplicates and prioritizes them, and Bragi offers one invitation: "Muninn has two unanswered
runbook questions for your ownership area. Spend up to five minutes now, upload a document, or
remind me later."

The mapped agent owns the question and acceptance criteria. Bragi only translates and renders it.
Declining or snoozing never blocks console access and never marks a goal complete.

### Knowledge transfer goals

A `HandoverGoal` is a versioned checklist with evidence requirements. The default template covers:

- operational scope and explicit exclusions;
- decision triggers, thresholds, SLOs, and maintenance windows;
- runbooks, rollback procedures, and verification steps;
- dependencies, contacts, primary and backup escalation routes;
- known failure modes, exceptions, and unresolved risks;
- authoritative documents, source owners, review dates, and retention class.

The shared `handover_checklist` `1.0.0` assigns six explicit slots. Each requires admitted document
evidence or its own reasoned `not_applicable` exemption; an unslotted legacy document proves no
completeness. States are `not_started`, `in_progress`, `blocked`, `ready_for_review`, `accepted`,
and `stale`. Legacy accepted or review-ready records missing current requirements project as
`blocked`; their persisted history is not rewritten.

Acceptance binds an independent Owner and, by the high-impact default, a distinct current backup
to the exact checklist digest. The first and prior reviewers' current directory roles and backup
duties are rechecked. Unknown impact does not lower review requirements. Reader-only backup
review requires current role-group membership observed by the directory and a matching document
ACL. A direct Reader role, duty, token, or goal field never proves membership. The group evidence
stays server-private; an unavailable or partial roster holds the review.
The document route uses the shared slots, exemptions, and server-authorized review commands.
Choose one file for each selected handover area. Multi-file drops are rejected before transfer;
processing warnings never hide an uploaded document's failed handover link.
Same-person, same-scope, same-current-ownership-revision evidence may be reused across current
agents after source revalidation, but reviews are never copied and the target needs new acceptance.

Operator's current source binding performs the required admission checks. Core binds its goal service,
`GoalEvidenceAdmission`, `GoalReviewerEligibility`, and retrieval through `CoreHandoverDocumentReader`,
`PostgresCoreHandoverReview`, and `PostgresCoreHandoverSearch`; the knowledge-owner path retains current Core goal validation.
`CombinedGovernedHandoverReader` accepts `target`, `exact_refs`, `context_source`, `conversation_ref`, and `document_context_digest`; any explicit selector is forwarded unchanged only to the existing governed reader, never the broad Core handover search.
For these scoped requests, an absent or failed existing source raises without widening or fallback. Direct `CoreHandoverDocumentReader` calls accept the same signature but hold scoped requests before I/O.
Ordinary unconstrained merging is unchanged. Source admission precedes content; missing or stale identity,
reviewer, ACL, or source evidence holds without borrowing Operator authority.
Operator admission requires governed knowledge, an active index, live retention, exact uploader
and digest, and actual boolean availability. Its restricted SQL reads require the Operator role;
neither that reader nor the Core source reader receives document-table `SELECT`.

### Fatigue budget

Use configurable defaults that prefer asynchronous evidence over repeated questions:

- at most one proactive invitation per login and one active handover session across the subject;
- at most three unique turn identities within a fixed, non-sliding five-minute session;
- a 24-hour snooze and no more than two actual handover sessions per ISO week;
- no invitation while the user is handling an incident or approval;
- ask the highest-risk unresolved question first and reuse accepted facts across agents;
- always offer `Upload document`, `Answer now`, and `Remind me later`.

Critical gaps remain visible in the assignment roster after the budget is exhausted. They become
accountable work, not repeated pop-ups.

Operator reserves each turn before narration in a durable subject-wide record. Exact retries keep
the original deadline; changed content conflicts. A fourth unique turn, another active session,
a third ISO-week session, expired reuse, or backward clock movement is held. Even exact retries
recheck current ownership, active identity, busy-work suppression, and goal eligibility; invalidated
ownership, a busy user, or a stale or accepted goal cannot bypass the hold. The semantic deadline is
lowered to the remaining session time, never extended by retry, restart, or the browser.
The Console conversation key retains both login and goal identity. A later login does not reuse
an exhausted goal-only session; the subject-wide server ceilings still apply.
Successful authentication redirects renew that identity even in the same tab. Reload and silent
token renewal keep the current identity; neither refreshes the server's weekly allowance.

## Knowledge processing and agent collaboration

Answers, links, and files first enter the existing document-ingestion boundary, which owns
admission, protection, chunking, and ACL enforcement. The conversation never writes directly to a
vector index or ontology. The handover chain now connects private semantic-package compilation
and independent review without replacing ingestion. The Core bootstrap uses
`bind_handover_semantics` through existing `AssignmentWorkflowBindings` with actual Norns/Mimir
providers.

Document providers use the shared venue resolver and document-provider capability table. An absent
or empty venue selects the stricter deployed binding; an unknown value fails before provider I/O.
Missing deployed prerequisites keep compilation unavailable even when a local document path exists.
Local storage is selected only by the explicit local capability, never as a remote-source fallback.

The worker publishes mechanical `knowledge.handover.source_observed.v1` notices, not source labels
that pretend to be Muninn, Mimir, or Norns decisions. The actual chain is:
Huginn -> Forseti -> Saga -> Muninn `StateSnapshot` -> Saga -> Norns -> Mimir -> Saga.

| Owner | Current responsibility |
|-------|------------------------|
| Huginn | Normalize the content-free source notice. |
| Forseti | Independently check the exact source and route explicit digest conflicts for clarification. |
| Saga | Record independent stage results and seal content-free package references at the chain's audit boundaries. |
| Muninn | Materialize a `StateSnapshot`, not a compiled rule or ontology fact. |
| Norns | Retain existing consensus, publication gate, and rate limit; compile exact `fdai.rule.candidate.v1` JSON Rules and existing described `Distiller` ontology candidates into private immutable SQL packages. |
| Mimir | Reread current sources before private content, independently recompile without model calls, and retire or scrub packages under current retention policy on its existing subscription; emit inert review results. |

Forseti, Muninn, Norns, and Mimir independently reread the source and use owner-local CAS. Messages carry
references and digests, never document text or shared mutable stage authority. Each subscriber is
independently retryable; another owner's state cannot substitute for its own decision.

- **Exact observation:** Goal observation `1.1.0` uses a content-free digest and exact source-read
  checks. Observing accepted state neither admits its documents nor grants review authority.
- **Restricted SQL:** Core's restricted document functions check exact uploader/digest, boolean
  availability, governed state, active index, retention, and principal-bound ACLs without raw
  document-table `SELECT`. Semantic reads also require `manual_distillation` purpose and current
  review before source or private package content access. These local checks are not live
  directory, cohort, or deployed source evidence.
- **Withdrawal:** Withdrawal is monotonic for the same source revision. A fixed five-minute
  recheck and a tracked latest source identity preserve deletion and restart handling.
  Ongoing revocation holds block contribution. A closed removal permits a separately active new
  grant for the exact agent and scope; it never reactivates the old case.
- **Conflict boundary:** An explicit same-document conflicting digest follows Forseti -> Odin and
  produces clarification-required, without a winner. The older `publish_knowledge_conflict` helper
  remains a proposal primitive, not arbitrary semantic contradiction detection.

Existing deterministic chunks retain source spans, version, ACL, chunk-policy version, content
digest, and optional goal references. Retrieval remains source-ACL-bound and requires current
admission. Compilation preserves significant whitespace within JSON strings and original source
locators. Compilation checks canonical package, source, and claim identities plus current policy,
remediation-template, and schema digests. Cancellation propagates, and work is capped by the
original notice deadline.

Private-package compilation, independent review, and source-connected retention are implemented.
Mimir checks at most 25 packages per notice and retires them monotonically on withdrawal, drift,
or the stricter original/current expiry. Legal hold preserves inaccessible bytes; unknown hold or
unavailable source never authorizes scrubbing. Erasure requires explicit current no-hold evidence
and preserves immutable claim, digest, receipt, and audit so extraction cannot restart under the
same identity. Typed Rule compilation still does not prove single-model prose Rule fidelity.
Provider conformance, deployed source/hold policy, and cohort evidence remain external. Private
packages grant no catalog, graph, promotion, IAM, or new document-read authority.

## Security, privacy, and failure behavior

- Directory search, roster read, role mutation, manager lookup, calendar, and presence use separate
  provider capabilities. Manager, calendar, and presence access is optional.
- Raw document text, names, usernames, object ids, tokens, and provider responses don't enter logs
  or general event topics. Audit stores stable references and digests.
- A directory outage blocks new assignment submission or IAM apply but doesn't erase ownership. A
  schedule outage uses the required static backup.
- If ownership merged but IAM is uncertain or failed, hold the case and preserve backup coverage.
  Reconcile the retained attempt without repeating a possibly applied mutation; a separately
  approved inverse is available only for proven owned change.
- A handover conversation can't raise autonomy, modify IAM, approve its own evidence, or promote a
  rule or ontology candidate.
- Every mutation retains all seven safeguards and independent effect verification. Recovery
  restores only the exact approved membership pre-state, never duty, approval, document ACL,
  or promotion authority.

## Delivery plan and exit criteria

The dependency order, PR-owned file surfaces, compatibility migration, focused tests, Azure
permissions, rollout evidence, and stop conditions are defined in the
[Human-agent assignment implementation plan](human-agent-assignment-implementation-plan.md).

Production controls expose independent availability, enabled, and authority-mode axes. A kill
switch only lowers mutation eligibility. The audited enabled preference takes effect at restart
and can suppress privileged adapter composition without changing promotion state. Reconciliation
uses the existing bounded worker at `human_access.reconciliation_interval_seconds`; it observes
held cases without invoking the IAM provider or writing recovery actions.

S5 adds a report from that reconciliation: sampled counts, total, invalid count, partial status,
alert observations, explicit source gaps, and external blockers. Mean effect-receipt interval uses
only cases with two effects and is `null` when none qualify. Owner-only `GET /handover/readiness`
expires after ten minutes; future-dated or malformed reports are unavailable. It always reports
`shadow` and not operationally ready. It does not dispatch alerts, check providers, write recovery
actions, or promote any capability.

The [current-change scope](human-agent-assignment-implementation-plan.md#current-change-evidence-and-remaining-scope)
and [12-round final integrated record](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation) document completed bounded source implementation and source review.
That conclusion is limited to the recorded checkpoint; overlapping evidence counts are not summed.
The second local merge is published as `c8edd2769`; CI 34921323157 attempt 1 failed. Focused local source repairs are implemented, while reviewed translation refresh, canonical generation, repair hooks/PR update, and passing exact-head protected CI/merge remain open under [#946](https://github.com/dotnetpower/fdai/issues/946).
Full UI-rubric/assistive-technology evidence and live provider, identity, IAM, GitHub App, Teams,
source policy, deployment, drills, and cohorts remain separate open requirements.

1. **Assignment projection:** Use the composite read model, coverage validator, IAM identity
  projection, and Governance Agent oversight workspace. Submission creates no provider mutation.
2. **Governed IAM apply:** Use the isolated, exact-approved path and independently observed recovery.
  Promote only after the required shadow comparisons and non-production drills.
3. **Approval supervisor:** Use primary, backup, and escalation duties plus the non-response timer.
   Run shadow timing against real approval history before enabling rung transitions.
4. **Proactive handover:** Use goal templates, one-invitation policy, snooze, summaries, and review.
   Measure completion and opt-out, not message count.
5. **Knowledge lifecycle:** Use independent source observations and inert private compilation,
   review, and retention. Retain provider conformance and live source/cohort evidence separately.

The following first-release operational criteria remain open; source checks alone do not close them:

- [ ] An Owner can search an exact active Entra subject and see existing role and agent mappings.
- [ ] Every active mapping proves one primary and one distinct backup or escalation target.
- [ ] A reviewed case automatically converges the ownership PR and allowlisted IAM membership.
- [ ] No requester or target can approve their own access, and elevated roles require quorum.
- [ ] An unanswered approval advances through eligible rungs and ends in an audited no-op.
- [ ] A mapped user receives no more than the configured handover budget and can snooze or upload.
- [ ] Every accepted goal cites admitted evidence, and every chunk preserves source ACL and span.
- [ ] Agent collaboration is typed-event-only, retryable, content-minimized, and Saga-audited.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/human-agent-assignment-and-knowledge-handover.md) |
| Dependency-ordered implementation and rollout | [Human-agent assignment implementation plan](human-agent-assignment-implementation-plan.md) |
| FDAI roles, directory search, and current access requests | [User RBAC and Entra identity](user-rbac-and-identity.md) |
| Ownership map and accountable owners | [Agent operational ownership and ownership handover](agent-stewardship-and-handover.md) |
| Human reporting relationships and approval routing | [Human report lines and approval routing](human-report-lines-and-approval-routing.md) |
| Human non-response and standing authorization | [Escalation and standing authority](../decisioning/escalation-and-standing-authority.md) |
| Agent-owned document admission and indexing | [Document ingestion agent ownership](document-ingestion-agent-ownership.md) |
| Console and ChatOps security boundaries | [Operator console](operator-console.md) |
