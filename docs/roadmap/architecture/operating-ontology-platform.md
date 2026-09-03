---
title: FDAI Ontology Safety Infrastructure
---
# FDAI Ontology Safety Infrastructure

This document extends the operating ontology into a typed infrastructure layer for FDAI's agents. It adds object polymorphism,
bounded object sets, semantic action effects, typed functions, authority-aware writeback, exact schema pinning, and generated SDK surfaces. Agents still own every runtime transition; these primitives constrain their inputs, plans, and effect verification.

> **Authority boundary:** Observed provider state remains a projection. An action can request a provider, Git, ledger, or FDAI-owned state change, but it cannot make an external fact true by
> editing the ontology graph.
>
> **Safety boundary:** Functions plan, query, derive, or validate. Only Thor executes an approved
> `MutationPlan`, and every external effect closes through independent reconciliation.
>
## Declaration workbench product boundary

The workbench uses object-centric inspection to connect an exact declaration to properties,
directional relationships, actions, dependents, evidence health, impact, and release compatibility.
`/ontology` registry search and Catalog topology remain the broad exploration surfaces. It excludes
visual schema editing, arbitrary release upload, raw instance tables, personalization, and kernel
icon metadata. Changes remain catalog-as-code pull requests; the Console never calculates
redaction, compatibility, completeness, or authority.

## Operational competency gates

The workbench is complete only when it answers these bounded operational questions honestly:

| Competency | Operator question | Required projection evidence |
|------------|-------------------|------------------------------|
| C1 - Identity and access | What exact declaration is this, and what may this principal see? | Release digest, declaration version and provenance, role/purpose filtering, and redaction reasons. |
| C2 - Relationships | How does this type connect to other types? | Recorded incoming, outgoing, or self direction, cardinality, causal/temporal flags, and provenance. |
| C3 - Dependents | Which catalog declarations depend on this type? | Deterministic topology references, a result bound, and explicit truncation. |
| C4 - Impact scope | Which active Resources are reachable from this exact target? | Active snapshot generation and cutoff, stored direction, depth/edge bounds, completeness, and edge verification state. |
| C5 - Evidence health | Is runtime evidence available, current, complete, conflicting, or synthetic? | Sanitized source alias, generation, cutoffs, freshness, conflicts, drop reasons, and nullable counts when unavailable. |
| C6 - Governed actions | Which actions are semantically bound to this declaration? | Exact ObjectType or InterfaceType target evidence and the complete ActionType safety contract, with no execute control. |
| C7 - Change safety | What changed between two retained releases? | Exact release digests, declaration-ref additions/changes/removals, compatibility verdict, migration requirement, and deterministic diff digest. |
## Catalog-owned instance projection

Core runtime startup now projects Rule, PolicyArtifact, ResourceClass, ResourceType, SignalType,
Property, and ActionType instances into one catalog-owned subgraph. Its taxonomy slice retains 11
classes, 77 memberships, and 11 bounded specialization links over all 77 neutral ResourceTypes.
The pure builder rejects semantic or identity defects; atomic identical replay remains a no-op.

The canonical release also declares `ControlObjective`, `RuleObjectiveBinding`, and
`EquivalenceValidationReceipt`, with `objective_bound_by`, `binding_targets_rule`, and
`binding_validated_by` relationships. Catalog loaders verify exact objective, Rule, policy
implementation, and required-evidence signatures before accepting a binding. These declarations
and candidate records are release vocabulary only: the current startup projector does not
materialize them into the runtime subgraph, and no semantic query, binding, or receipt grants
policy, promotion, approval, or execution authority. Deterministic equivalence execution and
reviewed receipt issuance remain separate delivery work.

This projection makes catalog relationships queryable but doesn't change their authority. Git
catalog-as-code remains authoritative, and the instance graph remains a read model. If OPA or the
ontology store is unavailable in an optional local profile, projection remains unavailable rather
than substituting synthetic state. Deployed profiles continue to require OPA for T0 evaluation.

An issued secured ObjectSet receipt has two distinct downstream uses. Decision, promotion, and
effect paths still require a current independently verified decision-evidence admission. A
`Bragi` `operations-review` query function can instead reuse the exact process-issued result for
read-only presentation after role, purpose, release, receipt, and materialization scope match. This
path cannot grant execution or promotion authority and cannot be selected by another agent or
purpose.

