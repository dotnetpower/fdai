---
title: FDAI Operating Ontology Metamodel
---
# FDAI Operating Ontology Metamodel

This document defines how FDAI separates operational meaning from versioned declarations and
runtime evidence. It hardens the intuitive Object, Relationship, State, Context, and Action view
without turning every view into a new ontology declaration kind.

> **Decision:** Object, Relationship, State, Context, and Action are the five operational lenses.
> The canonical release declaration kinds remain Object, Link, Interface, Function, and Action.
> State and Context are runtime semantic artifacts and versioned query patterns, not declaration
> kinds in the current release schema.
>
> **Authority boundary:** A state or context artifact can preserve or lower autonomy. It cannot
> assert external truth, approve an action, or become shared mutable coordination state.

## Design at a glance

```mermaid
flowchart TB
    subgraph L[Operational lenses]
        O[Object]
        R[Relationship]
        S[State]
        C[Context]
        A[Action]
    end

    subgraph D[Versioned declarations]
        OT[ObjectType]
        LT[LinkType]
        IT[InterfaceType]
        FT[FunctionType]
        AT[ActionType]
    end

    subgraph X[Runtime artifacts]
        OI[Object and Link instances]
        SF[Observed and derived facts]
        CS[Immutable context snapshot]
        MP[MutationPlan and ActionRun]
    end

    L --> D
    D --> X
```

The two groups answer different questions. Operational lenses explain the domain to an operator.
Declaration kinds define exact, content-addressed contracts. Runtime artifacts carry values,
evidence, and decisions under those contracts.

## Five operational lenses

| Lens | Question | FDAI representation |
|------|----------|---------------------|
| Object | What exists? | `OntologyObjectType` and `OntologyObjectRecord`. |
| Relationship | How are objects connected? | `OntologyLinkType` and `OntologyLinkRecord`. |
| State | What was observed, derived, desired, or executed? | Typed objects, observations, trajectories, and journals with explicit authority. |
| Context | Which bounded evidence was used for this question or decision? | A versioned query profile and immutable context snapshot. |
| Action | What change may be proposed under which safeguards? | `OntologyActionType`, `MutationPlan`, and `ActionRun`. |

State and Context are first-class in the operational model, but that does not require new
`STATE` and `CONTEXT` values in `OntologyDeclarationKind`. A declaration kind is justified only
when it needs independent compatibility, exact references, catalog lifecycle, and generated
consumer surfaces that cannot be expressed by the existing kinds.

## Canonical declaration plane

| Kind | Contract | Current status |
|------|----------|----------------|
| `OBJECT` | Entity shape, key, properties, lifecycle, provenance. | Active in canonical releases. |
| `LINK` | Endpoints, cardinality, causal and temporal semantics. | Active in canonical releases. |
| `ACTION` | Target, safety envelope, planning, execution, and postconditions. | Active in canonical releases. |
| `FUNCTION` | Bounded query, derive, validate, or plan operation. | Active in canonical releases. |
| `INTERFACE` | Shared semantic capability across ObjectTypes. | Shared contract and release-builder support exist; catalog and composition integration remain. |

`InterfaceType` should enter the release before State or Context receives another schema. This
unblocks `Operable`, `Observable`, `Ownable`, `Recoverable`, and similar polymorphic queries while
preserving concrete ObjectType identity.

## Relationship direction contract

A LinkType is directed by construction. `from_type -> to_type` is the declaration direction, and
`from_id -> to_id` is the matching runtime-instance direction. A separate generic `direction`
field would duplicate these endpoints and could contradict them, so the current metamodel does not
add one. Direction still needs explicit semantic roles because same-type links such as
`Resource -> Resource` cannot explain source and target meaning from their endpoint types alone.

| Dimension | Contract |
|-----------|----------|
| Stored endpoint direction | Read every link from `from` to `to`. Cardinality is interpreted in that order. |
| Semantic direction | The LinkType name, description, and reviewed mapping define source and target roles. Reversing those roles is a breaking semantic change. |
| Traversal direction | A query chooses `outgoing`, `incoming`, or `both`; traversal never rewrites the stored link. |
| Causal direction | When `is_causal` is true, the source is the candidate cause and the target is the candidate effect. The flag does not prove causality. |
| Temporal ordering | `temporal_order` sorts matching targets by `order_by_property`; it does not reverse the link or assert causality. |
| Symmetry and inverse | One directed record never implies its reverse. Bidirectionality requires two verified records until an explicit symmetric-link contract is released. |

