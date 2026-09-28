---
title: Ontology Reasoning Compiler
---
# Ontology Reasoning Compiler

This document owns the target design that turns an operator question into a closed, span-grounded
question logical form and compiles it deterministically into a verified ontology query plan. The
model understands the question, grounds concepts in complete catalogs, and phrases the answer. Code
validates that meaning, binds anchors, selects reviewed paths, and verifies every claim it shows.

> **Status:** Approved design, 2026-09-28. An initial, partial shadow implementation covers selected
> operations and is unwired from the production turn; the
> [ledger](../../roadmap-implementation/interfaces/ontology-reasoning-compiler.md) records scope,
> measured coverage, and deviations. The current runtime is described in
> [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) and
> [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md).
> Coverage targets and measured limits belong to [Ontology Reasoning Coverage](ontology-reasoning-coverage.md).
>
> **Authority boundary:** Logical forms, admission and compile receipts, anchor bindings, result
> handles, and plans are read-only records with `execution_authority=false`. An explicit change
> request still produces only the existing typed action draft.

## Design at a glance

| Stage | Accountable agent | Output | Model use |
|-------|-------------------|--------|-----------|
| 1. Conversation preflight | Bragi | Social, knowledge, and operational routing | T1, unchanged |
| 2. Logical-form judgment | Bragi | Proposed `SemanticQuestionForm` | T1, one call plus at most one schema repair |
| 3. Admission | Bragi | Admitted form, clarification, or review request | Optional T2 review |
| 4. Concept grounding | Bragi, over Mimir catalogs | One canonical concept per mention from the complete domain catalog | T1 over exhaustive catalog shards |
| 5. Anchor binding | Muninn | Exact identities pinned to one snapshot | None, one bounded read |
| 6. Compilation and verification | Bragi turn, mechanical | Plan, coverage witness, and independent coverage check | None |
| 7. Execution | Muninn and Heimdall readers | Receipts, tables, lineage, and completeness | None |
| 8. Answer composition | Bragi | Evidence-bound claims, per-goal status, and a bilingual answer | T1 author, V-CLAIM, independent T1 review |

The compiler and verifier are mechanical Core components inside the Bragi-owned semantic turn. They
consume immutable projections, make no agent calls, and publish nothing; Saga keeps the turn audit.
A supported form replaces the capability-named intent and the model-authored frame and plan, and an
unsupported form returns the exact missing atom and reason instead of the nearest capability.

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

