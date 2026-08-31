---
title: Operational Learning Ontology
---
# Operational Learning Ontology

This design turns benchmark treatments and real incident outcomes into reusable FDAI operating
knowledge. It uses case history for immutable evidence, the ontology for meaning, and the existing
rule and action catalogs for governed reuse instead of creating a benchmark-only knowledge path.

> **Authority boundary:** A benchmark pass is evidence, not permission. It cannot create an active
> rule, promote an `ActionType`, or raise autonomy.
>
> **Semantic authority:** [FDAI Operating Ontology](../architecture/operating-ontology.md) owns the
> shared service, objective, decision, and effect model. This document owns evidence-to-pattern learning.
>
> **Scope:** Benchmark names, customer resource names, raw logs, and model prose never become
> reusable identifiers. The reusable unit is a generic failure mechanism supported by redacted,
> content-addressed evidence.
>
> **Implementation status (2026-08-01):** O0 through O7 core contracts and runtime injection seams
> are implemented. Immutable operational-case
> inputs compile allowlisted audit, action, response-outcome, and evaluation receipt facts into
> canonical sources, then the existing case-history writer seals `ACTION` and `INCIDENT` revisions.
> Muninn groups the sealed projections by failure fingerprint, and Norns emits balanced inert
> candidates through its existing consensus and rate limits. Operational T1 reuse requires current
> evidence, causal and Dynamic grades require authoritative receipts, and promotion requires a
> verified immutable O7 receipt. O3 now binds a deterministic frozen-scenario validator and an
> inert draft-PR publisher when its complete deployment configuration is available. O7 has a
> strict immutable-file evidence source, manifest-bound causal and unit verifiers, durable receipt
> sink, and one-shot measurement job. Heimdall now has a typed terminal ActionRun observation path
> and an Azure Container Apps `ops.scale-out` collector, while deployments still supply its signed
> context issuer, complete Forseti-owned lineage inputs, and action-specific live evidence. Mimir emits
> review outcomes on its owned rule topic, and Saga seals them on its owned audit topic.
> Reproduced semantic-retrieval failures enter through Huginn, become Heimdall-owned independent
> validation evidence audited by Saga, and are materialized by Muninn on the context-index topic.
> Norns persists challenger-only StateStore records with shadow audit and reuses the ordinary
> consensus and Mimir candidate guard. Raw query text and online ranking mutation remain excluded.

## Design at a glance

FDAI learns in two layers. An **operational case** is an immutable record of what was observed,
decided, attempted, verified, and rolled back. A **promoted operating pattern** is the existing
catalog relationship `Rule -> remediates -> ActionType`, accepted only after cohort analysis,
replay, shadow comparison, and the ordinary promotion gate.

![Design at a glance. The main stages are Benchmark or live incident, Saga audit evidence, Muninn operational case revision, Deterministic failure fingerprint, Norns cohort analysis, Inert RuleCandidate, Mimir replay and shadow gate, Rule catalog, ActionType catalog, T1 similarity reuse with current checks, Risk, approval, execution, and audit.](../../diagrams/generated/fdai-roadmap-rules-and-detection-operational-learning-ontology-01.en.svg)

When active, an evaluation adapter is only an evidence source. It emits the same canonical case
inputs as a production incident, then leaves the normal agent-owned learning path to decide whether
the case contributes to a candidate. The current evaluation host integration is dormant, so no
adapter supplies case-history intake today. The conversational corpus under `eval/golden-dataset/`
is regression input, not an operational case or learning authority.

The O1 compiler accepts only canonical identifiers, SHA-256 digests, booleans, and bounded counts
declared by each receipt schema. It rejects unknown fields, inconsistent action or outcome facts,
raw resource identities, benchmark names, prompts, secrets, and free-form payload authority.

## Knowledge units

### Operational case

An operational case is a `CaseHistoryRevision` with `kind: incident` or `kind: action`. It does
not require a new ontology object in the first implementation wave. Its source records contain
bounded structured facts:

- **Observation**: normalized signal codes, resource type, topology roles, evidence digests, and
  event-time cutoff.
- **Diagnosis**: deterministic finding references, grounded RCA citations, failure mechanism, and
  ambiguity or abstention reason.
- **Decision**: selected `ActionType`, rejected alternatives, verifier result, risk decision, and
  approval reference.
- **Execution**: target digest, preconditions, dry-run receipt, idempotency key, affected
  resources, and terminal receipt.