The initial Resource relationship roles are:

| LinkType | Canonical direction | Operational reading |
|----------|---------------------|---------------------|
| `contains` | containing parent -> contained child | A resource group contains a VM; a VNet contains a subnet. Parent-to-child traversal finds impact descendants. |
| `attached_to` | attached resource -> attachment anchor | A NIC or disk is attached to a VM; a private endpoint is attached to its target. |
| `depends_on` | dependent -> prerequisite | A VM depends on a referenced user-assigned identity; a workload depends on a required data service. |
| `resource_classified_as` | observed Resource -> reviewed ResourceType | Classification follows a reviewed registry entry and never infers type from a name or embedding. |

Provider field ownership does not decide semantic direction. For example, a VM payload may contain
a NIC resource id, while the reviewed `attached_to` link is still NIC -> VM. A provider mapping
therefore records the source property path, allowed target provider types, semantic LinkType,
endpoint orientation, source schema digest, and evidence method. It remains a candidate until a
complete inventory generation observes both endpoint identities. Missing endpoints, an ambiguous
orientation, or incomplete coverage produces no link and lowers completeness.

Reviewed reference formats now distinguish provider ids, resolved names, and Kubernetes label
selectors. The Kubernetes candidate projector maps one Service to matching Pods and the same-name
Endpoints only within the same cluster and namespace. It consumes a bounded `ResourceRecord`
snapshot and still requires independent complete-generation verification before either link can
enter the active graph.

An inverse traversal is normally a query concern. FDAI adds a separately named inverse LinkType
only when the inverse has distinct domain meaning, provenance, or cardinality. A symmetric
relationship such as peering uses two independently supported directed records in the current
schema. A future `is_symmetric` or `inverse_link_type` field requires a compatibility design and
cannot retroactively reinterpret existing records.

## Direction hardening plan

| Step | Change | Exit criteria |
|------|--------|---------------|
| D0 | Publish this direction contract and VM adversarial examples. | Endpoint, semantic, traversal, causal, temporal, inverse, and symmetric direction are distinguishable. |
| D1 | Audit every shipped LinkType and producer against canonical roles and cardinality. | `contains`, `attached_to`, and `depends_on` declarations, Azure/Kubernetes projections, ownership rules, and tests agree on one orientation. |
| D2 | Add reviewed provider relationship mappings with explicit endpoint orientation and source-schema provenance. | Provider reference ownership cannot silently choose ontology direction. |
| D3 | Add complete, missing-endpoint, reversed-input, duplicate, and partial-coverage fixtures. | Only verified links enter the active graph; ambiguous or incomplete paths remain absent and reported. |
| D4 | Shadow-compare old and aligned graph generations before migration. | Directional query and blast-radius differences are measured, reviewed, replayable, and covered by a rollback pointer. |

A direction or cardinality correction that changes the interpretation of persisted links requires a
new LinkType major version or an explicit graph migration. It never edits historical context
snapshots in place.

## State model

FDAI separates state by authority rather than storing one mutable `state` bag.

| State lane | Examples | Authority and representation |
|------------|----------|------------------------------|
| Observed | Provider power state, provisioning result, metric sample. | Authoritative provider or telemetry receipt, then owned projection or `Observation`. |
| Derived operational | Healthy, degraded, resource pressure, forecast risk. | Versioned derive function plus immutable evidence and uncertainty. |
| Desired | SLO, RTO, budget, reviewed configuration. | Approved policy, configuration, or effective-time objective. |
| Execution | Planned, dispatched, verified, rolled back. | Process journal, `ActionRun`, outcome, and audit ledger. |

Every decision-relevant state fact records or resolves these fields:

- authority class and authenticated source identity;
- source revision and provenance digest;
- effective time, event time, recorded time, and evidence cutoff;
- freshness policy, completeness, and synthetic status;
- algorithm or function version for a derived value;
- immutable evidence references and conflict status.

High-frequency telemetry does not rewrite a Resource object for every sample. It remains in its
authoritative evidence source. A bounded observation or derived assessment enters the graph only
when an owning projection can preserve the fields above. Late evidence creates a new artifact and
never rewrites the context used by a historical decision.

## Context model

Context has two separate forms:

1. **Query profile:** A reviewed, versioned read pattern that selects a query FunctionType,
   ObjectSet definitions, required link paths, historical evidence functions, freshness rules,
   completeness policy, and resource ceilings.