The independently scheduled inventory process checks each mapped ResourceType target against the
current instance graph before it builds classification links. A target absent during rolling
catalog startup becomes the stable non-blocking drop `unseeded_resource_type`; the authoritative
Resource objects and other verified links in the complete generation still replace the owned
subgraph. A present endpoint with the wrong type and every other instance validation error continue
to fail the generation.

The reviewed `unclassified-resource` target is the only exception to provider-specific type
mapping. It is catalog-owned, carries no provider mapping or query terms, and receives a
classification link only after the complete provider identity set reconciles with the final-fence
coverage receipt. Runtime discovery never creates a new ResourceType declaration.

The shared property-semantics registry gives every canonical property one content-addressed
identity for meaning, unit, value kind, and bounds. Catalog projection validates each reference
against that registry and preserves finite numeric values without float coercion, so services and
replays cannot silently reinterpret the same property.

Adaptive causal discrimination consumes an exact hypothesis frame, ontology graph revision, and
evidence cutoff. It ranks only pre-verified read-only observation candidates by how many competing
hypothesis pairs they separate. Selection and revision receipts remain evidence records: they do
not create ontology facts, modify the graph, or grant query, approval, promotion, or execution
authority.

## Pod telemetry path runtime

`evaluate_pod_telemetry_path` is a pure A0 read over a `SecuredObjectSetQueryResult` and an immutable
mapping of state-evidence subjects to `StateFactMetadata`. It follows only the reviewed physical
links `kubernetes_selects`, `kubernetes_exposes_endpoints`, and
`observation_targets_resource`. Traversal is already bounded and purpose checked by the secured
ObjectSet gateway; the evaluator performs no provider, Kubernetes, network, registry, or store I/O.

The result contains four ordered segments: Pod selected by Service, Service exposing Endpoints,
Observation targeting the Pod, and the Observation sample. Segment evidence is verified only when
its state fact is complete, current at the supplied cutoff, non-synthetic, and conflict free.
The Pod, selected Service, and exposed Endpoints must all carry identities in the expected cluster
scope; a cross-cluster Service or Endpoints record makes the affected segment unverified even when
its relationship evidence is otherwise current and complete.
Incomplete graph receipts cannot prove absence, so unresolved segments remain `unverified` rather
than becoming `missing`. The exact secured graph receipt digest and all retained evidence refs are
returned for replay.

The delivery layer now includes a pure candidate projector for reviewed Service label-selector and
same-name Endpoints relationships. It emits no active graph link on partial input, missing targets,
or duplicate candidates. A separate complete-generation verifier must attach immutable observation
metadata before inventory projection can expose either relationship. Production Kubernetes
inventory binding and retained composition receipts remain open.

Focused production-composition checks use an exact-release Interface that spans Resource and
Observation evidence, then invoke the issued Pod function through its secured dependency digest.
They prove that complete evidence returns four verified segments and that a synthetic sample stays
unverified with `claimed_health: false` and `execution_authority: false`.

The source-derived FunctionType is part of the exact runtime release and is registered in the
production semantic function registry. Its wrapper accepts only a composition-issued secured
query result and derives typed relationship and sample state evidence from that graph. It does not
derive a health value, produce Finding or Forecast objects, grant action authority, or alter any
existing Kubernetes delivery module.

## Design at a glance

The infrastructure separates semantic declarations, authority-specific state, and agent-owned
kinetic execution. A graph write, function result, generated SDK call, or `MutationPlan` remains
proposal or context until the accountable agents complete judgment, authorization, execution, and
independent effect verification.

![Design at a glance. The main stages are Authority sources, ProjectionBinding, Observed object graph, ObjectSet query, Decision context, MutationPlan, Risk and approval, ActionRun, Provider, Git, ledger, or FDAI store, ReconciliationReceipt, ObservedOutcome.](../../diagrams/generated/fdai-roadmap-architecture-operating-ontology-platform-01.en.svg)

## Exact type identity

Every declaration belongs to one immutable `OntologyRelease`. Runtime records pin the exact
declaration that interpreted them:

```yaml
type_ref:
  name: Resource
  version: 2.1.0
  catalog_digest: sha256:<digest>
```

