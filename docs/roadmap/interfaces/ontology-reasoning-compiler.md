---
title: Ontology Reasoning Compiler
---
# Ontology Reasoning Compiler

This document owns the target design that turns an operator question into a closed, span-grounded
question logical form and compiles it deterministically into a verified ontology query plan. The
model classifies meaning among closed types. Code admits that meaning, binds concepts and anchors,
selects reviewed relation paths, proves that the plan preserves it, and decides what may be claimed.

> **Status:** Proposed design, 2026-09-28. Nothing in this document is implemented. The current
> runtime is described in [Hierarchical Conversation Planning](hierarchical-conversation-planning.md)
> and [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md).
> Implementation starts only after design approval.
>
> **Authority boundary:** Logical forms, admission and compile receipts, anchor bindings, result
> handles, and plans are read-only records with `execution_authority=false`. An explicit change
> request still produces only the existing typed action draft.

## Design at a glance

| Stage | Accountable agent | Output | Model use |
|-------|-------------------|--------|-----------|
| 1. Conversation preflight | Bragi | Social, knowledge, and operational routing | T1, unchanged |
| 2. Logical-form judgment | Bragi | Proposed `SemanticQuestionForm` | T1, one call |
| 3. Admission | Bragi | Admitted form, clarification, or review request | Optional T2 review |
| 4. Concept resolution | Mimir catalogs | Domain-restricted bindings for concept mentions | None |
| 5. Anchor binding | Muninn | Exact identities pinned to one snapshot | None, one bounded read |
| 6. Compilation and verification | Bragi turn, mechanical | Plan, coverage witness, and independent coverage check | None |
| 7. Execution | Muninn and Heimdall readers | Receipts, tables, lineage, and completeness | None |
| 8. Epistemic assessment and rendering | Bragi | Per-goal status and a bilingual answer | None |

The compiler and verifier are mechanical Core components inside the Bragi-owned semantic turn.
They consume immutable manifest, catalog, and graph projections, make no agent calls, and publish
nothing; Saga keeps the existing turn audit. For a supported form, the compiler replaces the
capability-named intent and the model-authored frame and plan. An unsupported form returns the
exact missing atom and reason instead of the nearest existing capability.

## Verified baseline