- **Effect**: expected and observed postconditions, SLO recovery, recurrence window, rollback
  result, and external validation when available.

Successful and failed treatments are both retained. A safe refusal, failed postcondition, or
successful rollback is negative evidence that prevents FDAI from repeating an unsafe action.
A success counts as reusable only when the response receipt explicitly records verified enforcement
and `rollback_succeeded: false`; missing rollback state remains insufficient evidence.

`EligibleOperationalOutcome` is the only composition contract that labels an outcome eligible for
this learning path. It binds one immutable FDAI revision and scenario set to the exact source
identity digest, event-time cutoff, Action receipt, independently observed effect receipt, Saga
audit receipt, completeness flag, synthetic status, and conflict set. Incomplete, stale,
conflicting, future-dated, or synthetic evidence labeled as live is rejected before a case event is
published.

### Failure fingerprint

The fingerprint identifies a failure class independently of the benchmark and proposed remedy. It
is SHA-256 over canonical JSON containing only:

```json
{
  "schema_version": "1.0.0",
  "resource_type": "kubernetes.service",
  "failure_mechanism": "selector_target_mismatch",
  "symptom_codes": ["endpoint_owner_mismatch", "request_route_failure"],
  "topology_roles": ["client", "service", "selected_workload"],
  "ownership_shape": ["service_selects_workload"]
}
```

Arrays are sorted and deduplicated before hashing. Resource ids, namespace names, benchmark ids,
timestamps, free-form explanations, and action names are excluded. Two environments with the same
mechanism and graph shape can therefore join one cohort without leaking either environment.

### Rule candidate

Norns compiles a cohort into the existing `RuleCandidate` object. Candidate evidence includes:

- case ids, revisions, and manifest digests;
- failure fingerprint and supported resource types;
- success, no-op, refusal, rollback, and recurrence counts;
- the proposed signal predicates and causal graph requirements;
- the proposed existing or new `ActionType` reference;
- at most 100 immutable cases, 64 digest refs per case, and 256 aggregate digest refs;
- confidence bounds, known exclusions, and unresolved conflicts.

Each candidate also carries the pinned FDAI revision, scenario-set version, and one review record
per immutable case. Norns checks completeness, freshness, source classification, conflicts, and
duplicate revisions before publication. Mimir independently parses the same records and rejects a
missing, stale, conflicting, synthetic-live, duplicate, release-mismatched, or digest-substituted
candidate before compiling the inert review package.

Typed learning handlers are serialized per Norns instance. The pending proposal queue is bounded at
5,000 entries; saturation first retries a drain and then backpressures the transport without changing
the new signal's learner state. Runtime composition can replace the deterministic
`OperatingPatternCompiler` through its constructor seam.

One successful benchmark case cannot produce a promotable candidate. The initial gate requires at
least one successful treatment, one negative or control case, deterministic replay, and no policy
escape. Action promotion still uses the stricter sample and observation requirements declared by
the `ActionType`.

### Promoted operating pattern

A promoted pattern uses existing catalog objects and links:

- `Rule -> triggered_by -> SignalType` selects relevant observations.
- `Rule -> applies_to -> ResourceType` narrows compatible targets.
- `Rule -> remediates -> ActionType` names the governed response.
- `ActionType` supplies preconditions, stop conditions, blast radius, rollback, tier ceilings, and
  the shadow promotion gate.

No separate benchmark rule format or learned-action executor is introduced. If an implementation
cannot express a required query with these links, it must first add a failing ontology query test.
Only then may a focused `ObjectType` or `LinkType` extension be proposed.

Publishing a candidate or draft review package grants no authority. An ActionType can move in the
authoritative promotion registry only when an independent reviewer approves the exact candidate,
package, deterministic replay digests, FDAI revision, scenario set, and O7 evidence digest.
Restart revalidates the same attribution; a duplicate is a no-op, and rollback or demotion returns
the registry to shadow.

### Pattern is one layer, not two

`PANTHEON_SPECS` once assigned Norns a `PatternObservation` while the catalog named the same record
`Pattern`. The two names described one inert compiled cohort record, not a raw observation and a
reviewed generalization, because no code performs the review that a second layer would require. The
spec, the topic, and every table now use `Pattern`.