`Action`, `ActionRun`, ontology objects, ontology links, audit records, and generated plans retain
an exact reference. Compatibility checking returns `compatible`, `migration_required`, or
`incompatible`. A release cannot replace a declaration in place when existing records would be
reinterpreted.

Cross-service semantic records use `OntologyReleaseRef`, a compact envelope containing the
contract `schema_version` and exact release `digest` without copying the declaration set. Legacy
discovery and explanation records may omit the envelope while they migrate. Decision-critical
`evaluate` and `action_draft` consumers require it, and any supplied mismatch is rejected before
semantic-index or provider I/O.

## Proof-carrying semantic interpretation

Lexical matching, embeddings, and models can produce a `SemanticInterpretationCandidate`. The
candidate pins its target type, ontology release, semantic catalog, normalized arguments, input,
unresolved terms, source, and content digest, but it always has `candidate_only` authority.

A candidate becomes a `VerifiedSemanticPlan` only when every term is resolved, its target matches
the exact active release, its operation class matches a typed function or ActionType, and it cites
an exact catalog record, promoted language surface, or operator-confirmation turn. The verified
plan remains `execution_authority: false`. Query, derive, and validate plans can target only typed
functions; an action interpretation can create only an ActionType-bound draft that re-enters the
normal judgment, approval, execution, recovery, and audit path.

Candidate and plan arguments are stored as canonical JSON rather than mutable nested containers.
Verification recomputes candidate integrity before producing a plan. Exact-catalog verification
pins the catalog digest directly and requires it to match the active semantic catalog supplied by
composition. Promoted surfaces and operator confirmations require an injected evidence validator
for the immutable promotion or conversation-turn reference.

The Operator API declares `inventory.select_resources` as a read-only ontology query function.
Production semantic candidates and the `/ontology/graph` manifest use the same release digest and
function reference. A candidate from another release is rejected before provider I/O.
The semantic function registry also exposes an immutable name-to-authority snapshot after
composition. Query manifests and readiness receipts use that same registered set, while provider
functions remain below evidence-ready until a current bounded probe succeeds.

## Semantic interfaces and object sets

`OntologyInterfaceType` is distinct from the existing `ActionInterface` safety flags. A semantic
interface declares properties, required links, supported actions, and inherited interfaces.
Object types can implement multiple interfaces. Initial kernel interfaces are `Operable`,
`Ownable`, `Observable`, `ObjectiveBound`, `Recoverable`, and `CostBearing`.

An `ObjectSetDefinition` selects objects by concrete type or semantic interface. It supports typed
property predicates, named-link traversal, deterministic ordering, an `as_of` cutoff, freshness,
purpose, and a hard result limit. It does not accept free-form Cypher, SPARQL, SQL, or model text.
Every materialization records the release digest, cutoff, source watermarks, truncation reason,
and redaction summary.

The current instance-store contract has no historical observation API. The secured gateway
therefore accepts `as_of` only at the trusted evaluation cutoff, with an explicitly configured
skew of at most five seconds. It rejects past or future cutoffs outside that envelope as
unsupported and records `current_state_only`, the cutoff, and the accepted skew without claiming
historical completeness. Each secured receipt binds the exact ontology release, caller role,
singleton purpose, canonical projected-result digest, completeness and truncation state, and a
content-free redaction summary. Returned graph properties are recursively immutable, and the
semantic query boundary revalidates the result-receipt binding before use.

LinkType declarations do not yet define property ACLs. Secured projections consequently strip all
link properties and count the removed fields in the receipt. They preserve only the typed
endpoints and exact type reference. Redacted object aliases are allocated outside the complete
source identity set, and the projector validates unique object identities and visible-endpoint
closure before returning the graph.

Property predicates support `equals`, `not_equals`, `in`, `exists`, `absent`, `at_least`,
`at_most`, and `contains`. Single-value operators use `equals`, `in` uses a non-empty `values`
tuple, single-value operands cannot be null, and presence operators accept no operand. The store
receives only `equals` predicates for indexed pushdown. Both direct queries and traversals apply
every predicate again to the bounded candidate graph and remove links whose endpoints were
filtered out. Predicate operands are canonical JSON with finite numbers, at most 32 nesting
levels, and at most 64 KiB of encoded data.
One definition accepts at most 32 predicates, one `in` predicate accepts at most 1000 values, and
one traversal accepts at most 1000 roots and 64 named link types. Root ids without a traversal and
traversals without a named link type are rejected before store I/O.