The review traced one turn from `SemanticPlanningService.plan` in
[`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py)
to rendering in [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py).

| Stage | Where reasoning happens today | Gap |
|-------|-------------------------------|-----|
| Preflight | T1 picks one of nine closed operational families or `none` | No relation, aggregation, or epistemic axis, so a relational question can be promoted into a list or current-state family |
| Judgment | T1 picks a FunctionType name as `primary_intent`; target kind and facets are free tokens | Meaning outside a FunctionType name has no typed carrier, and the model guesses instance kinds such as `resource_group` |
| Frame | 22 deterministic builders, else a T1 frame model | `SemanticProblemFrame` has no anchor, relation, direction, aggregation, or prior-result field |
| Plan | 32 shape-specific compilers, else a T1 plan model | Compilers re-derive identities and windows from the utterance with regular expressions; the plan model fills recipes and can invent operands |
| Verifier | Exact manifest, endpoint chain, bounds, shape-to-node alignment | No semantic-preservation, operand-provenance, or instance-versus-schema check |
| Execution | Bounded secured ObjectSets, single-root traversal, stepwise typed paths | Traversal rows have no root lineage, and link evidence properties are redacted |
| Answer | Shape-specific templates; any incomplete receipt holds the turn | No per-goal epistemic status; follow-up context is prior-turn text only |

A bounded live planning probe on 2026-09-28 ran 36 English and Korean reasoning cases twice
through the production planning service with the active T1 profiles. It is a session-local design
input, not a governed receipt. Six cases per run answered the asked question. Fourteen to sixteen
cases produced a verified plan for a different question: the anchor itself instead of its
neighbors, schema relationships for an instance question, an inverted containment direction, a
region read as a name fragment, or an all-zero incident identity. The rest failed closed, and only
23 of 36 cases produced the same outcome in both runs.

The local development graph already held verified containment, attachment, dependency, routing,
and peering links for the probed anchors, each with verification metadata. Retained topology
history was empty, no workload or service composition links existed, and provider location existed
only inside the nested `properties` value. Most relational failures are compiler and contract gaps.

## Root causes

| Class | Root cause | Observed failures |
|-------|------------|-------------------|
| Contract and taxonomy gap | Closed types name capabilities, not meaning; relation, direction, aggregation, region, epistemic want, and prior-result reference have no closed field | Connected resources, dependents, containment, per-group counts, `among them`, `the first one` |
| Missing deterministic compiler | Per-shape recipes re-derive operands lexically, and no component maps a relation to reviewed LinkType sides or paths | Change attribution without an explicit window, `what is inside`, `which group contains`, service paths |
| Prompt | Recipe prompts ask the plan model to copy node shapes; prompt text cannot enforce provenance | All-zero incident identity, repeated judgment retries on invented canonical values |
| Data and reader absence | No retained topology history, workload mappings, alert or open-incident reader, cost observations, declared location property, or link-evidence projection | Topology diff, service impact, alerts, open incidents, region filters, verification status |

Prompt edits move a case between nearest capabilities but cannot create an operator, compiler, or
reader. The design adds contracts and deterministic components and shrinks the prompts.

## Question logical form

`SemanticQuestionForm` version `1.0.0` travels as the additive `question_form` field of
`SemanticJudgmentProposal` schema `1.3.0`. Every field is a closed enum, a bounded integer, a
mention reference, or an exact current-utterance span. The model never supplies a FunctionType, a
LinkType, an ObjectType operand, an object identifier, or a canonical instance value.

| Field | Closed values |
|-------|---------------|
| `mentions[].form` | `identifier`, `name`, `concept`, `value`, `anaphor`, `ordinal` |
| `mentions[].domain` | `instance`, `object_type`, `resource_type`, `resource_class`, `state`, `health`, `metric`, `region`, `declaration_kind` |
| `goals[].level` | `instance`, `schema` |
| `goals[].operation` | `select`, `count`, `lookup`, `traverse`, `path`, `aggregate`, `rank`, `history`, `compare_windows`, `diff_versions`, `explain_cause`, `verify_evidence`, `describe_schema`, `diagnose`, `draft_action` |
| `goals[].subject_scope` | `anchor`, `collection`, `prior_result`, `goal_output` |
| `filters[].role` | `type`, `state`, `health`, `region`, `name_fragment`, `scope` |
| `relation.sense` | `containment`, `attachment`, `dependency`, `connectivity`, `traffic`, `classification`, `composition`, `ownership`, `evidence` |
| `relation.scope` | `one_sense`, `all_kinds` |
| `relation.subject_position` | `source`, `target`, `either` |
| `relation.reach` | `one_hop`, `transitive` |
| `measure.kind` | `count`, `state`, `health`, `metric`, `change`, `event` |
| `measure.group_by` | `endpoint`, `type`, `container`, `none` |
| `time.kind` | `current`, `window`, `as_of`, `two_windows`, `versions`, `unspecified` |
| `want` | `fact`, `cause`, `verification`, `completeness` |

One form holds at most 16 mentions and 4 goals. Each goal carries a confidence and a cue span for
its operation and relation, and a goal may depend on an earlier goal. Ambiguity uses at most three
complete alternative forms, never one merged form.

Example: `Which resources depend on aks-prod-01?`

```yaml
question_form:
  mentions:
    - {id: m1, form: name, domain: instance, span: [26, 37]}
  goals:
    - id: g1
      level: instance
      operation: traverse
      subject: m1
      subject_scope: anchor
      relation: {sense: dependency, scope: one_sense, subject_position: target, reach: one_hop, cue: [16, 25]}
      time: {kind: current}
      want: fact
      confidence: 0.93
```

The model states that `aks-prod-01` is the target of a dependency. Core binds the anchor, selects
the `depends_on` LinkType through its reviewed `dependency` trait, and maps the target position to
the `depends_on.incoming` side.

## Admission

Bragi admits a proposed form only when every span matches the current utterance or a typed context
reference, every goal meets the configured confidence floor, no alternative form survives, the
level fits every mention domain, and each restrictive atom has a cue span. A failed admission
returns one clarification that lists the competing readings, or it sends a low-confidence level,
relation, direction, or referent to one independent T2 review that compares closed fields only.
After anchor binding, a sense that the bound anchor type cannot carry also returns a clarification.

Admission bounds model authority; it does not remove it. The model still chooses meaning among
closed types, so a wrong but self-consistent form is caught only by cue-span review, T2 review,
and the independent evaluation gold. The model never chooses identities, LinkTypes, path steps,
FunctionTypes, or answer claims.

## Deterministic compilation

### Concept resolution

Core resolves each `concept` or `value` mention only inside its declared domain, using reviewed
bilingual catalogs and the existing span normalization. FunctionTypes and ActionTypes are never
resolved from language; they follow from admitted operations and contracts.

- **Class closure**: A `resource_class` mention compiles through `query.resource_class_closure`
  into an exact `Resource.type` set and pins the closure receipt.
- **Cross-domain match**: `AKS ObjectType` declares domain `object_type`, but `AKS` exists only as
  the `kubernetes-cluster` `Resource.type` value. Core returns a clarification that names that
  candidate instead of substituting another declaration.
- **Ambiguity**: Two surviving values inside one domain return one clarification that names both.

### Anchor binding

An `identifier` or `name` mention with domain `instance` becomes an anchor. Binding is a two-phase
protocol:

1. After admission and manifest, purpose, and scope checks, Core verifies a single-node resolution
   plan: exact `id` or `name` equality, the principal scope, the current graph cutoff, and a limit
   of seven rows.
2. The executor reads one snapshot. The binding receipt pins the source generation, object
   revisions, cutoff, and release, manifest, and scope digests.
3. The compiled plan must reference that receipt digest and use exact `root_ids` or `object_ids`.
   The executor checks that the active source generation still equals the pinned one. Drift allows
   one recorded rebind and recompile, then holds.

| Result | Outcome |
|--------|---------|
| One object | Compile with exact ids and the bound ObjectType and `Resource.type` |
| Two to six objects | One clarification with bounded candidates |
| Seven objects | Incomplete clarification that asks the operator to narrow the name |
| None, complete source | Verified-scope absence with bounded name suggestions |
| None, incomplete source | Hold with the typed completeness reason |

The model never labels an instance as a resource group or a cluster; the bound type replaces that
guess. Replay resolves the same receipt against the retained snapshot or reports that the binding
is not reproducible.

### Relation compilation

A sense selects LinkTypes by reviewed `semantic_traits` and the bound anchor ObjectType.
`subject_position` maps through `forward_role` and `reverse_role` to the `outgoing` or `incoming`
query side, and stored direction is never rewritten. `transitive` reach requires a LinkType
declared transitive and self-composable, with depth at most five.

| Sense | Trait | Current LinkTypes |
|-------|-------|-------------------|
| `containment` | containment | `contains` |
| `attachment` | attachment | `attached_to` |
| `dependency` | dependency | `depends_on` |
| `connectivity` | connectivity | `peered_with`, `routes_to`, `kubernetes_exposes_endpoint_slice` |
| `traffic` | traffic | `routes_to`, `runtime_calls` |
| `classification` | classification | `resource_classified_as`, `resource_type_member_of_class` |
| `evidence` | evidence | `kubernetes_backed_by`, `capacity_forecast_targets_resource`, `cost_observation_targets_resource` |
| `composition` | new reviewed trait | `implemented_by`, `workload_runs_on` |
| `ownership` | new reviewed trait | `owns`, `service_owned_by`, `workload_owned_by` |

- **Unmapped links**: A LinkType without a reviewed trait is excluded and counted as
  `link_sense_unmapped`.
- **Paths**: A `path` goal uses only a reviewed, versioned path grammar, such as
  `BusinessService implemented_by Workload workload_runs_on Resource`. An offline search over
  manifest query sides may propose grammars for review, but the runtime never picks the shortest
  path on its own. Two applicable grammars return a clarification that shows both.
- **All kinds**: Ambiguous language such as `connected` yields alternative forms and one
  clarification, as [Hierarchical Conversation Planning](hierarchical-conversation-planning.md)
  requires. Only an explicit request for every relationship admits `scope: all_kinds`, which reads
  a bounded one-hop neighborhood and presents edges grouped by LinkType role, never as one merged
  relation.
- **Feasibility**: When the compiled side is empty and the opposite side has edges, the answer
  states that fact as a limitation and never flips the direction.

### Operators

| Operation | Compilation |
|-----------|-------------|
| `select`, `count`, `rank` | ObjectSet with grounded type, state, health, name-fragment, and scope predicates, then order, limit, or aggregate nodes |
| `lookup` | Anchor ObjectSet plus the FunctionType whose declared output covers the requested measure |
| `traverse` | ObjectSet with `root_ids` and traversal, or `typed_path` for endpoint-typed steps |
| `aggregate` | Traversal or ObjectSet plus an aggregate node; `endpoint` and `container` grouping require per-row root lineage |
| `history` | `query.resource_change_activity`, `query.resource_state_transitions`, or `query.resource_event_history` over the anchor |
| `compare_windows`, `diff_versions` | Two `topology_at` nodes plus `topology_diff`, or `query.ontology_release_diff` |
| `explain_cause` | Symptom measure, neighborhood changes, and causal support or refutation evidence |
| `verify_evidence` | Link-evidence projection for anchor relations, or `query.ontology_evidence_health` for scope completeness |
| `describe_schema` | `query.manifest`, `query.ontology_declaration`, `query.ontology_relationships`, or `query.resource_class_closure` |
| `diagnose` | A reviewed recipe selected by the bound `Resource.type` and the symptom concept |

- **Contracts**: FunctionType selection matches declared inputs, outputs,
  `x-fdai-measure-concepts`, and dependency-only arguments.
- **Aggregation identity**: Counts use distinct object identities by default, suppress duplicates
  across paths, count redacted endpoints as redacted, and stay incomplete when lineage or
  relationship coverage is incomplete.
- **Time**: Windows use trusted UTC and distinguish effective, event, and recorded time. An
  `unspecified` history window uses a version-pinned server default per operation.
- **Region**: A `region` filter compiles only after a declared `Resource.location` property exists;
  until then it is an unsupported atom, never a name predicate.
- **Diagnose**: A goal without an applicable recipe is unsupported instead of reusing a recipe for
  another resource type.

### Follow-up references

Core issues a `ResultSetHandle` after deterministic rendering, so it matches what the operator saw.
The opaque server-side handle binds the deployment scope, principal, conversation, purpose,
manifest digest, expiry, and rendered-order digest. It stores typed row keys with each row's
ObjectType, sort, page, and truncation metadata, and bounded rows. Operator persists handles with
the durable turn and sends at most four recent handle references as typed request context under
negotiated request and projection versions.

An `ordinal` or `anaphor` mention binds to handle rows after reauthorization. `current_rehydrate`
reads the exact ids at the current cutoff and labels the answer as current; `snapshot_reference`
answers only from the retained snapshot. A missing, expired, cross-conversation, deleted, or
out-of-range reference returns one clarification.

## Verification and evidence semantics

The compiler emits a `SemanticCoverageProof` as a witness. The verifier does not trust it. It
reconstructs the expected coverage from a versioned coverage-rule table in the catalog and from
typed node output lineage, and keeps every existing check:

- **V-SEM coverage**: Every operation, filter, relation, measure, order, time, and want atom maps
  to a node pattern required by its rule. A restrictive atom that cannot compile blocks its goal and
  dependents; it is never downgraded into a broader result.
- **V-SEM relation**: Traversal LinkTypes and sides equal the rule set for the bound anchor type
  and subject position.
- **V-PROV operands**: Every identity or literal operand cites a span, a binding receipt, a result
  handle, trusted server context, or a server default. An all-zero identifier has no provenance.
- **V-LEVEL**: An instance goal cannot resolve to schema-only functions, and a schema goal cannot
  read instances.
- **V-WANT**: A `cause` want must satisfy the causal conditions in
  [Temporal and causal questions](hierarchical-conversation-planning.md#temporal-and-causal-questions)
  and keep named alternatives. Otherwise the goal is limited to temporal distance and cannot claim
  a cause.

Each goal receives a runtime status from the `EpistemicStatus` vocabulary in
[`epistemic_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/epistemic_coverage.py).
`VERIFIED_EMPTY` needs closed-population proof: complete source, no truncation, and complete
relationship coverage for the compiled LinkTypes. Any other empty result is `UNKNOWN_INCOMPLETE`
and says that no match exists in the verified scope. Missing workload mappings are unavailable, not
empty. One failed goal does not hide verified sibling goals, and the answer lists every unknown
atom. Link evidence uses a reviewed projection allowlist of `verified`, `verification_method`,
authority, effective time, freshness ceiling, and completeness, and a visible link still cannot
reveal a hidden endpoint.

