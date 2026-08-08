---
title: FDAI Operating Ontology
---
# FDAI Operating Ontology

This document defines the typed operational truth infrastructure used by FDAI's 15 agents. Agents
remain the active control plane; the ontology prevents them from disagreeing about target identity,
dependencies, objectives, evidence, allowed actions, and expected effects. Upstream owns stable
cloud-operations concepts, while each deployment supplies its observed instances and intent.

> **Positioning:** FDAI is agent-driven, not ontology-driven. The graph constrains interpretation
> and makes agent work replayable; it never senses, judges, approves, executes, recovers, or learns.
> It is nonetheless the required read path. An operational question resolves object identity,
> relationships, and evidence through the ontology instead of an ad hoc provider query, so the
> evidence an answer depends on stays typed, bounded, citable, and complete enough to name what it
> did not observe.

> **Authority boundary:** The ontology graph is a shared semantic read model, not a mutable system
> of record and not an execution surface. Events, approved configuration, telemetry sources, the
> append-only audit ledger, and catalog-as-code remain authoritative for their own facts.
>
> **Safety boundary:** Ontology context can only preserve or lower autonomy. Missing, stale,
> conflicting, or unproven context remains explicitly unknown and triggers bounded evidence
> recovery, a smaller safe plan, no-op, or review. It never supplies permission to execute.
>
> **Implementation status (2026-08-08):** O1-O4 implement semantic declarations, immutable context,
> Forseti ceiling wiring, decision-case selection, response closure, and Muninn/Norns learning
> intake. `OperatingModelProvider` projects bounded deployment instances; context snapshots retain
> typed evidence paths, revisions, effective time, provenance, and complete freshness receipts.
> M3 adds immutable `StateFactMetadata` for observed, derived, desired, and execution lanes.
> Optional inventory link observation metadata survives ontology projection and operational-context
> materialization, contributes to snapshot identity, and lowers the snapshot ceiling when evidence
> is stale, incomplete, conflicting, synthetic, future-cutoff, or unverified.
> Verified links require an independent verifier, a trusted verification method, and an immutable
> verification receipt. Required source freshness, trusted UTC clock identity, recorded time, and
> skew-bounded future checks also contribute to context safety and replay identity.
> Wave 2 provides an unwired, content-addressed `OperationalEvidenceBundle` foundation that keeps
> secured ontology paths, authoritative state facts, catalog references, and governed document
> excerpts in separate authority lanes. Admission requires content-addressed source receipts that
> pin the ontology release, catalog and document revisions, authenticated source, purpose, scope,
> redaction summary, and typed temporal scope. Deterministic claim and citation validation, exact
> typed-claim contradiction detection, and final-body byte and item budgets emit hold evidence and
> can only preserve or lower the bundle's autonomy ceiling. No runtime or composition path consumes
> this bundle yet, so it is not part of the production autonomy path and has no action authority.
> Change management adds planned-change evidence to `Change`, a reviewed `ChangeWindow`, and typed
> links from target and decision through impact, process, outcome, and recovery. These declarations
> are semantic evidence only and grant no approval or execution authority. Huginn now carries the
> same normalized Change on its causal Event and owner topic. Forseti computes a bounded
> `ChangeAssessment`, preserves it on Verdict and DecisionCase evidence, and requires human review
> for stale, incomplete, failed, or review-required assessment. The runtime currently supplies no
> graph-freshness authority, so planned changes cannot auto-clear this gate.
> Wave 2 adds reviewed shared Property semantics without adding a declaration kind. The catalog
> loader validates canonical meaning, value type, optional unit, enum or range, normalization,
> authority, freshness, and equivalent provider paths. Catalog projection exposes those fields
> only for reviewed entries and carries the exact semantic-registry version and content digest.
> Runtime projection reuses the registry validated during catalog loading instead of reading the
> file again. Legacy properties remain valid but cannot claim normalized equivalence.
> M5 adds the catalog-declared `routes_to` and `peered_with` Resource links to inventory projection
> and a read-only deterministic `query.network_path_segments` function foundation. The function
> consumes one bounded, purpose-bound query result only after an injected verifier authenticates
> its role, purpose, exact release, and projected-result digest against the contextual invocation
> and an opaque composition-owned trust context. No production issuer is available, so the
> foundation remains unwired and self-minted receipts are rejected. Evaluation time exactly equals
> the trusted receipt cutoff; future effective, evidence, or recorded times and unbounded freshness
> stay unverified. It preserves stored edge direction and requires two directed peering records with
> distinct direction-bound observation and verification receipt lineage. Missing endpoints,
> incomplete queries, or absent paths remain unknown, never a claim that traffic cannot flow.
> Inventory projection rejects endpoint-type conflicts against observed resources. The function
> uses a source-derived artifact digest, emits exact-release invocation receipts, and has no
> provider I/O or execution authority.

