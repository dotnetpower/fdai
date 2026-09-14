---
title: Alert Noise Governance
description: Diagnose organization-wide alert overload and propose approval-bound notification changes without weakening detection.
---
# Alert Noise Governance

This capability provides shadow-first assessment of unnecessary alerts across people, teams,
roles, and channels. It separates advice from approval-bound Azure notification changes and
requires independent evidence before reporting reduced interruption or preserved response.

> **Implementation boundary:** Shadow-first implementation; operational adoption remains gated.
> Four catalog actions and opt-in runtime mechanics exist, but this checkpoint claims no provider
> notification test, Azure mutation, promotion, publication, or completed rollout. Reading a report,
> accepting advice, and enabling a preference never authorize a change.
> The requirements below remain the target contract; current limits and the implementation ledger
> distinguish implemented mechanics from missing operational evidence.
>
> **Owner boundary:** This document owns organization-level alert-noise assessment and its bounded
> change proposal. [Channels and notifications](../interfaces/channels-and-notifications.md) still
> owns FDAI outbound routing; [Action Ontology](../decisioning/action-ontology.md) owns execution
> contracts. Azure is the initial provider; shared contracts remain provider-neutral.

## Design at a glance

Start with a read-only report of which rules notify which audiences and why. Compare a no-change
baseline with one proposed routing, scheduling, or evaluation change, obtain approval from people
authorized for the entire impact scope, and verify the result through an independent observer.
Frequent notifications are a symptom, not proof of a false positive.

**Example:** In a synthetic organization of 500 people and 20 teams, a subscription-role email
receiver and a shared mailing list may reach overlapping audiences. FDAI would explain the overlap,
propose an already configured service on-call destination for non-protected alerts, preserve the
critical route, and request approval. Counts remain estimates until delivery evidence supports them.

## 1. Scope and boundaries

| Plane | What can be optimized | What it cannot prove or change |
|-------|-----------------------|--------------------------------|
| Detection | Duplicate conditions, flapping, threshold and evaluation-window candidates | A quieter detector is not automatically a better detector. |
| Azure delivery | Alert Rule bindings, Action Group notification receivers, bounded Alert Processing Rule schedules | Internal FDAI deduplication does not stop Azure email or SMS. |
| FDAI delivery | Existing channel routes, incident grouping, and A4 summaries | Channel acceptance does not prove each member received or read a message. |
| Personal preference | Explain existing browser opt-in and provider-hosted unsubscribe controls | One user's preference cannot modify a shared Azure rule or compulsory on-call coverage. |

- **In scope:** Same-tenant authorized assessment across subscriptions, team/role audience overlap,
  actionable guidance, explicit change approval, bounded rollout, verification, and recovery.
- **Out of scope:** Cross-tenant mutation, mailbox-content collection, changing Azure RBAC or Entra
  membership to silence mail, detector deletion, blanket disablement, and autonomous learning-based
  suppression. New Azure resources are provisioned through infrastructure as code (IaC), not a
  conversation-created resource or an inline workflow action.
- **Protected traffic:** Azure Sev0/Sev1, security/compliance, service-health, recovery, telemetry-loss,
  required approvals, and policy-designated service-level objective (SLO) alerts cannot be suppressed,
  delayed, downgraded, or moved to digest by this capability. Unknown classification is protected.
- **Incident boundary:** An active incident blocks tuning of its dependent detector or route. An
  unrelated incident does not block an independently bounded assessment. Storm response stays with
  the existing incident workflow; reduced volume is not incident resolution.

## 2. Evidence and audience model

Reuse the [operating ontology](../architecture/operating-ontology.md): `Resource` for alert rules
and action groups, `Observation` for measured delivery, `Finding` for overload, `Ownership` and
`ChangeWindow` for operating intent, and `DecisionCase`, `ActionOption`, `ExpectedEffect`, `Change`,
`Process`, `ActionRun`, and `ObservedOutcome` for the change lifecycle. A correlation key never
creates an Incident by itself.

Existing `routes_to` links describe resource routing, not human authorization. The implemented
audience and assessment records are versioned, schema-validated private evidence attached to that
spine, not mutable authority objects or inventory truth. Register any missing resource, property,
or link declaration with an owner and provenance; a private `ProcessingRule` is not that registration.

