---
title: Agent Operational Ownership Lifecycle
---
# Agent Operational Ownership Lifecycle

This document defines the implemented runtime and governance lifecycle for FDAI operational
ownership (`stewardship`). It complements the handover-map schema and ownership concepts in
[Agent operational ownership and ownership handover](agent-stewardship-and-handover.md).

> The console's ownership projection remains read-only. Its guided form submits a handover document
> to the ingestion boundary; ownership changes are still generated as draft pull requests, reviewed
> through the Git host, and observed after merge through a signed webhook. Stewardship grants no
> RBAC capability and never receives Thor's executor identity. Upload-format discovery, governed
> preview, connectors, and cancellation reconciliation remain ingestion-owned; they grant no
> document-read, connector, or ownership authority to the webhook. Local or Azure OCR readiness
> changes advertised image formats, not the handover, RBAC role, or accountable owner.
> **Current evidence:** The 2026-09-15 source checkpoints include scoped Console ownership,
> Core goal/reviewer/admission/retrieval, private semantic retention, and isolated IAM recovery.
> The [final record](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation) completes 12 distinct rounds after remaining source implementation, with no unresolved confirmed Medium/High source finding.
> Translation SHA refresh, canonical generation, local hooks, publication/CI, and full UI/assistive/live
> evidence remain pending. Readiness stays `shadow`, `operationally_ready=false`; [#458](https://github.com/dotnetpower/fdai/issues/458) remains open.

Cloud-reference collection and signed intake share this ingestion host, not its ownership authority.
They never create a handover draft or change a steward; [their lifecycle](cloud-resource-knowledge-lifecycle.md)
uses separate source/trust policy and the existing independent document approval gates.

## Design at a glance

The lifecycle has four independent safety boundaries:

1. **Startup readiness** loads the same handover map in production and rejects placeholder
   identities.
2. **Scheduled health** checks active Entra users off the control-loop hot path and audits only
   health-state transitions.
3. **Draft delivery** turns a grounded handover document into one idempotent governance PR.
4. **Merge observation** verifies the GitHub signature, re-reads changed files and merged content,
   then writes the merge audit and notifies the new accountable owners.

![Design at a glance. The main stages are Terraform bindings, Production startup validation, GET /stewardship, Scheduled Entra liveness check, Guided registration form, Grounded handover upload, Durable handover draft, Idempotent draft governance PR, Git review and approval, Signed merge webhook, GitHub files and merged YAML re-read, Append-only Saga audit.](../../diagrams/generated/fdai-roadmap-interfaces-agent-stewardship-operations-01.en.svg)

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Startup binding and read-only projection | implemented | `services/operator-service/src/fdai_operator_service/`; `services/operator-service/tests/test_operator_operations_family.py`; `tests/integration/infra/test_operator_api_stewardship.py`; focused Operator and Terraform tests (15 passed) | The route and deployment bindings exist. Source wiring doesn't by itself prove a live deployment is ready. |
| Terraform binding completeness gates | implemented | `infra/production-gates.tf`; `.github/workflows/deploy-dev.yml`; `tests/integration/infra/test_operator_api_stewardship.py`; `tests/integration/infra/test_core_stewardship_gitops.py` | Production configuration requires maintainers and every non-autonomous agent binding while keeping identities and GitOps credentials deployment-owned. |
| Guided registration and grounded durable draft | implemented | `console/src/routes/handover-editor.tsx`; `services/document-processing-worker/src/fdai_document_worker_service/handover.py`; focused console tests (21 passed); focused ingestion delivery tests (9 passed) | The SPA submits a governed upload and the worker stores a review-only draft. Neither effect changes the active map. |
| Idempotent draft governance PR delivery | implemented | [`governance.py`](../../../services/core-control-plane/src/fdai/core/stewardship/governance.py); [`stewardship_governance.py`](../../../services/core-control-plane/src/fdai/runtime/stewardship_governance.py); focused stewardship and runtime tests | The runtime reads durable `handover_draft:*` records, validates each complete candidate without accepting identity overrides, publishes through the configured `RemediationPrPublisher`, and atomically records the PR reference or rejection with a Saga audit. Content-addressed receipts make restart and replay safe. A governed deployment receipt remains separate evidence. |
| Signed merge intake and downstream ownership effects | implemented | `services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/stewardship.py`; `services/core-control-plane/src/fdai/runtime/stewardship_merge_effects.py`; focused merge and ownership-coordination tests | Signed intake persists inert evidence. Core validates the merged map, computes recipients, and advances only a digest-matched proposal with notification and Saga audit. A grant merge publishes a replay-stable shadow IAM request; a removal merge never requests another grant. |
| Scheduled persisted identity health | implemented | `services/core-control-plane/src/fdai/runtime/stewardship_identity_health.py`; `services/operator-service/src/fdai_operator_service/ownership_projection.py`; Core service Terraform | A readiness-gated Core worker deduplicates user subjects, records transition-only health and expiring successful observations, preserves the last success across Graph failure, and feeds only revision-matched unexpired results into the read-only Operator projection. |
| Refreshable GitHub App authentication | implemented | `packages/github-app-auth`; Core and ingestion GitHub adapters; focused authentication, deployment, and Terraform checks | Each long-running service mints a repository-scoped installation token from a Key Vault-backed private key, caches it under an async lock, and refreshes before expiry. Static tokens remain a bounded compatibility input, not the deployment target. |
| Review-only old-duty removal | implemented | [Revocation coordinator](../../../services/core-control-plane/src/fdai/core/human_assignment/revocation_ownership.py); [revocation intent](../../../services/core-control-plane/src/fdai/core/human_assignment/revocation_intent.py); [execution checkpoint](../../internals/handover-lifecycle-hardening-20260914.md#execution-source-critique-checkpoint) | Request/result `1.1.0` pin original and replacement revisions. Fresh independent review and an original-case CAS hold precede effects; independently observed IAM removal and atomic closure precede the old-duty PR. Source connection does not promote enforcement. |
| H10 scoped review and Console | implemented | [Scoped request processing](../../../services/core-control-plane/src/fdai/core/human_assignment/scoped_duty_requests.py); [Console workspace](../../../console/src/routes/scoped-duty-workspace.tsx); [UI checkpoint](../../internals/handover-lifecycle-hardening-20260914.md#h10-console-implementation-and-focused-critique-evidence):95 unit and6 Playwright passes | Current group/schedule/scope evidence, two-Owner review, immutable artifact/merge observation, supersession, and manual GET reach the actual Mapping reviews route. Synthetic API checks are not full WCAG/rubric or live-scope proof; no IAM, role, or ACL grant. |
| Isolated membership execution and fresh inverse | implemented | [Core runtime](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py); [isolated executor](../../../services/isolated-executor/src/fdai_executor_service/human_access.py); [inverse](../../../services/core-control-plane/src/fdai/runtime/human_access_recovery.py); [closure](../../../services/core-control-plane/src/fdai/delivery/human_access_closure.py); [checkpoint](../../internals/handover-lifecycle-hardening-20260914.md#execution-source-critique-checkpoint):132 focused and separate21 real-SQL/fixed-agent passes | Shared SDK, original HIL/preparation, same subject/group lock, durable intent/result, and independent Heimdall effects are connected. Vidar proposes/finishes, Var freshly approves, Thor alone dispatches, Core stays degraded after inverse. Provider/Owner observations are synthetic; counts overlap. Legacy Core refuses enforce; isolated enforce remains separately gated. |
| Bounded handover readiness report | implemented | [Readiness model](../../../services/core-control-plane/src/fdai/core/human_assignment/readiness.py); [reconciliation worker](../../../services/core-control-plane/src/fdai/runtime/human_assignment_reconciliation.py); [recorded evidence](../../internals/handover-lifecycle-hardening-20260914.md) | The worker reports sampled/total/invalid/partial evidence, effect intervals, alerts, an empty completed source-gap inventory, and external blockers. Owner reads stay `shadow`, `operationally_ready=false`; reporting performs no alert dispatch, provider check, recovery write, or promotion. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | implemented | Aligned the ingestion API's fallback Pantheon transport with the canonical `fdai.pantheon.objects` Event Bus topic. Terraform remains the naming authority, and the change does not alter stewardship resolution, notification ordering, RBAC, approval, or execution authority. | `current change`; ingestion composition defaults, Event Bus naming contract, and focused independent-service checks. | Retain the protected Event Bus migration and post-apply transport receipt tracked by the deployment naming owner. |
| 2026-08-18 | in-progress | Made the ingestion API composition that builds the stewardship webhook and repository handover intake resolve its execution venue through the shared contract instead of a private parser, so a venue-selected credential or endpoint cannot diverge from the other services. No stewardship lifecycle behavior changed. | `current change`; `services/document-ingestion-api/tests` passed with the other independent service suites at 874 focused cases and 1 skip; the venue gate reported OK across 6 source trees. | The unwired post-merge ownership effects and scheduled identity health below remain open. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the lifecycle claim to distinguish startup, draft generation, signed merge intake, and unimplemented operational effects. | `current change`; source and focused checks listed in the scope table. | Wire governance PR publication, complete post-merge effects and scheduled identity health, then retain runtime evidence. |
| 2026-08-16 | in-progress | Composed the idempotent handover-artifact-to-`RemediationPrPublisher` path with a content-addressed key, review-only rendering, and fail-closed draft validation. | `pytest services/core-control-plane/tests/core/stewardship/test_governance.py` passed 9 focused tests, including retry reuse of one draft PR after an ambiguous transport failure and bounded warning rendering in the PR body. | Bind the service in production composition, complete post-merge ownership effects, and add scheduled identity health. |
| 2026-09-05 | in-progress | Added the production runtime worker for durable handover drafts. It rejects malformed candidates without blocking later records, ignores runtime identity overrides while validating tracked YAML, preserves older serialized drafts, and records one content-addressed receipt plus Saga audit. | `current change`; `stewardship_governance.py`; focused stewardship, runtime governance, and bootstrap tests passed 149 cases; Ruff and strict mypy passed. | Retain a real draft-PR receipt, then complete merge effects and scheduled identity health. |
| 2026-09-05 | implemented | Connected signed merge evidence to affected-owner notification, matching assignment effects, replay-stable shadow IAM requests, and scheduled Entra liveness observations without joining ownership, IAM, approval, or execution authority. | `current change`; focused Core and Operator tests; Core service Terraform validation. | Retain governed deployment, restart, notification, Graph recovery, and promotion evidence. |
| 2026-09-06 | implemented | Bound the protected platform workflow to the deployment-owned stewardship activation flag, GitOps target, GitHub credential, and merge-webhook secret. Activation remains false unless the explicit repository variable is enabled. | `current change`; `deploy-dev.yml`; focused Core stewardship GitOps workflow tests. | Configure the provider-hosted GitHub App token, webhook secret, and ChatOps channel secrets, then retain a governed plan, apply, and end-to-end draft receipt. |
| 2026-09-06 | implemented | Replaced the static installation-token target design with a refreshable GitHub App credential lease shared by Core publication and ingestion merge verification. | `current change`; GitHub App provider, adapter, service materializer, guard, and three Terraform roots; 516 focused tests passed. | Configure and install the provider-hosted App, then retain token refresh and end-to-end draft/merge evidence without exposing credentials. |
| 2026-09-14 | implemented | Connected the separately reviewed reverse-removal lifecycle and bounded read-only readiness reporting; neither enables enforcement or establishes operational readiness. | `current change`; revocation and readiness sources above; the main implementation session reported 451 passing focused task tests including actual SQL role tests. | H10 and the other source gaps remain open; #458 provider, identity, GitHub App, independent IAM effect, target-lock, and drill evidence plus notification, document, deployment, and cohort evidence remain separate blockers. |
| 2026-09-15 | implemented | Correction: H10 now includes the actual scoped Console route, and current Core goal/reviewer/admission/retrieval plus private typed Rule/ontology compilation/review and Mimir retention close the earlier source gaps. Retirement is monotonic; unknown hold or unavailable source never authorizes erasure. | `current change`; [workspace](../../../console/src/routes/scoped-duty-workspace.tsx), [Core binding](../../../services/core-control-plane/src/fdai/runtime/core_handover.py), [semantic binding](../../../services/core-control-plane/src/fdai/runtime/handover_semantics.py), [retention](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/handover_retention.py); [record](../../internals/handover-lifecycle-hardening-20260914.md):95 unit/6 Playwright UI checks and60 retention checks, with earlier Core/semantic selections kept separate. | No full WCAG/rubric or live-scope claim. Final integrated/static/delivery review, current identity, GitHub/Teams/source/hold evidence, cohorts, and drills remain open; no role or ACL changes. |
| 2026-09-15 | implemented | Correction: actual isolated membership execution, current HIL, exact preparation, same target lock, independent observation, atomic post-release closure, and fresh `recovery_of` inverse are source-connected. Only the legacy Core adapter always refuses enforce; source/configuration rules stay venue-independent, local authority cutover stays forbidden, and shadow never mutates. | `current change`; [runtime](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py), [executor](../../../services/isolated-executor/src/fdai_executor_service/human_access.py), [inverse](../../../services/core-control-plane/src/fdai/runtime/human_access_recovery.py), [closure](../../../services/core-control-plane/src/fdai/delivery/human_access_closure.py); [execution checkpoint](../../internals/handover-lifecycle-hardening-20260914.md#execution-source-critique-checkpoint):132 focused and separate21 real-SQL/fixed-agent passes, overlapping and not summed; provider HTTP and Owner observations synthetic. | Original five-minute Owner HIL, existing role/action policy and kill/degradation/promotion checks remain mandatory. Var freshly approves inverse, Vidar proposes/finishes, Thor dispatches, Core stays degraded; no `ALREADY_APPLIED` inverse or unknown retry. #458 stays open for live credentials/permissions/effects/drills/promotion; readiness remains shadow/not ready and final integrated/static/delivery checks remain pending. |
| 2026-09-15 | implemented | Completed 12 distinct final integrated source critique rounds after remaining implementation, with no unresolved confirmed Medium/High source finding. | `current change`; [FI-01 through FI-12](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation); recorded selections overlap and are not summed. | Translation SHA refresh, canonical generation, local hooks, publication/CI, full UI/assistive evidence, and live operational criteria remain pending; #458 stays open and readiness stays shadow/not ready. |

The dated corrections distinguish source completion from release readiness; earlier rows remain
unchanged historical evidence rather than current gap lists.

### Remaining work

- [x] Compose an idempotent handover-artifact-to-`RemediationPrPublisher` path and pass a focused test proving that retries reuse one draft PR for `config/agent-stewardship.yaml`.
- [x] Bind `StewardshipGovernanceService` into production composition so a stored handover draft reaches the configured GitOps publisher, validate tracked YAML independently of runtime identity overrides, and store the returned PR reference and replay flag in a content-addressed receipt.
- [ ] Retain a governed deployment receipt proving one stored handover draft opens one review-only PR and a restart reuses that PR without a second Saga audit.
- [x] Validate merged stewardship YAML through the resolver, calculate affected owners, bind assignment proposal digests, and pass focused tests proving Saga audit, replay-stable IAM-request publication, and recipient notification.
- [x] Implement the scheduled identity-health monitor and retain tests proving transition-only audit, revision-matched successful observations, expiry, Graph-failure preservation, and read-only projection behavior under `stewardship_health:current` and `stewardship_health:last_success`.
- [x] Bind a refreshable GitHub App installation-token provider to Core and document ingestion, prove concurrent refresh and expiry recovery, and retain only the App private-key reference in Key Vault.
- [ ] Retain a deployment receipt and operational drill showing real startup bindings, one guided proposal and reviewed merge, notification delivery, audit closure, and stale-to-clean identity recovery before raising any row to `validated`.
- [x] **Source work H10:** [Scoped requests](../../../services/core-control-plane/src/fdai/core/human_assignment/scoped_duty_requests.py) and [the actual Console workspace](../../../console/src/routes/scoped-duty-workspace.tsx) implement exact group/schedule subjects, current scope/effective intervals, static fallback, reviewed supersession, and projection. The recorded95 unit/6 Playwright checks are bounded synthetic evidence.
- [x] **Handover source scope:** Complete the [source checklist](human-agent-assignment-implementation-plan.md#current-change-evidence-and-remaining-scope) with [Core bindings](../../../services/core-control-plane/src/fdai/runtime/core_handover.py), [semantic retention](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/distill/handover_retention.py), and [execution binding](../../../services/core-control-plane/src/fdai/runtime/human_access_runtime.py), supported by the retained checkpoints rather than readiness output.
- [x] **Final source critique:** Complete 12 distinct integrated rounds after remaining source implementation; [FI-01 through FI-12](../../internals/handover-lifecycle-hardening-20260914.md#final-integrated-critique-after-remaining-source-implementation) leave no unresolved confirmed Medium/High source finding.
- [ ] **Publication evidence:** Complete EN/KO review, translation SHA refresh, canonical generation, local hooks, publication, and exact-pushed-SHA protected CI evidence.
- [ ] **UI and operational evidence:** Retain complete UI-rubric/assistive-technology evidence and separately governed #458/Teams/document/deployment/cohort/drill receipts; source review establishes neither full WCAG/UI score nor operational acceptance.

The grounded T2 `HandoverInterpreter` remains an optional deployment binding. The deterministic
extractor and exact Graph resolution work without it, and the default interpreter holds for review
instead of guessing.

## Lifecycle contracts

### Production startup

The Operator API loads the ownership map before route construction. The same environment mapping used
by the production factory is passed into the resolver, so deployment overrides and
`FDAI_STEWARDSHIP_REQUIRE_BINDINGS` cannot diverge from the process that serves the projection.

A deployment with `enable_operator_api=true` supplies:

- at least one real maintainer OID, with two recommended;
- an accountable binding for each non-autonomous pantheon agent;
- `FDAI_IAM_DIRECTORY_PROVIDER=entra` for scheduled liveness checks;
- a liveness interval of at least 60 seconds.

Terraform checks completeness before apply. The resolver accepts schema v1 during migration and
v2 for new maps. It enforces distinct real maintainers and steward subjects, UUID-shaped
personal-channel keys, exact environment-token shape, forbidden-role absence, placeholder policy,
agent parity, responsibility and duty values, autonomous reasons, and v2 primary plus distinct
backup/escalation coverage at startup. Version 1 stays operational but surfaces derived-duty and
missing-backup findings.

### Scheduled identity health

`StewardshipIdentityHealthWorker` adapts the production human directory to the core `IdentityDirectory`
protocol. It checks maintainer and user-steward OIDs off the hot path.

The monitor stores a revisioned transition snapshot under `stewardship_health:current`:

- the current stale findings;
- the transition timestamp;
- a monotonically increasing revision;
- a deterministic fingerprint used by the audit correlation.

Every successful sweep also replaces `stewardship_health:last_success` with the observation time,
expiry time, and matching transition revision. An unchanged result refreshes only this successful
observation and creates no audit record. A clean-to-stale or stale-to-clean transition atomically
updates the transition snapshot and appends `stewardship.identity_health_transition`. A
Graph failure logs only the error type and retries at the next interval; it does not refresh the
heartbeat, mark every identity stale, or stop the control loop. The first sweep starts in a named
Core background task, so Graph latency never delays Operator API startup. The Operator API merges stale
findings only when both snapshots are valid, their revisions match, and the heartbeat has not
expired. Missing, malformed, mismatched, or expired health renders
`identity_health.status=unavailable` without hiding the base map.

### Draft PR creation

After the ingestion worker stores a `HandoverDraftArtifact`, the optional
`StewardshipGovernanceService` validates the rendered YAML through the same core resolver and
publishes a draft PR through `RemediationPrPublisher`.

The Handover console form emits one explicit structured line per assignment using the canonical
agent name, responsibility, subject kind, and identity display name or email. The deterministic
extractor accepts only one of the fixed 15 agent names. After publication, the artifact stores the
PR reference, URL, and replay flag so the authenticated submitter can open the same idempotent
proposal returned by a retry.

Slack and Teams can enter the same path only through an exact `/handover` attachment directive and
the Contributor role floor. See [conversation-attachments.md](conversation-attachments.md).

The PR candidate is an additive overlay on the current validated map. Grounded mappings add or
retag subjects, while existing owners, maintainers, channels, and thresholds remain intact. The
service never turns an unmapped draft agent autonomous or removes an owner automatically. A human
must make any removal explicitly in the reviewed PR.

The proposal contract is fixed:

| Field | Value |
|-------|-------|
| Target path | `config/agent-stewardship.yaml` |
| Mode | `shadow` |
| Labels | `shadow`, `governance`, `stewardship` |
| Idempotency key | `handover:<upload_id>` |
| Rollback | Revert the merged configuration commit |
| Actor | Authenticated upload-session `actor_id` |

The publisher probes the Git host for an existing branch before writing. After publish, the service
atomically claims durable proposal state and appends `stewardship.change.requested`. Only the first
claim sends the operational notification. If the process stops after remote PR creation but before
the local claim, a retry finds the existing PR and repairs the missing local state without opening a
duplicate. After local state exists, the service resolves the receipt by correlation id before any
remote call, so reprocessing cannot open another PR even after the first PR is closed.

Approved human-assignment grant cases use the same publisher with a stricter input gate. Only
`scope:platform` duties are representable in this global map, and the rendered candidate must
provide complete schema-v2 primary plus backup/escalation coverage for every non-autonomous agent.
The proposal state binds assignment case id, PR ref, and canonical candidate digest. A signed merge
records the case's ownership effect only when the merged digest matches that proposal; a partial
map or mismatched merge remains held and cannot start IAM apply. After the matching receipt is
stored, the governance service publishes one idempotent `human.assignment.iam_apply_requested`
origin into typed ingress. The ingestion gateway receives no Graph write identity.
Its storage, Event Hubs, model, and stewardship adapters use the same exact attached
`FDAI_MI_CLIENT_ID`; none may resolve an ambient or system-assigned principal.

Removal uses a new `revocation` intent with request and result transport `1.1.0`, pinned original
and replacement revisions, and fresh independent removal review. The grant's old approval cannot
authorize it. Before effects, Core places a durable CAS hold on the original case without changing
the map. The order is `approved -> iam_applying -> iam_revoked -> ownership_pr_open -> revoked`.
Only an independently recorded IAM removal receipt and sealed review allow the review-only old-duty
PR. Rendering rereads the exact old duty, pinned active replacements, and their current map entries,
preserving unrelated agents, maintainers, channels, and roles. Exact signed merge closes the old
hold without another grant request. The current source path includes isolated execution, exact
current approval, target locking, independent effects, and atomic closure. Real SQL and fixed-agent
checks use synthetic provider/Owner observations; live effects, permissions, drills, and promotion
under open #458 remain separate evidence.

### Scoped ownership review

H10 uses separate ownership-only scoped-duty cases, not personal IAM assignments or edits to the
global v2 map. Current group/schedule expansion, exact scope and effective dates, static fallback,
two independent Owners, immutable artifacts, and current human-merge observation determine the
expiring scoped projection. The actual `/agent-oversight/mapping-reviews` workspace uses six
existing APIs; HTTP202 stays `awaiting_core` until manual GET. Reviewed supersession cannot revive
old duties during an outage. 95 unit and 6 actual-route/component Playwright checks are recorded,
not full WCAG/rubric or live-scope proof. No group declaration grants IAM, a role, or document ACL.

### Governed membership and recovery

The [execution plan](human-agent-assignment-implementation-plan.md#package-5---governed-entra-membership-apply)
binds the shared SDK and immutable Core material to a dedicated isolated Graph writer. Core has no
mutation identity. Var retains the original five-minute HIL window and one current eligible Owner
for Reader/Contributor access or two distinct current eligible Owners for Approver/Owner access,
excluding requester/target and applying existing role/ActionType approval policy. Original case
reviews are not execution approval. Muninn's preparation advances `r -> r+1` while approved
`expected_revision=r`, Action bytes, and expiry remain unchanged.

Thor alone dispatches through all seven shared safeguards and the same normalized subject/group
lock in either direction. Current kill/degradation, approval, source, and promotion checks remain
mandatory. Durable Executor intent/pre-state/result is not independent success: Heimdall observes,
Forseti judges, Saga seals, and shared atomic post-release closure precedes the Core case effect.
Fresh `recovery_of` reuses existing ActionTypes and binds exact owned pre-state/current lineage.
Vidar proposes and finishes on owned topics, Var requires new approval and the existing whitelist,
and Thor alone dispatches. Independently observed inverse closure leaves Core `degraded`, not
restored to duty or goal authority. No `ALREADY_APPLIED` inverse, unknown mutation retry, or
reference-only rollback success is permitted. The legacy Core adapter still refuses enforce;
isolated enforce needs separate promotion. Same source/configuration rules apply across venues,
local authority cutover is forbidden, and shadow performs no mutation.

### Read-only handover readiness

The existing bounded reconciliation worker also records sampled counts, total, invalid count,
partial-scan status, alert observations, source gaps, and external blockers. The mean effect-receipt
interval uses only cases with two effects and is `null` when none qualify; it is not a complete
population or whole-product latency claim. Invalid rows remain visible in the counts.

Owner-only `GET /handover/readiness` reads that report for ten minutes. Expired, future-dated, or
malformed reports are unavailable. Every report remains `shadow` and not operationally ready.
Reporting dispatches no alerts, makes no provider checks, writes no recovery action, and performs
no promotion. `source_gaps=[]` now reflects completed bounded source requirements, not a green
release decision; `operationally_ready=false` and external blockers remain. Mimir's connected
private-package retention likewise establishes neither deployed source policy nor permission to
erase content when legal hold or source availability is unknown.
Neither this report nor actual SQL role tests verify live directory, cohort, or document-source
state in a deployment; see the [current-change boundary](human-agent-assignment-implementation-plan.md#current-change-evidence-and-remaining-scope).

### Merge observation

The ingestion gateway registers `POST /ingestion/webhooks/github/stewardship` only when governance
is enabled. The route accepts at most 1 MiB and uses HMAC authentication instead of the console
Entra flow.

The adapter performs these checks in order:

1. Compare `X-Hub-Signature-256` in constant time.
2. Require a `pull_request` delivery id and the configured `owner/repository`.
3. Require `action=closed`, `merged=true`, a PR number, and a merge commit SHA.
4. Query up to 3000 changed files in bounded 100-file pages and require
  `config/agent-stewardship.yaml`.
5. Fetch that file again at the merge commit and decode GitHub's whitespace-wrapped base64 UTF-8
  content.
6. Validate the merged map and compute affected agents from the old and new maps.
7. Claim `stewardship_governance:merge:<delivery_id>` with its append-only merge audit.
8. Notify the affected owners from the merged map plus the FDAI maintainers.

GitHub login is recorded as a provider-qualified audit identity such as `github:<login>`; it is not
misrepresented as an Entra OID. Duplicate deliveries return success without a second audit or
notification.

## Affected-owner calculation

The diff is deterministic:

- a changed agent block affects only that agent;
- changed maintainers, personal channels, escalation timeout, or coverage threshold affect all 15
  agents because those values can change every escalation chain;
- workflow documents continue to use recursive pantheon-name extraction;
- unknown agent names never reach diffing because the resolver rejects them first.

Requested notifications use the currently active map. Merge notifications use the merged map so the
new accountable owners receive the handover result.

## Deployment configuration

Set `enable_stewardship_governance=true` only after document ingestion, the Operator API, and ChatOps are
enabled. Terraform requires the following deployment-owned values:

| Input | Runtime binding | Storage |
|-------|-----------------|---------|
| `stewardship_maintainers` | `FDAI_MAINTAINERS` | non-secret environment configuration |
| `stewardship_agent_bindings` | `FDAI_STEWARD_<AGENT>` | non-secret environment configuration |
| `gitops_owner`, `gitops_repo` | `FDAI_GITOPS_OWNER`, `FDAI_GITOPS_REPO` | non-secret environment configuration |
| `github_app_client_id`, `github_app_installation_id` | `FDAI_GITHUB_APP_CLIENT_ID`, `FDAI_GITHUB_APP_INSTALLATION_ID` | non-secret environment configuration |
| `github_app_private_key` | `FDAI_GITHUB_APP_PRIVATE_KEY` | Key Vault reference only |
| `gitops_token` | `FDAI_GITOPS_TOKEN` | Key Vault reference only; bounded compatibility path |
| governance worker control | `FDAI_STEWARDSHIP_GOVERNANCE_ENABLED`, `FDAI_STEWARDSHIP_GOVERNANCE_INTERVAL_SECONDS`, `FDAI_STEWARDSHIP_GOVERNANCE_BATCH_LIMIT` | non-secret environment configuration |
| durable governance receipts | `FDAI_STATE_STORE_DSN` | Key Vault reference only |
| `github_webhook_secret` | `FDAI_GITHUB_WEBHOOK_SECRET` | Key Vault reference only |
| `chatops_webhook_url` | `FDAI_CHATOPS_WEBHOOK_URL` | Key Vault reference only |

The GitHub App should have only repository content, pull-request, metadata, and issue-label
permissions needed by the adapters. Core and document ingestion mint repository-scoped installation
tokens from the Key Vault-backed App private key. The provider signs a short-lived RS256 App JWT,
serializes concurrent refresh, caches no token past its verified expiry, and refreshes before the
one-hour installation lease closes. No token or JWT is logged. A static `gitops_token` is accepted
only as a mutually exclusive compatibility input. Configure the GitHub webhook for pull-request
events and point it to the published ingestion gateway route.

The protected workflow reads `ENABLE_STEWARDSHIP_GOVERNANCE`, `GITOPS_OWNER`, and `GITOPS_REPO`
from repository Variables and reads `GITOPS_TOKEN` and `GITHUB_WEBHOOK_SECRET` from repository
Secrets. Keep activation disabled until those values and the existing ChatOps secrets are present.

## Failure and recovery

| Failure | Behavior | Recovery |
|---------|----------|----------|
| Placeholder or missing owner | Terraform plan or process startup fails | Supply real deployment bindings and restart. |
| Graph unavailable | Current ownership remains usable; no synthetic stale result | Retry on the next monitor interval. |
| GitHub publish interrupted | Worker retry uses the same upload id | Existing PR is recovered by remote idempotency probe. |
| Notification delivery fails | Router tries fallbacks, then persists a HIL escalation | Repair the channel and replay from audit evidence. |
| Invalid webhook signature | Request is rejected before GitHub I/O | Correct the GitHub webhook secret. |
| GitHub App token mint or refresh failure | Draft publication and merge re-read fail closed without a write or success receipt | Repair the App installation or private-key binding and retry with the same idempotency key. |
| Unrelated PR merge | Delivery is acknowledged without state change | No action required. |
| Duplicate merge delivery | Durable claim returns no change | No duplicate audit or notification is emitted. |

## Verification

Run the focused ownership gates before deployment:

```bash
bash scripts/governance/check-stewardship.sh
uv run pytest services/core-control-plane/tests/core/stewardship services/core-control-plane/tests/delivery/stewardship \
  services/core-control-plane/tests/delivery/ingestion_gateway/test_handover.py -q --no-cov
terraform -chdir=infra validate
```

After deployment, verify:

1. `GET /stewardship` returns 15 agents and the expected coverage findings.
2. `stewardship_health:current` exists and `stewardship_health:last_success` has the same revision
  with an unexpired `expires_at`.
3. A synthetic handover upload creates one draft PR and one request audit.
4. Reprocessing the upload returns the same PR reference.
5. Merging a reviewed test change produces one merge audit and one operational notification.
6. Re-delivering the same GitHub delivery id produces no second record.
7. Advancing the injected clock across the refresh skew produces one renewed installation token,
   while concurrent callers share one mint request and no credential appears in logs or receipts.

## Related docs

| To learn about | Read |
|----------------|------|
| Ownership schema and handover concepts | [agent-stewardship-and-handover.md](agent-stewardship-and-handover.md) |
| Notification routes and fallback | [channels-and-notifications.md](channels-and-notifications.md) |
| Human authorization | [user-rbac-and-identity.md](user-rbac-and-identity.md) |
| Azure deployment inputs | [../deployment/deploy-and-onboard.md](../deployment/deploy-and-onboard.md) |