- [`OperatingPatternCompiler.compile()`](../../../services/core-control-plane/src/fdai/core/operational_learning/patterns.py)
  applies mechanical predicates only: one shared failure fingerprint, resource type, and action
  type, at least one reusable and one negative sealed case, no repeated immutable case reference,
  and bounded evidence. Nothing reviews or generalizes its `OperatingPatternCandidate` output.
- Review happens later, at Mimir, on a `Rule`. Calling a pattern record reviewed asserts a step
  that no code performs.
- The record is never published as its own object. `Norns._observe_operational_case_cohort`
  flattens it through `to_rule_candidate_mapping()` onto `object.rule-candidate`, so the compiled
  cohort reaches Mimir only inside a `RuleCandidate`.
- `object.pattern` is a registered topic with no publisher and no subscriber, so `Pattern` remains
  an owned object type that nothing produces. Unifying the name did not close that gap.

This is why `learned_as` (`ObservedOutcome -> Pattern`) has no producible endpoint pair. A cohort
cites sealed cases as `case-history:<case_id>:<revision>:<manifest_digest>` and never receives an
`ObservedOutcome` identity, so the edge could only be fabricated. If it is ever declared it stays a
reviewed learning projection and MUST NOT create a path from a learned record to an active catalog
entry or threshold; promotion remains the authority of the independently reviewed registry.

### Why Forecast and Pattern are declared

Both types were banded on the console before the catalog declared them, so the availability filter
dropped them without a signal. Both are declared now because each already has a fixed-pantheon
owner and a producing mechanism: Heimdall produces `Forecast` in
[`forecast.py`](../../../services/core-control-plane/src/fdai/core/detection/forecast.py), and Norns
produces `Pattern` in `OperatingPatternCompiler`. Deleting them from the bands would have hidden
implemented behavior instead of correcting an overclaim. Neither declaration adds a link type,
projection, instance path, or authority, and `predicts_breach_of` and `learned_as` stay undeclared
because neither endpoint pair is producible.

### Retired relationship plans

