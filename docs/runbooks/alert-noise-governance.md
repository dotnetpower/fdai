---
title: Alert Noise Governance Runbook
description: Review shadow-first alert assessments and exact-plan prerequisites for governed manual-PR changes and recovery.
fdai_runbook:
  schema_version: 1.0.0
  action_type_patterns:
    - ops.update-alert-routing
    - ops.set-alert-notification-window
    - ops.tune-alert-evaluation
    - ops.restore-alert-configuration
  sections:
    preconditions: Preconditions
    procedure: Procedure
    verification: Verification
    rollback: Rollback
    audit_trail: Audit trail
---
# Alert Noise Governance Runbook

Use this runbook to interpret an alert-quality assessment, prepare an inert proposal, and review
the evidence needed for a later governed change. The implementation is shadow-first; operational
adoption remains gated. This procedure does not authorize a provider notification test, Azure
mutation, PR publication, capability promotion, or deployment.

> **Checkpoint, not completion:** Focused implementation, coverage, hardening and local validation
> results, plus remaining source, operational and CI work, are recorded only in the
> [implementation ledger](../roadmap-implementation/operations/alert-noise-governance.md).

## What this runbook covers

All four registered actions use `pr_manual`, default to `shadow`, and retain `pr_revert` recovery.
Each action accepts only the exact forward plan's 64-character lowercase hexadecimal `plan_digest`.
The plan, not the caller, supplies the target, fields, original revision, and rollback baseline.

| ActionType | Current supported treatment | Required boundary |
|------------|-----------------------------|-------------------|
| `ops.update-alert-routing` | Replace one observed Action Group binding on one non-protected metric or scheduled-query rule | Existing groups and exact Terraform JSON action list only; no receiver rewrite or new group |
| `ops.set-alert-notification-window` | Enable one existing inert suppression rule for one exact rule and a finite UTC interval | Complete effective routing, unaffected independent collection, propagation budget, and absolute expiry |
| `ops.tune-alert-evaluation` | Change one simple metric threshold, window, or frequency | Independently admitted same-bucket threshold or uniform-series temporal comparison with paired recall/latency guards |
| `ops.restore-alert-configuration` | Restore the pinned baseline of that same forward plan | Current repository bytes equal the retained forward result and separate current recovery authority exists |

## Preconditions

- **Scope and evidence:** Use one server-configured authorized scope. The bounded Azure reader
  alone remains partial without directory, current ownership/incident, complete reverse-dependency,
  historical revision, and delivery evidence. An independently admitted supplement must match the
  exact native base; an old or failed read cannot be replaced by a ledger-only answer.
- **Protected paths:** Preserve Sev0/Sev1, security, service-health, recovery, telemetry-loss,
  mandatory approvals, policy-protected SLO alerts, and unknown classifications. Active dependent
  incidents, mixed automation routes, absent backup coverage, or unknown dependencies hold changes.
- **Existing IaC:** Bind an existing Terraform JSON file and resource selector. Only observed Action
  Groups are eligible. Provisioning a group or processing rule is a separate approved IaC task.
  There is no direct Azure fallback, inline resource creation, or whole-object concurrent overwrite.
- **Existing control plane:** Use the canonical Workflow/Process runtime, Var approval provider,
  promotion registry, safeguard coordinator, audit, GitOps publisher, and independent evidence
  admission. A factory or identity map supplies no approval, writer exclusion, or effect receipt.

### Runtime configuration

Deployment owners supply the following private bindings through existing configuration and secret
references. Names below are keys, not populated tenant values. Do not put identifiers, endpoints,
credentials, DSNs, native receiver data, or receipt bodies in repository examples or chat.