## Catalog semantic projection

The rule catalog now models authored Rego as a first-class `PolicyArtifact`. Every shipped Rule
uses concrete `SignalType` and canonical `Property` references, and `implemented_by_policy` links
the Rule to its deterministic policy. `scripts/catalog/sync-rule-semantics.py` parses Rego through
OPA, verifies package metadata, and blocks drift between policy property reads and Rule metadata.

One reviewed configuration baseline SignalType handles unmatched raw event types. This preserves
deterministic T0 coverage without retaining wildcard ontology links. These catalog declarations
describe meaning only. They don't assert current provider state or grant execution authority.

The catalog-owned `Property` ObjectType remains the meta object for rule property references.
`rule-catalog/vocabulary/property-semantics.yaml` adds reviewed semantics to selected Property
instances as data. Each entry declares a canonical `semantic_id`, `PropertyType`, optional
canonical unit, enum or numeric range, normalization rule identifier, authority and freshness
policy, and equivalent provider paths. Provider-specific paths stay in this vocabulary and don't
become provider branches in core code.

The loader normalizes units and provider identity paths before rejecting collisions, and it
normalizes, deduplicates, and orders enum values before use. String case folding is followed by NFC
normalization. Decimal values use context-independent canonicalization with bounded input,
coefficient, exponent, and output sizes; range checks compare the exact parsed value before
rendering. YAML numeric range bounds are parsed from their authored scalar lexemes into `Decimal`
before Pydantic validation, serialized as canonical decimal strings for content digests, and never
pass through binary floating point. A finite JSON number with an integral mathematical value is a
valid integer bound. Datetimes reject surrounding whitespace and require an RFC 3339 `T` separator,
an explicit timezone, UTC conversion within the supported datetime range, and no more than six
fractional digits. Booleans are never integers or numbers. Object and array Property semantics are
rejected until bounded canonical JSON support exists.

Every registry requires a version and provenance envelope whose SHA-256 covers canonical content
excluding the provenance envelope itself. Every semantic requires authenticated source identity,
and freshness has a finite positive upper bound. Catalog projection pins the verified registry
version and digest on each reviewed Property. A missing registry file produces one stable legacy
empty registry for loading and runtime projection. A Property without reviewed metadata keeps its
legacy projection fields and omits `normalized_equivalence`; callers cannot infer equivalence or
normalize it through this registry.

### Configuration drift vocabulary

The catalog declares `ConfigurationBaseline`, `ConfigurationDriftEvidence`,
`ConfigurationDriftCheck`, and `ConfigurationDriftFinding` as provider-neutral data shapes.
Together they separate reviewed desired configuration, bounded current-state evidence, one
comparison result, and its resource or field differences. Terraform plan output is one possible
`source_kind`; Azure Policy, GitOps manifests, and Kubernetes desired state can produce the same
semantic records without adding provider branches to core.

The links preserve baseline-to-check, check-to-evidence, check-to-finding, and finding-to-resource
direction. A `CausalHypothesis` may attempt to explain a drift finding, but the link never proves
that an operator, deployment, or provider caused it. Raw plans and values remain in governed
evidence storage. Ontology records retain bounded summaries and digests, require redaction
metadata, and set `execution_authority` explicitly. These declarations are vocabulary data only:
no runtime projector, scheduled detector, remediation proposal, approval, or execution path is
added by the catalog change.

### Diagnostic knowledge projection

The SREGym absorption ledger projects 61 reviewed diagnostic mechanisms into
`DiagnosticMechanism`. Seven independent validation axes create 427 content-addressed
`BenchmarkValidation` receipts. Each receipt keeps its source revisions, result, validation kind,
available evidence summary, and canonical digest. Catalog refreshes append new receipts instead of
rewriting prior validation history, and rejected mechanisms remain explicit negative knowledge.

Live Kubernetes evaluation projects `DiagnosticEvidence` and hold-only `DiagnosticFinding`
objects before control-loop judgment. Every finding is bound to an exact `derive` function release,
Heimdall caller, canonical input and output digests, and content-addressed invocation identity.
Current topology uses cluster-scoped resource identities derived from the selected kubeconfig API
server and certificate authority. Complete observations replace current relationships, incomplete
observations withdraw unsupported relationships without deleting resource objects, and unavailable
inventory leaves the prior projection untouched. None of these objects grants action, approval,
promotion, or execution authority.

### Pod telemetry competency foundation

M5 reuses `Resource` for Kubernetes Pod, Service, and Endpoints instances and reuses `Observation`
for bounded metric samples. The physical `observation_targets_resource` LinkType records
`Observation -> Resource`; existing `kubernetes_selects` and `kubernetes_exposes_endpoints` links
cover the Pod, Service, and Endpoints topology. No `TelemetryChain` ObjectType is introduced.