## Model role

| Decision | Today | Target |
|----------|-------|--------|
| Question meaning | Capability name plus free facet tokens | Closed logical form with cue spans and admission |
| Instance kind of a named object | Model target kind | Anchor binding |
| Relation direction | Frame or plan model | Admitted position mapped to a reviewed side |
| Path and LinkType set | Plan model or fixed recipe | Reviewed traits and path grammars |
| Operands | Utterance regular expressions or the plan model | Spans, bindings, handles, and server defaults |
| Answer claims | Shape templates | Independent coverage check plus epistemic status |

The judgment prompt keeps the protected root and describes the closed form, span and cue rules,
and bilingual examples per operation. It no longer needs the FunctionType capability catalog for
read goals. Frame and plan model calls retire for compiled forms. The plan model stays shadow-only
for uncompiled forms, and its output must pass V-SEM and V-PROV. T2 never authors a plan. The unused
`query.<LinkType>` intent affordance is removed.

## Alternatives and critique

| Alternative | Decision | Reason |
|-------------|----------|--------|
| Add recipes and prompt packs per failing question | Rejected | Grows with question count, keeps lexical re-derivation, and still drops unmodeled atoms |
| Agentic T2 traversal with tool calls | Rejected | The model would compute paths, weakening determinism, provenance, and replay |
| Model-generated graph query text | Rejected | Raw query text is outside the plan contract and hard to verify |
| Embedding authority for concepts | Rejected | Similarity can propose candidates only |
| Logical form plus deterministic compiler | Selected | Keeps the model on closed classification and moves binding, paths, and claims to code |