Two relationships that earlier revisions of the
[relationship contract](../architecture/operating-ontology.md#relationship-contract) listed as
contract rows are retired, not declared. Their ObjectTypes remain available for semantic queries,
but FDAI does not keep an active plan to create these links.

| Relationship | Intended endpoints | Retirement decision |
|--------------|--------------------|---------------------|
| `predicts_breach_of` | Forecast -> Objective | Retired because `ForecastFinding` carries no objective identity and `Objective` is a conceptual union. A writer would have to invent the target endpoint. |
| `learned_as` | ObservedOutcome -> Pattern | Retired because a cohort cites sealed case-history revisions and never receives an `ObservedOutcome` identity. A writer would have to invent the source endpoint. |

Both names stay absent from the active LinkType catalog. Reintroducing either plan requires a new
reviewed design with authoritative endpoint producers, an exact release policy, and a competency
question. It is not residual work for the current learning runtime.

## Agent ownership

| Agent | Responsibility |
|-------|----------------|
| Huginn | Normalize benchmark and production observations into the same event vocabulary. |
| Heimdall | Gather bounded evidence and close expected-versus-observed effects. |
| Saga | Append decisions, attempts, postconditions, and rollback evidence. |
| Muninn | Seal access-scoped operational case revisions and index their metadata. |
| Norns | Build balanced cohorts and emit inert `RuleCandidate` objects. |
| Mimir | Replay candidates, compare active and challenger behavior in shadow, and govern promotion or demotion. |
| Forseti | Judge the current case and any candidate response through the normal quality and policy gates. |
| Var | Record independent human approval when the resolved ceiling requires it. |
| Thor | Execute only a currently eligible promoted action. |
| Vidar | Apply the declared rollback and publish its observed outcome. |

All collaboration uses typed event-bus topics. Case materialization and learning stay off the hot
path: a delayed learner cannot block detection, mitigation, rollback, or unrelated incidents.

## Intake from benchmarks

An evaluation result is eligible for case-history intake only when it carries:

1. stable scenario and attempt identity digests;
2. bounded agent-visible evidence captured before the decision;
3. grounded diagnosis and cited rule or evidence references;
4. the proposed action and verifier/risk/approval decisions;
5. a dry-run or explicit no-mutation receipt;
6. observed postconditions and external validation;
7. rollback evidence when mutation or convergence failed.

The adapter maps these fields to ordinary case source records. Hidden oracle text, judge expected
answers, benchmark implementation details, and raw credentials are rejected. A benchmark score is
stored as external validation, never as the root-cause label or promotion decision.

## Operational target absorption

A benchmark pass and an FDAI capability are separate states. FDAI records these states explicitly:

- **`benchmark_passed`** means the external diagnosis and mitigation checks accepted one attempt.
- **`operationalized`** means normal FDAI agents can collect the evidence and propose or execute the
  governed action without importing the benchmark package or starting an evaluation session.
- **`azure_validated`** means the same operational path passed a non-production drill against the
  applicable Azure resource, including its provider identity, postcondition, rollback, and audit
  receipts.

A passed treatment may enter case history as evidence, but it cannot count as a reusable treatment,
candidate success, or FDAI capability until it is operationalized. Because Azure is the implemented
provider, completion also requires `azure_validated`. Each operational case records the target
profile, canonical resource types, evidence capability ids, action type ids, owning agents,
operational provider references, proof references, and any unsupported surface.

| Target profile | Required operational proof |
|----------------|----------------------------|
| Kubernetes | The normal Heimdall and ControlLoop path uses the same bounded Kubernetes API evidence and governed action adapters. A non-production AKS drill proves the complete diagnosis, approval, dry-run, mutation, postcondition, rollback, audit, and restart-replay path. |
| AKS-integrated Kubernetes | The Kubernetes proof above is combined with relevant Azure management-plane evidence for node pools, scale sets, networking, identity, load balancing, storage, or control-plane health. Azure Resource Graph supplies topology, Activity Log supplies change evidence, and Azure Monitor or managed Prometheus supplies telemetry as applicable. |
| Azure resource | The failure fingerprint uses a canonical `ResourceType`; the injected `Inventory` provider supplies topology; Azure Monitor, Activity Log, policy, cost, or service-health adapters supply current evidence; and a governed Azure action provider supplies dry-run, execution, postcondition, and rollback receipts. |

An unavailable Azure adapter is recorded as an unsupported surface. It never becomes an implicit
success, a synthetic fixture presented as live evidence, or a reason to add benchmark-only logic.
Portable Kubernetes behavior remains cloud-provider-neutral in the core, while AKS and other Azure
bindings stay in delivery and composition.

## Runtime reuse

T1 retrieves prior cases by deterministic filters before similarity ranking:

1. match resource type, failure mechanism, and required topology roles;
2. reject stale evidence, censored outcomes, unresolved rollbacks, and policy escapes;
3. rank the remaining case cards by symptom and graph similarity;
4. reconstruct the candidate `ActionType` reference, not historical raw parameters;
5. gather current evidence and re-evaluate every precondition, target identity, blast radius, and
   policy decision;
6. hold for review when the current graph differs or evidence is insufficient.

Historical success raises retrieval relevance only. It never bypasses the verifier, risk gate,
human approval, dry-run, resource lock, idempotency, postcondition, rollback, or audit path.

## Delivery plan

| Wave | Change | Exit criteria |
|------|--------|---------------|
| O0 - Contract fixtures | Implemented: canonical operational-case and failure-fingerprint models plus fixtures. | Two differently named environments produce the same fingerprint; mechanism or topology changes produce a different fingerprint. |
| O1 - Case projection | Implemented: immutable input, allowlisted receipt compilation, projection, artifact-first writer intake, generic metadata persistence, and revision backfill. | Canonical digest, redaction, byte ceiling, duplicate delivery, negative-outcome, StateStore, PostgreSQL, and legacy forecast compatibility tests pass. No adapter writes a rule or action catalog. |
| O2 - Cohort compiler | Implemented: Huginn carries strict operational-case events; Muninn seals and stores bounded fingerprint cohorts; Norns emits existing inert `RuleCandidate` mappings through consensus and rate limits. | Differently named cases with one fingerprint join; another mechanism does not; success-only and raw `ResponseOutcome` evidence are held; balanced evidence emits once with immutable revision citations. |
| O3 - Catalog compilation | Core implemented: Mimir can compile an accepted candidate into an immutable review package containing a draft Rule, optional explicit shadow-first `ActionType`, and schema, policy, replay, and shadow receipts. Production validator and PR publisher remain deployment work. Norns supplies stable wire identity. | Failed or conflicting receipts quarantine the candidate. Concurrent retry publishes once, unresolved capacity backpressures without eviction, successful publication compacts in-memory package state after Saga-owned audit, and operational candidates cannot use direct runtime promotion. |
| O4 - T1 reuse | Core and persistence implemented: T1 stores immutable operational-case context, accepts an injected current-evidence verifier, and rechecks failure fingerprint, resource type, topology role, graph, owner, preconditions, identity, blast radius, policy, dry-run, idempotency, and rollback state. Signatures bind canonical parameters plus the full case context. Concrete Kubernetes and Azure collectors are O5/O6 bindings. | Missing verifier or evidence, stale or changed context, and any failed safety check always holds for review without mutation. Azure evaluates bounded cache age against the evaluation clock while allowing a recent cache observed just before event ingestion. Legacy incident patterns retain their existing behavior. |
| O5 - AKS delivery | Implemented and live-validated in non-production: existing Kubernetes and Azure read seams feed current reuse, temporal causality, and Dynamic requests. A one-pod invalid-image fault used server dry-run, an isolated namespace, and a 45-second observation window. | Kubernetes reported `ErrImagePull` and `ImagePullBackOff`; Azure Monitor reported the pod `Pending`; Log Analytics retained pull-failure and terminating evidence; Activity Log retained cluster lifecycle. Namespace deletion completed rollback and the one-node cluster returned to `Stopped` / `Succeeded`. Production remained unavailable. |
| O6 - Azure resource absorption | Implemented: strict promoted-inventory snapshots plus configured Azure metrics provide generic current-reuse, causal, and Dynamic evidence bindings for Kubernetes and non-Kubernetes resource types. | A read-only non-production Container App drill observed one healthy active revision, one replica, zero restarts, and unchanged pre/post state with no administrative write. Unit evidence proves policy/precondition/dry-run fail-closed behavior, ontology projection, bounded queries, and deterministic restart replay without benchmark imports. |
| O7 - Promotion measurement | Core implemented: immutable FDAI revision, ActionType digest, scenario case, authoritative measurement unit, and latest correction join frozen benchmark and live-shadow cohorts. Corrections cannot change cohort, case, observation time, or causal lineage. The audited idempotent runner measures separate Wilson 95% cohort bounds, distinct live days, executed-action rollback and complete recurrence windows, zero escapes, verified causal receipts, and Dynamic review rate. A closed causal receipt is eligible only with confirmed closure. Deployment binds the evidence source and receipt/unit verifiers. | Raw scalar metrics cannot promote. Failed evaluation audit does not suppress a later successful receipt, repeated receipts preserve the original promotion time, and persisted enforcement is reverified after restart. A separate review is eligible only when every per-action gate passes. Current drills prove bindings but not the required action-specific days and confidence sample size, so promotion remains held. |

O0 through O4 are cloud-provider-neutral. O5 and O6 supply Azure evidence bindings without
changing the learned pattern or control-loop authority model.

## Initial implementation slice

The O0 through O2 code batches implemented these foundations:

1. `OperationalCaseProjection` and `FailureFingerprint` are pure immutable models under
   `services/core-control-plane/src/fdai/core/case_history/`;
2. canonical identifiers, sorted and deduplicated graph descriptors, and schema version form the
  only fingerprint input;
3. sealed case revision identity and evidence references form the immutable learning projection;
4. tests prove environment-name and input-order independence plus mechanism and topology
   sensitivity;
5. strict receipt schemas compile bounded standard facts into immutable `CaseSourceRecord` values;
6. `CaseHistoryMaterializer` seals action and incident cases with duplicate-delivery idempotency,
   append-only source continuity, retention, legal hold, and negative outcomes preserved.
7. Huginn can carry the bounded strict input as `case_history.operational_case.v1`; unknown fields
  or invalid producers are held closed by Muninn.
8. Huginn and Muninn use the failure fingerprint as the event and context correlation partition;
  Muninn stores at most 100 immutable cases per fingerprint and publishes case identity, revision,
  manifest digest, classification, and digest evidence on `object.context-index`.
9. Norns requires one fingerprint and ActionType plus verified success and negative/control
  evidence, deduplicates by pattern digest, and emits only an inert mapping through consensus and
  proposal rate limits. Raw `ResponseOutcome` telemetry cannot create a candidate.

## Norns consensus and catalog boundary

Norns closes the Saga-to-learning loop without mutating a catalog or threshold. Every output is an
inert `RuleCandidate` that requires three deterministic internal perspectives before publication:

| Perspective | Bounded check |
|-------------|---------------|
| Urd | Historical evidence is grounded. |
| Verdandi | The current candidate contract and Norns ownership are valid. |
| Skuld | The proposal does not raise autonomy or enter enforcement. |

These perspectives are not agents or bus principals. Norns remains the sole writer. `3/3`
agreement emits one bounded `norns_consensus`; disagreement retains an aggregate hold without
free-form reasoning. Deterministic candidate sources include repeated fingerprints, rollback-rate
adjustment, overrides or approval rejections, retirement, and optional scenario gaps.
They also include independently reproduced semantic retrieval gaps with an exact versioned target
Rule. Those candidates are persisted before publication and carry no promotion authority.

Trajectory intake accepts reviewed aggregates only. Muninn seals strict operational cases and
publishes bounded failure-fingerprint cohorts. Norns rejects cohorts over 100 cases before
materialization and requires one fingerprint, one ActionType, balanced success and negative
evidence, immutable revisions, and stable correlation and idempotency keys. It emits only into its
bounded 5,000-entry pending queue. Mimir serializes review, quarantines failed receipts, applies
backpressure, and compacts after idempotent PR publication. Reviewed catalog PR and reload remain
the only activation path; Saga seals review outcomes from Mimir-owned `object.rule` events.

## Verification matrix

| Concern | Required proof |
|---------|----------------|
| Generalization | Same mechanism and graph shape across synthetic environments produce one fingerprint. |
| Non-leakage | Customer ids, benchmark ids, raw logs, prompts, and expected answers cannot enter fingerprint or case metadata. |
| Completeness | Every mutable attempt records preconditions, dry-run, terminal receipt, postconditions, and rollback state. |
| Negative learning | Failed, refused, rolled-back, and recurrence cases reduce or block candidate eligibility. |
| Agent ownership | Only Muninn seals cases, Norns proposes candidates, Mimir governs catalog growth, and Thor executes. |
| Determinism | Input order does not change canonical bytes or fingerprint; evidence mutation does. |
| Safety | Historical reuse cannot bypass current verifier, policy, risk, approval, lock, idempotency, or rollback checks. |
| Benchmark parity | Evaluation adapters emit standard case inputs and contain no candidate compiler or learned executor. |
| Deployment parity | Local drills and AKS use the same projection, fingerprint, candidate, and action contracts. |
| AKS parity | Every Kubernetes treatment passes the same end-to-end path on non-production AKS; integrated faults include both Kubernetes API and Azure management-plane evidence. |
| Azure absorption | Every non-Kubernetes treatment names a canonical resource type, Azure evidence provider, agent owner, governed action provider or explicit no-mutation outcome, and non-production proof. |
| Coverage honesty | Missing provider coverage remains an explicit unsupported surface and cannot satisfy `operationalized` or `azure_validated`. |

## O7 evidence deployment contract

The O7 job consumes reviewed evidence; it does not collect or manufacture live observations. A
deployment packages the digest-only JSON files in its pinned runtime image or exposes them through
a protected read-only mount. The configured evidence root is absolute inside the container, while
the manifest and every batch path are relative and remain inside that root. Symlinks, non-regular
files, path escapes, oversized files, digest mismatches, unknown fields, and unverified causal or
measurement-unit references fail closed.

The manifest uses `schema_version: 1.0.0` and contains exactly these fields:

- `batches`: one entry per ActionType with `action_type_name`, relative `path`, and the expected
  canonical `content_digest`;
- `causal_receipt_digests`: the complete allowlist of causal receipt SHA-256 digests; and
- `unit_evidence_refs`: a mapping from canonical measurement-unit id to its exact evidence digest
  set.

Each batch binds the full FDAI revision, scenario-set version, ActionType name, version, and digest,
seal time, and bounded records. A record carries a canonical scenario case, cohort, observation
time, execution and rollback facts, recurrence-window state, causal receipt, Dynamic review state,
and unique evidence digests. Corrections can raise `audit_sequence` only for the same measurement
unit and cannot change cohort, case, observation time, or causal lineage.

Terraform creates the Container Apps Job only when
`operational_promotion_measurement_enabled=true`. The deployment also supplies a full immutable
`operational_promotion_measurement_revision`, an absolute
`operational_promotion_evidence_root`, and a relative `operational_promotion_manifest`. The job
reuses the existing managed identity and Key Vault-backed StateStore DSN. It measures and stores
receipts only; it has no catalog, promotion-registry, or executor authority.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| O0-O1 case contracts and projection | implemented | `services/core-control-plane/src/fdai/core/case_history/`; `services/core-control-plane/tests/core/case_history/test_operational_case.py`; `test_service.py` | Immutable inputs, canonical fingerprints, negative outcomes, revisions, and persistence are covered. |
| O2 cohort learning | implemented | `services/core-control-plane/src/fdai/core/operational_learning/patterns.py`; `services/core-control-plane/tests/agents/test_operating_pattern_learning_e2e.py`; `test_norns_operating_pattern.py` | Muninn seals bounded cohorts and Norns emits only balanced inert candidates through consensus. |
| O3 catalog compilation | implemented | `services/core-control-plane/src/fdai/core/operational_learning/catalog.py`; `services/core-control-plane/src/fdai/delivery/gitops_pr/catalog_validator.py`; `catalog_review.py`; `services/core-control-plane/src/fdai/runtime/operational_catalog_review.py`; focused O3 tests | Complete configuration binds existing Rule schema validation, deterministic frozen replay, regression and policy checks, and a content-addressed inert draft PR. Missing or partial configuration stays unavailable or fails startup. |
| O4 current-evidence T1 reuse | implemented | `services/core-control-plane/tests/core/tiers/t1_lightweight/test_contextual_reuse.py`; `tests/core/test_control_loop_t1_wire.py` | Missing, stale, changed, or unsafe current evidence holds for review without mutation. |
| O5-O6 Azure evidence bindings | validated | [Delivery plan](#delivery-plan); `services/core-control-plane/src/fdai/delivery/azure/operational_evidence.py`; focused delivery tests | Repository-recorded non-production AKS and read-only Azure drills provide the required operational evidence without a production claim. |
| O7 promotion measurement | implemented | `services/core-control-plane/src/fdai/core/measurement/operational_promotion.py`; `operational_promotion_runner.py`; `services/core-control-plane/src/fdai/delivery/measurement/{operational_promotion_evidence.py,operational_promotion_batch.py}`; `measurement_runner_cli.py`; `infra/modules/measurement-runners/`; focused O7 tests and Terraform validation | The exact-digest consumer, manifest verifiers, durable receipt sink, opt-in job, and governed batch producer are implemented. The producer requires immutable frozen-benchmark records and composes them with live-shadow records without changing promotion state. Action-specific observation days, confidence samples, and authenticated runtime receipts remain incomplete. |
| Governed case-to-promotion composition | implemented | `core/operational_learning/{eligible_outcome,patterns,catalog,promotion_review}.py`; `tests/agents/test_governed_learning_loop.py`; frozen `v2026.08` scenario | Exact source and receipt lineage is sealed into immutable cases, Norns and Mimir independently reject the complete negative matrix, candidate publication remains inert, and only independently reviewed replay can authorize the durable promotion registry. |
| Evaluation-adapter case intake | deferred | [Benchmark adapter dormant status](../interfaces/benchmark-adapters.md#dormant-status) | No current EvaluationHost or adapter runtime can emit case inputs. The semantic golden dataset remains outside case history and learning. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Composed eligible outcomes, immutable cases, event-bus candidate publication, independent Norns/Mimir review, and reviewed-replay promotion on one pinned release. Publication remains authority-free; restart, duplicate, rollback evidence, release mismatch, and demotion stay fail-closed. | `current change`; focused Story #370 regression passed 119 cases, including the frozen `v2026.08` scenario. | Retain action-specific live evidence and a governed deployment receipt before claiming operational validation. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; delivery-plan evidence and focused source/tests listed in the scope table. | Complete deployment bindings and O7 action-specific evidence thresholds. |
| 2026-08-21 | deferred | Corrected evaluation intake after the host integration was found absent from the current tree. Kept the new semantic golden dataset outside operational-case and promotion authority. | `current change`; benchmark adapter dormant-status decision; `eval/golden-dataset/`; focused dataset contract checks. | Reopen adapter intake only with a restored governed host and canonical case-input receipts. |
| 2026-08-23 | implemented | Bound O3 to the existing Rule loader, shadow evaluator, regression gate, and draft-only GitOps adapter. The published artifact is content-addressed and cannot activate its draft Rule or ActionType. | `current change`; `delivery/gitops_pr/{catalog_validator,catalog_review}.py`; `runtime/operational_catalog_review.py`; focused O3 tests passed. | Retain a governed draft-PR receipt from a configured deployment. |
| 2026-08-23 | in-progress | Added an exact-digest O7 evidence consumer, manifest-bound causal and unit verifiers, durable receipt persistence, and an opt-in `operational-promotion` Container Apps Job. | `current change`; `delivery/measurement/operational_promotion_evidence.py`; `delivery/measurement_runner_cli.py`; `infra/modules/measurement-runners/`; focused O7 tests and Terraform validation passed. | Implement the governed live-batch producer, then supply action-specific batches and close their observation and recurrence windows. |
| 2026-08-24 | implemented | Reconciled the one-to-many `expects` relationship with runtime lineage by preserving an ordered complete `expected_effect_refs` set and requiring one independent ObservedOutcome per effect. A singular-only stored record reads as one effect, dual-field ambiguity fails closed, and new writes use the plural field. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; focused lineage and operational-hypothesis competency checks passed 15 cases. | Supply the remaining real lineage properties and runtime producer before binding the projector. |
| 2026-08-27 | implemented | Added a governed live-shadow batch producer that emits canonical batch and manifest files consumable by the existing O7 exact-digest source without touching promotion state. | `current change`; `delivery/measurement/operational_promotion_batch.py` and focused producer/consumer checks passed. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-27 | implemented | Added immutable frozen-benchmark cohort composition to the live batch producer while preserving the live-shadow classification and exact-digest consumer contract. | `current change`; focused O7 producer/consumer checks passed. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-27 | implemented | Hardened the producer so benchmark evidence is required, immutable, and never relabeled as live-shadow evidence. | `current change`; focused adversarial O7 producer/consumer checks passed. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |
| 2026-08-28 | implemented | Hardened the O7 live-batch producer so a retry with a real, advancing clock can no longer be mistaken for a conflicting publish. It now reuses an already-sealed batch's `sealed_at` instead of minting a new one on every attempt, publishes the batch and its manifest through an atomic temp-file rename instead of a raw exclusive write that could leave a torn file on a crash, and serializes the publish sequence for one ActionType behind an exclusive per-stem lock. | `current change`; `delivery/measurement/operational_promotion_batch.py`; focused O7 batch retry, atomic-publish, and conflict checks (`4 passed`); Ruff, formatter, and strict mypy. | Supply deployment-owned action evidence and retain complete live days, recurrence, confidence, and authenticated review receipts. |

### Remaining work

- [x] Bind the O3 production validator and pull-request publisher. Focused compiler, Mimir,
  publisher, retry, audit, and idempotency checks prove the local end-to-end path; deployed PR
  evidence remains operational validation rather than implementation work.
- [ ] Bind the deployment-owned signed-context issuer and preserve the missing planning properties
  required by the Forseti-owned causal lineage projection. The exact-plan resolver, Heimdall typed
  producer, Azure scale-out collector, verified mailbox, O7 source, and receipt verifiers are
  implemented, but no runtime producer can yet materialize the complete lineage records.
- [x] Reconcile the catalog's one-to-many `expects` relationship with runtime lineage. New lineage
  writes require the ordered complete `expected_effect_refs` set and one independent outcome per
  effect. Singular-only stored records retain one-effect read compatibility, while simultaneous
  singular and plural fields fail closed. Focused catalog-backed tests preserve every selected
  option effect without choosing or fabricating one metric.
- [ ] Accumulate O7 per-action live days, sample sizes, complete recurrence windows, Wilson bounds, and zero-escape evidence required for promotion review.
- [x] Complete [issue #370](https://github.com/dotnetpower/fdai/issues/370) with one pinned-release
  case-to-candidate-to-reviewed-promotion path and restart, duplicate, rollback, release-mismatch,
  and demotion evidence.
- [ ] If evaluation host integration is reactivated, prove that adapter results enter only through
  canonical operational-case receipts and cannot treat golden-answer success as promotion evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Shared service, objective, decision, and effect semantics | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Immutable case revisions and governed analysis | [Prediction learning and case history](prediction-learning-and-case-history.md) |
| Action safety and promotion fields | [Action ontology](../decisioning/action-ontology.md) |
| External harness authority boundaries | [Benchmark adapters](../interfaces/benchmark-adapters.md) |
| Rule candidate and promotion governance | [Rule governance](rule-governance.md) |
| Reviewed trajectory intake | [Governed trajectory datasets](../interfaces/governed-trajectory-datasets.md) |