The read-only evaluator consumes one purpose-scoped secured ObjectSet result plus immutable
`StateFactMetadata` for every relationship and sample. It reports each required segment as
`verified`, `unverified`, `stale`, or `missing`, along with evidence references and an exact
completeness fraction. A missing relation is reported as `missing` only when the secured graph
receipt proves complete coverage. Truncated graphs, cycles, ambiguous paths, synthetic samples,
partial state, conflicts, stale samples, and wrong-cluster identities remain unverified or missing.
The result always records `claimed_health: false` and `execution_authority: false`.

This slice is a platform foundation only. It does not register a runtime FunctionType, call a
Kubernetes or provider adapter, join Finding or Forecast objects, alter composition, or feed an
authority-bearing decision path.

## Design at a glance

The operating ontology connects four questions that the current resource-centered graph cannot
answer as one deterministic path: what the organization operates, what good means, what is
happening now or may happen next, and whether an intervention produced the intended effect. It is
the common language for reliability, architecture review, predictive cost governance, and
operational learning.

```mermaid
flowchart LR
    BC[BusinessCapability] -->|delivered_by| BS[BusinessService]
    BS -->|implemented_by| W[Workload]
    W -->|runs_on| R[Resource]
    W -->|depends_on| W2[Workload]
    BS -->|governed_by| O[Operational objectives]
    S[Signal] -->|observes| R
    F[Forecast] -->|predicts_breach_of| O
    C[Change] -->|affects| W
    D[DecisionCase] -->|protects| O
    D -->|considers| AO[ActionOption]
    AO -->|expects| EE[ExpectedEffect]
    AO -->|executed_as| AR[ActionRun]
    AR -->|resulted_in| OO[ObservedOutcome]
    OO -->|learned_as| P[Pattern]
```

## Domain stance

FDAI is not domain-agnostic. It is a cloud-operations control plane with a stable domain model.
The boundaries are:

| Boundary | Upstream position |
|----------|-------------------|
| Cloud operations meaning | Specialized and stable across deployments. |
| Cloud provider | Neutral contracts, with Azure as the implemented provider. |
| Customer organization | Generic types and links only; no customer instances or values. |
| Business semantics | Stable concepts upstream, deployment-specific mappings and values downstream. |
| Autonomy | Governed by policy, risk, approval, execution, and audit contracts outside the graph. |

This distinction prevents two failure modes. A provider-specific model would make every operating
concept an Azure resource property. A fully domain-agnostic model would push service, reliability,
cost, and architecture meaning into untyped property bags that agents cannot share reliably.

## Semantic layers

### Operating scope

These objects answer what is operated and why it matters.

| ObjectType | Purpose |
|------------|---------|
| `BusinessCapability` | A generic business outcome delivered by one or more services. |
| `BusinessService` | Stable identity used for ownership, criticality, objectives, and impact. |
| `Workload` | A deployable or operable unit that implements a service. |
| `Resource` | An observed cloud resource, retained from the existing ontology. |
| `Environment` | A governed lifecycle scope such as production or non-production. |

`BusinessCapability` is optional for an initial SRE deployment. `BusinessService`, `Workload`, and
their resource mappings form the minimum operational spine. An unmapped resource remains visible
as `unknown_service`; it is never silently assigned to a synthetic service.

### Operating intent

These objects define the conditions FDAI should preserve.

| ObjectType | Purpose |
|------------|---------|
| `ServiceObjective` | Availability, latency, correctness, or freshness target with an SLI and window. |
| `RecoveryObjective` | RTO and RPO target for a service or workload. |
| `CostObjective` | Budget, run-rate, unit-cost, or variance target with currency and period. |
| `ArchitectureConstraint` | Reviewed architecture condition used by ARB and change assurance. |
| `Ownership` | Accountable operating owner and escalation reference. |
| `ChangeWindow` | Reviewed maintenance, freeze, quiet, or emergency interval for a bounded scope. |

An objective is not a free-form metric label. It records its kind, unit, target or range,
measurement source, scope, owner, effective interval, and evidence freshness policy.

### Operating reality

Existing `Signal`, `Finding`, and `Incident` objects remain. The shared model adds explicit time
and prediction concepts instead of placing them only in a finding's open `context` bag.

| ObjectType | Purpose |
|------------|---------|
| `Observation` | A normalized measured value and evidence reference at an event-time cutoff. |
| `Change` | A planned, proposed, active, drift-observed, or completed change with intent, desired-state evidence, affected scope, and provenance. |
| `Forecast` | A versioned projection with horizon, interval, confidence, and feature cutoff. |
| `Experiment` | A bounded chaos or validation activity that may intervene in an observed episode. |

