---
title: Rule-to-Decision Lookup
---
# Rule-to-Decision Lookup

This document owns the deterministic rule-dispatch ontology and the layered T0, reuse, similarity,
cache, and residual T2 lookup path. It defines semantic signatures and audit lineage but grants no
judgment or execution authority; storage remains owned by
[Rule Lookup Ontology Storage](rule-lookup-ontology-storage.md).

## Rule-to-Decision Lookup Pipeline

The tier percentages in [Model Tiers](llm-strategy.md#model-tiers) are the *outcome* of a deliberate
**layered lookup pipeline**: an incoming event traverses cheap-to-expensive layers, and a
frontier LLM (L5) is reached only when every cheaper layer abstains. The pipeline is built
on a typed **ontology**: rules, resources, signals, and actions are ontology entities, and
matching them is a deterministic graph traversal rather than a text-similarity guess.

The ontology framing borrows the object-type / link-type / action-type separation from a
prior AGI ontology design (typed objects with cardinality-aware links, functions integrated
into actions via `required_interfaces` and `submission_criteria`), applied to CSP resources
and rules. This gives every rule a deterministic dispatch path and every reuse a
canonical, hashable signature.

### Ontology Foundation

The low-level rule-dispatch foundation starts with four **ObjectTypes**; [FDAI Operating Ontology](operating-ontology.md)
owns service, objective, decision, and effect semantics. The extensible registry keeps product objects such as Process,
Conversation, and ReviewCase plus meta objects such as ResourceType, SignalType, Property, and ActionType first-class. Declarations live in `rule-catalog/vocabulary/`; runtime instances use the shared ontology store.

| ObjectType | Meaning | Backing |
|------------|---------|---------|
| `Resource` | a target under governance (Azure resource; CSP-neutral schema, populated by the provider adapter) | `shared/providers/` |
| `Rule` | a deterministic control with an intent (`applies_to`, `evaluates`, `remediates`) | `rule-catalog/` |
| `Signal` | a typed observation (Activity Log line, drift diff, cost anomaly, canary result) - the primitive that enters `event-ingest` | `shared/contracts/event` |
| `Finding` | a rule match on a resource at a point in time, with context and severity | derived at runtime; persisted in the audit store |

Meta ObjectTypes make LinkType endpoints honest. `applies_to` targets `ResourceType`,
`triggered_by` targets `SignalType`, `evaluates` targets `Property`, and `remediates` targets
`ActionType`. They may have zero runtime instances on a deployment that reads the corresponding
catalog directly; their declarations still prevent endpoint aliases such as modeling an
ActionType as a Rule.

Every shipped ObjectType, LinkType, and ActionType declaration is evidence-governed: it cites a
source URL and resolved declaration version, records license and retrieval time, and carries a
loader-verified canonical content hash. Missing or stale provenance blocks catalog composition.

Relationships are **typed LinkTypes** with cardinality metadata, so traversal is O(indexed
lookup), not scan. Each declaration also carries `is_transitive`, `is_causal`, and
`temporal_order` flags so the traversal engine knows when a recursive expansion is safe and
when a query must respect time. A temporal LinkType also declares `order_by_property`, which
MUST resolve to an ordered property on its target ObjectType. The instance store enforces
cardinality before every link write, permits a repeated same-LinkType traversal only when
`is_transitive` is true, and returns temporal links in target-property order. These are runtime
invariants, not visualization hints.

| LinkType | Cardinality | Transitive | Meaning |
|----------|-------------|:---------:|---------|
| `applies_to` | Rule → ResourceType (M:M) | - | which resource types the rule may match |
| `triggered_by` | Rule → SignalType (M:M) | - | which signals cause the rule to be evaluated |
| `evaluates` | Rule → Property (M:M) | - | which resource properties the rule reads |
| `remediates` | Rule → ActionType (M:1) | - | which ontology action the rule proposes on match |
| `resource_of` | Signal → Resource (M:1) | - | which resource the signal is about |
| `overrides` | Override → Rule (M:1) | - | the override targets this rule (see [rule-governance.md](../rules-and-detection/rule-governance.md#overrides)) |
| `causes` / `prevents` | Rule → Outcome (M:M, causal) | - | causal metadata that T2 may reason over (rare) |
| `precedes` / `follows` | Finding → Finding (M:M, temporal) | - | correlation of related findings on one incident |
| `contains` | Resource -> Resource (1:M, parent -> child) | ✓ | ownership / scope containment: subscription -> resource-group -> resource, VNet -> subnet, cluster -> node-pool. Recursive traversal follows the stored parent-to-child direction. Populated by the [inventory adapter](csp-neutrality.md#5-inventory-contract--resource-graph). |
| `attached_to` | Resource → Resource (M:1) | - | lifetime-bound attachment: NIC→VM, disk→VM, private-endpoint→target. Removing the parent breaks the child. |
| `depends_on` | Resource → Resource (M:M) | - | logical reference required for correct operation: ContainerApp→Key-Vault / ACR / Postgres, managed-identity→app. Broken edges degrade the dependent, not the target. |
| `peered_with` | Resource ↔ Resource (M:M, symmetric) | - | network peer represented by two independently supported directed records; one record never implies its reverse. |
| `routes_to` | Resource → Resource (M:1) | - | directed traffic path or reference such as a UDR next hop; absence never proves unreachable. |

Traversal is directional and cached; a `Signal` of type `T` on a `Resource` of type `R`
resolves to exactly the set of rules where `triggered_by ∋ T` and `applies_to ∋ R` via
two index intersections - no text search, no model call.

The Resource→Resource links (`contains`, `attached_to`, `depends_on`, `peered_with`, and
`routes_to`) are what let the risk-gate compute an *actual* blast radius
instead of the three-value enum in [risk-classification.md](../decisioning/risk-classification.md), and
what let T2 be prompted with a **depth-2 neighborhood subgraph** around the target
resource - grounded, cited context instead of a bare resource id. Their authoritative
source is the [inventory contract](csp-neutrality.md#5-inventory-contract--resource-graph);
`core/` never queries a cloud SDK for them. New link kinds MUST be added to
`shared/contracts/ontology/link-type.json` before an adapter can emit them - an
unrecognized link, like an unrecognized `ResourceType`, opens an issue rather than
auto-registering (self-extending ontology, see [Fork Extension](#fork-extension-self-extending-ontology)).

Runtime ObjectType properties and LinkType properties MUST be canonical JSON data. Mapping keys
are strings, numbers are finite, datetimes are timezone-aware and normalized to RFC 3339 UTC, and
unsupported Python objects are rejected at the write boundary. Both the in-memory and PostgreSQL
stores apply the same normalization so replay does not depend on the selected adapter.

### Concrete Rule semantics

Shipped Rules don't use wildcard ontology relationships. `triggered_by` references a reviewed
`SignalType`, `evaluates` references canonical `Property` identities, and
`implemented_by_policy` connects the Rule to a first-class `PolicyArtifact`. A bounded OPA AST
synchronizer verifies Rego package identity and property reads before catalog composition.

Raw events resolve through `vocabulary/signal-types.yaml`. Exact pattern matches select specialized
types; unmatched events select the single reviewed configuration baseline type. Semantic retrieval
may rank candidate Rules, but exact ids and graph links remain the authority for dispatch and
grounding.

### Rule as Ontology Artifact

Rule schema v2 in
[rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md) carries the
ontology fields the pipeline dispatches on. It migrates the former scope-map meaning of
`applies_to` to `scope_predicates`; every dispatch field is validated by CI at load.

```yaml
# rule-catalog/rules/example.yaml (illustrative fragment; full schema in rule-catalog-collection.md)
id: object-storage.public-access.deny
version: 1.2.0
source: authored
severity: high
category: security
resource_type: object-storage
check_logic: <opa-package-ref>            # deterministic evaluator
remediation: <action-ref>                 # points to an ontology ActionType instance

# ── ontology fields (new; CI-validated) ──
applies_to:    [object-storage]
triggered_by:  [property.public_access.changed, config.public_access.enabled]
evaluates:     [object-storage.public_access]
scope_predicates: {}                         # optional labels/tags/scope filters
remediates:    remediate.disable-public-access
required_interfaces: [Evaluable, Remediable]   # submission_criteria enforced at load
submission_criteria:
  - kind: resource_type_registered
    value: object-storage
provenance: { ... }
```

`required_interfaces` and `submission_criteria` follow the same
Functions-plus-Interfaces pattern as the referenced ontology design: a rule is only
dispatchable when its interface contract is satisfied on the runtime object, and CI
rejects a rule whose `applies_to` / `triggered_by` cannot be resolved against the
schema registry.

`resource_type` remains the canonical single target used by existing policy and remediation
code; it MUST occur in `applies_to`. `scope_predicates` carries the former label/tag scope map so
it cannot be confused with the type axis. Existing and newly collected rules are backfilled with
`triggered_by: ["*"]` and `evaluates: ["*"]` only when the upstream source supplies no narrower
metadata. The wildcard is an explicit catch-all, not an inferred signal. TrustRouter and T0 use
the same `applies_to` x (`triggered_by` exact or `*`) intersection.

### Pipeline Stages and ActionTypes (distinct concepts)

Two things are called "action" in this system and MUST NOT be conflated:

- **PipelineStage** - where in the layered lookup a decision was made. This is an
  **audit vocabulary**, not a schema artifact. Every audit-log entry records the
  `pipeline_stage` field so the decision path is reconstructable end-to-end. Stages are
  read-only from the executor's perspective (no CSP mutation happens here except at
  `remediate`).
- **ActionType** - a **CSP-neutral mutation category** with a rollback contract. Declared
  in `shared/contracts/ontology/action-type.json`; instances (e.g.
  `remediate.disable-public-access`) live in the catalog and are referenced from a rule's
  `remediates` field. This is the schema artifact.

Only `remediate` couples the two: it is a PipelineStage (the executor step) whose
output is an ActionType **instance** applied to a Resource. `escalate` / `abstain` / `deny`
are terminal stages that never invoke an ActionType.

**PipelineStage vocabulary** (recorded in `audit_log.pipeline_stage`):

| PipelineStage | Layer | Cost | Preconditions | Terminal? |
|---------------|-------|------|---------------|:---------:|
| `L1_evaluate` | L1 (T0) | pure function, in-memory OPA/Rego | rule's `applies_to` matches Resource; `check_logic` compiled | - |
| `L1_simulate` (what-if) | L1 (T0) | pure function against declarative state | resource state snapshot available | - |
| `L2_reuse` | L2 | O(1) indexed SELECT | `(signature, rule_id, catalog_version)` hit in learned-action store | - |
| `L3_similarity` | L3 (T1) | 1 embedding + pgvector kNN | context compatibility check passes on the neighbor | - |
| `L4_cache_hit` | L4 | O(1) key lookup | signature match within TTL and catalog / model version | - |
| `L5_reason` | L5 (T2) | frontier LLM (primary + secondary; escalated on disagreement) | quality-gate authoritative | - |
| `remediate` | risk-gate ⇒ executor ⇒ delivery | apply an ActionType instance to a Resource | policy-as-code verifier passed; all ActionType preconditions hold | - |
| `escalate` | risk-gate ⇒ ChatOps | HIL request | no cheaper layer resolved the case | ✓ |
| `abstain` | any layer | audited no-op | grounding unavailable or verifier abstained | ✓ |
| `deny` | any layer | audited no-op | risk-classification blocked the action | ✓ |

Only `L5_reason` invokes the LLM. Every other stage is deterministic and executes in
microseconds to milliseconds.

### ActionType Contract

An **ActionType** ([schema](../../../services/core-control-plane/src/fdai/shared/contracts/ontology/action-type.json))
declares one CSP-neutral mutation category and the safety invariants for every instance
of it. All fields except `preconditions` / `stop_conditions` / `blast_radius` /
`description` are required.

- `name` - stable id (e.g. `remediate.disable-public-access`).
- `operation` - CSP-neutral verb from the enum below.
- `interfaces` - runtime contracts the executor honors; risk-gate composes its feature
  vector from this set.
- `rollback_contract` - how instances are undone. **`none` is not a valid value**; every
  ActionType MUST declare an undo path, even a best-effort one. Genuinely one-way
  mutations set `irreversible: true` (below) and are routed HIL+quorum by
  risk-classification, they do NOT silence rollback.
- `irreversible` - true only when the pre-action state cannot be fully restored (e.g.
  `purge` of a soft-deleted resource). Rollback_contract is still required and describes
  best-effort recovery.
- `default_mode` - every upstream ActionType MUST ship as `shadow`. Promotion to enforce
  is a separate governed action after its promotion gate passes.
- `promotion_gate` - measurable criteria (`min_shadow_days`, `min_samples`,
  `min_accuracy`, `max_policy_escapes`) a shadow-mode ActionType MUST clear on the
  frozen scenario set before an assignment can promote it to enforce. Rule assignments
  may tighten these values, never loosen them.
- `preconditions[]` - deterministic checks the T0 verifier evaluates BEFORE the action
  reaches the risk-gate. A failing precondition MUST abstain, never partially apply.
- `stop_conditions[]` - deterministic conditions the executor evaluates DURING or AFTER
  apply. Any true value auto-halts and triggers rollback per `rollback_contract`.
- `blast_radius` - how the risk-gate computes the blast-radius classification dimension
  for an instance. `static_enum` uses a fixed bucket; `graph_derived` walks Resource →
  Resource links (default: `contains` + reverse `depends_on`, depth 2) and counts
  affected Resources. Instances exceeding `max_affected_resources` abstain and escalate.
  Traversal implementation lands with the risk-gate (P2); P1 only records the declaration.

#### Operation Verbs

The `operation` enum is CSP-neutral. Each verb has a fixed semantic so rule authors and
provider adapters agree on intent.

| Verb | Semantic | Rollback default |
|------|----------|------------------|
| `create` | provision a new Resource | `pr_revert` (destroy in the same PR) |
| `update` | in-place property change (non-destructive) | `pr_revert` (prior property values in the diff) |
| `delete` | remove a CSP-level Resource | `snapshot_restore` (pre-delete snapshot) |
| `disable` | turn off without deleting | `state_forward_only` via `enable` |
| `enable` | inverse of `disable` | `state_forward_only` via `disable` |
| `tag` | metadata-only mutation | `pr_revert` |
| `drop` | DB-DDL removal (schema / object) | `pitr` |
| `purge` | soft-delete then hard-delete; `irreversible: true` | best-effort `snapshot_restore` |
| `scale` | count / SKU adjustment | `pr_revert` to prior spec |
| `restart` | in-place process/pod bounce | `scripted` or `state_forward_only`, depending on the provider contract |
| `failover` | trigger managed failover; `RequiresMaintenanceWindow` | `scripted` (failback) |
| `rotate` | secret / cert rotation | `snapshot_restore` (prior version retained) |
| `revert` | explicit rollback of a prior action instance | `pr_revert` on the revert PR itself |
| `attach` | create a Resource → Resource link (PE→target, MI→App, disk→VM) | `state_forward_only` via `detach` |
| `detach` | remove such a link | `state_forward_only` via `attach` |
| `quarantine` | network/policy isolation without deletion | `state_forward_only` (lift the isolation policy) |

#### Interfaces

The `interfaces` set on an ActionType names runtime contracts the executor MUST honor. A
missing interface is not "allowed anything" - the risk-gate refuses to auto-execute an
ActionType whose interface set does not cover the safety-invariant requirements for its
`operation`.

| Interface | Meaning |
|-----------|---------|
| `ControlPlane` | Touches only CSP metadata / configuration (never user data). Baseline for auto candidates. |
| `DataPlaneMutating` | Touches user data. **HIL by default** regardless of blast radius. |
| `IdempotentByKey` | Safe to retry with the same idempotency key; the executor's dedup uses this key. |
| `RateLimited` | Must respect a bucket cap (per-resource, per-tier, or global); overflow degrades to HIL. |
| `RequiresInventoryFresh` | MUST NOT fire if the target Resource's inventory record is stale beyond `freshness_ttl`. Prevents acting on ghost resources - the inventory contract ([csp-neutrality.md § 5](csp-neutrality.md#5-inventory-contract--resource-graph)) supplies the freshness cursor. |
| `GraphTraversalRequired` | Blast-radius calculation depends on Resource → Resource links (`contains` / `attached_to` / `depends_on`). If the graph is unavailable, the ActionType abstains. |
| `CrossResource` | Mutation touches multiple Resources; the executor acquires N per-resource locks in a deterministic order to stay deadlock-free. |
| `AsymmetricRollback` | Rollback path is not the exact inverse (e.g. PITR may lose Δ-data). Forces auto → HIL demotion; auto is never selected regardless of other dimensions. |
| `RequiresMaintenanceWindow` | Only executes inside an approved window (P3 chaos / DR). Missing window scheduler → abstain, never fall through to a bare execute. |


### Layered Lookup Pipeline

![Layered Lookup Pipeline. The main stages are Signal arrives, L0. event-ingest / normalize + dedup + correlate into incident, no-op, audited, L1. T0 rule match / ontology traversal: applies_to ∩ triggered_by / run each rule's evaluate action (OPA/Rego, in-memory), risk-gate, L2. Learned-action lookup / (signature, rule_id, catalog_version) → verified action, L3. Embedding similarity (T1) / 1 embedding call → pgvector kNN / reuse neighbor.action iff cos > threshold and context compatible, L4. T2 result cache / signature includes catalog_version + model_config_version + mode, L5. T2 cascade / primary → agree? → done / disagree? → escalated / quality-gate authoritative, writeback: promote verified outcome / into L2 (learned action) + L4 (result cache).](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-03.en.svg)

**Expected hit distribution** (design targets, subject to measurement per
[goals-and-metrics.md](goals-and-metrics.md)):

| Layer | Cost per hit | Design share of incoming events |
|-------|--------------|--------------------------------|
| L0 dedup / correlate | µs | folds N events → 1 incident (compression, not a coverage number) |
| L1 T0 | µs, in-memory | ~70-80% |
| L2 learned-action | ms, indexed SELECT | grows over time as L5 outcomes distill down |
| L3 embedding similarity | ~1 embedding call + kNN | remainder of the T1 ~15-20% band |
| L4 T2 cache | O(1) key | absorbs repeats of unresolved-but-recent cases |
| L5 T2 cascade | frontier LLM | **~5-10% only** - the actual token spend |

Two structural consequences:

- **LLM usage decreases over time**, not increases. Every L5 verified outcome writes back
  to L2, so a recurring case that took a full T2 cascade last week is a hash lookup this
  week. This is the concrete mechanism behind the "use the LLM less" principle.
- **A rule change invalidates the right rows automatically** (see below). No manual cache
  bust; no stale reuse survives a promotion or a demotion.

### Signature Composition

The signature that keys L2 and L4 is a canonical hash over ontology-typed fields, so
recording and reuse are semantics-aware, not string-similar.

```text
signature = sha256(
  Signal.type,
  canonical(Signal.params),                # sorted, redacted, typed
  Resource.type,
  canonical(Resource.props),               # only props referenced by evaluates
  Rule.id, Rule.version,
  Catalog.version,
  Model.config.version,                    # L4 only; L2 omits (model-independent reuse)
  Mode                                     # shadow | enforce
)
```

- **Redaction runs before hashing** so a secret can never enter a signature.
- **Only properties named in `evaluates`** participate, so unrelated resource churn does
  not invalidate reuse.
- **Catalog / model version bumps** and **shadow ↔ enforce transitions** force new
  signatures, guaranteeing the invalidation rules in [Cost Controls](llm-strategy.md#cost-controls) are
  applied without a separate cache-flush step.

### Reuse Audit (every layer, including hits)

Autonomy requires that a decision - including one produced by a reuse - is fully
attributable. Every layer writes an audit entry with:

- `layer` (L1..L5)
- `rule_id` and `rule_version` that fired
- `signature` and how it matched (exact hit / cos similarity + score / cache age)
- `reused_from`: back-reference to the audit_id whose outcome was reused (L2/L4)
- `mode` (shadow / enforce) and the resulting risk-gate decision

A reuse without a resolvable `reused_from` is a defect - the audit chain must be walkable
from any decision back to the L5 outcome that originally verified it, and forward to the
rule/model versions in effect.

### Fork Extension (self-extending ontology)

The ontology is **domain-agnostic in the core** and **extensible per fork**. A fork adds
`ObjectType` and `LinkType` catalog entries in its own package and binds a provider that emits
records conforming to those definitions; it never edits `core/` or the upstream contract
package.
- New `Resource` subtypes enter through reviewed catalog entries and inherit the pipeline
  automatically - `evaluate`, `reuse`, and `similarity` work over them with no code change
  in `core/`.
- New `LinkType`s (e.g. a fork-specific causal relation) declare their cardinality,
  transitivity, and reasoning metadata; unused links stay inert.
- New `ActionType`s (e.g. a fork-specific delivery adapter) declare their
  `required_interfaces` and `submission_criteria`; a rule that references an unregistered
  action fails at catalog load, not at runtime.
- Autoprovisioning: an unrecognized ResourceType observed in a Signal opens an issue
  (never auto-registers), so the ontology extends by review, not by drift.

### Ontology Storage Layout

The complete storage, schema, and boot/reload design now lives in
[rule-lookup-ontology-storage.md](rule-lookup-ontology-storage.md).

## Related docs

| To learn about | Read |
|----------------|------|
| Tier boundaries, cost controls, and quality gates | [LLM Strategy](llm-strategy.md) |
| Runtime storage and reload behavior | [Rule Lookup Ontology Storage](rule-lookup-ontology-storage.md) |
| Shared operational semantics | [FDAI Operating Ontology](operating-ontology.md) |
| Governed mutation vocabulary | [Action Ontology](../decisioning/action-ontology.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/rule-to-decision-lookup.md) |