| Evidence record | Required content and interpretation |
|-----------------|-------------------------------------|
| Configuration snapshot | Native rule kind, exact scope, enabled state, raw and mapped severity, condition, evaluation semantics, referenced groups/processing rules, source revision, IaC ownership, and reverse dependencies |
| Audience snapshot | Recipient binding kind, scoped pseudonymous principal or group reference, role/ownership revision, primary/backup duty, membership completeness, and authorized disclosure class |
| Delivery observation | Source alert identity, fired/resolved episode, rule revision, destination, attempt/acceptance/delivery/acknowledgement states, event time, and receipt reference |
| Assessment | Fixed observation window, evidence cutoff, query/policy versions, coverage, unavailable sources, no-change baseline, overlap bounds, and per-service/team findings |
| Change proposal | One treatment axis, exact before/after diff, target and dependency revisions, affected audiences, protected paths, expected range, expiry, rollback reference, and immutable digest |

Every record also carries source identity, effective/event/recorded time, freshness policy,
completeness, provenance digest, and synthetic status. Late evidence creates a new revision.
Provider throttling, unsupported history, failed paging, and missing directory permission remain
`unknown` or `partial`; they never become zero notifications or an empty audience.
Incomplete effective routing also lowers the whole report to partial, not just its finding.

### Collection and privacy

- **Read separation:** An injected read-only provider collects authorized Azure configuration and
  alert history. A separately authorized directory resolver supplies bounded membership evidence;
  Azure read access does not imply Microsoft Graph access. No permission is granted during assessment.
- **Audience kinds:** Distinguish direct recipient, distribution list, subscription-role receiver,
  team channel, and on-call schedule. Azure role membership is a recipient mechanism, not proof of
  service ownership, FDAI role, or approval eligibility. External or unresolved expansion stays unknown.
- **Identity:** Deduplicate only verified identity links within the same tenant and purpose. Use
  opaque or keyed pseudonymous references, not enumerable email hashes. Keep addresses and provider
  identifiers in governed private stores; exclude them, message bodies, and secret-bearing webhook
  configuration from model prompts, audit payloads, examples, and repository artifacts.
- **Minimal disclosure:** Reports show aggregated audience counts by authorized service/team.
  Detailed membership needs separate scope permission. Small cohorts follow deployment redaction
  policy. Finite retention, legal holds, deletion, and access audits follow existing data governance.
- **No assumed receipt:** A mailing list's membership count is potential reach, not observed
  deliveries. Cross-channel deduplication requires proven identity linkage; unknown intersections
  produce lower/upper bounds. Delivery failure and Azure rate limiting are not successful reductions.

### Current evidence implementation

The bounded Azure reader collects metric, log, and activity alert configuration, Action Groups,
processing rules, and a 24-hour alert-instance history. Native evidence remains partial without
directory expansion, current service ownership, incident and delivery evidence, all reverse
dependencies, and historical rule revisions. Today's rule revision cannot label a historical alert.
`AdmittedAlertEvidenceSource` can supplement the exact native snapshot only through independently
admitted, current, scope- and source-bound records; it cannot replace a failed native read or change
known configuration. The factory supplies readers, not those independently produced receipts.

Private alert records use a dedicated canonical codec capped at 8 MiB, 250000 JSON nodes and
32 levels. It hashes every byte, preserves prior small-record digests, and does not widen the
ontology query's 64 KiB ceiling. Reports and bus results retain their smaller transport limits.

## 3. Deterministic diagnosis and recommendation

Use T0 (deterministic rules) over the frozen evidence before T1 (lightweight similarity reuse).
T2 (grounded LLM reasoning) is optional for residual ambiguity and retains the existing mixed-model,
verifier, risk, and approval boundaries. Bragi explains typed results; text never selects a write
target, invents a receiver, or grants permission. Ambiguous user scope requires clarification.

| Observed symptom | Evidence needed | First recommendation |
|------------------|-----------------|----------------------|
| Overlapping recipient paths | Verified binding/identity intersections and source episodes | Remove one unnecessary notification path, preserving required coverage |
| Broad subscription-role email | Actual native recipient semantics plus service ownership | Bind an existing service audience; do not remove anyone's Azure role |
| Frequent fired/resolved transitions | Native stateful/stateless behavior and metric history | Compare debounce/evaluation candidates; do not relabel every recurrence a duplicate |
| Expected maintenance notifications | Approved window, exact resources, complete effective routing | Consider a finite notification window only after protected/automation checks |
| Low-value informational updates | Reviewed classification, delivery deadline, existing FDAI ingest | Offer an A4 summary through existing FDAI routes, not an Azure-native digest claim |
| Stale or unowned destination | Current owner and primary/backup delivery evidence | Repair ownership first; hold removal until the replacement is proven |