### Decision and learning

These objects make the complete intervention trace queryable without treating model prose as
authority.

| ObjectType | Purpose |
|------------|---------|
| `DecisionCase` | Immutable context with objectives, constraints, evidence, and no-action baseline. |
| `ActionOption` | One considered response, including a hold or no-op option. |
| `ExpectedEffect` | Predicted metric range, observation window, uncertainty, and predictor version. |
| `ActionRun` | The existing execution identity and terminal receipt. |
| `ObservedOutcome` | Observed effect, rollback, SLO recovery, recurrence, and scoring status. |
| `Pattern` | A reviewed generic mechanism supported by a balanced case cohort. |

`DecisionCase` does not replace the RiskGate decision or the audit record. It is the immutable
semantic input that lets Forseti, Odin, Var, Saga, and replay consumers refer to the same facts.

## Relationship contract

The initial relationship set should stay small and query-driven.

| LinkType | Endpoints | Meaning |
|----------|-----------|---------|
| `delivered_by` | BusinessCapability -> BusinessService | Services that deliver a capability. |
| `implemented_by` | BusinessService -> Workload | Workloads that implement a service. |
| `runs_on` | Workload -> Resource | Runtime placement without changing resource ownership. |
| `depends_on` | Workload/Resource -> Workload/Resource | Dependency required for correct operation. |
| `contains` | Resource -> Resource | Containing parent to contained child; traversal never reverses stored ownership. |
| `attached_to` | Resource -> Resource | Attached resource to its anchor; a query may traverse the inverse without rewriting storage. |
| `routes_to` | Resource -> Resource | Directed observed forwarding or next-hop reference; absence proves nothing about reachability. |
| `peered_with` | Resource -> Resource | Symmetric peer represented by two independently supported directed records. |
| `governed_by` | Service/Workload -> Objective/Constraint | Intent that applies to the target. |
| `owned_by` | Service/Workload/Objective -> Ownership | Accountable operating owner. |
| `observes` | Observation/Signal -> Service/Workload/Resource | Target of measured evidence. |
| `observation_targets_resource` | Observation -> Resource | Physical measured-evidence target used by bounded telemetry verification. |
| `affects` | Change/Incident/Experiment -> Service/Workload/Resource | Scope influenced by an episode. |
| `predicts_breach_of` | Forecast -> Objective | Objective at risk within the declared horizon. |
| `considers` | DecisionCase -> ActionOption | Bounded alternatives evaluated together. |
| `protects` | DecisionCase/ActionOption -> Objective | Objective the decision seeks to preserve. |
| `expects` | ActionOption -> ExpectedEffect | Predicted effect before execution. |
| `executed_as` | ActionOption -> ActionRun | Governed execution of the selected option. |
| `resulted_in` | ActionRun -> ObservedOutcome | Independent effect closure. |
| `learned_as` | ObservedOutcome -> Pattern | Reviewed learning projection, never direct promotion. |
| `change_targets_resource` | Change -> Resource | Direct managed-resource target of the change. |
| `case_evaluates_change` | DecisionCase -> Change | Immutable decision context that evaluates the change revision. |
| `change_instantiates_process` | Change -> Process | Durable Workflow journal for a multi-step change. |
| `change_bounded_by_envelope` | Change -> ImpactEnvelope | Approved impact upper bound, without execution authority. |
| `change_scheduled_in_window` | Change -> ChangeWindow | Effective maintenance, freeze, quiet, or emergency window. |
| `change_conflicts_with_change` | Change -> Change | Overlapping target, objective, or effective-time conflict. |
| `change_resulted_in_outcome` | Change -> ObservedOutcome | Independent post-change effect closure. |
| `change_recovered_by_plan` | Change -> RecoveryPlan | Prepared or applied version-pinned recovery path. |

Cardinality, causal direction, temporal ordering, and allowed endpoint combinations belong in each
LinkType declaration. A relation that cannot support a required competency question should not be
added for visualization alone.

The current LinkType schema has one source and one target type per declaration. Conceptual union
links therefore compile to explicit physical names such as `workload_runs_on`,
`workload_depends_on`, `service_has_service_objective`, `service_has_recovery_objective`,
`service_has_cost_objective`, `service_has_architecture_constraint`, `service_owned_by`,
`workload_owned_by`, and `objective_owned_by`. This keeps endpoint validation deterministic.

## Identity and time

Operational meaning changes over time. Decision-critical objects therefore carry both when a fact
was true or observed and when FDAI recorded it.

- **Stable identity:** Service and workload ids survive resource replacement and deployment.
- **Effective time:** Objectives, ownership, budgets, and constraints carry `effective_from` and
  optional `effective_to`.