An independent review of the first draft found these defects; each revision is part of this design:

| Finding | Revision |
|---------|----------|
| Overstated removal of model authority | Admission, cue spans, per-goal confidence, optional closed-field T2 review, and a narrowed claim |
| Lexical concept inference | `mentions[].domain`, domain-restricted resolution, and clarification for cross-domain matches |
| Merged `connected` answers | No sense `any`; ambiguity clarifies, and only an explicit request admits `all_kinds` |
| Self-certified coverage | Independent rule-based coverage, blocking restrictive atoms, and the full causal conditions |
| Binding race | Two-phase snapshot protocol, receipt pinning, and seven-row truncation detection |
| Unsafe handles | Conversation, purpose, manifest, and rendered-order binding with explicit modes |
| Unclear ownership and shortest-path guessing | Named agents per stage and reviewed path grammars |
| Weak statistics and missing prerequisites | Locked holdout, independent gold, floors, intervals, a contract round, and data gates |

## Evaluation

The reasoning cohort extends the live planning harness and adds a deterministic execution level.

| Aspect | Contract |
|--------|----------|
| Types | Closure, relations, reviewed paths, containment, time and versions, cause versus correlation, evidence verification, relational aggregation, follow-up, and schema versus instance |
| Size | Per type, at least 12 development and 8 locked holdout cases split by locale, including three honest negative cases and multi-turn follow-up cases |
| Gold | Two reviewers adjudicate form atoms, LinkType set and side, node kinds, the epistemic status on a generic fixture graph, and forbidden outcomes |
| Robustness | Metamorphic wording, locale, name, and order variants; adversarial duplicate names, empty or truncated neighborhoods, and redacted endpoints |
| Levels | L1 measures live T1 form accuracy; L2 runs admission, compilation, and execution over the frozen fixture graph without a model |
| Hard zeros | Silent semantic loss against the gold, operands without provenance, wrong-level answers, causal claims without causal evidence, and unauthorized execution |
| Measured | Atom accuracy, form stability, L2 correctness, honest-reason precision, clarification precision and recall, model calls, and p95 latency from at least 100 turns |