Materialization distinguishes `result_limit`, `candidate_limit`, and `traversal_limit`. A
`candidate_limit` means memory filtering saw only the first 1000 store candidates, so an empty or
short result is incomplete evidence rather than a complete absence claim. A `traversal_limit`
means graph expansion reached its object ceiling. The in-memory and PostgreSQL stores both apply
the requested object limit to initial roots as well as reached objects.
Exact-id predicates use fixed batches of at most 128 ids through one indexed store query per batch.
The reader stops after it has enough matching objects to prove `result_limit`.

## Semantic actions and mutation plans

`ActionType` retains its stop conditions, rollback, impact scope, execution path, promotion gate,
and autonomy ceilings. Version 2 adds these semantic fields:

- **Target:** An exact ObjectType or InterfaceType reference plus one-or-set cardinality.
- **Parameters:** Primitive, enum, struct, object-reference, or object-set inputs with validation
  and redaction metadata.
- **Read set:** Object sets and properties required to plan and verify the action.
- **Submission criteria:** Deterministic criterion or `validate` function references.
- **Planner:** Declarative effect rules or one signed `plan` function.
- **Effects:** Expected internal writes, catalog pull requests, provider commands, notifications,
  or schedules.
- **Postconditions:** Independent observations that close the action outcome.
- **Transaction policy:** Internal atomicity or external saga semantics, lock scope, and maximum
  affected object count.

Planning produces an immutable `MutationPlan`. It contains exact target revisions, the computed
write set, commands, impact evidence, rollback or compensation steps, expected effects, and a
digest. Semantic plans preserve the signed planner FunctionType identity in `planner_ref` and bind
an upstream selected operational plan separately in `operational_plan_ref` when that lineage
exists. Approval and execution revalidate the digest and current revisions. A stale plan returns
to planning or human review and never executes with widened scope.

## Typed ontology functions

An `OntologyFunctionType` has one of four kinds:

| Kind | Output | Authority |
|------|--------|-----------|
| `query` | `ObjectSetDefinition` or bounded data | Read only. |
| `derive` | Typed scalar or struct | Read only. |
| `validate` | Typed criterion result with evidence | Can lower eligibility only. |
| `plan` | Immutable `MutationPlan` | Proposal only. |

Functions declare exact input and output schemas, read sets, determinism class, artifact digest,
publisher, resource ceilings, and network policy. A function never receives executor identity and
never invokes a provider mutation directly.

The registry keeps existing one-argument callbacks through an explicit adapter. A function that
needs authenticated read context registers separately and receives an immutable
`FunctionInvocationContext` with the exact authorized role and attenuated purpose. Arguments are
canonicalized for the input digest and deep-copied before callback execution, so nested callback
mutation cannot alter caller-owned input or invocation evidence.

Query-plan handlers fail closed without expanding the receipt contract. A stable `TypeError`,
`ValueError`, or `RuntimeError` produces a failed `capability_failed` receipt, and dependent nodes
remain skipped. The runtime emits `ontology_query_node_failed` with only the allowlisted
`node_kind` and `failure_type` fields. It doesn't record the exception text, arguments, node
identifier, provider payload, or operator data for these stable failures.

For a resource-scoped semantic read, the optional operational evidence source and authenticated
principal Context provider bind as one pair. Core admits the exact bundle and Context metadata
before Operator persistence and presentation. Any identity, evidence, graph, citation,
contradiction, or budget failure holds the response; the path adds no provider read or authority.

The diagnostic runtime registers 22 Kubernetes reducers as exact-release `derive` functions. Live
providers invoke the registry as Heimdall under the `diagnostic-evaluation` purpose and preserve
the canonical function arguments with each invocation receipt. The observer accepts a finding only
when the active release, caller, invocation identity, input digest, and output digest all match.
These receipts are read-only provenance; they do not turn a diagnostic function into an action.