2. **Context snapshot:** One immutable, content-addressed materialization of that profile at a
   cutoff. It contains exact object and link revisions, state facts, evidence paths, source
   watermarks, temporal exclusions, conflicts, truncation reasons, and an autonomy ceiling.

A query profile is represented by catalog-as-code plus a `query` FunctionType. It is not a mutable
Context object and does not need a `CONTEXT` declaration kind. The existing
`OperationalContextSnapshot` is the first context-snapshot implementation and should be extended,
not replaced.

An agent never edits a context snapshot. When newer evidence is required, it requests a new
snapshot from the accountable materializer. Context is an input and replay artifact, never an
authority-bearing collaboration channel.

## Operational intent flow

```mermaid
flowchart LR
    N[Natural language] --> C[Candidate interpretation]
    C --> V[Verified semantic plan]
    V --> F[Query FunctionType]
    F --> Q[ObjectSet and evidence functions]
    Q --> S[Context snapshot]
    S --> P[Policy input when needed]
    P --> D[Decision pipeline]
```

Lexical matching, embeddings, and models produce candidates only. A candidate must resolve the
exact ontology release, semantic catalog, arguments, and reviewed evidence before it becomes a
`VerifiedSemanticPlan`. The verified plan still has no execution authority.

Current-state graph reads and historical evidence are different operations. `ObjectSetDefinition`
selects the current graph. Metrics, logs, activity, audit, and retained trajectories are bounded
functions in the same query plan. An `as_of` value does not turn the current instance store into a
bitemporal database. Until a store contract exposes an authoritative observation cutoff or
watermark, the secured gateway accepts only the trusted current evaluation cutoff within a
configured skew of at most five seconds. Other past or future values are explicitly unsupported,
never historical-completeness claims.

OPA/Rego is not mandatory for every read. It evaluates access, policy, and action eligibility over
a bounded typed input when those decisions are required. It does not search the ontology or call a
provider API.

## Ownership

| Artifact | Accountable owner |
|----------|-------------------|
| Provider observation and topology ingress | Huginn, with the authoritative inventory projection as mechanical writer. |
| Runtime observations, findings, forecasts, and independent outcome evidence | Heimdall. |
| Cost and capacity state facts | Njord and Freyr for their owned advisory objects. |
| Chaos experiment state | Loki. |
| Immutable operational context snapshots | Muninn. |
| Decision cases and verdicts | Forseti. |
| Cross-objective arbitration | Odin. |
| Human approval records | Var. |
| Action runs and attempts | Thor. |
| Recovery and rollback outcomes | Vidar. |
| Audit records | Saga. |
| Catalog lifecycle and promoted semantic surfaces | Mimir. |
| Natural-language rendering and candidate translation | Bragi, with no decision or execution write. |

Infrastructure projectors may persist an owner's typed output, but they do not become hidden
agents. Each projection keeps one writer, revision fencing, owned-identity manifests where
replacement is possible, and a complete audit or outbox path.

## Rejected designs

- A generic mutable `State` object that mixes observed, desired, derived, and execution values.
- A mutable `Context` cache shared by agents.
- A state value that directly raises autonomy or grants permission.
- Provider-observed state updated from a command or graph-write receipt.
- High-frequency telemetry copied into the instance graph without bounds and freshness receipts.
- Question examples stored as deployment object instances. They belong to a reviewed semantic
  language catalog and remain candidate-only until verified.
- Adding `STATE` or `CONTEXT` declaration kinds before a competency fixture proves that ObjectType,
  InterfaceType, and query FunctionType cannot express the required compatibility contract.

## Additive delivery sequence

| Wave | Change | Exit criteria |
|------|--------|---------------|
| M0 | This metamodel decision, direction contract, and adversarial fixtures. | Declaration, runtime, direction, authority, time, and ownership layers are unambiguous. |
| M1 | Include semantic InterfaceTypes in `OntologyRelease`. | Interface digest, exact ref, compatibility, and empty-input backward-compatibility tests pass. |
| M2 | Add a query FunctionType that materializes bounded ObjectSets with plan and invocation lineage. | Purpose, release, truncation, and evidence receipts survive end to end. |
| M3 | Standardize state-fact fields and link observation metadata using existing ObjectTypes and function outputs. | Observed and derived facts cannot be confused; stale or conflicting facts lower autonomy. |
| M4 | Move one `read_investigation` intent through a verified query profile in shadow. | Existing and ontology-native results agree or differences remain explicit. |
| M5 | Add competency-driven network and telemetry relationship coverage after D1-D4. | VM connectivity and Pod telemetry chains report correctly oriented verified and unverified segments. |