The session-local 68-case prompt corpus moves into the repository with level, forbidden-function,
and required-atom checks, so a wrong verified plan no longer passes. An A/A run of the current profiles differed by 1.5 points, so
paired comparisons use at least three repeats, bootstrap confidence intervals, and a 3-point noise
band. Zero hard failures in about 60 holdout turns bounds the true rate below about 5% at 95%
confidence, so shadow operation also samples live turns for human review before promotion.

## Delivery rounds

| Round | Scope | Exit evidence |
|-------|-------|---------------|
| R0 | Cohort, holdout, fixture graph, strict gold, production-faithful function binding in the harness | Baseline L1 and L2 receipts |
| R1 | Form, admission, binding, handle, and coverage-rule contracts with version negotiation | Codec and N/N-1 tests; no behavior change |
| R2 | Interim V-PROV and V-LEVEL over existing typed judgment fields | Zero invented identity literals and zero schema answers to instance targets on both corpora |
| R3 | Shadow form judgment and admission | Atom accuracy of at least 90% and stability of at least 90% per type on the holdout |
| R4 | Concept resolver and anchor binding protocol | L2 binding correctness 100% on the fixture graph |
| R5 | Relation compiler after trait review, path grammars, and traversal root lineage | Shadow relation and containment holdout at least 85% with hard zeros |
| R6 | Aggregation, rank, and diagnose recipes; region after the location property ships | Shadow aggregation and diagnose holdouts pass hard zeros |
| R7 | History, versions, cause, and verification after the link-evidence allowlist | Typed unavailability for absent history; zero causal claims without causal evidence |
| R8 | Result handles after a threat review | Follow-up holdout at least 85%; zero cross-conversation bindings |
| R9 | Promotion per operation family through the promotion registry | Promotion receipt per family; frame and plan prompts retired for promoted families |
| R10 | Removal of lexical re-derivation in promoted paths | Replay equivalence and one stable rollback release |