| Setting | Actual contract and prerequisite |
|---------|----------------------------------|
| `FDAI_ALERT_NOISE_SCOPE_BINDINGS_JSON` | Core: 1-64 exact rows with `subscription_id`, `resource_group`, `tenant_ref`, `scope_ref`. Supply together with principal scopes; no inferred scope or wildcard. |
| `FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON` | Core and Operator: private current subject-to-opaque-scope map, up to 1000 subjects and 64 exact scopes per subject. Empty permissions grant nothing; mappings never assign roles. |
| `FDAI_SOURCE_REVISION` | Exact nonzero Git commit identity. Without it, alert Workflow/writer bindings remain unavailable; do not manufacture provenance. |
| `FDAI_ALERT_NOISE_TRANSPORT_KEY` | Existing secret injection, at least 32 bytes, shared only across the authenticated request/result boundary. Operator also requires its durable store, event transport, and event topic. |
| `FDAI_ALERT_NOISE_PSEUDONYM_KEY` | Core secret injection, 32-256 bytes for purpose-separated opaque evidence references. A real HTTP reader and read identity are also required. |
| `FDAI_ALERT_NOISE_WRITER_BINDINGS_JSON` | Optional exact rows: `scope_ref`, `executor_ref`, `repository_ref`, `repository_revision`, `verification_trust_anchor_id`, `principal_refs`. Pins existing identities and source, not authority. |
| `FDAI_ALERT_NOISE_IAC_BINDINGS_JSON` | Optional 1-64 exact rows: `path`, `source_digest`, `resource_type`, `resource_name`, `field`, `group_ids`, `target_ref`. Path names an existing Terraform JSON file. Source bytes must match its digest; the already configured GitOps adapter reads them. |
| `FDAI_ALERT_NOISE_EFFECT_BINDINGS_JSON` | Optional 1-64 exact rows: `tenant_ref`, `scope_ref`, `source_ref`, `observer_ref`, `executor_ref`, `identities`, `authority_class`. Three reference aliases map to three distinct canonical identities, including case-insensitive separation. |
| `FDAI_STATE_STORE_DSN`, `FDAI_RESOURCE_LOCK_DSN` | Explicit effect binding requires the existing service-owned PostgreSQL target; an optional lock DSN must equal the state DSN. Use the correct venue's existing configuration, never another service's or venue's database. |

Absent optional bindings leave the corresponding path unavailable. Explicit malformed or partial
bindings fail rather than installing a fixture, permissive verifier, recording publisher, or new
provider. The effect factory reuses lazy PostgreSQL dispatch, closure, and lock adapters; their
construction is not a database connectivity or restart test. The existing real GitOps publisher and
production-eligible evidenced lock are prerequisites for a writer fence, not evidence of exclusion.

Canonical admitted-source readers require actual independently produced scope, evaluation,
authority, writer-exclusion, effect, and recovery records, with exact purpose, scope, source revision,
freshness, and verifier separation. The effect observation additionally needs separate Workflow
outcome admission before the existing Process can advance. These factories do not produce the
records, run notification tests, create a provider observer, or promote any capability.

The exact `alert-noise:evaluation:` payload binds `evidence_digest` and `treatment_digest`, plus
exactly one of `comparison`, `threshold_scenarios`, or `temporal_scenarios`. The same independent
admission authenticates the full frozen content before deterministic replay. Replays use its fixed
`verified_at`, not the time of a retry. Temporal inputs require complete uniform samples and
independent onset labels; no missing sample, lost positive or delayed positive is accepted.
Bind `criteria.0.threshold`, `window_size`, or `frequency` to the selected axis. Unsupported native
values, dynamic/mixed criteria, missing source durations, or a mismatched baseline hold the plan.

### Settings and request API

All routes revalidate current identity and exact scope; responses use `Cache-Control: no-store`.

| Request | Meaning |
|---------|---------|
| `GET /alert-quality/scopes` | Discover only the signed-in subject's configured opaque scopes; no query arguments. |
| `GET /alert-quality?scope_ref=<scope-ref>` | Read retained evidence and current requestability. A missing assessment is not proof of zero noise. |
| `GET /alert-quality/requests?scope_ref=<scope-ref>` | Read at most 25 recent original acceptances and exact signed terminals for the current principal. `truncated` is explicit; optional `request_key` selects one original client idempotency key. |
| `POST /alert-quality/assess` | Human Contributor, Approver, or Owner requests a bounded assessment with one `Idempotency-Key`. `202` proves durable acceptance only. |
| `POST /alert-quality/proposals` | Same human role floor; submit exact `scope_ref`, current `evidence_digest`, and one typed `treatment` with one `Idempotency-Key`. No approval or execution fields. |
| `GET /alert-quality/settings?scope_ref=<scope-ref>` | Read prerequisites, preference state/revision, `mode: shadow`, and `execution_authority: false`. |
| `PUT /alert-quality/settings` | Scoped human Owner updates only `scope_ref` and `enabled`, with one revision precondition. This is not action approval or promotion. |

PUT accepts either integer `expected_revision` in the body or one strong/plain numeric `If-Match`,
never both. The revision is at least zero and below `9007199254740991`; missing preconditions return
`428`, malformed/ambiguous input `400`, stale revision `409`, and unauthorized access `401`/`403`.
A successful save returns the retained next revision and a quoted-revision ETag. On conflict, refresh
explicitly and make a new deliberate choice; do not overwrite or retry an unknown outcome.

With a bound readable preference store, an unsaved default is enabled at revision zero with no
fabricated timestamp. A missing or failed store is explicitly unavailable. Operator composition
passes `StateKvAlertQualityPreferenceStore` into the existing dependency factory. Local PostgreSQL
checks prove competing revision writes and new-connection replay; they do not qualify a deployment.
A disabled or
unreadable bound preference vetoes new requests, never accepted work or separately approved recovery.