- **Event time:** Observations, changes, forecasts, incidents, and outcomes carry source time and
  an evidence cutoff.
- **Recorded time:** Every projection records when FDAI accepted it and the source revision.
- **Immutable decision context:** A late fact never rewrites the context a historical decision
  used. The decision context is content-addressed and pinned at its cutoff, so a later observation
  produces a new context instead of editing the recorded one.
- **Current-state instance store:** The instance graph holds current observed state under one
  writer per subgraph. It is not a bitemporal store: an update replaces the prior property values
  and a disappeared object is deleted by its owning projection. Historical instance values live in
  the authoritative source generation that produced them, not in the instance graph.
- **Freshness:** Every decision context records freshness per source. One fresh source cannot hide
  a stale objective, topology edge, or cost observation.

Decision-relevant state facts use one immutable metadata shape across four authority-separated
lanes: `observed`, `derived`, `desired`, and `execution`. The metadata pins authority class, source
identity and revision, effective and recorded time, evidence cutoff, freshness ceiling,
completeness, synthetic status, conflicts, and immutable evidence references. Lane-authority
validation prevents a provider observation from being decoded as a derived fact or the reverse.
Inventory links can carry the same state-fact envelope plus independent verification identity.
New verified links also carry a trusted verification method and immutable receipt, and the verifier
identity must differ from the observation source. Legacy links without metadata remain valid during
additive adoption and never claim verification. Their absence lowers authority only for a query
profile that explicitly requires verified links.

Replay resolves the pinned catalog release and the retained decision context, not an arbitrary past
state of the instance graph. Recomputing a context identity proves equivalence; reconstructing the
original content requires that context to have been retained. Current-state queries use the latest
valid revisions that pass freshness checks.

## Sources of truth

The ontology does not collapse independent authorities into one mutable graph.

Execution authorization adds capability, requirement, policy-assignment, execution-profile,
provider-mapping, observation, grant, and decision objects to the semantic graph. These objects
make the decision explainable and replayable, but the graph never grants access. Scoped policy,
deployment identity bindings, provider evidence, and the risk gate remain independent authorities.
See [Execution Authorization Ontology](../decisioning/execution-authorization-ontology.md).

| Fact | Authority | Ontology role |
|------|-----------|---------------|
| Type, link, action, and rule definitions | Git catalog-as-code | Versioned schema and meaning. |
| Service and workload mapping | Deployment service catalog or approved manifest | Runtime projection with provenance. |
| Resource topology | Injected `Inventory` provider | Fresh resource and dependency projection. |
| Objectives, budgets, constraints, ownership | Approved systems and fork configuration | Effective-time intent projection. |
| Telemetry and cost observations | Configured evidence providers | Event-time observations with source refs. |
| Decisions, approvals, actions, rollback | Append-only audit and Process journal | Immutable semantic links. |
| Cases and patterns | Case history plus reviewed catalogs | Learning projection and governed reuse. |

Each ObjectType declares one owning agent, one authority class, a freshness policy, retention, and
allowed purposes. Conflicting sources produce an explicit conflict or `unknown` state and lower
autonomy.

## Agent ownership

The ontology makes the fixed pantheon more capable without adding a central coordinator.

| Agent | Owned semantic write |
|-------|----------------------|
| Huginn | Normalized observations and discovered topology change events. |
| Heimdall | Findings, forecasts, and independent effect observations. |
| Njord | Cost observations, cost forecasts, and cost objective status. |
| Freyr | Demand, capacity forecasts, and sizing options. |
| Loki | Experiments and resilience evidence. |
| Forseti | Decision cases and governed decisions. |
| Odin | Cross-objective arbitration decisions and score breakdowns. |
| Var | Independent approval records. |
| Thor | Action runs and attempts. |
| Vidar | Rollback and recovery outcomes. |
| Saga | Audit evidence and immutable correlation links. |
| Muninn | Time-consistent context snapshots and case revisions. |
| Norns | Patterns and inert candidates. |
| Mimir | Reviewed ontology, rule, and action catalog lifecycle. |
| Bragi | No decision write; localized explanation over cited projections only. |

Agents collaborate through typed events. No agent mutates another agent's object, calls another
agent directly, or shares mutable workflow state.

## Operational context and decisions

Muninn materializes an immutable `OperationalContextSnapshot` for each decision cutoff. It is a
projection contract, not a new authority. At minimum it includes:

- target service, workload, resource, environment, and dependency neighborhood;
- active service, recovery, cost, and architecture objectives;
- ownership and escalation references;
- active changes, experiments, incidents, and maintenance windows;
- current observations and bounded forecasts;
- source freshness, provenance, unresolved conflicts, and catalog versions.