The network competency runtime declares `query.network_path_segments` as an exact-release
deterministic `query` function. Its input is one purpose-bound `SecuredObjectSetQueryResult` plus
explicit source, target, evaluation time, depth, and segment ceilings. It never calls an inventory
provider. Registration requires a trusted `NetworkQueryReceiptVerifier` and an opaque
composition-owned verification context. The contextual callback checks that the receipt role,
singleton purpose, exact release, and result digest match `FunctionInvocationContext`, then asks the
verifier to authenticate the same tuple. Production ObjectSet handlers issue bounded receipts and
Function handlers resolve the exact dependency digest; self-minted receipts remain unavailable.
An omitted `evaluated_at` uses the issued receipt observation cutoff, while an explicit value must
equal it exactly. Link
effective, evidence, and recorded times stay at or before that cutoff, and freshness ceilings above
one year or overflowing timestamp arithmetic remain unverified. `attached_to` may be traversed
inversely for a query while retaining its stored direction, `contains` and `routes_to` follow stored
direction, and `peered_with` requires both directed records with distinct observation and
verification receipt lineage. Only a complete path whose every segment has fresh independent
verification reports `reachability_verified: true`; every other result uses `null`, never `false`.
An incomplete graph returns `query_incomplete`, and unrelated graph links don't consume the
network-segment limit.

## Authority-aware writeback and projection

Each ObjectType declares one authority class and write policy:

| Authority class | Examples | Write policy |
|-----------------|----------|--------------|
| `catalog_owned` | Rule, ActionType, policy | Reviewed Git pull request. |
| `fdai_owned` | Workflow draft, approval | Atomic state transaction plus outbox. |
| `provider_observed` | Cloud resource, topology | Provider command followed by independent observation. |
| `ledger_owned` | DecisionCase, ActionRun | Append only. |
| `derived` | Forecast, pattern projection | Owning-agent projection. |

For `provider_observed` objects, a successful API receipt is not a state update. Reconciliation
compares the intended effect with fresh evidence and emits a `ReconciliationReceipt` with
`matched`, `mismatched`, `timed_out`, or `unscorable`. Only the authoritative projection updates
observed state.

The reconciliation coordinator binds the exact release, ActionType, immutable plan, authenticated
observer context, and independently observed records before closing an attempt. A terminal outcome
and its proposal-only next-step event commit atomically; neither the receipt nor its outbox entry
updates provider-observed state or grants execution authority.

Authority comes from a trusted `AuthenticatedObservationContext` supplied separately from the
untrusted observation envelope. The context binds distinct observer, executor, and source
credential lineages to a signed, content-addressed verification receipt. Envelope authority claims
never grant authority. Every recommendation is proposal-only and carries `grants_authority: false`.

| Receipt status | Terminal | Proposal-only next step | Persistence |
|----------------|----------|-------------------------|-------------|
| `matched` | Yes | `close_matched` | Atomically commit terminal outcome and outbox recommendation. |
| `mismatched` | Yes | `request_vidar_recovery` | Atomically commit terminal outcome and outbox recommendation. |
| `timed_out` | Yes | `request_vidar_recovery` | Atomically commit terminal outcome and outbox recommendation. |
| `unscorable` | No | `hold_unscorable` | Record only the observation attempt; a later authenticated observation may retry the terminal identity. |

Observed inventory relationships may carry immutable state-fact and verification metadata. The
projection preserves that envelope without treating it as permission, suppresses relationship
claims for incomplete observations, and lets stale, synthetic, conflicting, or unverified evidence
lower downstream autonomy.

`ProjectionBinding` makes source-to-ontology mapping reviewable. It declares source identity,
type targets, identity and property mappings, watermark behavior, freshness, deletion semantics,
conflict policy, and batch limits. A source cannot silently overwrite another authority.

## Dynamic state and graph effects

The platform separates three layers that must not grant authority to one another:

| Layer | Question | Output authority |
|-------|----------|------------------|
| **Semantic** | What exists, what does it mean, and which relationships are valid? | Type, unit, identity, cardinality, and compatibility only. |
| **Kinetic** | What registered operation may change an exact target under which safety contract? | Proposal-only `MutationPlan`; judgment, approval, and execution remain external. |
| **Dynamic** | How may state evolve over time under an intervention or external event, and how well did that prediction match reality? | Read-only prediction, invariant, propagation, and fidelity evidence only. |