Use existing `alert.storm` and `alert.flapping` recipes as signals, not write authority. Every
recommendation cites its evidence, unknowns, rejected options, expected benefit range, and manual
guidance. The [alert-tuning runbook](../../runbooks/alert-tuning.md) supplies the single-axis
baseline/treatment procedure. No-action and hold-for-review are valid first-class results.

## 4. Azure-specific correctness boundary

Public Microsoft Learn behavior was reviewed on 2026-09-14. The provider adapter needs a pinned
API/version capability profile and conformance evidence before any write becomes available.

| Azure mechanism | Consequence for this design |
|-----------------|-----------------------------|
| Action Groups can be shared by multiple alert rules | Compute reverse references and audience reach, not just the edited resource count. Unknown or out-of-scope dependents block mutation. |
| Action Groups contain notifications and automated actions | Preserve webhook, Event Hub, Function, Logic App, Runbook, and incident integration behavior. Never treat an entire group as email-only. |
| Alert Processing Rule suppression removes all action groups on matched fired alerts | It is not a per-person mute and can interrupt automation or FDAI ingress. Block suppression if any required action or evidence path depends on those calls. |
| Suppression takes precedence over adding groups | An overlapping add-group rule cannot preserve a critical lane. Evaluate all effective rules, filters, scopes, and schedules together. |
| Suppressed alerts remain queryable and are not resent when the window ends | Retain source evidence and independently reconcile the interval; recovery does not recreate missed pages or undo time spent uninformed. |
| Processing changes can take up to 30 minutes to take effect | Declare propagation and observation bounds. Do not promise immediate storm relief or assume API acceptance means activation. |
| Processing rules do not affect Azure Service Health alerts | Report this unsupported mechanism explicitly; do not imply universal Azure suppression. |
| ARM-role email and channel membership follow provider-specific rules | Record supported subscription-role semantics and propagation; do not flatten inherited, eligible, nested, or unresolved roles into invented recipients. |

Sources: [Alert processing rules](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-processing-rules)
and [Action groups](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups).
Notification tests may contact people or invoke actions. They are explicitly approved side effects,
never part of a read-only assessment or a harmless substitute for dry-run.

## 5. Approval and mutation boundary

| Request | Required authority |
|---------|--------------------|
| Read a report or simulate | Current scoped read permission; no executor identity |
| Explain a personal preference | Authenticated subject's existing preference contract; no shared configuration write |
| Prepare a shared change | Authorized requester plus verified ownership; produces an inert proposal only |
| Approve shared routing, suppression, or evaluation change | Independent human approval for the exact plan and all affected services, through Var |
| Execute or recover | Thor's scoped executor, current risk decision, promotion, safeguards, and approval-bound recovery contract |

For the initial shared-change release, require two distinct authorized human approvals: the
accountable service-owner lane and an Owner-level change-authority lane. The requester and executor
cannot fill either approval slot. A job title, Azure email role, chat acknowledgement, or group
membership alone grants none of these rights. Missing owner/backup coverage holds the proposal.
Every affected service needs an authorized owner decision; one approver can represent several
services only with verified scope. Splitting a shared group into smaller requests cannot evade quorum.

Approval pins the plan digest, policy and workflow versions, target revisions, full dependency and
audience snapshot, change window, expiry, and rollback envelope. A material change or revocation
invalidates approval. Just-in-time revalidation occurs at dispatch, not only when the card is sent.
No response, approval timeout, and capacity pressure produce no-op or escalation, never consent.
Standing authorization (`autonomy.a3_e`) is out of scope for this capability's initial release.
Admission requires the declared propagation, execution, observation, and recovery deadlines to fit
their authorization intervals. Recovery is separately bound in the approved plan; an expired or
revoked forward approval never becomes blanket recovery permission.

### Registered actions and current delivery limits

The four `ActionType` declarations are registered with `default_mode: shadow`, `pr_revert`, and
`execution_path: pr_manual`. Their only action argument is the retained forward plan's 64-character
lowercase `plan_digest`, not caller-selected fields. Registration is not promotion: current Var
quorum, risk, source fencing, safeguards, and independent proofs still gate dispatch. T2 remains
`shadow_only` under current policy.