The snapshot keeps replay lineage without widening the data surface. For every reachable context
object, it records the object id, type, revision, effective interval, allowlisted provenance refs,
and one deterministic shortest typed path from the target resource. It also retains each source's
observation time and accepted maximum age. The snapshot identity covers those revisions, paths,
effective intervals, provenance refs, freshness receipts, stale-source results, and conflicts, so a
topology, revision, validity, provenance, or freshness change cannot reuse the prior identity. Raw
object properties remain in their authoritative provider and are not copied into the snapshot.
Snapshot time is normalized to canonical UTC. The identity also covers trusted recorded time,
trusted clock identity, and whether the query required verified links. Historical replay supplies
the retained recorded time instead of sampling a new wall clock.

Typed link observation metadata is the exception to dropping raw link properties: the materializer
retains only its canonical verification envelope on each evidence link and includes that envelope
in both link and path identity. A stale, incomplete, conflicting, synthetic, after-cutoff, or
unverified link adds an explicit context conflict and can only lower the snapshot ceiling to
`SHADOW_ONLY`. Healthy metadata does not raise a ceiling, and absent metadata preserves legacy
decoding without claiming verification unless the query profile requires verified links. A
reachable object that declares a freshness policy requires a matching source-freshness receipt;
missing receipts lower the ceiling to `SHADOW_ONLY`. A decision cutoff or evidence timestamp beyond
trusted recorded time plus the configured clock-skew allowance also lowers the ceiling.

Materialization includes an object only when `effective_from <= cutoff` and either
`effective_to` is absent or `cutoff < effective_to`. Objects outside that half-open interval are
retained as typed temporal exclusions for replay, but not used as current decision facts.
`context_temporal_exclusion` lowers the autonomy ceiling to `SHADOW_ONLY` so an expired or future
mapping cannot preserve automatic execution authority. The provenance allowlist is limited to
`source_ref`, `measurement_source_ref`, and `expression_ref`.

A bounded traversal that reaches its node limit is incomplete evidence. Materialization records
`context_graph_truncated` as a conflict and lowers the autonomy ceiling to `SHADOW_ONLY`; a partial
graph never preserves automatic execution authority.

An `OperationalEvidenceBundle` foundation can combine graph and document evidence without
flattening their authority. It is not wired into runtime composition, Forseti decision-case
construction, or the production prompt path. Production autonomy continues to use the existing
operational-context snapshot and ordinary policy, risk, approval, execution, and audit gates. Its
four immutable lanes retain verified source receipts independently:

- **Ontology evidence:** Secured typed facts and closed, acyclic deterministic paths from the
  operational graph. The preferred input is a secured ObjectSet snapshot receipt; every nested
  link is checked for verification, freshness, completeness, conflicts, and synthetic status.
- **State evidence:** The original observed, derived, desired, or execution `StateFactMetadata`.
- **Catalog evidence:** Exact rule or catalog references from reviewed catalog-as-code.
- **Document evidence:** Governed excerpts stored as untrusted data with no instruction authority.

Before admission, each lane item has a canonical payload that includes its evidence ref and exact
lane content but excludes the source envelope to avoid a digest cycle. The verified source receipt
binds that payload digest, the lane, and canonical source-supplied membership or inclusion
evidence. Admission recomputes the digest and rejects an excerpt, graph path, or state fact changed
under the same receipt. An injected receipt validator receives the receipt, lane, item digest,
canonical payload, and lane-specific membership evidence so it can verify the source's inclusion
proof rather than only the receipt reference. For state evidence, freshness ceiling, completeness,
synthetic status, and conflicts must exactly match `StateFactMetadata`, and the bundle evaluates
those metadata fields directly when deriving holds.

Every exact claim stores canonical JSON, a subject, predicate, typed effective/evidence/recorded
scope, and citation bindings containing the evidence ref, item digest, and source revision. The
citation manifest is derived only from included evidence, so an omitted, fabricated, or
revision-mismatched citation produces an explicit missing path and hold. Duplicate claims are
rejected. Contradiction detection compares claims with the same subject, predicate, effective
interval, and evidence cutoff, and reports a conflict only when their canonical typed values
differ. Recorded time remains in each immutable claim identity but doesn't split a contradiction
group, and it never implies supersession. The foundation has no implicit latest-wins rule; a future
supersession policy would require an explicit reviewed claim relationship. The detector doesn't
infer semantic disagreement from prose. Candidate and diagnostic counts and field lengths are
bounded, nested sequences are copied to immutable tuples, and `max_bytes` applies to the final
canonical body including its manifest, omissions, conflicts, and hold data. Stale, incomplete,
conflicting, synthetic, after-cutoff, after-trusted-recorded-time, uncited, or truncated evidence
lowers the result to `SHADOW_ONLY`; healthy evidence never raises the caller's input ceiling.
Document prompt rendering places excerpts only in an escaped, delimited JSON data block. These
tests establish a safe foundation but don't prove production wiring. The bundle remains read-only
evidence and never grants approval or action authority.