`OperationalStateTrajectory` is distinct from the existing governed conversation and execution
`TrajectoryEnvelope`. It pins an ontology release, baseline graph revision, inventory generation,
event-time cutoff, horizon, affected object revisions, predicted or observed state slices,
intervention references, source watermarks, completeness, truncation, and one replay-stable digest.
It stores normalized values and opaque evidence references, never raw cloud payloads. A predicted
trajectory cannot assert provider truth; an observed trajectory requires authoritative provider
or telemetry receipts.

`GraphEffectModel` extends the current action-and-metric effect model without replacing it. It
declares a source object or interface, an ActionType or external-event trigger, one bounded LinkType
path, a target object or interface and metric, propagation lag, response function, uncertainty,
context conditions, evidence grade, learning cutoff, and active or challenger status. The simulator
applies deterministic topology effects first, then verified active models. Challenger output is
reported only as divergence evidence and never ranks or selects a branch.

`DynamicInvariant` describes a machine-evaluable bound that must hold over the complete trajectory,
such as an SLO, RTO, RPO, capacity floor, cost envelope, data-integrity predicate, or affected-set
ceiling. A predicted violation removes the branch before arbitration. An observed violation during
execution stops forward dispatch and re-enters the existing typed recovery path; it does not let a
simulator alter a running plan.

`TrajectoryOutcome` compares predicted and independently observed state slices by object, metric,
and time window. Its terminal status is `matched`, `mismatched`, `intervention_censored`,
`incomplete`, or `unscorable`. Only complete, post-cutoff, independently observed outcomes update a
challenger model. Active models remain immutable until a separate reviewed promotion applies an
exact evidence receipt.

Conversation or internal-processing failures may open an off-path adequacy review only after a
deterministic attribution step preserves the exact verification reason, route, evidence manifest,
ontology release, graph revision, freshness, and completeness. Context, provider, routing,
rendering, policy, semantic, kinetic, and Dynamic failures remain distinct. Only reproduced
semantic, projection, rule, or Dynamic gaps create inert ontology or model-review candidates.

## Query, security, and SDK surfaces

Security applies at object, property, link, object-set, action-discovery, action-submission, and
function invocation boundaries. A visible link cannot reveal an otherwise hidden endpoint.

An ontology release can generate scoped Python and TypeScript SDKs plus OpenAPI metadata. The
generator includes only approved types and capabilities. Write methods submit typed action
proposals; they never call an executor. The publication adapter writes immutable content-addressed
artifacts with explicit scope, purpose, role ceiling, release, and artifact digests. Existing bytes
must replay exactly, and declaration removals require an explicit migration reference.

## Operational state transitions

The platform exposes `query.resource_state_transitions` as a read-only FunctionType over one secured
Resource set. The FunctionType reads the Core-owned PostgreSQL transition ledger rather than
inferring history from the current ontology graph. Inventory scope contributes an explicit
`authority_inputs` receipt, while the returned transition keeps its independent operational-state
history authority.

Each concrete observed edge retains its lane, authority, effective and recorded time, completeness,
conflicts, synthetic status, and evidence references. Presentation can state `from_state ->
to_state` only for complete, conflict-free, non-synthetic observations. Derived or otherwise
unverified rows remain unresolved and cannot become an observed-state claim.

## Delivery sequence

| Slice | Deliverable | Exit criteria |
|-------|-------------|---------------|
| P0-A | Exact declaration detail projection. | ObjectType, LinkType, and ActionType responses preserve one release, deterministic revision, completeness, redaction, and `mutation_authority=false`. |
| P0-B | ObjectType workbench and clean detail routes. | Direct navigation, refresh, and keyboard paths work; `Decision` properties, lifecycle absence, provenance, and relationships render without horizontal page overflow at 1440 x 900, 993 x 641, and 390 x 844. |
| P0-C | Governed action navigation. | Related actions require exact semantic target evidence; legacy unbound actions lower completeness and are never inferred by name or description. |
| P1-A | Deterministic dependents and evidence health. | Dependents come only from Catalog topology; unavailable runtime evidence carries nullable counts rather than measured zero. |
| P1-B | Active-inventory impact scope. | Traversal is bounded, snapshot-pinned, stored-direction, visibly unverified where applicable, and grants no execution or mutation authority. |
| P1-C | Retained-release comparison. | Additions, changes, and removals are deterministic; missing historical field schemas require review and never grant restore or migration authority. |
| P2 | Dedicated InterfaceType and FunctionType details. | Entry requires more than one meaningful active declaration plus an authoritative usage source; otherwise registry identity and topology nodes remain sufficient. |