| Registered ActionType | Implemented bounded change | Delivery boundary |
|---------------------|----------------|------------------|
| `ops.update-alert-routing` | Replace one existing Action Group binding on one non-protected metric or scheduled-query rule | Exact existing Terraform JSON action list; no receiver rewrite, resource creation, or direct Azure fallback |
| `ops.set-alert-notification-window` | Enable one existing inert suppression rule for one exact rule and a finite UTC interval | Exact existing Terraform JSON schedule; complete effective-rule, protected-path, and independent-collection evidence required |
| `ops.tune-alert-evaluation` | Change only the threshold of one simple metric criterion | Same-bucket comparison and admitted evaluation receipt; window/frequency guidance remains held, not implemented |
| `ops.restore-alert-configuration` | Restore the retained plan's pinned baseline only when current bytes match its forward result | Separately current recovery authority through `pr_manual`; no overwrite of a newer revision |

`AlertPlanArtifactPreparer` reads an exact existing Terraform JSON file through the already bound
GitOps adapter and retains its source/result digests and forward/rollback bytes. Group references
must resolve to real observed Action Groups. A source read is not writer exclusion: the authority
fence still requires independently admitted exclusion proof covering the repository and dependencies.
No adapter creates a replacement group or falls back to a direct Azure write.

Resource creation, replacement, mixed notification/automation edits, subscription-wide suppression,
unbounded recurring windows, and auto-approval are blocked. A new group or processing rule is a
separately approved IaC prerequisite. Existing shared groups spanning the allowed impact boundary
remain guidance-only until redesigned. Provider permissions never expand to make a proposal runnable.

## 6. Agent and persistence ownership

Use the fixed pantheon and [operational-planning](../decisioning/operational-planning.md) spine.
No alert-optimization agent, alternate workflow engine, shared mutable coordinator, or provider call
from the Console is added.

| Responsibility | Accountable agent and boundary |
|----------------|--------------------------------|
| Collection and normalization | Huginn owns normalized Events; delivery adapters are mechanical readers |
| Overload evidence and independent outcome | Heimdall owns observation findings and effect verification, independently of Thor |
| Context, eligible proposals, final decision | Forseti owns the bounded DecisionCase and safety decision; Odin ranks only eligible tradeoffs |
| Declaration review | Mimir validates exact rule, action, workflow, and ontology releases |
| Human approval | Var owns action-bound approval evidence |
| Apply and recovery | Thor alone dispatches provider mutations; Vidar owns recovery planning through that same path |
| Evidence and audit | Muninn materializes owned read models; Saga records append-only intents and terminal outcomes |
| Explanation and learning | Bragi renders scope-bound advice; Norns proposes inert improvements for Mimir review |

Forseti is accountable for the assessment's decision progression. The existing single-writer
Process runtime journals owner-issued typed events with compare-and-set revisions; it is a relay,
not a new decision maker. Muninn and Operator projections never advance a Process. Authority-bearing
handoffs use schema-validated pub/sub with producer ownership, predecessor identity, deadlines,
idempotency, and independent retry/backpressure. Missing required evidence closes as held.

Record assessment phases as child events, not replacements for canonical Process statuses:
`evidence_frozen`, `assessment_ready`, `proposal_ready`, `approval_pending`, `dispatch_recorded`,
`effect_observing`, and `outcome_recorded`. Rejection, expiry, conflict, cancellation, or failed
verification stops forward dispatch. Recovery uses the existing compensation and automation-hold
contracts; an interrupted attempt cannot be retried as an unrelated fresh plan.

Core owns decision records, Operator owns authenticated request outboxes and authorized projections,
and the Executor owns dispatch state. Services consume typed events, not each other's database
tables. Observer artifacts remain private and content-addressed; bus and audit carry references.
Local and deployed venues use the same contracts and gates; local processes gain no privileged
identity. The deterministic assessment adds no live-model dependency; the conversational semantic
boundary retains its existing model requirements. No new service or browser execution route is added.

The opt-in runtime reuses the existing Workflow coordinator, Process store, Var approval path,
promotion registry, safeguard lifecycle, and GitOps publisher. It retains the exact plan, workflow,
target, mode, and correlation across resume; a shadow Process is not promoted by replay.
`bind_alert_effect_runtime` connects Heimdall/Forseti callbacks and bounded retained-publication
reconciliation to canonical dispatch, closure, and outcome stores. Independent effect admission and
separate Workflow outcome admission remain required; factory construction produces neither.
See the [operator runbook](../../runbooks/alert-noise-governance.md) for configuration and prerequisites.