Forseti creates a `DecisionCase` from that snapshot. Each case contains the no-action baseline,
bounded options, expected effects, protected objectives, violated constraints, uncertainty, and
evidence references. Odin arbitrates only when eligible options conflict across objectives. Var
receives the same case when human approval is required, and Saga records its digest for replay.

Production startup reads `FDAI_OPERATING_MODEL_PATH` through the provider boundary, validates the
complete object/link snapshot, and atomically replaces the provider-owned subgraph. A monotonic
`applying` manifest retains the union of prior and current owned identities for stale deletion and
crash recovery. After replacement succeeds, the `projected` manifest compacts to current ownership
so historical revisions cannot exceed the configured model bounds. Startup cleans an interrupted
`applying` union before it stages another snapshot, preventing repeated crashes from accumulating
ownership across revisions. The optional
`FDAI_OPERATING_MODEL_MAX_BYTES` ceiling defaults to 16 MiB. `GET /ontology/graph` exposes only the
projection status, source revision, and aggregate counts, never deployment instance properties.

The promoted inventory projection validates every resource and link record before graph projection.
Malformed identities, properties, or observation timestamps fail the attempt, and conflicting
duplicate links are rejected instead of being interpreted as complete absence. If promoted
observation accumulation is incomplete, the runtime preserves the prior graph and ownership
manifest and records the new attempt as `unavailable`; only a complete projection can replace the
owned resource subgraph.

Cost and capacity specialist event-time travels with their advice. Forseti materializes one
time-consistent snapshot, builds the shared case, and includes it in the arbitration request. Odin's
resolved choice returns through Forseti as a verdict, and Thor's durable `ActionRun` plus Var's HIL
ticket preserve the bounded baseline, option effects, constraints, and evidence. Thor requires the
verdict action to match the selected option exactly. Missing, malformed, or mismatched case evidence
is denied rather than creating approval or execution authority.

## Continuous operating loops

"Living agents" means event-driven and time-driven control loops that close effects. It does not
mean an LLM runs continuously or gains implicit authority.

### Reliability loop

`Observation -> Finding/Forecast -> DecisionCase -> ActionRun -> ObservedOutcome -> objective`

The loop prioritizes service-objective and error-budget risk, not isolated resource utilization.

### Architecture review loop

`Change -> graph diff -> ChangeWindow/Constraint/Objective evaluation -> DecisionCase -> ImpactEnvelope -> approval -> Process/ActionRun -> ObservedOutcome/RecoveryPlan`

The Assurance Twin simulates the proposed graph as a read-only branch. A review can approve,
condition, reject, or hold the change, but it cannot enable an `ActionType` or bypass execution
checks. A `Workflow` and its durable `Process` journal multi-step work; every mutation step still
re-enters the typed ActionType, risk, approval, Thor execution, Heimdall verification, and Vidar
recovery boundaries.

### Predictive cost loop

`Cost observation -> CostObjective/Forecast -> options -> reliability guard -> outcome settlement`

Cost optimization is valid only when the selected option preserves service and recovery
objectives. Estimated savings remain predictions until an observed outcome closes the settlement
window.

### Outcome learning loop

Huginn normalizes the bounded `case_history.operational_case.v1` event. Muninn requires the O1
case-history materializer, seals the strict input, and durably retains at most 100 immutable cases
per failure fingerprint before publishing `operational_case_fingerprint_cohort` context. Norns
requires one failure fingerprint and ActionType, at least one verified reusable success, and at
least one failure, refusal, no-op, rollback, or recurrence control before it emits an inert
candidate through its existing consensus and rate limits. Every candidate cites case id, revision,
manifest digest, resource type, fingerprint, per-outcome counts, and digest evidence. A raw
`measurement.action_outcome.v1` remains telemetry with insufficient mechanism evidence and cannot
enter a promotable cohort.

## Extension model

The ontology grows in four controlled layers:

1. **Operating kernel:** Upstream ObjectTypes and LinkTypes shared by all deployments.
2. **Vertical packs:** Upstream reliability, architecture review, and cost-governance profiles.
3. **Fork extensions:** Reviewed industry or organization-specific types, links, objectives, and
   adapters that conform to the kernel.
4. **Deployment instances:** Customer service mappings, objectives, budgets, owners, resources,
   and evidence that remain outside upstream source control.