P0-A through P0-C pass together before P1 is complete. Revise any slice that needs a new kernel
field, similarity links, raw provider payloads, mutation/executor credentials, or browser-calculated
authority or compatibility. Runtime Context remains a separate receipt-bound projection.

| Wave | Deliverable | Exit criteria |
|------|-------------|---------------|
| K0 | Exact `OntologyTypeRef` and `OntologyRelease` pinning. | Action, graph, audit, and replay tests preserve exact versions and digests. |
| K1 | Interfaces and bounded object sets. | Concrete expansion, ACL, cutoff, truncation, and query fixtures pass. |
| K2 | Semantic ActionType v2 and `MutationPlan`. | Plan digest, stale revision, impact, rollback, and shadow no-mutation tests pass. |
| K3 | Typed functions and authority-aware reconciliation. | Functions cannot mutate; every external effect reaches one typed closure. |
| K4 | Projection bindings and schema migrations. | Snapshot/delta parity, watermark recovery, conflict, and migration fixtures pass. |
| K5 | Generated SDKs and ontology application surfaces. | Python/TypeScript compile tests and proposal-only write tests pass. |
| K6 | Operational state trajectories and deterministic graph propagation. | Identical release, graph, cutoff, models, and interventions produce one digest; stale, truncated, cyclic, or unmodeled paths require review. |
| K7 | Dynamic invariants and trajectory outcome closure. | No invariant-violating branch reaches arbitration; provider acceptance cannot close an outcome; incomplete observations remain unscorable. |
| K8 | Failure attribution and governed Dynamic learning. | Exact verification reasons survive intake; non-ontology failures create no ontology proposal; only challengers learn and no learned artifact raises authority without review. |

New fields begin optional for decoding but are required for newly built runtime records. Legacy
decoding is removed only after retained audit and instance fixtures replay under exact releases.

## Verification matrix

| Concern | Required proof |
|---------|----------------|
| Replay | A historical record resolves the same declaration and plan digest. |
| Authority | A graph write cannot grant permission or assert external state. |
| Query safety | Every object set is bounded, purpose checked, and explicit about truncation. |
| Action safety | Stop, rollback, impact, dry-run, lock, idempotency, and audit remain mandatory. |
| Function safety | Query and planning code has no executor identity or direct mutation path. |
| Network path safety | Directed storage, reciprocal peering, per-segment evidence, cycle detection, and depth/segment ceilings are receipt-bound; absence never becomes an unreachable claim. |
| Reconciliation | Provider acceptance and observed convergence remain distinct states. |
| Dynamic replay | The same bounded inputs produce the same predicted trajectory and invariant verdict. |
| Dynamic authority | Prediction, model agreement, or model promotion evidence cannot approve or execute an action. |
| Dynamic closure | Only complete independent observations score trajectory fidelity or update a challenger. |
| Pod telemetry | A purpose-scoped secured graph plus state evidence yields deterministic verified, unverified, stale, and missing segments without provider I/O or health inference. |
| Pod diagnosis | One exact secured Pod UID can join bounded lifecycle and content-free log evidence; zero rows, incomplete sources, and scope conflicts remain explicit and cannot grant cause or execution authority. |
| Historical topology | PostgreSQL replay retains the exact ontology release and source receipt bindings for each selected revision batch; dangling active links lower completeness. |
| Projection reload | The inventory status marker and manifest share a content digest, so a restart never exposes a mixed generation. |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/operating-ontology-platform.md) |
| Declaration kinds and runtime State/Context boundaries | [Operating Ontology Metamodel](operating-ontology-metamodel.md) |
| Existing semantic and authority model | [FDAI Operating Ontology](operating-ontology.md) |
| Existing ActionType safety contract | [Action Ontology](../decisioning/action-ontology.md) |
| Runtime execution authority | [Execution Model](../decisioning/execution-model.md) |
| Repository and dependency boundaries | [Project Structure](project-structure.md) |