Operator reserves the authenticated terminal result with insert-if-absent before updating any
report or plan projection. A conflicting result cannot change a projection. After an interruption,
only replay of that exact retained result may finish its idempotent projection writes.
PostgreSQL claims use parameterized namespaces, exclusive row leases and exact worker fencing.

## 7. Bounded rollout and recovery

The [constitutional seven safeguards](../architecture/fdai-constitution.md#article-7-autonomous-action-safeguards)
apply to every state change. The implementation checks the following required proofs; their
independent production and operational validation are not established by this checkpoint.

| Safeguard | Required proof |
|-----------|----------------|
| Stop condition | Protected-path loss, stale context, new dependency, active dependent incident, identity/policy change, telemetry loss, or deadline stops forward work |
| Tested rollback | Pinned prior fields, IaC revision, authorized recovery operation, expected recovery duration, and independently observed restore |
| Impact limit | Explicit resource/rule/audience/dependency manifest; one resource-group-equivalent boundary per execution unit |
| Successful dry-run | Exact provider-shape validation, IaC diff, complete effective-routing simulation, positive/negative scenarios, and unchanged protected paths |
| Logical-target lock | Stable keys for changed objects and shared routing dependencies; provider-native revision checks where supported |
| Stable idempotency | Same plan, target revision, effect, and window reuse one dispatch identity across retries/restart |
| Two-phase audit | Saga intent before dispatch, then authoritative applied/held/failed/recovered outcome with all receipt references |

If a provider does not enforce conditional updates, a process-local lock and read-then-write check
are insufficient. That write stays unavailable until a governed exclusive-writer mechanism proves
no competing portal, IaC, or automation writer can change the target. Unknown writer ownership holds.
The same protection covers critical routing dependencies through commit. An advisory reverse-edge
snapshot or a lock that ignores other writers cannot protect against a newly attached alert rule.

Compare frozen baseline and treatment first. Pilot one existing non-protected rule and service;
advance to the next independently approved unit only after its predecessor's outcome closes.
Prove the replacement route and primary/backup reachability before removing the original. Any
notification test requires its own approved side-effect scope. Temporary dual delivery is explicit
transition cost, not a reduction; an unavailable replacement blocks cutover.
Each temporary window has a provider-enforced absolute end, explicit time zone and daylight-saving
interpretation, maximum duration, and post-expiry verification. A cleanup job is not the expiry
mechanism. Recurring business-hours suppression stays outside the first release.

Cancellation prevents new effects but does not undo applied fields. Recover in reverse dependency
order, preserving unrelated concurrent edits. An ambiguous acknowledgement requires independent
reconciliation before any resend or restore. Unverified recovery records `recovery_incomplete`,
keeps the durable automation hold, and pages through an unaffected channel. A kill switch blocks
new optimization without disabling already authorized recovery.

## 8. Measurement and operator experience

Keep four denominators separate: source alert episodes, notification attempts, confirmed channel
deliveries, and observed human acknowledgements. Report duplicates and interruptions per authorized
service/team and time window. Potential recipient fan-out and modeled savings are estimates, not
observed per-user deliveries. Empty, censored, and unavailable samples are not a zero baseline.

Threshold changes need underlying telemetry plus independently labeled positive, negative, and
missed-incident cases; fired-alert history alone cannot measure false negatives. Compare the same
frozen scenario set, rule versions, workload exposure, and observation window. Live before/after
changes in traffic or membership are confounders, not proof of causation. Missing acknowledgement
does not label an alert unnecessary. Raw event, episode, destination, and human burden stay distinct.

Success requires independent configuration readback, continued source-event collection, the
expected delivery behavior, preserved protected-response deadlines, and the declared observation
window. API success or fewer messages alone is insufficient. No eligible events makes effectiveness
unscorable; do not leave temporary suppression active to wait for a better sample. Baseline recall,
missed incidents, SLO burn, escalation latency, delivery failures, and rollback completeness are
guard metrics. Stop and recover on a protected-path regression, even if volume improved.

The implemented **Operations > Alert quality** surface is Live-only and uses server-discovered
authorized scopes, rule/service filters, and inert routing, finite-window, and evaluation forms.
It separates observed counts from unknowns, observation bounds from evidence cutoff/expiry, and
named treatment values from retained baseline references. Team/audience-kind/period filters, full
baseline and guard metrics, approval/outcome details, and modeled benefits are not yet projected.
A report action submits a typed request, never an ARM call or approval. The Settings API and UI
separate prerequisites, enabled preference, and authority, with scoped human Owner revision checks.
Operator composition binds its durable preference store; an unavailable Settings record is not a
saved switch. Neither enabling nor an accepted request promotes an action.

Guidance and optimization notifications are themselves bounded: one deduplicated case per policy,
scope, and observation window, material updates in the same case, and normal summaries via A4.
Required approvals and urgent safety escalations bypass optional digest preferences. Never create
one proposal or approval card for each of hundreds of recipients. Per-audience interruption budgets
can prioritize advice or aggregate optional FDAI messages, never silently drop protected traffic.

## 9. Delivery sequence and exit evidence

These are dependency-ordered exit conditions, not completion claims or rollout dates. The
[implementation ledger](../../roadmap-implementation/operations/alert-noise-governance.md) separates
implemented mechanics from the baseline checkpoint, remaining hardening, and operational evidence.

| Package | Observable exit condition |
|---------|---------------------------|
| ANG-1: evidence and semantics | Versioned provider/audience contracts, ownership, complete/partial/denied behavior, privacy checks, and exact ontology mappings pass focused tests without writes |
| ANG-2: assessment and guidance | Deterministic overload/overlap report, no-action option, manual guidance, and scoped bilingual projections pass on frozen synthetic organization cases |
| ANG-3: approval-bound routing | Exact-plan quorum, revocation, shared-group impact, dry-run, duplicate/reorder/restart, conditional write, independent closure, and recovery pass for one existing rule |
| ANG-4: finite suppression | Protected/automation exclusion, effective-rule precedence, independent collection, propagation, expiry/time-zone behavior, and restart-safe recovery pass |
| ANG-5: evaluation tuning and promotion | Native rule-kind semantics and held-out recall/latency gates pass; separately authorized provider tests and a timed pilot retain independent evidence before promotion |

The scale fixture covers at least 500 synthetic principals, 20 teams, overlapping direct/group/role
bindings, and 10000 alert events, including skew toward one service. Versioned policy bounds pages,
membership expansion depth, graph edges, candidates, bytes, concurrency, provider cost, total/stage
time, and no-progress time. Hitting a bound preserves partial evidence and holds affected changes;
it never silently truncates an approval scope. Fair per-scope queues isolate a noisy tenant or team.

Required negative cases include unauthorized group expansion, wrong-tenant identity, unresolved
mailing-list overlap, protected alerts mislabeled informational, missing backup, shared-group changes
outside scope, removal of FDAI ingress, overlapping suppression/add rules, API success without
effect, expired approval, unsafe provider concurrency, late receipts, failed rollback, and telemetry
loss mistaken for improvement. Runtime evidence stays separate from synthetic mechanical checks.

## 10. Design review decisions

The design critique tightened these boundaries. This records design reasoning, not human approval,
provider conformance, or a passing executable test.

| Rejected shortcut | Revised decision |
|-------------------|------------------|
| Count alerts and mute the busiest rule | Separate episodes, deliveries, and people; protect recall and response deadlines before optimizing volume. |
| Suppress email while keeping another group on the same alert | Azure suppression removes all groups; preserve an independently unaffected collection and safety path or hold. |
| Let one recipient approve a shared change | Cover every affected service, retain independent quorum, and never infer authority from Azure recipient roles. |
| Accept readback or rollback as proof nobody missed an alert | Verify delivery and recovery independently; keep any missed interval as evidence that restoration cannot erase. |
| Use a local lock or a later cleanup task | Require effective writer fencing and provider-enforced finite windows, including dependency and restart cases. |

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation status and remaining work | [Implementation ledger](../../roadmap-implementation/operations/alert-noise-governance.md) |
| Existing detection and correlation | [Observability and detection](../rules-and-detection/observability-and-detection.md) |
| FDAI channel audiences and delivery | [Channels and notifications](../interfaces/channels-and-notifications.md) |
| Azure-native event ingress | [Near-real-time detection paths](../rules-and-detection/near-real-time-detection-paths.md) |
| Configuration, request handling, and governed recovery | [Alert noise governance runbook](../../runbooks/alert-noise-governance.md) |
| Measured single-axis tuning | [Alert tuning runbook](../../runbooks/alert-tuning.md) |
| Typed planning and execution | [Operational planning](../decisioning/operational-planning.md), [Action Ontology](../decisioning/action-ontology.md) |