`StateType` or `ContextType` becomes a future declaration-kind proposal only after M3 or M4
produces a compatibility requirement that cannot be represented by ObjectType, InterfaceType,
FunctionType, exact release refs, and immutable snapshots.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Canonical declaration release | implemented | [`ontology_catalog.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/ontology_catalog.py), [`release.py`](../../../services/core-control-plane/src/fdai/shared/ontology/release.py), and [`test_ontology_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_ontology_catalog.py) | Object, Link, Action, Interface, and Function declarations contribute to an exact release. |
| Bounded ObjectSet execution and lineage | implemented | [`semantic_query.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/semantic_query.py), [`test_interfaces_and_object_sets.py`](../../../services/core-control-plane/tests/core/ontology_platform/test_interfaces_and_object_sets.py), and [`test_semantic_query.py`](../../../services/core-control-plane/tests/core/ontology_platform/test_semantic_query.py) | The secured query path preserves release, plan, invocation, truncation, and evidence references without granting authority. |
| Provider state and relationship evidence contracts | implemented | [`state_evidence.py`](../../../services/core-control-plane/src/fdai/shared/providers/state_evidence.py) and [`test_state_evidence.py`](../../../services/core-control-plane/tests/providers/test_state_evidence.py) | Typed metadata distinguishes observed state and link evidence from derived interpretation. |
| Relationship direction and classification hardening | in-progress | The direction contract and `resource_classified_as` design in this document; [`kubernetes_relationships.py`](../../../services/core-control-plane/src/fdai/delivery/kubernetes_relationships.py), [`direction_shadow`](../../../services/core-control-plane/src/fdai/core/ontology_platform/direction_shadow), [`inventory_ontology.py`](../../../services/core-control-plane/src/fdai/runtime/inventory_ontology.py), focused tests, and retained receipt `sha256:ad64c267b6f0c6ac5a1a037067f926aa5613f1fe5a84702877eb607e368736f6`. | D1 and D3 are covered. A real D4 comparison is replayable and retained as `review_required`; the historical release is unbound and the aligned generation is incomplete with unverified links, so it isn't migration evidence. |
| Network and Pod telemetry competency | in-progress | [`operational_functions.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_functions.py), [`inventory_sync.py`](../../../services/core-control-plane/src/fdai/delivery/inventory_sync.py), [`test_inventory_sync.py`](../../../services/core-control-plane/tests/delivery/test_inventory_sync.py), and [`test_wire_pod_telemetry.py`](../../../services/core-control-plane/tests/composition/test_wire_pod_telemetry.py). | Production inventory composition now projects and independently verifies Kubernetes relationships whenever an authoritative source supplies Service, Pod, and Endpoints records. No production Kubernetes inventory source or retained live receipt exists yet. |
| Production metamodel assurance | in-progress | Focused source and test evidence above. | Authenticated cross-service and operational receipts are still required before this document can claim production validation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger and replaced the aggregate production-ready narrative with bounded states; earlier provenance was not reconstructed. | `current change`; the source and focused checks listed in the scope table. | Complete the direction and classification audit, M5 competency, and production assurance items below. |
| 2026-08-13 | in-progress | Added reviewed Kubernetes Service selector and Endpoints mappings plus a bounded candidate projector that fails closed on missing, duplicate, reversed-order, and partial input. | `current change`; `test_kubernetes_relationships.py` reports 6 passed and the focused provider catalog test reports 1 passed. | Complete the D1 producer audit, retain D4 comparison and rollback evidence, and bind the projector through production inventory composition. |
| 2026-08-13 | in-progress | Reconciled the existing D4 implementation instead of creating a duplicate comparator. The content-addressed receipt already measures directional queries and blast radius, supports exact replay, and carries a no-authority rebuild pointer. | Commit `18be5ab02`; focused `pytest -q services/core-control-plane/tests/core/ontology_platform/direction_shadow` reports 6 passed. | Run the comparator over retained legacy and aligned production generations, review the differences, and preserve the resulting receipt before migration. |
| 2026-08-13 | in-progress | Added an exact D1 catalog audit for all 17 shipped provider relationship mappings so a single semantic direction or reference-format regression cannot load silently. | `current change`; focused `test_shipped_relationship_mappings_match_canonical_endpoint_roles` reports 1 passed. | Audit the remaining runtime producers and relationship ownership rules against the same canonical roles. |
| 2026-08-13 | implemented | Completed the bounded D1 audit across Resource LinkType declarations, reviewed mappings, Azure and Kubernetes producers, complete-generation verification, and delta ownership. | `current change`; the exact declaration audit reports 1 passed and the combined producer/ownership audit reports 13 passed. | Retain a reviewed D4 receipt from real legacy and aligned production generations before migration. |
| 2026-08-13 | in-progress | Added production-composition M5 checks that invoke the issued Pod telemetry function over a release-pinned Resource and Observation Interface. Complete evidence returns four verified segments, while a synthetic sample remains unverified with no health or execution authority. | `current change`; focused `test_wire_pod_telemetry.py` reports 2 passed. | Bind the Kubernetes projector to retained production inventory and preserve authenticated live-assurance evidence on the same ontology release. |
| 2026-08-14 | implemented | Bound every newly built inventory ontology projection result, durable manifest, and status to the exact catalog release used by the inventory job. Invalid or absent release digests fail before projection. Historical manifests are not assigned a reconstructed release. | `current change`; focused `test_inventory_ontology.py` reports 9 passed. | Refresh inventory after central validation, then retain release-bound D4 and M5 evidence from new generations; historical comparison remains review-required. |
| 2026-08-14 | in-progress | Allowed retained graph generations to preserve an explicitly unbound release and captured a replay-identical D4 comparison in the deployment-local StateStore. The receipt reports 607 added, 0 removed, and 0 reversed links and grants no migration or graph authority. | `current change`; focused direction-shadow suite reports 8 passed; StateStore receipt `sha256:ad64c267b6f0c6ac5a1a037067f926aa5613f1fe5a84702877eb607e368736f6` has `review_required` with `legacy_release_unbound`, `aligned_generation_incomplete`, and `aligned_link_evidence_unverified`. | Review the measured differences and capture a complete aligned generation with verified link metadata before migration. |
| 2026-08-14 | implemented | Bound the reviewed Kubernetes relationship projector through the common promoted-inventory observation path and injected the shipped mapping catalog from scheduled and local inventory composition. | `current change`; the focused inventory observer test reports 1 passed and the two caller-wiring checks report 2 passed. | Add an authoritative Kubernetes inventory source and retain exact-release Pod telemetry evidence; current Azure inventory doesn't supply Kubernetes workload objects. |