## Procedure

1. **Read before requesting.** In **Operations > Alert quality**, use Live mode and a discovered
   authorized scope. Inspect observation bounds, cutoff, expiry, coverage, unknowns, and source
   references. Source episodes, attempts, deliveries, and acknowledgements are different measures.
2. **Request one assessment.** Use the typed assessment request only when the authenticated source,
   writer, producer readiness, and preference checks allow it. Preserve its correlation reference.
   If the result is unknown, explicitly refresh request history to reconcile its exact original key
   before another deliberate submission. A newer report, broker acceptance, missing row or elapsed
   deadline cannot clear uncertainty. History refresh never resends a write.
3. **Prepare one inert treatment.** Use current complete evidence and one routing, finite-window,
   or supported evaluation change. Retain the immutable plan and exact source/forward/rollback
   artifacts. Window/frequency changes require temporal evidence; threshold-only receipts cannot
   substitute. Provider and promotion qualification remain separate.
   Recorded request details show the plan-bound baseline, measured replay guards and original
   Process reference when present. Follow the canonical Process link for current approvals,
   independent outcomes and recovery, not a second approval surface in this report.
4. **Review future enforcement prerequisites.** Through Var, obtain current decisions from all
   affected service owners and a distinct Owner-level change authority. Neither requester nor
   executor can approve. Pins cover the plan, dependencies, policy, workflow, expiry, and recovery.
   Catalog registration and the generic Workflow approval step alone do not prove these receipts.
5. **Keep the shadow boundary.** A shadow Process retains its original mode on replay. Only a later
   separately authorized, promoted attempt may cross the existing manual-PR sink after all seven
   safeguards, actual source exclusion, and final current-proof checks pass. This runbook requests
   no such publication. A read-then-write check without exclusion cannot satisfy that boundary.
6. **Close from independent evidence.** A retained publication or merge is not an Azure effect.
   Heimdall/Forseti relays use exact dispatch/bundle/Process lineage and independent admissions;
   missing or adverse observations stay held and enter the existing recovery/automation-hold path.

## Verification

Verify configuration readback, continued source collection, real delivery behavior, preserved
protected-response deadlines, and the complete declared observation window independently of the
executor. Finite suppression needs both activation and post-expiry evidence. No eligible events is
unscorable, not success; do not prolong a window to obtain a better sample.

Separate local mechanics from actual PostgreSQL concurrency/restart, authenticated English/Korean
browser behavior, provider conformance, and exact-head CI. Retain each required class of evidence
before reporting operational adoption. This checkpoint supplies no such operational qualification
and does not initiate live validation.

## Rollback

1. Stop new forward effects on stale evidence, changed ownership/dependencies, failed guards,
   lost exclusion, active dependent incidents, telemetry loss, or expired deadlines.
2. Reconcile an ambiguous publication before any resend or restore. Keep the original plan and
   actual dispatch identity; do not create an unrelated request to escape the retained state.
3. Use `ops.restore-alert-configuration` through the existing compensation/recovery path with the
   same forward plan digest and separately current recovery authority. Restore only when source
   bytes equal the retained forward result; a newer revision requires review, not overwrite.
4. Verify restoration independently. Missing, failed, or unscorable recovery remains
   `recovery_incomplete` with a durable automation hold. The effect relay does not release holds.
   Re-enabling notifications cannot undo time spent uninformed or recreate missed pages.

## Audit trail

Retain the request/correlation identity, private evidence and plan digests, original Workflow/Process
binding, exact file/source/result/rollback digests, Var decisions, current admission and exclusion
references, safeguard generation, publication receipt, independent outcome, and recovery lineage.
Bus and audit records carry bounded references, not private recipient lists, source bodies, secrets,
or caller-authored success flags. Report publication, observed effect, recovery, and promotion as
separate states. Keep the authoritative implementation history in its ledger, not in this runbook.

## Related docs

| To learn about | Read |
|----------------|------|
| Capability semantics and protected traffic | [Alert Noise Governance](../roadmap/operations/alert-noise-governance.md) |
| Current evidence and open delivery work | [Implementation ledger](../roadmap-implementation/operations/alert-noise-governance.md) |
| Baseline and single-axis measurements | [Alert tuning](alert-tuning.md) |
| Existing governed mitigation path | [Incident mitigation and rollback](incident-mitigation-and-rollback.md) |
| Action and Process authority | [Action Ontology](../roadmap/decisioning/action-ontology.md), [Process Automation](../roadmap/decisioning/process-automation.md) |
