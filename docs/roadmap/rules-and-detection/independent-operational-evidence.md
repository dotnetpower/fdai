---
title: Independent Operational Evidence Issuance
---
# Independent Operational Evidence Issuance

This design defines how FDAI issues independent, source-authenticated decision evidence for governed test
context, forecast intervention history, and case-history reuse. A separate read-only verifier workload reads
each authoritative source under its own identity and issues content-free proofs, while the existing boundary
owners keep consuming them through the unchanged admission seam.

> **Status:** Partially implemented. The owner reviewed the design for exit criterion 1 of
> [#1022](https://github.com/dotnetpower/fdai/issues/1022) on 2026-09-28; see [Review decisions](#review-decisions).
> The verifier engine, issuance seam, pinned trust and case-scope grant registries, insert-only proof store,
> Operator authentication receipt, the three test-context readbacks, an unwired case-history
> readback module, class-specific records in every consuming owner, and Settings readiness observation exist and pass local checks; see
> [Implementation notes](#implementation-notes). No verifier workload is deployed, and forecast purposes without a bound source readback stay `unavailable`.
>
> **Agent boundary:** The pantheon remains exactly 15 agents. This design adds no agent or topic, changes no
> agent's `owns` or `subscribes`, and grants no execution or promotion authority.

## Design at a glance

Eleven purpose ids across eight decision slices already require an exact `DecisionEvidenceAdmission` (a
short-lived, no-authority eligibility record that exists only after five independent proofs), but nothing
issues one. A non-agent verifier with its own workload identity fills that gap: it reads the authoritative
source named by a typed locator, recomputes the consumer's digest, proves completeness, absence of conflict,
freshness, and principal authorization, and writes an admission or a typed rejection to a store only it can
write. Owners read admissions through the unchanged `admit` method and record every rejection class
explicitly; only `unavailable` keeps today's generic hold.

## Current state and gap

Core paths are relative to `services/core-control-plane/src/fdai/`; other paths are repository-relative. This
section records the gap the design closes as reviewed; [Implementation notes](#implementation-notes) describe what
now exists.

- **Consumers exist.** Every boundary below calls `assess_decision_evidence_admission` from
  `shared/providers/decision_evidence_verifier.py`. Without an admission it holds with a generic reason, such
  as `context_admission_required`, that can't tell a conflict from an outage.
- **Nothing issues operational evidence.** `StateStoreDecisionEvidenceAdmissionProvider`,
  `AzureBlobDecisionEvidenceAdmissionProvider`, and `AzureManagedIdentityDecisionEvidenceVerifier` only read
  retained records or prebuilt proofs. The one issuer, bound to `deployment-apply` by
  `config/decision-evidence-deployment-policy.json`, derives its own proofs and can't authenticate these sources.
- **The gate sees two identities.** `DecisionEvidenceReadinessGate` rejects a verifier equal to `source_identity`
  or `producer_id`, not a reviewer or executor, and retained admissions skip a binding-revocation recheck.
- **Core can't verify itself.** The Core app runs as the executor managed identity (`module "identity"` in
  `infra/main.tf`), so an in-process verifier would share the producer and executor identity.

## Verifier workload and identity separation

The verifier is an internal-only, deterministic service with a dedicated user-assigned managed identity. It
invokes no model and isn't an agent: like the inventory projector, it owns only its non-agent durable output,
the operational proof store. It publishes and subscribes to no topic, never judges, approves, executes, or
promotes, and holds no write role on any source it verifies.

| Role | Current identity | Separation rule | Enforcement |
|------|------------------|-----------------|-------------|
| Source | Operator API identity (command outbox); Core runtime identity (StateStore revisions and hash-chained `audit_log`); inventory identity (journal and incarnation ledger); Azure platform (metrics, Resource Graph, Activity Log); pinned operating-intent source | Reads each source with its own read-only role and never holds a source write role | Registry source anchors, compared at startup and per issuance; role readback |
| Producer | Core runtime identity hosting the requesting boundary | Accepts a claimed producer only when the registry lists it for the purpose and the caller's identity matches its anchor; choosing a producer grants nothing | Receipt `producer_id` differs from `verifier_id`; the caller token is validated and discarded |
| Reviewer | Authenticated human Approver or Owner, carried by Var | A workload is never a reviewer, and the reviewer's subject differs from the requester's | Subject ids from Operator records, never display strings |
| Executor | Every executor-class identity: the Core runtime (executor) identity, isolated executor, dev operations gateway executor, vertical effect executors (`effect_executor_principal_ids` in `infra/main.tf`), and deploy runner | No resource write role, no executor credential, and no Azure data-plane role except exact secret read for its DSN and exact registry pull | Preflight builds the anchor set from every executor-class identity; the verifier refuses to start on equality and reads back its own role assignments, refusing vault-wide, resource-group-wide, subscription-wide, other-secret, write, or unrelated data-plane roles |

The verifier authenticates sources without retaining tokens:

- **Workload tokens.** Short-lived managed identity tokens live only in memory for one bounded read and never
  reach proofs, records, logs, metrics, errors, or responses, as in `AzureManagedIdentityDecisionEvidenceVerifier`.
- **Source artifacts.** An artifact counts only after the verifier read it under its own identity from a store
  that only the source owner writes and validated its digest or chain (such as the hash-chained `audit_log` in
  `delivery/persistence/postgres.py`). Any fact that originates outside the producer is also corroborated by a
  source another identity writes. Copying Core state, hashing a caller identity, or reusing `deployment-apply`
  evidence never counts.
- **Human principals.** The verifier never re-authenticates a human. It reads the content-free receipt, a prerequisite,
  that `OperatorAuthenticator` in `services/operator-service/src/fdai_operator_service/auth.py` would retain on token
  verification: issuer, audience, tenant digest, subject, principal kind, exact group ids with a no-overage flag,
  token-id digest, issue and expiry time, roles, and role-mapping revision, with no token; local CLI receipts are `local-loopback`.

## Issuance path and proof format

1. **Request.** The boundary owner sends the same lookup tuple it passes to `admit`, namely
   `(evidence_digest, scope_digest, purpose_id, source_revision)`, plus a coordinates-only source locator, in
   one bounded call through a new `OperationalEvidenceIssuer` provider seam: a provider call, not an agent call.
2. **Readback.** The verifier resolves the purpose in the pinned trust registry, checks the claimed producer,
   reads every declared source, and recomputes the evidence digest with the consumer's own pure
   canonicalization function. A different digest is `evidence_mismatch`, never a correction.
3. **Issue or reject.** It builds a `DecisionCriticalEvidenceReceipt`, five proofs, and a
   `DecisionEvidenceVerificationBundle`, evaluates them with `DecisionEvidenceReadinessGate` in
   `core/readiness/decision_evidence.py`, and writes the admission, or a rejection record naming the failed
   class, create-only. The content-free response names only the status and that record's digest.
4. **Admit.** The owner calls the unchanged `admit`, and the operational admission provider validates the
   record with `parse_decision_evidence_record` and rechecks the binding and separation anchors. Without an
   admission, `outcome` accepts only the rejection record this attempt's response named; anything else,
   including an older rejection for the same lookup, is `unavailable`.

A request uses a proposed two-second limit inside the consumer's five-second deadline; a timeout, `429`, or
`503` ends it without retry as `unavailable`. Only in-flight duplicates coalesce. A current admission may be
reused, but a rejection never is, so every new attempt gets a fresh result.

Each owner records the class in a record it already writes and cites the rejection digest: Forseti's hold
reason, Thor's dispatch hold, Mimir's refused-transition audit, Heimdall's scoring exclusion (in a new
`ForecastOutcome` minor version), the T1 reason code, and the Pattern read status. `conflicting` always
reaches the owner as an explicit conflict that lowers autonomy; only `unavailable` keeps today's generic reason.

| Receipt field | Value derived by the verifier |
|---------------|-------------------------------|
| `authority_class`, `method_*`, `freshness_policy_*` | The pinned registry entry for the purpose, never the request |
| `source_identity`, `producer_id`, `producer_version` | Logical source id, such as `operator-service.test-context-outbox`, and the registered producer |
| `evidence_digest`, `scope_digest`, `source_revision` | The consumer's exact lookup values, accepted only after recomputation |
| `authentication_evidence_digest` | Source artifact identity, writer-anchor binding, human authentication receipt, and matched grant revisions |
| `completeness_evidence_digest` | Required parts, checkpoints, watermarks, terminal cursors, and verified chain bounds |
| `conflict_evidence_digest` | Compared sources and their agreement; any disagreement makes the receipt `conflicting` |
| `provenance_digest` | Locator digest, source record references, source revisions, and both registry revisions |
| `event_at`, `evidence_cutoff`, `fresh_until` | Source event time, the cutoff named in each slice table, and cutoff plus the registry ceiling |
| `completeness_basis_points`, `conflict_status`, `synthetic` | `10000`, `clear`, and `false` for every issued admission |

Each proof's `subject_digest` equals its receipt field through `expected_verification_subjects`. The bundle's
`valid_until` is the minimum of `fresh_until`, the binding's `valid_until`, and any slice cap, so the retained
admission window equals the bundle window as `_validate_relations` requires. A failed class produces a
rejection record, never an issued receipt.

The operational proof store is a set of insert-only PostgreSQL tables in both venues, separate from the
`deployment-apply` container and from the Core state store:

- **Layout.** Separate tables hold authentication receipts, readback records, bundles, admissions keyed by
  `<registry-pins>/<lookup>/<reverse-time>-<receipt>`, and rejections with the same key shape. A key per
  issuance lets a lookup be reissued after expiry without overwriting an immutable record.
- **Rejections.** A rejection record is content-free: attempt id, lookup digest, purpose, class, reason codes from
  `LiveEvidenceClaimRejectionReason`, `DecisionEvidenceReadinessReason`, or the readback's fixed code set, conflict
  evidence digests, pins, verifier id and version, recorded time, and a fixed 60-second `valid_until` that covers
  that attempt only.
- **Pins and reads.** `<registry-pins>` names the trust and grant registry revisions behind a record. Consumers
  read at most the two newest records for a lookup under the current pins or under earlier pins that no
  revocation revision retired; neither record extends the other.
- **Writers.** The verifier's database role is the only writer and holds `INSERT` without `UPDATE` or
  `DELETE`; consumer roles hold `SELECT` only; the deploy runner and the migration role hold no runtime data
  role; and records are immutable. A readiness probe reads back the table grants and role memberships and reports
  `self_verified` when another role can write.
- **Local venue.** The same insert-only tables with separate writer and reader roles run on loopback
  PostgreSQL. The local verifier reads real local sources, and provider-backed purposes stay unavailable.

## Trust registry and purpose mapping

A pinned, reviewed trust registry maps each purpose to its evidence contract. The upstream file (proposed
`config/operational-evidence-trust-registry.json`) holds logical identifiers only; deployment configuration
binds trust anchors to workload principals and the proof store address, which never enter the repository.

| Entry field | Meaning |
|-------------|---------|
| `purpose_id`, `authority_class`, `method_*` | One of the eleven purpose ids and its readback contract; no purpose substitutes for another |
| `producers`, `sources` | Registered requesting boundaries, authoritative and corroborating sources, and their anchors |
| `freshness_policy` | Policy id, version, and ceiling; its digest is the freshness-policy proof subject |
| `verifiers` | One or more bindings, each with `verifier_id`, `verifier_version`, `trust_anchor_id`, `valid_from`, `valid_until`, and `revoked`; rotation adds a binding beside the one it replaces |
| `separation` | Source, producer, reviewer, and every executor-class anchor that must differ from the verifier |
| `evidence_class` | `live` in deployed venues; a `local-loopback` anchor is refused outside local venues |

- **Review and load.** A revision is content-addressed and pinned out of band after review, like the
  [operating-intent source](../architecture/operating-intent-source.md). Author and reviewer are distinct
  humans; the full-authority development profile's one Owner may do both, recorded as development-only. The
  verifier and every consumer load the same pin; a digest mismatch, unknown field, duplicate key, missing
  anchor, or verifier trust anchor that is also a producer, source, or separation anchor makes the purpose
  unavailable. Identity-separation checks therefore skip only anchors that verifier bindings use exclusively.
- **Rotation and revocation.** The loader classifies each revision by content, not by label. Any removal,
  narrowing, validity shortening, or `revoked` flag on a binding, grant, purpose, or case scope makes it a revocation
  revision; authors revoke entries instead of deleting them. A revocation revision retires live admissions under
  earlier pins, which boundaries re-request, and ends any lineage whose matched binding or grant it revoked. Any other
  change, such as adding a verifier version beside the one it replaces, is routine rotation and keeps earlier records
  valid until they expire. `admit` rechecks the binding every time; scaling the verifier to zero stops new issuance.
- **Capability state.** Each purpose reports `available`, `enabled`, `mode`, and prerequisites through the
  existing capability and settings surface. It is `available` only when the registries, verifier binding,
  writer readback, and every declared source are bound and healthy; availability grants no authority.

## Principal-to-case-scope and purpose binding

Authorization is an explicit reviewed record, never an equality between digests. A deployment-owned case-scope
grant registry, pinned and revoked like the trust registry, has three parts:

- **Case scopes.** Each opaque `access_scope_digest`, its resource selectors, allowed purposes, and its current
  reviewed test-context `policy_revision`.
- **Principal grants.** A group or app-role selector (never a display name or email), case scopes, operations
  (`test-context.propose`, `test-context.review`, `test-context.revoke`, `case-history.read`), purposes,
  validity, reviewer, and revocation state.
- **Reuse grants.** Case scopes whose immutable cases may be reused for events in a named target scope.

The verifier takes the subject, principal kind, and exact groups only from the Operator authentication receipt,
rejects a context whose `principal_groups` differ, and requires a current grant for the exact case scope, operation,
and purpose. A matching revoked or expired grant denies, and overlapping grants never widen scope. Every digest,
including `principal_scope_digest` and `access_scope_digest`, stays opaque; equal values never imply a grant. The
target must belong to the case scope in the reviewed operating scope, and a command's `policy_revision` must equal
the scope's pinned revision. A read-only Operator projection of these grants supplies the server-owned choices that
[#1023](https://github.com/dotnetpower/fdai/issues/1023) needs; browser input never selects a scope.

## Source-specific design

Each subsection names the consumer, its exact lookup (scopes keep the `sha256:` prefix), and five read-back
proofs. Freshness ceilings are proposals for review.

### Operator test-context command

Consumer: `TestContextCommandHandler.validate` in `core/operational_context/test_context_commands.py`, used by Var
and Mimir. Lookup: `content_digest(TestContextCommand)`, the request scope, `operator-test-context-command`, and
the request `policy_revision`.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | The Operator outbox record for the idempotency key, read through a view limited to test-context command rows: `principal_kind=human`, `scope.subject_id` equal to `principal_id`, and a valid authentication receipt at `accepted_at` |
| Evidence | The command rebuilt by the same rule as `command_from_record` in `services/operator-service/src/fdai_operator_service/test_context_runtime.py` equals the lookup; a grant permits the operation; the target is in scope |
| Completeness | Exactly one record for the key, a matching `request_digest`, complete grant and scope revisions, and no rejected delivery state |
| Conflict | No second record for the key with another digest, and no revoked grant or superseded policy revision |
| Freshness policy | 600 seconds from `accepted_at`; an older command must be resubmitted |

### Test-context transition

Consumer: `GovernedTestContextStore._record` in `core/operational_context/test_context_lifecycle.py`; Mimir
requests issuance before its compare-and-set (CAS) write. Lookup: the digest of the claim and prior digests,
the claim scope, `test-context-transition`, and the claim `policy_revision`.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | The triggering Operator command and, for a review or revocation, the proposal command; each actor holds the grant for its operation, and the reviewer's subject differs from the requester's |
| Evidence | The claim rebuilt from the command and the prior revision, and the transition digest, equal the lookup |
| Completeness | The complete `test-context-target:v1` history for the scope and target, validated with the store's chain rules, with each revision matched to its atomic audit entry and its authenticated Operator command |
| Conflict | No overlapping reviewed claim for the same signal, no store revision change between two reads, and no competing command for the key |
| Freshness policy | 120 seconds from the store read; a review is also capped at the claim's `effective_to` |

### Current test context

Consumers: Forseti through `evaluate_test_context` in `agents/_framework/forseti_judgment.py`, and Thor through
`TestContextDispatchGuard.current`. Lookup: the claim digest, the scope, `operational-test-context`, and the claim
`policy_revision`. Both keep their latest-read check, so a later revocation holds judgment and dispatch. If a revocation
retires the lineage below, the context holds; with no second review allowed, re-attestation is revoke and re-propose.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | Re-verified from sources under the current binding: the reviewed revision's chain and atomic audit entry, and both lifecycle commands. The cited `test-context-transition` admission is lineage; it counts only if the pin history shows its binding and every grant it matched present and unrevoked from its `verified_at` through the current pins |
| Evidence | The context's current revision equals the claim, is `reviewed`, covers the evaluation instant, and its target is still in scope |
| Completeness | The complete target history shows no later and no future-recorded revision |
| Conflict | Exactly one active reviewed claim for the target and signal |
| Freshness policy | 300 seconds from the store read, capped at `effective_to` |

### Test observation

Consumer: Forseti through `evaluate_test_context`, only for a signal already inside the reviewed envelope.
Lookup: `observation_context_digest`, the scope, `operational-test-observation`, and the claim
`policy_revision`.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | Provider readback under the verifier's own reader identity; the event payload's value is never trusted |
| Evidence | The provider sample for the exact target, metric, dimensions, aggregation, and `observed_at` equals `observed_value`; `service_impact=none` only when every production dependency in the reviewed operating scope is healthy in its bound health source; `protected_signal` comes from the current policy revision |
| Completeness | The target is in scope, one series has a sample in the exact bin, no dependency is unmapped (`OperatingScopeCoverage.complete`), and every dependency has health coverage |
| Conflict | No conflicting sample, series, or health source |
| Freshness policy | 300 seconds from the provider read |

### Forecast history source slices

Consumer: Heimdall's `StateStoreForecastContextProvider._require_admission` in
`delivery/persistence/state_store_forecast_context.py`. Lookup per slice: the slice digest, the access scope,
`forecast-history-<kind>`, and the slice `source_revision`.

| Kind | Authoritative source | Independent corroboration | Completeness requirement |
|------|----------------------|---------------------------|--------------------------|
| `actions` | Thor-owned ActionRun records and their hash-chained audit entries | Activity Log operations by the executor identity on the target | A contiguous verified audit segment from before the lookback to after horizon end plus grace |
| `changes` | Inventory observation journal, read through the contract in `delivery/forecast_change_history.py` | Resource Graph change and Activity Log records read under the verifier's identity | A positive start checkpoint, a terminal cursor, a watermark past horizon end, and provider history within retention |
| `resource_lifecycle` | Confirmed-tombstone incarnation ledger in `core/ontology_platform/operational_history_lifecycle.py` | Provider existence and delete records at both window edges | An established initial state and incarnation boundaries that cover the window |
| `excluded_windows` | Revisioned `ChangeWindow` history | Pinned operating-intent source revisions that declared each window | Revision history that covers the whole window |

For every kind, the evidence proof is the recomputed slice digest, the conflict proof covers disagreement with
the corroboration or same-instant conflicting records, and freshness is 3,600 seconds from the source watermark,
never past the slice's `valid_until`. Scope membership comes from the reviewed operating scope, not from
`FDAI_FORECAST_TARGETS_JSON`. Raw history production remains [#1021](https://github.com/dotnetpower/fdai/issues/1021),
and an unimplemented source means no issuance.

### Forecast context aggregate

Consumers: `StateStoreForecastContextProvider._retain` for retention and
`ContextualForecastObservationProvider._join_context` in `core/detection/forecast_context.py` for scoring.
Lookup: the aggregate digest, the scope, `forecast-context`, and the aggregate `source_revision`.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | Four current slice admissions under this binding for the same scope, target, and window; the aggregate never replaces them |
| Evidence | The aggregate rebuilt with the same aggregation rule as `_retain` equals the lookup |
| Completeness | All four kinds are present and complete; an amendment names the exact current predecessor |
| Conflict | No identity or window disagreement between slices |
| Freshness policy | 3,600 seconds from the oldest slice cutoff, and never past any slice admission |

### Case-history read

Consumer: `OperatingPatternQuery._read` in `core/ontology_platform/pattern_queries.py` for
`query.operating_patterns`. Lookup: the digest of the arguments and `FunctionInvocationContext`, the digest of
the principal scope, case scope, and purpose, `case-history-read`, and the active ontology release digest.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | The Operator authentication receipt for the request that carried `principal_ref`, retained like the command receipt |
| Evidence | A current explicit grant for the receipt's subject and groups, case scope, `case-history.read`, and purpose, and a case scope whose recorded purpose matches |
| Completeness | The complete pinned grant registry revision and a known case-scope definition |
| Conflict | No revoked, expired, or contradictory matching grant, and no `principal_groups` that differ from the receipt |
| Freshness policy | 60 seconds from the grant read |

### Current-case reuse

Consumer: `contextual_reuse_reasons` in `core/tiers/t1_lightweight/contextual_reuse.py`, the T1 (lightweight
similarity reuse) tier of Forseti's judgment, fed by `AzureCurrentReuseVerifier` in
`delivery/azure/operational_evidence.py`. Lookup: `current_reuse_evidence_digest`,
`current_reuse_scope_digest`, `current-case-reuse`, and the case `graph_digest`. Thor still revalidates.

| Proof | Read-back subject |
|-------|-------------------|
| Authentication | The current inventory snapshot and Muninn's current case revision, read under the verifier's identity |
| Evidence | Recomputed fingerprint, resource type, topology role, graph and owner digests, and seven safety results, each backed by a retained receipt reference, plus a reuse grant that covers the case scope and the event's target scope |
| Completeness | A complete current graph generation for the target and a readable receipt for every safety result |
| Conflict | No generation, case-revision, or receipt disagreement |
| Freshness policy | 300 seconds from the snapshot observation, matching the current five-minute snapshot bound |

## Fail-closed rejection matrix

| Class | Detected by | Recorded outcome |
|-------|-------------|------------------|
| Stale | Verifier preflight `stale`, consumer `not_current`, and boundary time windows | Rejection record `stale`; the owner holds or excludes with that class |
| Revoked | Grant or binding revocation at issuance, content-classified revocation revisions, the binding recheck on every `admit`, and consumer latest-source reads | Rejection record `revoked`, or a retired admission that the boundary re-requests; revoked evidence admits nothing, even before it expires |
| Conflicting | The conflict proof across a source and its corroboration | Rejection record `conflicting` with conflict digests; the owner records an explicit conflict that lowers autonomy and is never averaged away |
| Partial | Completeness below 10,000 basis points, a missing checkpoint, a truncated page, or an unmapped dependency | Rejection record `partial`; an empty result never proves absence |
| Synthetic-live | `synthetic=true`, a source outside the pinned anchors, or a `local-loopback` anchor or receipt in a deployed venue | Rejection record `synthetic_live` |
| Cross-scope | A missing grant, a target outside the scope, a group mismatch, or a scope or purpose mismatch | Rejection record `cross_scope`; digest equality never substitutes for a grant |
| Replay-substituted | Exact lookup, receipt-bound proofs, predecessor digests, a per-purpose store, and latest-source rechecks | Rejection record `replay_substituted`; an old, foreign, or `deployment-apply` record never admits another input |
| Self-verified | Verifier anchors equal to a source, producer, reviewer, or executor-class anchor, or a proof store that another principal can write | The verifier refuses to start or issue, and capability state names `self_verified` rather than an outage. This class exists only in capability state: it writes no rejection record, and owners keep their generic hold |
| Unavailable | A missing verifier, source, store, or registry, a timeout, `429`, or `503` | No record; the owner keeps today's generic reason, and capability state names the missing dependency |

## Pantheon ownership and topics

| Purpose | Source owner | Accountable consuming agent |
|---------|--------------|-----------------------------|
| `operator-test-context-command` | Operator service outbox (non-agent) | Var for reviews and Mimir for transitions |
| `test-context-transition` | Operator commands and Mimir's governed store | Mimir |
| `operational-test-context` | Mimir's governed store | Forseti for judgment and Thor for the dispatch recheck |
| `operational-test-observation` | Telemetry provider and reviewed operating scope | Forseti |
| `forecast-history-*` | Thor, the inventory journal, the incarnation ledger, and the operating-intent source | Heimdall |
| `forecast-context` | The four admitted slices | Heimdall |
| `case-history-read` | Grant registry and Muninn case metadata | Bragi, which calls the read function (`caller_agent="Bragi"` in `composition/semantic_query_invocation_context.py`); Muninn stays the case owner |
| `current-case-reuse` | Inventory graph, Muninn cases, and safety receipts | Forseti, with Thor revalidation |

The verifier issues for every purpose and never joins the pantheon, publishes an owned object, judges, approves,
executes, or promotes. No topic is added or re-owned: Var still publishes `object.approval`, Mimir `object.policy`,
Forseti `object.verdict`, Thor `object.action-run`, and Heimdall `object.forecast-outcome`. Consumers cite
admission and rejection digests in records they already own, as the transition audit `admission_ref` does.
Accountability stays per boundary: each consuming decision above already names its agent, as with today's injected
verifier providers. Saga isn't a steward, because it audits these decisions afterward and its loss demotes the whole
system to shadow, while an issuance outage makes only the affected purpose `unavailable`.

## Local testability and connected handoff

Local deterministic checks run without a live model, Azure service, or remote database:

- **Digest parity and exact sources.** The verifier and each consumer share one canonicalization function per purpose.
  Fakes shaped like Operator outbox rows, `test-context-target:v1` records with audit entries, journal pages, incarnation
  rows, `ChangeWindow` revisions, metric responses, and grant revisions check each class's exact recorded outcome.
- **Transport, writers, and registry.** Tests cover the deadline, one attempt with `429` and `503` as `unavailable`,
  in-flight coalescing, an older rejection that `outcome` refuses, and a re-read after a forged response body.
  Loopback PostgreSQL writer and reader roles prove Core can't create either record and replay is idempotent. An
  unlabeled removal or narrowing still retires records, and routine rotation doesn't.
- **Regression baseline.** Existing decision-evidence tests, such as `core/readiness/test_decision_evidence.py`,
  and each consumer's focused tests under `services/core-control-plane/tests/` keep passing.

These checks validate mechanics only and never count as operational qualification. The connected handoff runs
only after separate explicit authorization, on a selected non-production target, with the same source revision:

| Stage | Observable evidence required |
|-------|------------------------------|
| Identity | The verifier principal differs from every source, producer, and executor-class principal, its own role assignments are limited to exact DSN-secret read, exact registry pull, and approved read scopes, and the writer readback shows only the verifier database role |
| Registry | Both registry digests match their pins in the verifier and every consumer |
| Positive issuance | One admission per purpose from real sources, consumed by its boundary, with receipt and bundle digests in the owner's audit |
| Negative drills | Each rejection class except self-verified produces its expected rejection record and matching owner reason in the dedicated test scope; the self-verified drill asserts capability state `self_verified`; a stopped verifier yields only `unavailable` and never passes another class's drill |
| Stop conditions | Missing identity, `429` or `503`, a deadline, or conflicting evidence stops the run and records the missing stage |
| Record | The deployed SHA, registry digests, scope digest, timestamps, and receipt references; independent operational qualification stays with [#1026](https://github.com/dotnetpower/fdai/issues/1026) |

## Implementation notes

Core paths are relative to `services/core-control-plane/src/fdai/`. Each item records how the design is realized
today; the [implementation ledger](../../roadmap-implementation/rules-and-detection/independent-operational-evidence.md)
tracks what remains.

- **Contracts.** `fdai_service_contracts.operational_evidence` defines the lookup, the coordinates-only locator, the
  content-free request and response, and the rejection record with its fixed 60-second window.
  `fdai_service_contracts.operator_authentication` defines the token-free Operator authentication receipt.
- **Seam and owners.** `shared/providers/operational_evidence_issuer.py` declares `OperationalEvidenceIssuer` and the
  attempt-scoped outcome reader. `core/operational_evidence/owner_outcome.py` coalesces identical in-flight requests
  and accepts a rejection only after re-reading the record that attempt named. Every consuming owner requests
  issuance before `admit`, and a proven class replaces only its generic reason while citing the rejection record
  digest: Var and Mimir refuse with `OperationalEvidenceRejectedError`, and Mimir also appends a
  `test_context.transition_refused` audit entry with no `context_digest`; Forseti's hold carries
  `evidence_rejection_ref`; Thor's dispatch hold sets the `ActionRun` outcome and `evidence_rejection_ref`; Heimdall
  excludes scoring with an `operational_evidence_*` class in `ForecastOutcome` schema `1.2.0` and an
  `operational-evidence-rejection:` evidence reference, whether scoring or slice retention was rejected; the T1
  reason codes and the Pattern read's refusal name the class and cite the record.
- **Verifier.** `core/operational_evidence/issuance.py` and `proofs.py` build the receipt, five proofs, and bundle
  from registry entries and its own readback, evaluates them with `DecisionEvidenceReadinessGate`, and writes one admission or one
  rejection. `separation.py` refuses a verifier principal that equals any independent principal, and
  `delivery/operational_evidence_server.py` serves the loopback and deployed endpoints. The deployed startup
  path requires explicit executor-class anchors, a registered producer-token authenticator, and an own-role
  readback before it can report `ready` or issue. `deployment_preflight.py` builds the executor-class anchor set, `operational_evidence_caller_auth.py`
  validates the short-lived caller token and discards it, and `own_role_readback.py` refuses partial readbacks,
  unresolved role definitions, identity mismatches, vault-wide secret access, other-secret access, or write/data-plane roles outside the exact rendered read scopes. Terraform
  renders only internal ingress. The current caller authenticator consumes a deployment-supplied JWKS snapshot;
  an unknown `kid` is a clear authentication refusal until a later bounded JWKS refresh provider is added. The workload issues only under the exact
  binding of its own verifier version, so a routine rotation leaves an earlier workload and its retained admissions
  valid until they expire, while a revocation revision retires them. A replayed attempt returns its stored outcome,
  even when a concurrent writer inserted it first; an attempt id reused for another lookup is `unavailable`.
- **Venue.** `FDAI_EXECUTION_VENUE`, resolved by `resolve_execution_venue`, is authoritative. An anchor document
  that names another venue or repeats a key leaves every purpose unavailable and stops the verifier workload, and
  the local workload accepts only loopback callers. A deployed workload may bind a non-loopback endpoint, but it
  starts only after the caller authenticator, executor-anchor preflight, writer readback, and own-role readback all
  pass.
- **Registries.** `config/operational-evidence-trust-registry.json` is the reviewed upstream registry.
  `trust_registry.py`, `grant_registry.py`, their `*_loader.py` modules, and `revision_history.py` load pinned
  revisions strictly, classify each revision by content, retire earlier pins after a revocation revision, and end lineage only when its matched binding or
  grant is revoked. A matching grant that is not yet valid neither grants nor denies; only revoked or expired
  matches deny. A purpose whose verifier trust anchor is also a producer, source, or separation anchor reports
  `verifier_anchor_not_exclusive`. The upstream `forecast-context` entry now names a Core-owned
  forecast-context retention source and a Core-owned slice-admission index, not the verifier trust anchor,
  so the registry loads without that defect while the readback remains unbound until raw forecast sources exist.
  Deployment supplies the grant registry, pins, and anchor binding.
- **Proof store and sources.** The core-control-plane service migration `core_operational_evidence_20260928` creates
  the five insert-only tables, the verifier and reader roles, and immutability triggers. It also lets only the Operator
  identity insert test-context command rows, freezes their request fields and receipt, and defines read-only
  security-barrier views over those rows, Mimir's history, and its audit rows. The follow-on migration
  `core_operational_evidence_source_functions_20260929` revokes the verifier's `SELECT` on those views and grants it
  `EXECUTE` only on four fixed-parameter `SECURITY DEFINER` SQL functions with a pinned `search_path` and no dynamic
  SQL. Each function filters inside the definer's context, so a caller-supplied predicate sees only returned rows and
  planner estimates or `EXPLAIN ANALYZE` row counts no longer reveal other `state_kv` keys; its downgrade restores the
  view grant. The first migration revokes any direct `TEMPORARY` grant from the verifier role; the PostgreSQL default
  `PUBLIC` grant remains because Core uses temporary tables. The Operator retains the receipt beside, not inside, the
  idempotent request digest.
- **Readbacks.**  `operator-test-context-command`, `test-context-transition`, and `operational-test-context` read real
  sources. A current context is admissible only when the transition admission it cites has the lookup rebuilt from
  that context and its prior record; any other cited admission is `replay_substituted`. `admit` rechecks each
  retained record against its exact verifier binding and that binding's readiness under the current anchors. The
  `operational-test-observation`, `case-history-read`, and `current-case-reuse` remain unbound. The observation provider is not yet available under verifier identity. Case-history now has an insert-only Operator semantic authentication receipt schema, `operator-core-request` `1.9.0` receipt reference, Core-to-Bragi reference propagation, and an unwired exact readback module, but the Operator stream path does not yet populate the durable receipt table or prove a positive issuance through real codecs, Core, Bragi, `OperatingPatternQuery._read`, and a bound verifier. The Operator setting `FDAI_SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENABLED` defaults off and may be enabled only after Core that accepts `operator-core-request` `1.9.0` is deployed. Current reuse lacks independent inventory/Muninn/safety receipt sources. Forecast-history and forecast-context purposes also have no bound source readback.
- **Shared grant validation.** The case-scope grant registry loader and authorization model are packaged in the shared service-contract SDK and re-exported by Core. Operator's test-context choice projection uses that same loader with a content pin instead of maintaining a parallel grant validator.
- **Capability and handoff.** `delivery/operational_evidence_readiness.py` adds one Settings row per purpose. Runtime
  Settings materialization observes the verifier readiness endpoint once, through a bounded read that treats every
  failure as unobserved, and passes the typed `OperationalEvidenceVerifierReadiness` snapshot into the projection. A
  row is `available` only when that snapshot is at most 120 seconds old, names this verifier and the same registry
  pins, reports a writer-exclusive proof store, binds the purpose, has an active binding for its own verifier
  version, and reports every source the purpose declares as healthy after a bounded probe read; each failed
  prerequisite is named, configuration alone never makes a row available, and availability grants no authority.
  `delivery/operational_evidence_handoff_cli.py` runs the automatable connected-handoff stages and lists the owed drills.

## Non-goals

- No new agent or topic, no `owns`, `subscribes`, or role-binding change, and no execution or promotion authority.
- No reuse of the `deployment-apply` policy, its workflow proofs, or its container.
- Consumers stay fail-closed, including the existing self-review rejection; only their hold reasons gain classes.
- Out of scope: raw history (#1021), the Console workflow (#1023), Pattern-to-T1 intake (#1024), and P0-P6
  qualification (#1026). No tenant values, secrets, or live Azure, model, or deployment activity.

## Review decisions

The owner recorded these decisions on 2026-09-28 for exit criterion 1 of #1022:

1. **Proof authenticity.** Write exclusivity plus immutability is the anchor. There are no detached signatures
   and no proof contract version change.
2. **Human authentication.** The Operator authentication receipt alone establishes the human principal. There
   is no identity-provider sign-in corroboration.
3. **Accountability.** Per-boundary accountability applies, with no single steward.
4. **Proof store.** Insert-only PostgreSQL tables in both venues.
5. **Freshness ceilings.** The per-slice ceilings, from 60 to 3,600 seconds, are confirmed as proposed.
6. **Corroboration cost.** The five-second history deadline stays. Corroboration that doesn't finish within it
   yields `unavailable`; no deadline change is approved.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/independent-operational-evidence.md) |
| Consumers, context contract, and forecast admission | [Prediction learning and case history](prediction-learning-and-case-history.md) |
| Decision-critical evidence rules | [FDAI Constitution](../architecture/fdai-constitution.md) |
| Agent ownership and topics | [Agent pantheon](../agents/agent-pantheon.md) |
| Pinned deployment-owned sources | [Operating-intent source](../architecture/operating-intent-source.md) |