Every round implements, runs focused tests, runs L1 with at least two repeats and L2, fixes
regressions, and appends a ledger row. The form path runs in shadow beside the current path and
records only digests and dispositions. A family is promoted only when hard zeros hold on all
repeats and sampled shadow turns, holdout correctness meets its absolute floor and beats the current
path outside the noise band, English and Korean differ by at most 5 points, p95 latency does not
rise, and the 68-case corpus does not regress beyond noise. Rollback restores the previous registry
entry, and the current path stays intact until R10.

## Decisions requiring approval

1. Carry the form in the same judgment call as an additive field.
2. Allow the two-phase anchor binding read before compilation.
3. Keep clarification for ambiguous relations and admit `all_kinds` only on explicit request.
4. Require T2 state review only when a state span is not catalog-grounded.
5. Own version-pinned default history windows in configuration.
6. Declare `Resource.location` with a reviewed provider-region value domain.
7. Expose the reviewed link-evidence allowlist through the secured projection.
8. Persist result handles and add them to the semantic request contract.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-compiler.md) |
| Highest design authority | [FDAI Constitution](../architecture/fdai-constitution.md) |
| Current semantic turn path | [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) |
| Query contracts and work packages | [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md) |
| LinkType roles, traits, typed paths, and closure | [Ontology Structural Model](../architecture/ontology-structural-model.md) |
| ObjectSets and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Graph freshness and completeness | [Continuous Operational Instance Graph](../architecture/continuous-operational-instance-graph.md) |
| Question universe and assurance | [Continuous Question Space](continuous-question-space.md) |
| Prompt profiles and dynamic assembly | [Evolving System Prompt](../decisioning/prompt-composition.md) |