### Remaining work

- [x] Retain a replayable D4 comparison and rebuild pointer from real inventory generations as `review_required`; receipt `sha256:ad64c267b6f0c6ac5a1a037067f926aa5613f1fe5a84702877eb607e368736f6` preserves the unbound historical release and grants no migration authority.
- [ ] Review the retained D4 differences and capture a new receipt from a complete release-bound aligned generation with verified link metadata before any migration decision.
- [x] Bind the reviewed Kubernetes relationship projector through production and local inventory composition and verify that supplied Service, Pod, and Endpoints records produce independently verified links.
- [ ] Add an authoritative Kubernetes inventory source, then run the VM connectivity and Pod telemetry competency checks against retained inventory evidence on the exact release.
- [ ] Retain authenticated cross-service and live-assurance receipts that bind the exact ontology release before changing production metamodel assurance to `validated`.

## Verification checklist

- Does every declaration that affects interpretation contribute to the release digest?
- Does every state fact identify authority, provenance, time, freshness, and completeness?
- Does every LinkType define one source-to-target semantic reading consistent with its cardinality?
- Can incoming, outgoing, inverse, and symmetric traversal be distinguished without rewriting links?
- Can the runtime distinguish external observation, derived interpretation, desired intent, and
  execution progress?
- Is every context immutable, bounded, replayable, and owned by one materializer?
- Can a missing or truncated path only preserve or lower autonomy?
- Does every semantic candidate remain non-authoritative until exact evidence verification?
- Does every action still re-enter judgment, risk, approval, execution, recovery, and audit?
- Can every provider-observed effect close only through independent authoritative observation?

## Related docs

| To learn about | Read |
|----------------|------|
| Domain objects, relationships, time, and ownership | [FDAI Operating Ontology](operating-ontology.md) |
| ObjectSet, functions, actions, and writeback boundaries | [Ontology Safety Infrastructure](operating-ontology-platform.md) |
| Constitutional authority | [FDAI Constitution](fdai-constitution.md) |
| Natural-language and model boundaries | [LLM Strategy](llm-strategy.md) |
| Action safeguards | [Action Ontology](../decisioning/action-ontology.md) |