Extensions can add meaning but cannot redefine kernel identities, weaken cardinality, replace an
owning agent, or raise autonomy. Unknown observed types open a governed proposal instead of
self-registering. Breaking schema changes use semantic versioning, migration fixtures, a
deprecation window, and replay tests.

## Competency questions

Ontology quality is measured by deterministic questions, not by object count. Version 1 should
answer these questions with evidence and explicit unknowns:

1. Which business services and objectives can this resource change affect?
2. Which services may breach an objective within the configured horizon, and why?
3. Which active change or experiment can explain the current service degradation?
4. Which response options preserve reliability and recovery objectives within the cost envelope?
5. What happens if FDAI takes no action?
6. Why did Odin prefer one objective, and how close was the alternative?
7. Did the selected action produce its expected effect without guard-metric regression?
8. Is the prior case reusable under the current topology, objectives, and policy versions?
9. Which evidence-backed network segments connect two resources, and which segment is stale,
   unverified, missing, cyclic, or outside the query bound?
10. Is a Pod's telemetry path complete and current across its Service, Endpoints, and Observation
  evidence without inferring health from a missing sample?

Each question becomes a versioned query fixture with positive, negative, stale, conflicting, and
unknown cases. A new type or link is justified by a failing fixture, then retained by regression.

## Delivery plan

| Wave | Deliverable | Exit criteria |
|------|-------------|---------------|
| O0 - Constitution | This authority, competency fixtures, identity/time rules, and ownership matrix. | Terms, authorities, unknown handling, and extension boundaries are agreed before schema work. |
| O1 - Semantic spine | Implemented: catalog declarations and deterministic query fixtures. | Loader, provenance, cardinality, versioning, and query tests pass with no catalog-owned runtime writer. |
| O2 - Context projection | Implemented: immutable `OperationalContextSnapshot`, materializer, runtime store sharing, and Forseti ceiling. | Fresh context preserves authority; stale, conflicting, and unmapped context lowers auto to human approval. |
| O3 - Reliability loop | Implemented core: objective-aware decision case, option selection, and `ResponseOutcome` closure. | Frozen tests traverse service -> objective -> option -> action -> effect with one correlation. |
| O4 - ARB and cost loops | Implemented core: architecture-constraint exclusion, typed change lifecycle declarations, and protected-objective cost tradeoff. | Change and cost options cannot trade away protected reliability objectives or derive authority from the graph. |
| O5 - Governed learning | Implemented through operational-learning O2: strict Huginn case events, Muninn fingerprint cohorts, and balanced inert Norns candidates. Mimir catalog behavior is unchanged. | Success-only and raw-response cohorts are held; candidates cite immutable revisions; no outcome edits a live catalog declaration directly. |

The first code slice after O0 should add only the semantic-spine declarations, link constraints,
and query fixtures. Runtime writers, decision changes, and execution behavior belong to later,
separately validated slices.

## Verification matrix

| Concern | Required proof |
|---------|----------------|
| Meaning | Decision-critical fields are typed or reference a typed objective; open bags are not authority. |
| Provenance | Every instance names source, revision, effective/event time, recorded time, and freshness. |
| Unknown safety | Missing mapping, stale topology, or conflicting objective lowers autonomy and stays visible. |
| Ownership | Each object has one owning agent; all cross-agent collaboration uses typed events. |
| Replay | Historical decisions resolve the same snapshot, versions, options, and score breakdown. |
| Effect closure | Every executed option reaches a scored or explicitly unscorable outcome. |
| Extension safety | Fork additions cannot redefine kernel semantics or raise execution authority. |
| Customer isolation | Upstream fixtures use synthetic values and contain no deployment instances. |
| Network evidence | Every segment preserves stored direction and evidence state; unilateral peering, missing endpoints, cycles, and traversal limits never become reachability claims. |
| Pod telemetry | Complete, missing-selector, stale, synthetic, wrong-cluster, bounded-cycle, and missing-observation fixtures preserve segment status and never claim health. |

## Related docs

| To learn about | Read |
|----------------|------|
| Declaration kinds, operational lenses, state, and context boundaries | [Operating Ontology Metamodel](operating-ontology-metamodel.md) |
| Current resource, rule, signal, and finding foundation | [LLM strategy](llm-strategy.md#ontology-foundation) |
| Runtime ontology storage | [Rule lookup ontology storage](rule-lookup-ontology-storage.md) |
| Action safety contract | [Action ontology](../decisioning/action-ontology.md) |
| Agent roles and arbitration | [Agent pantheon](../agents/agent-pantheon.md) |
| Forecast and response outcome closure | [Observability and detection](../rules-and-detection/observability-and-detection.md) |
| Operational case reuse | [Operational learning ontology](../rules-and-detection/operational-learning-ontology.md) |
| Read-only graph simulation | [Assurance Twin](../operations/assurance-twin.md) |