A bounded two-run live planning probe of 36 English and Korean reasoning cases on 2026-09-28, a
session-local design input rather than a governed receipt, answered six cases per run as asked.
Fourteen to sixteen cases produced a verified plan for a different question: the anchor instead of
its neighbors, schema relationships for an instance question, inverted containment, a region read
as a name fragment, or an all-zero incident identity. Only 23 cases were stable across runs. The
local graph already held verified links for the probed anchors, so most relational failures are
compiler and contract gaps; [Ontology Reasoning Coverage](ontology-reasoning-coverage.md#measured-baseline)
records the measured data and capacity limits.

## Root causes

| Class | Root cause | Observed failures |
|-------|------------|-------------------|
| Contract and taxonomy gap | Closed types name capabilities, not meaning; relation, direction, aggregation, region, epistemic want, and prior-result reference have no closed field | Connected resources, dependents, containment, per-group counts, `among them`, `the first one` |
| Missing deterministic compiler | Per-shape recipes re-derive operands lexically, and no component maps a relation to reviewed LinkType sides or paths | Change attribution without an explicit window, `what is inside`, `which group contains`, service paths |
| Prompt | Recipe prompts ask the plan model to copy node shapes; prompt text cannot enforce provenance | All-zero incident identity, repeated judgment retries on invented canonical values |
| Data and reader absence | No retained topology history, workload mappings, alert or open-incident reader, cost observations, declared location property, or link-evidence projection | Topology diff, service impact, alerts, open incidents, region filters, verification status |

## Question logical form

`SemanticQuestionForm` version `1.0.0` travels as the additive `question_form` field of
`SemanticJudgmentProposal` schema `1.3.0`. Every field is a closed enum, a bounded integer, a
mention reference, or a quoted phrase with its occurrence number, which Core binds to an exact
span. The model never supplies a FunctionType, LinkType, ObjectType operand, or instance value.

| Field | Closed values |
|-------|---------------|
| `mentions[].form` | `identifier`, `name`, `concept`, `value`, `anaphor`, `ordinal` |
| `mentions[].domain` | `instance`, `object_type`, `resource_type`, `resource_class`, `state`, `health`, `metric`, `region`, `declaration_kind` |
| `mentions[].qualifier` | One earlier mention id plus a relation sense, such as a subnet name inside a named network |
| `goals[].level` | `instance`, `schema` |
| `goals[].operation` | `select`, `count`, `lookup`, `traverse`, `path`, `aggregate`, `rank`, `history`, `compare_windows`, `compare_entities`, `diff_versions`, `impact`, `explain_cause`, `verify_evidence`, `describe_schema`, `diagnose`, `draft_action` |
| `goals[].subject_scope` | `anchor`, `collection`, `prior_result`, `goal_output` |
| `filters[].role` | `type`, `state`, `health`, `region`, `name_fragment`, `scope` |
| `relation.sense` | `containment`, `attachment`, `dependency`, `connectivity`, `traffic`, `classification`, `composition`, `ownership`, `authorization`, `evidence` |
| `relation.scope` | `one_sense`, `all_kinds` |
| `relation.anchor` | The mention the relation starts from; omitted when it is the goal subject |
| `relation.anchor_role`, `relation.result_role` | Both ends of the sense, such as `container` and `member` or `dependent` and `dependency`; `either` for both |
| `relation.reach` | `one_hop`, `transitive` |
| `measure.kind` | `count`, `state`, `health`, `metric`, `change`, `event`, `forecast`, `cost` |
| `measure.group_by` | `endpoint`, `type`, `container`, `none` |
| `time.kind` | `current`, `window`, `as_of`, `two_windows`, `versions`, `future`, `unspecified` |
| `want` | `fact`, `cause`, `verification`, `completeness` |

One judgment pass holds at most 16 mentions and 4 goals within 6 KiB. Each goal carries a
confidence and a cue span for its operation and relation, and may depend on an earlier goal. A
larger question is judged in successive passes until every goal is accounted. Ambiguity uses at most
three alternatives, each an atom diff of at most six atoms, never one merged form.

Example: `Which resources depend on aks-prod-01?`

```yaml
question_form:
  mentions: [{id: m1, form: name, domain: instance, span: {text: aks-prod-01, occurrence: 1}}]
  goals:
    - {id: g1, level: instance, operation: traverse, subject: m1, subject_scope: anchor,
       relation: {sense: dependency, anchor_role: dependency, result_role: dependent,
                  cue: {text: depend on, occurrence: 1}}, confidence: 0.93}
```

The model states only that `aks-prod-01` is the dependency and the results are its dependents.
Core binds the anchor, selects `depends_on` through its `dependency` trait, and reads `incoming`.

## Admission

Bragi admits a form only when every span matches the utterance without cutting through a longer
identifier, every goal meets the confidence floor, no alternative survives, both relation roles are
the ends of one sense, every declared mention is used, and the level fits every mention domain.
Otherwise it returns one clarification or sends a low-confidence field to one independent T2 review
of closed fields. An admitted atom that no reviewed builder reads, such as a qualifier or a stated
counterpart, returns a typed unsupported reason; it is never ignored.

A form that breaks its closed schema or a structural rule gets at most one repair call with the
code-authored violations. The repaired form passes the same admission and must keep every quoted
operand, goal, operation, want, typed time, operand-bearing relation, competing reading, and
pending-goals signal of the rejected proposal; otherwise the original fault stands. These fields
compare as the closed schema normalizes them, and a proposal that never parsed keeps any stated
pending-goals value and fails closed on an unreadable want. Clarifications are answers to the
operator and are never repaired.

Admission bounds model authority; it does not remove it. A wrong but self-consistent form is caught
only by cue-span review, T2 review, the restated interpretation and confirm-first cells in
[calibrated admission](ontology-reasoning-coverage.md#calibrated-admission), and the evaluation
gold. The model never chooses identities, LinkTypes, path steps, FunctionTypes, or answer claims.

## Deterministic compilation

### Concept selection

The model grounds each non-referential mention inside its declared domain. Core presents the
complete candidate catalog, with reviewed labels, in as many bounded shards as the budget needs; the
model evaluates every shard, and a receipt proves each candidate was presented exactly once. Core
accepts an identifier only from the shard that presented it. Finalists that differ across shards
meet in one runoff call. Labels are model context, never a lookup table, and an explicit root
candidate stands for resources in general. FunctionTypes and ActionTypes follow from operations.

- **Class closure**: A `resource_class` mention compiles through `query.resource_class_closure`
  into an exact `Resource.type` set and pins the closure receipt.
- **Cross-domain match**: `AKS ObjectType` declares domain `object_type`, but the model finds `AKS`
  only among `Resource.type` candidates as `kubernetes-cluster`. Core returns a clarification that
  names that candidate instead of substituting another declaration.
- **Ambiguity**: Two surviving candidates in one domain return one clarification that names both.

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
guess. A mention with a `qualifier` binds its qualifier first and then searches only inside that
qualifier's containment or type scope, so a shared name such as a default subnet stays exact.
Replay resolves the same receipt or reports that the binding is not reproducible.

### Relation compilation

A sense selects LinkTypes by reviewed `semantic_traits` and the bound anchor ObjectType. A reviewed
sense-role convention names the role of each stored end, such as container for the `from` end of a
containment link, so the anchor role selects `outgoing` or `incoming` without rewriting stored
direction. Stated roles that are not the two ends of the sense return a clarification.
`transitive` reach requires a LinkType declared transitive and self-composable, depth at most five.

| Sense | Trait | Current LinkTypes |
|-------|-------|-------------------|
| `containment` | containment | `contains` |
| `attachment` | attachment | `attached_to` |
| `dependency` | dependency | `depends_on` |
| `connectivity` | connectivity | `peered_with`, `routes_to`, `kubernetes_exposes_endpoint_slice` |
| `traffic` | traffic | `routes_to`, `runtime_calls` |
| `classification` | classification | `resource_classified_as`, `resource_type_member_of_class` |
| `evidence` | evidence | `kubernetes_backed_by`, `capacity_forecast_targets_resource`, `cost_observation_targets_resource` |
| `composition`, `ownership`, `authorization` | reviewed traits pending | `implemented_by`, `workload_runs_on`, `owns`, `service_owned_by` |

- **Unmapped links**: A LinkType without a reviewed trait is excluded and named as
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
| `select`, `count`, `rank` | ObjectSet with grounded type, state, health, name-fragment, and scope predicates, then order and limit nodes; inventory-wide counts use the secured aggregate pushdown |
| `lookup` | Anchor ObjectSet plus the FunctionType whose declared output covers the requested measure, including forecast and cost readers when bound |
| `traverse` | ObjectSet with `root_ids` and traversal, or `typed_path` for endpoint-typed steps |
| `aggregate` | Traversal or ObjectSet plus an aggregate node; `endpoint` and `container` grouping require per-row root lineage |
| `history` | `query.resource_change_activity`, `query.resource_state_transitions`, or `query.resource_event_history` over the anchor |
| `compare_windows`, `diff_versions` | Two `topology_at` nodes plus `topology_diff`, or `query.ontology_release_diff` |
| `compare_entities` | Two anchors of one ObjectType read with the same measure at one pinned cutoff |
| `impact` | Reverse dependency and composition closure from the anchor; the answer states possible impact, never observed impact |
| `explain_cause` | Symptom measure, neighborhood changes, and causal support or refutation evidence |
| `verify_evidence` | Link-evidence projection for anchor relations, or `query.ontology_evidence_health` for scope completeness |
| `describe_schema` | `query.manifest`, `query.ontology_declaration`, `query.ontology_relationships`, or `query.resource_class_closure` |
| `diagnose` | A reviewed recipe selected by the bound `Resource.type` and the symptom concept |

- **Contracts**: FunctionType selection matches declared inputs, outputs,
  `x-fdai-measure-concepts`, and dependency-only arguments.
- **Aggregation identity**: Counts use distinct object identities, suppress duplicates across
  paths, exclude hidden objects from totals and connectivity without reporting them, and stay
  incomplete when lineage or relationship coverage is incomplete.
- **Time**: The model proposes typed values, such as an amount-and-unit duration or a calendar
  offset in the operator's time zone, with spans. Code computes trusted UTC instants, keeps
  effective, event, and recorded time distinct, and uses a version-pinned default for `unspecified`.
- **Plan batches**: Goals beyond one plan's 32 nodes or 8 outputs compile into ordered plan batches
  under one turn budget; remaining batches continue as a bounded continuation of verified segments.
- **Unsupported atoms**: A `region` filter compiles only after a declared `Resource.location`
  property exists, and a `diagnose` goal without an applicable recipe never reuses another type's
  recipe. Both return a typed unsupported atom instead of a name predicate or a substitute.
- **Schema reads**: A schema relation is answered only by the one-hop `query.ontology_relationships`
  read of the subject ObjectType's own LinkTypes in both directions, and a manifest count groups only
  by declaration kind. Any other schema relation, direction, counterpart, reach, anchor, or grouping
  returns a typed unsupported reason, and V-SEM rejects it independently.

### Follow-up references

Core issues a `ResultSetHandle` after deterministic rendering, so it matches what the operator saw.
The opaque server-side handle binds the deployment scope, principal, conversation, purpose,
manifest digest, expiry, and rendered-order digest, and stores typed row keys, sort, page, and
truncation metadata. Operator persists handles with the durable turn and sends at most four recent
handle references as typed request context under negotiated versions. An `ordinal` or `anaphor`
mention binds to handle rows after reauthorization. `current_rehydrate` rereads the exact ids at the
current cutoff and labels the answer as current; `snapshot_reference` answers only from the
retained snapshot. A missing, expired, cross-conversation, deleted, or out-of-range reference
returns one clarification.

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
| Concepts, values, and time | Term lists, lexical ranking, and regular expressions | Model choice from complete catalog shards and typed values, validated by code |
| Operands | Utterance regular expressions or the plan model | Spans, bindings, handles, and server defaults |
| Answer prose | Shape templates in code | Model-authored claims that pass V-CLAIM and independent review |

The judgment prompt keeps the protected root and describes only the closed form, span and cue rules,
and bilingual examples per operation, without the FunctionType catalog for read goals. Frame and
plan model calls retire for compiled forms; the plan model stays shadow-only for uncompiled forms
and must pass V-SEM and V-PROV. T2 never authors a plan, and the unused `query.<LinkType>` intent
affordance is removed.

## Alternatives and critique

| Alternative | Decision | Reason |
|-------------|----------|--------|
| Add recipes and prompt packs per failing question | Rejected | Grows with question count, keeps lexical re-derivation, and still drops unmodeled atoms |
| Agentic T2 traversal with tool calls | Rejected | The model would compute paths, weakening determinism, provenance, and replay |
| Model-generated graph query text | Rejected | Raw query text is outside the plan contract and hard to verify |
| Embedding authority for concepts | Rejected | Similarity can propose candidates only |
| Deterministic answer templates | Rejected | Rigid prose misses the operator's question and cannot meet the SRE Agent bar; verified model-authored claims keep facts exact |
| Logical form plus deterministic compiler | Selected | Keeps the model on closed classification and moves binding, paths, and claims to code |

An independent review of the first draft found these defects; each revision is part of this design:

| Finding | Revision |
|---------|----------|
| Overstated model authority and lexical concept inference | Admission, cue spans, per-goal confidence, closed-field T2 review, and domain-restricted grounding |
| Merged `connected` answers and shortest-path guessing | Clarification for ambiguity, explicit `all_kinds`, and reviewed path grammars |
| Self-certified coverage and binding races | Independent rule-based coverage, blocking restrictive atoms, and the two-phase snapshot protocol |
| Unsafe handles, unclear ownership, and weak statistics | Bound handles, named agents, a locked holdout, independent gold, and confidence intervals |
| Capacity review: duplicate names, output budget, missing question shapes | Qualified mentions, atom-diff alternatives, and the taxonomy additions in [Ontology Reasoning Coverage](ontology-reasoning-coverage.md#question-taxonomy-closure) |
| Owner directives: no lexical meaning, no template answers, nothing dropped by a bound | Model grounding over complete shards, evidence-bound composition with V-CLAIM, successive passes, and plan batches |

## Answer composition

Bragi's T1 author writes every answer, including the interpretation restatement, from the admitted
form, verified evidence tables, per-goal epistemic statuses, and typed limitation codes. No answer
prose comes from code templates; only catalog notices and verified data views render without the
model, and they add no fact. The author returns structured claims, shown only after verification.

| Claim field | Contract |
|-------------|----------|
| `kind` | `restatement`, `fact`, `count`, `relation`, `state`, `change`, `cause_hypothesis`, `limitation`, or `next_check` |
| `refs` | Evidence cells or limitation codes that support the claim |
| `proposition` | Canonical subject, predicate with direction, object or value, polarity, comparator or quantifier, unit, temporal basis and time zone, modality, and rounding |
| `spans` | The exact text span of every surface phrase and literal, bound to the proposition |
| `rows` | For list and count goals, the row identifiers that the claim names or aggregates |

V-CLAIM compares names through canonical identities, never substrings. It rejects an answer when a
claim lacks references, a proposition or literal differs from its evidence, a literal is undeclared,
a required limitation, goal, or form atom is missing, a count differs from the authoritative count,
a result row is neither named, aggregated, nor listed in the complete table, or a cause claim lacks
causal evidence. An independent T1 reviewer then checks entailment. A rejected answer regenerates
once with typed reasons, then holds with the verified evidence view. Evidence larger than one author
call is composed in bounded chunks and synthesized under the same row account. Evaluation and the
parity gate belong to [Ontology Reasoning Coverage](ontology-reasoning-coverage.md#assurance-and-sre-agent-parity).

## Delivery rounds

| Round | Scope | Exit evidence |
|-------|-------|---------------|
| R0 | Cohort, holdout, fixture graph, strict gold, a production-faithful harness, and an Azure SRE Agent baseline | Baseline L1, L2, and parity receipts |
| R1 | Form, admission, concept-selection, binding, handle, coverage-rule, evidence-manifest, pushdown, and claim contracts with version negotiation | Codec and N/N-1 tests; no behavior change |
| R2 | Interim V-PROV and V-LEVEL over existing typed judgment fields, plus resource-group membership through `contains` from the exact group | Zero invented identity literals, zero schema answers to instance targets, and membership equal to `contains` closure on the fixture graph |
| R3 | Shadow form judgment, admission, and concept selection over complete shards | Atom and concept accuracy and stability of at least 90% per type on the holdout |
| R4 | Anchor binding protocol and typed temporal values | L2 binding and time correctness 100% on the fixture graph |
| R5 | Relation compiler after trait review, path grammars, and traversal root lineage | Shadow relation and containment holdout at least 85% with hard zeros |
| R6 | Aggregation, rank, and diagnose recipes; region after the location property ships | Shadow aggregation and diagnose holdouts pass hard zeros |
| R7 | History, versions, cause, and verification after the link-evidence allowlist | Typed unavailability for absent history; zero causal claims without causal evidence |
| R8 | Result handles after a threat review, and evidence-bound answer composition | Follow-up holdout at least 85%; zero cross-conversation bindings; zero V-CLAIM escapes |
| R9 | Promotion per operation family through the promotion registry | Promotion and SRE Agent parity receipts per family; frame and plan prompts retired for promoted families |
| R10 | Removal of lexical re-derivation and template renderers in promoted paths | Replay equivalence and one stable rollback release |

Every round implements, runs focused tests, runs L1 with at least two repeats and L2, fixes
regressions, and appends a ledger row. The form path runs in shadow beside the current path and
records only digests and dispositions. A family is promoted only when hard zeros hold on all
repeats and sampled shadow turns, holdout correctness meets its absolute floor and beats the current
path outside the noise band, English and Korean differ by at most 5 points, p95 latency does not
rise, SRE Agent parity holds, and the 68-case corpus does not regress. Rollback restores the
previous registry entry, and the current path stays intact until R10. The per-family lanes in
[Ontology Reasoning Coverage](ontology-reasoning-coverage.md#closure-program) gate these rounds.

## Approved decisions

The Owner approved these decisions on 2026-09-28.

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
| Coverage guarantees, measured limits, and closure program | [Ontology Reasoning Coverage](ontology-reasoning-coverage.md) |
| Highest design authority | [FDAI Constitution](../architecture/fdai-constitution.md) |
| Current semantic turn path | [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) |
| Query contracts and work packages | [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md) |
| LinkType roles, traits, typed paths, and closure | [Ontology Structural Model](../architecture/ontology-structural-model.md) |
| ObjectSets and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Graph freshness and completeness | [Continuous Operational Instance Graph](../architecture/continuous-operational-instance-graph.md) |
| Question universe and assurance | [Continuous Question Space](continuous-question-space.md) |
| Prompt profiles and dynamic assembly | [Evolving System Prompt](../decisioning/prompt-composition.md) |
