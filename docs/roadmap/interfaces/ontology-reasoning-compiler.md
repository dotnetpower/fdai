---
title: Ontology Reasoning Compiler
---
# Ontology Reasoning Compiler

This document owns the target design that turns an operator question into a closed, span-grounded question logical form and compiles it
deterministically into a verified ontology query plan. The model understands the question, grounds concepts in complete catalogs, and phrases the
answer. Code validates that meaning, binds anchors, selects reviewed paths, and verifies every claim it shows.

> **Status:** Approved design, 2026-09-28. An initial, partial shadow implementation covers selected operations
> and is unwired from the production turn; the [ledger](../../roadmap-implementation/interfaces/ontology-reasoning-compiler.md)
> records scope, measured coverage, and deviations. The current runtime is described in
> [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) and
> [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md). Coverage targets and
> measured limits belong to [Ontology Reasoning Coverage](ontology-reasoning-coverage.md).
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
| 3a. Constraint review | Bragi | Blind constraint extraction compared with the admitted form | T1 of another model family, one call beside the judgment |
| 4. Concept grounding | Bragi, over Mimir catalogs | One canonical concept per mention from the complete domain catalog | T1 over exhaustive catalog shards |
| 5. Anchor binding | Muninn | Exact identities pinned to one snapshot | None, one bounded read |
| 6. Compilation and verification | Bragi turn, mechanical | Plan, coverage witness, and independent coverage check | None |
| 7. Execution | Muninn and Heimdall readers | Receipts, tables, lineage, and completeness | None |
| 8. Answer composition | Bragi | Evidence-bound claims, per-goal status, and a bilingual answer | T1 author, V-CLAIM, independent T1 review |

The compiler and verifier are mechanical Core components inside the Bragi-owned semantic turn. They consume immutable projections, make no agent
calls, and publish nothing; Saga keeps the turn audit. A supported form replaces the capability-named intent and the model-authored frame and plan,
and an unsupported form returns the exact missing atom and reason instead of the nearest capability.

## Verified baseline

The review traced one turn from `SemanticPlanningService.plan` in
[`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py) to rendering in
[`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py).

| Stage | Where reasoning happens today | Gap |
|-------|-------------------------------|-----|
| Preflight | T1 picks one of nine closed operational families or `none` | No relation, aggregation, or epistemic axis, so a relational question can be promoted into a list or current-state family |
| Judgment | T1 picks a FunctionType name as `primary_intent`; target kind and facets are free tokens | Meaning outside a FunctionType name has no typed carrier, and the model guesses instance kinds such as `resource_group` |
| Frame | 22 deterministic builders, else a T1 frame model | `SemanticProblemFrame` has no anchor, relation, direction, aggregation, or prior-result field |
| Plan | 32 shape-specific compilers, else a T1 plan model | Compilers re-derive identities and windows from the utterance with regular expressions; the plan model fills recipes and can invent operands |
| Verifier | Exact manifest, endpoint chain, bounds, shape-to-node alignment | No semantic-preservation, operand-provenance, or instance-versus-schema check |
| Execution | Bounded secured ObjectSets, single-root traversal, stepwise typed paths | Traversal rows have no root lineage, and link evidence properties are redacted |
| Answer | Shape-specific templates; any incomplete receipt holds the turn | No per-goal epistemic status; follow-up context is prior-turn text only |

A bounded two-run live planning probe of 36 English and Korean reasoning cases on 2026-09-28, a session-local design input rather than a governed
receipt, answered six cases per run as asked. Fourteen to sixteen cases produced a verified plan for a different question: the anchor instead of its
neighbors, schema relationships for an instance question, inverted containment, a region read as a name fragment, or an all-zero incident identity.
Only 23 cases were stable across runs. The local graph already held verified links for the probed anchors, so most relational failures are compiler
and contract gaps; [Ontology Reasoning Coverage](ontology-reasoning-coverage.md#measured-baseline) records the measured data and capacity limits.

## Root causes

| Class | Root cause | Observed failures |
|-------|------------|-------------------|
| Contract and taxonomy gap | Closed types name capabilities, not meaning; relation, direction, aggregation, region, epistemic want, and prior-result reference have no closed field | Connected resources, dependents, containment, per-group counts, `among them`, `the first one` |
| Missing deterministic compiler | Per-shape recipes re-derive operands lexically, and no component maps a relation to reviewed LinkType sides or paths | Change attribution without an explicit window, `what is inside`, `which group contains`, service paths |
| Prompt | Recipe prompts ask the plan model to copy node shapes; prompt text cannot enforce provenance | All-zero incident identity, repeated judgment retries on invented canonical values |
| Data and reader absence | No retained topology history, workload mappings, alert or open-incident reader, cost observations, declared location property, or link-evidence projection | Topology diff, service impact, alerts, open incidents, region filters, verification status |

## Question logical form

`SemanticQuestionForm` version `1.0.0` travels as the additive `question_form` field of `SemanticJudgmentProposal` schema `1.3.0`. Every field is a
closed enum, a bounded integer, a mention reference, or a quoted phrase with its occurrence number, which Core binds to an exact span. The model never
supplies a FunctionType, LinkType, ObjectType operand, or instance value.

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
| `relation.reach_cue` | Optional quote of reach words that stand apart from the relation words |
| `measure.kind` | `count`, `state`, `health`, `metric`, `change`, `event`, `forecast`, `cost` |
| `measure.group_by` | `endpoint`, `type`, `container`, `none` |
| `time.kind` | `current`, `window`, `as_of`, `two_windows`, `versions`, `future`, `unspecified` |
| `want` | `fact`, `cause`, `verification`, `completeness` |
| `filters[].cue`, `measure.cue` | Optional quotes of the words that state a restriction, a measure, or a grouping |
| `context` | At most 32 quotes of words that state no constraint |
| `unsupported_constraints` | At most 8 quotes of words that state a constraint no closed field expresses; any one clarifies |

One judgment pass holds at most 16 mentions and 4 goals within 6 KiB. Each goal carries a confidence and a cue span for its operation and relation,
and may depend on an earlier goal. A larger question is judged in successive passes until every goal is accounted. Ambiguity uses at most three
alternatives, each an atom diff of at most six atoms, never one merged form.

Example: `Which resources depend on aks-prod-01?`

```yaml
question_form:
  mentions: [{id: m1, form: name, domain: instance, span: {text: aks-prod-01, occurrence: 1}}]
  goals:
    - {id: g1, level: instance, operation: traverse, subject: m1, subject_scope: anchor,
       relation: {sense: dependency, anchor_role: dependency, result_role: dependent,
                  cue: {text: depend on, occurrence: 1}}, confidence: 0.93}
```

The model states only that `aks-prod-01` is the dependency and the results are its dependents. Core binds the anchor, selects `depends_on` through its
`dependency` trait, and reads `incoming`.

## Admission

Bragi admits a form only when every span matches the utterance without cutting through a longer identifier, every goal meets the confidence floor, no
alternative survives, both relation roles are the ends of one sense, every declared mention is used, no two mentions share words, no group is both a
goal's scope and its relation anchor unless the relation is a containment from that group to its members, which only restates the scope's whole
membership and is read as that membership, every qualifier places one named instance inside another named instance, and the level fits every
mention domain. A relation anchored on the named subject of a lookup, history, or cause goal only restates that subject, as in the operations
in aks-app, and a stated failure state of an impact goal only restates its premise; neither is an unread atom. A kind, a
state, or a container of the results stated as a qualifier is a structural fault with one repair that restates it as a filter or as the goal's
relation, unless the qualifier sits on a goal subject and names one of that goal's own filters, as in running VMs with a running filter; the
filter reads it, so the qualifier restates it and drops nothing. Otherwise it returns one clarification or sends a low-confidence field to one independent T2 review of closed fields. An admitted atom
that no reviewed builder reads, such as a qualifier or a stated counterpart, returns a typed unsupported reason; it is never ignored.

**Utterance span accounting**: Every letter, digit, and math or currency symbol of the utterance must lie inside a mention, a goal, filter, relation,
time, or measure cue, a context quote, or an unsupported constraint. Core checks this only by Unicode category and never classifies what a word means.
A form that leaves any such character out is invalid, and its one repair names the missing words, with identifiers masked. A word that a quote holds
only in part is named whole, with the place of its unquoted characters, such as its last character, so a fragment of a name is never quoted alone. The
model decides whether a word states a constraint, so labeling one as context is its explicit judgment, which the blind constraint review checks. A
pass that sets `remaining_goals` defers the check to the final pass, which may rely on the mentions and cues of earlier admitted passes but never on
their context, and no compilation is released until the final pass is admitted. A repair of unaccounted words may add mentions, goals, filters, cue
reach, context, and values left at their defaults, but it never changes or removes a stated value. A word still unaccounted after that repair is left
to the blind constraint review, because accounting only makes the proposer consider every word; the review decides whether a word states a constraint.
When that repair reads every goal as the proposal did, except for quotes, but changes a quote a placement may not change, the proposal stands as it
was and its unplaced words go to the same review; a repair that reads a goal differently, such as a count for a list, or that does not parse is a
competing or missing reading and holds the turn, and the words a review repair leaves unplaced go to the review that reads its form again. A particle
attached to an instance name or identifier in the same word is accounted with it, and no repair may change the quote of such a mention, because it is
an exact lookup key that a widened quote would look up as another name; the review still judges any restriction the particle states. Reach words that
stand apart from the relation words, such as all the way down, are quoted in the relation's `reach_cue`.

**Blind constraint review**: A second T1 call of another model family reads only the question, beside the judgment call, and extracts every constraint
with a closed role. Core compares the two outputs structurally: every letter and digit of each extracted constraint must lie in a span that states
meaning, never only in a goal cue or context, and a named thing must overlap a mention, whose whitespace-delimited word carries an attached particle;
a restriction, negation, comparison, order, or time that the extractor isolates inside such a particle, such as only, is never stated by that mention.
No closed field expresses an exclusion such as not or only, and only a ranking or comparison goal expresses an order or a comparison, so a negation,
comparison, or order must reach an unsupported constraint or that goal's cue, and its repair adds the unsupported constraint while every cue stays. A
word that only means all or every has its own role, quantifies, and like a request word it states no restriction to cover; without that role the
extractor labeled such words as exclusions. Roles beyond that stay advisory, because two readers may fairly disagree on whether a word restricts or
relates, except that a hypothetical premise is stated only by an impact goal. One mention binds one concept or identity, so a mention must not hold an
extracted restriction beside another disjoint extracted constraint, as when one mention quotes `AKS ObjectTypes`: binding would keep one and drop the
other. An ObjectType or declaration-kind mention binds one closed name, so it holds no second disjoint extracted constraint of any role: live,
`Resource ObjectType` bound to the ResourceType ObjectType, and `Workload ObjectType` bound as a declaration kind listed every ObjectType, so the kind
word is its own declaration-kind mention. A reference's position words, such as second in the second one, are its typed position, so a reference is
never a merged mention. The extractor also quotes each literal value on its own, without surrounding words or particles. A literal operand, the
mention a name-fragment filter reads, is used verbatim, so its quote must equal one of those literals; otherwise the turn is held, and no single
reader decides where a literal ends. An uncovered constraint gets one review repair that may only add information, checked against the same
extraction. Its violation names a mention that quotes part of the constraint, and a literal operand's quote must stay exact, so the other words go to
the cue that cites it. A merged mention or a disagreeing literal is held without a repair, because such a repair cannot split a mention or move a
literal. A missing, empty, unlocated, uncovered, merged, or disagreeing extraction releases nothing. Every question states at
least what it asks and every quote comes from the question alone, so an empty extraction made beside earlier turns is asked once
more without them; live traces showed the extractor returning nothing for a standalone question after several long answers.

**Direction confirmation**: A reversed relation answers the opposite question, and open-ended extraction named relation starts too rarely to catch it.
After a faithful review, each goal whose relation has a direction, unless it is stated as either, gets one focused call to a reasoning model, because
direction turns on syntax: on seven questions asked twice, a reasoning model read every direction right while the small models misread Korean object
clauses the same way the proposer did. The reader sees the masked question, the named start, the sense, and the sense's two roles in their declared
order, never the role the proposer chose, and answers first, second, either, or unclear. Core compares that answer with the form. A different role, an
unclear or missing answer, or either for a sense without a reciprocal LinkType holds the turn; either for a sense with one is accepted, because that
LinkType is read on both sides anyway.

A form that breaks its closed schema or a structural rule gets at most one repair call with the code-authored violations. Each violation states the
contract rule the form breaks, such as the mention domains a filter accepts, and an unaccounted run is quoted; no violation interprets the question's
words. Mention ids are labels, so before a repaired form is compared with the proposal, each earlier mention's id goes back to the one repaired
mention of the same form and domain whose quote holds the earlier quote, and every reference follows; if any earlier mention lacks exactly one such
counterpart, the ids stay as written. The repaired form passes the same admission and must keep every quoted operand, goal, operation, want, typed
time, operand-bearing relation, competing reading, and pending-goals signal of the rejected proposal; otherwise the original fault stands, except that
a fault of accounting alone is left to the review as described above. These fields compare as the closed schema normalizes them. A proposal that never
parsed treats every stated pending-goals value other than an explicit false or null as pending, and it fails closed when any compared field loses its
closed shape, such as a missing goal list, a wrong container, a duplicate goal id, or an unreadable operation or want. Only an uncited mention of a
parsed proposal that quotes exactly a typed time cue may survive inside a repaired time cue instead of a repaired mention. Clarifications are answers
to the operator and are never repaired.

Admission bounds model authority; it does not remove it. A wrong but self-consistent form is caught only by cue-span review, T2 review, the restated
interpretation and confirm-first cells in [calibrated admission](ontology-reasoning-coverage.md#calibrated-admission), and the evaluation gold. The
model never chooses identities, LinkTypes, path steps, FunctionTypes, or answer claims.

## Deterministic compilation

### Concept selection

The model grounds each non-referential mention inside its declared domain. Core presents the complete candidate catalog, with reviewed labels, in as
many bounded shards as the budget needs; the model evaluates every shard, and a receipt proves each candidate was presented exactly once. Core accepts
an identifier only from the shard that presented it. Finalists that differ across shards meet in one runoff call. Labels are model context, never a
lookup table, and an explicit root candidate stands for resources in general. FunctionTypes and ActionTypes follow from operations.

- **Class closure**: A `resource_class` mention compiles through `query.resource_class_closure`
  into an exact `Resource.type` set and pins the closure receipt.
- **Cross-domain match**: At schema level, `AKS ObjectType` declares domain `object_type`, but the
  model finds `AKS` only among `Resource.type` candidates as `kubernetes-cluster`. Core returns a
  clarification that names that candidate instead of substituting another declaration.
- **Kind lanes**: The proposer confuses ObjectTypes and resource types in both directions, and the
  choice flips with unrelated prompt wording. A concept that every citing goal uses only as an
  instance-level collection subject, where both kinds compile, is grounded first in its stated
  catalog. When both choosers find nothing there, both are asked in the sibling kind catalog, and a
  meaning both choose sets the mention's domain. When the stated catalog was contested and the
  sibling agrees, both choosers see the contested finalists beside that meaning once, and the
  mention binds only when both pick the same meaning. The retyped form is admitted again and
  replaces the proposal for every later stage and record. A critique rejected treating an ObjectType
  and the resources root as one meaning, because they differ as a type filter, a relation end, and a
  schema subject, and rejected any retyping that leaves a stage reading the stated form.
- **Ambiguity**: Two surviving candidates in one domain return one clarification that names both.
- **Two blind choosers**: Two choosers of different model families, the proposer's and the
  extractor's, each see every shard and resolve their own runoff without seeing the other's choice.
  A binding stands only when both reach the same values, so a group and its type agree; any other
  answer, including general resources against one exact type, clarifies with
  `concept_disagreement`. Without the second family nothing binds. Each chooser answers through a
  schema closed over the presented mention ids, candidate ids, and shard digest, so a text answer or
  an invented identifier cannot parse. The secret and identifier scan of a reviewed shard runs once
  per shard digest rather than for every chooser, shard, and retry, so presenting a complete catalog
  does not block the event loop.

### Anchor binding

An `identifier` or `name` mention with domain `instance` becomes an anchor. Binding is a two-phase protocol:

1. After admission and manifest, purpose, and scope checks, Core verifies a single-node resolution
   plan: exact `id` equality or `name` equality without regard to case, pushed to the store, the
   principal scope, the current graph cutoff, and a limit of seven rows. Names that differ only in
   case are ambiguous.
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

The model never labels an instance as a resource group or a cluster; the bound type replaces that guess. A mention with a `qualifier` binds its
qualifier first and then searches only inside that qualifier's containment or type scope, so a shared name such as a default subnet stays exact.
Replay resolves the same receipt or reports that the binding is not reproducible.

### Relation compilation

A sense selects LinkTypes by reviewed `semantic_traits` and the bound anchor ObjectType. A reviewed sense-role convention names the role of each
stored end, such as container for the `from` end of a containment link, so the anchor role selects `outgoing` or `incoming` without rewriting stored
direction. Stated roles that are not the two ends of the sense return a clarification. A reciprocal LinkType, such as peering, has no direction, so
both stored sides are read whatever roles the form states, and V-SEM re-derives that. `transitive` reach requires a LinkType declared transitive and
self-composable, depth at most five.

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
- **Unsupported atoms**: A `region` filter compiles to a `Resource.location` predicate only when two
  blind choosers ground its mention to the same codes of the reviewed region vocabulary, and a
  `diagnose` goal without an applicable recipe never reuses another type's recipe. An unbound region
  and a missing recipe return a typed reason instead of a name predicate or a substitute.
- **Schema reads**: A schema relation is answered only by the one-hop `query.ontology_relationships`
  read of the subject ObjectType's own LinkTypes in both directions, and a manifest count groups only
  by declaration kind. A LinkType subject scoped to one ObjectType, as in the LinkTypes in Workload,
  is the same read and compiles as that ObjectType's relationship read; any other kind scoped to an
  ObjectType is unsupported. Any other schema relation, direction, counterpart, reach, anchor, or
  grouping returns a typed unsupported reason, and V-SEM rejects it independently.

### Follow-up references

Core issues a `ResultSetHandle` after deterministic rendering, so it matches what the operator saw. The opaque server-side handle binds the deployment
scope, principal, conversation, purpose, manifest digest, expiry, and rendered-order digest, and stores typed row keys, sort, page, and truncation
metadata. Operator persists handles with the durable turn and sends at most four recent handle references as typed request context under negotiated
versions. An `ordinal` or `anaphor` mention binds to handle rows after reauthorization. `current_rehydrate` rereads the exact ids at the current
cutoff and labels the answer as current; `snapshot_reference` answers only from the retained snapshot. A missing, expired, cross-conversation,
deleted, or out-of-range reference returns one clarification.

Standalone questions in a long conversation remain standalone unless the typed judgment cites an
ordinal, anaphor, or explicit prior-result reference. Multi-turn routing must prove the reference
binding rather than infer it from conversation length, and parity probes compare the same question in
fresh and 20-turn contexts so a standalone answer cannot drift into an advisory or ambiguous hold.

The shadow runner implements the binding core. A `ResultSetHandle` holds the rows shown, in order, bound to the conversation, principal, purpose,
`QueryManifest.manifest_digest`, and a timezone-aware expiry, with at most 1,000 unique row ids and a truncation flag. A follow-up binds only the most
recent handle, and each mismatch returns one typed clarification: `prior_result_unavailable`, `_foreign`, `_changed`, `_expired`, `_empty`,
`_out_of_range`, or `_ambiguous` for a count from the end of a truncated answer. The model gives an ordinal a signed `position`, 1 for the first and
-1 for the last; admission rejects a missing or zero position, a position on another form, and a position that differs from decimal digits in the
ordinal's words. A reference that names exactly one row, an ordinal or an anaphor over a one-row answer, anchors a read it starts: a relation
whose anchor, or whose subject when the anchor is unstated, is the reference itself, or a lookup, history, or impact read. The traversal-root
check verifies that anchor. Otherwise a reference narrows the results of a collection read, or of a
relation anchored elsewhere, through an `id in` predicate over exactly its rows: every handle row for an anaphor and the one row for an ordinal.
V-PROV admits `id in` operands only from those rows, and V-SEM re-derives from the form which reads a reference narrows and requires the
restriction on each of them. A read never starts from several rows; that returns `prior_result_multiple_anchors_unsupported`, and a restriction
too large for one plan node returns `prior_result_too_large`. A reference clarifies only after every check that a new handle could not change. A truncated handle adds the `prior_result_truncated` limitation to an anaphor. The rows
are reread through the secured gateway, so a row the principal can no longer read never reaches an answer, and each pass records a reference digest
without row ids. Operator persistence, the request contract, the rendered-order digest, `snapshot_reference`, and selection of an older handle
remain R8 work.

## Verification and evidence semantics

The compiler emits a `SemanticCoverageProof` as a witness. The verifier does not trust it. It reconstructs the expected coverage from a versioned
coverage-rule table in the catalog and from typed node output lineage, and keeps every existing check:

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
[`epistemic_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/epistemic_coverage.py). `VERIFIED_EMPTY` needs
closed-population proof: complete source, no truncation, and complete relationship coverage for the compiled LinkTypes. Any other empty result is
`UNKNOWN_INCOMPLETE` and says that no match exists in the verified scope. Missing workload mappings are unavailable, not empty. One failed goal does
not hide verified sibling goals, and the answer lists every unknown atom. Link evidence uses a reviewed projection allowlist of `verified`,
`verification_method`, authority, effective time, freshness ceiling, and completeness, and a visible link still cannot reveal a hidden endpoint.

## Model role

| Decision | Today | Target |
|----------|-------|--------|
| Question meaning | Capability name plus free facet tokens | Closed logical form with cue spans and admission |
| Completeness of the reading | Nothing checks for a dropped constraint | Blind constraint extraction by another model family, compared structurally |
| Instance kind of a named object | Model target kind | Anchor binding |
| Relation direction | Frame or plan model | Admitted position mapped to a reviewed side |
| Path and LinkType set | Plan model or fixed recipe | Reviewed traits and path grammars |
| Concepts, values, and time | Term lists, lexical ranking, and regular expressions | Model choice from complete catalog shards and typed values, validated by code |
| Operands | Utterance regular expressions or the plan model | Spans, bindings, handles, and server defaults |
| Answer prose | Shape templates in code | Model-authored claims that pass V-CLAIM and independent review |

The judgment prompt keeps the protected root and describes only the closed form, span and cue rules, and bilingual examples per operation, without the
FunctionType catalog for read goals. Frame and plan model calls retire for compiled forms; the plan model stays shadow-only for uncompiled forms and
must pass V-SEM and V-PROV. T2 never authors a plan, and the unused `query.<LinkType>` intent affordance is removed.

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

Bragi's T1 author writes every answer, including the interpretation restatement, from the admitted form, verified evidence tables, per-goal epistemic
statuses, and typed limitation codes. No answer prose comes from code templates; only catalog notices and verified data views render without the
model, and they add no fact. The author returns structured claims, shown only after verification.

| Claim field | Contract |
|-------------|----------|
| `kind` | `restatement`, `fact`, `count`, `relation`, `state`, `change`, `cause_hypothesis`, `limitation`, or `next_check` |
| `refs` | Evidence cells or limitation codes that support the claim |
| `proposition` | Canonical subject, predicate with direction, object or value, polarity, comparator or quantifier, unit, temporal basis and time zone, modality, and rounding |
| `spans` | The exact text span of every surface phrase and literal, bound to the proposition |
| `rows` | For list and count goals, the row identifiers that the claim names or aggregates |

V-CLAIM compares names through canonical identities, never substrings. It rejects an answer when a claim lacks references, a proposition or literal
differs from its evidence, a literal is undeclared, a required limitation, goal, or form atom is missing, a count differs from the authoritative
count, a result row is neither named, aggregated, nor listed in the complete table, or a cause claim lacks causal evidence. An independent T1 reviewer
then checks entailment. A rejected answer regenerates once with typed reasons, then holds with the verified evidence view. Evidence larger than one
author call is composed in bounded chunks and synthesized under the same row account. Evaluation and the parity gate belong to [Ontology Reasoning
Coverage](ontology-reasoning-coverage.md#assurance-and-sre-agent-parity).

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

Every round implements, runs focused tests, runs L1 with at least two repeats and L2, fixes regressions, and appends a ledger row. The form path runs
in shadow beside the current path and records only digests and dispositions. A family is promoted only when hard zeros hold on all repeats and sampled
shadow turns, holdout correctness meets its absolute floor and beats the current path outside the noise band, English and Korean differ by at most 5
points, p95 latency does not rise, SRE Agent parity holds, and the 68-case corpus does not regress. Rollback restores the previous registry entry, and
the current path stays intact until R10. The per-family lanes in [Ontology Reasoning Coverage](ontology-reasoning-coverage.md#closure-program) gate
these rounds.

**Production shadow wiring**: Promotion evidence comes only from the form carried as an additive field of the existing judgment call, the approved
first decision; a tap that makes its own model calls beside a turn measures a different, independently sampled reading, so its records are an
experiment that promotion excludes. Either wiring must meet these conditions, from a design critique:

- An anchor read takes the gateway's cutoff at the moment of the read, because the gateway accepts an `as_of` only within seconds of its own cutoff
  and model calls take longer; a rejected read is the typed `as_of_stale`, never a generic unavailability.
- Cancelling or timing out the shadow cancels and drains every provider call it started.
- The shadow runs from a sanitized context under its own provider budget, stops its fan-out on HTTP 429 or 503, and never charges or cancels the
  answer's budget.
- Only one top-level eligible operational utterance per turn is observed; other routes and break-glass principals record typed skips, and capacity
  skips and timeouts stay in the denominators.
- Anchor reads use the same role, purpose, and principal scope digest construction as the turn's executor.
- Records carry a keyed sample identifier instead of an unsalted digest of the utterance or principal, go to a durable sink, and are enabled only by a
  typed configuration setting that defaults to off.

**Interim current-path fixes (R2)**: Until families are promoted, the current judgment path applies the same principles where a
live defect showed a wrong or empty answer. A `resource_group` target always means its exact container, so members are read through
`contains` whatever collection facets accompany it, and subtype filters beside it narrow the members rather than the subscription. The
judgment is offered every declaration identity instead of a ranked slice; property-level identities are optional detail within a
smaller allowance. The preflight router no longer stands in for the judgment on a Resource collection, and no fixed product-specific
clarification remains. Prior-turn context yields newest-first when a request would exceed its budget. In the local profile an
independent second reader of another narrator deployment grounds unbound subtype words by closed choice with two blind choosers, and a
blind constraint reading must see every stated restriction, negation, comparison, order, or time in a copied span: an uncovered one
returns to the judgment as repair feedback and otherwise holds the turn as `semantic_constraint_uncovered`; a negation word such as
only or not is covered by the copied operand it touches. A named thing standing apart from every copied span is offered to the same
closed choice as a possibly omitted subtype. A membership frame never compiles without its exact group, the container's own kind word
never filters its members, and where no second reader runs a frame that drops the operand of a stated relation holds instead of
widening the list. A state collection needs T2 review only when a stated state lacks a reviewed state concept, as the fourth approved
decision requires, and a collection whose typed targets are grounded states is planned as a state collection. A proposal that copies
one span as two targets is repaired. Relationship questions about one named instance remain unexpressible on this path and wait for
the relation compiler. A judgment that ends ambiguous now ends the turn with its clarification once the deterministic pre-frame checks
have run; the frame model no longer reinterprets the utterance without the judgment and its constraint review.

**Local compiled answers**: In the local development profile the launcher also sets `FDAI_SEMANTIC_COMPILED_ANSWERS=1`, which needs
the second reader, and the composition honors the flag only in the local execution venue. The planner then starts the form path beside
the judgment on every unbound operational turn that needs no document evidence, with its own provider calls and budget scope, an
absolute deadline, and anchor reads under the same role, purpose, and principal scope as the turn's executor. The planner consults the
path only after the deterministic pre-frame checks, and an ambiguous judgment's clarification wins over it. The path answers only when
it is released and its single retained compilation holds exactly one goal compiled into one verified batch, with no continuation and no
limitation. The planner then stamps the plan with the gateway's current cutoff, verifies it again, and answers from that compiled
frame and plan instead of the judgment path's frame and plan stages. When the judgment leaves a stated constraint uncovered, such a
compilation may answer instead of the hold. Every other outcome leaves the current path to answer the turn: a typed unsupported
reason, a clarification, a held review, a continuation, a timeout, or a provider failure. Ending or cancelling the turn cancels the
path, and the owner loop drains its provider calls. The path emits one content-free decision event for every outcome, including a
skip, cancellation, timeout, or failure, with its pass dispositions, review outcome, per-goal statuses, reasons, and limitations, so
`dev discuss` shows why a question was or was not compiled. The form comes from a separate call beside the turn, so these records are
the experiment that production shadow wiring excludes from promotion evidence, and no family is promoted by them.
A goal whose relation sides span several batches answers as one plan only when every side fits one intent graph; a
shared anchor read may repeat only with identical content. One plan names at most eight outputs, so beyond eight sides
the traversals that reach one ObjectType stay as nodes and one union of them becomes the output, which reads every side
and keeps each reached endpoint once. A Resource state filter binds through
a reviewed state catalog built from the state inventory function's declared concepts and labels, and the collection is
read through that function, whose state concepts V-PROV and V-SEM check against the bound state. A state filter on
another ObjectType stays `filter_unsupported:state`, because no reviewed reader holds that lifecycle.
A count grouped by container groups members by their direct parent, the `from` end of `contains`, and V-SEM rejects
an aggregate whose grouping differs from the stated one. The routing preflight's context now also yields newest-first
within its smaller bound: before, a context longer than that bound skipped the preflight, so after a few long
answers a standalone question went to the adaptive planner, which could answer it from general knowledge. A trimmed
context records the kept and dropped item counts as a decision event.
A declined path also records the one selection rule it failed, such as `not_released`, `goal_not_compiled`, or
`merge_over_budget`, and its batch count. An invalid review records why the extraction could not serve, such as an
empty extraction or a quote that is not in the question, without the quote. When the released reading holds a goal
that no builder compiles, it names what the question needs. The current path may then still answer through its own
typed builders, but a filter recovered only from the judgment's words, such as a stated type, would answer a narrower
question, for example every storage account when the question also states a region. The planner therefore returns
`semantic_stated_constraint_unsupported` for such a recovered plan and records the unsupported reasons, instead of
presenting a verified answer to a question the operator did not ask. Only a reason that names an unsupported atom
counts; a data outcome, such as an incomplete anchor read, says nothing about the question. A parsed reading of any
pass, released or not, also holds such a plan when it asks more than one filtered Resource list answers: a state,
region, grouping, relation other than a named container's members, time, schema level, second goal, or competing
reading. The form's first shape token records that verdict.

## Typed-only answers and causal context

This section records the 2026-09-30 audit of lexical meaning on the answer path and the next stage it
proposes. The stage changes behavior only in the local development profile.

### Lexical meaning audit

Five groups of runtime code on the current judgment path still derive meaning from the operator's words.

| Group | Examples | Meaning derived from words |
|-------|----------|----------------------------|
| Keyword signal tables | `query_signal_matches`, `query_target_cardinality`, and `query_term_spans` over the inventory query language catalog | Collection or single-item requests, counts, mutations, relationships, locations, activity, and causal diagnosis |
| Stated-value matching | `stated_value_filters`, `stated_value_term_spans`, and `stated_subject_fragment` | Resource types, names, and property values found as words in the utterance |
| Recovery fallbacks | Stated resource filter, current-state, and target-candidate recoveries | A filtered list or state lookup built from those matches when the judgment or frame is incomplete |
| Investigation and time normalization | Slowness, CPU, MySQL, network, and application hypothesis normalizers; activity and service-health normalizers | Causal hypotheses, symptoms, negation, and lookback windows |
| Clarification builders | Resource-target and filter-meaning clarifications | Ambiguity decided from word overlap |

No answer template states an operational fact. Answers render verified evidence tables and reviewed
catalog notices. The model-authored answer and V-CLAIM remain round R8 work.

### Typed-only answering

In the local profile, `FDAI_SEMANTIC_TYPED_ONLY=1` makes the question-form path the only way an
operational read can answer. The flag requires compiled answers and the local execution venue, and the
composition refuses to start when either is missing. The planner keeps its current order: the
preflight, the judgment and its coverage review, verified denials, action-draft boundaries, and
deterministic clarifications run first, then the judgment's own clarification, then the form path.
None of those earlier stages answers a read. The only change is what happens after the form path:

1. A released compilation that the selection rules accept answers the turn.
2. Otherwise the form path's tagged decision ends the turn with a typed outcome. The turn never reaches
   the legacy frame and plan cascade, its keyword signals, stated-value matching, recoveries, or the
   frame model.

| Decision | Planner outcome | Meaning |
|----------|-----------------|---------|
| `unsupported` | unsupported, `semantic_stated_constraint_unsupported` | A released reading states an atom no reviewed builder reads |
| `clarification` | held, `semantic_reading_ambiguous` | The reading has competing readings, an unused mention, or a constraint no field expresses |
| `continuation` | held, `semantic_reading_continuation_required` | The reading needs another pass or more plans than one answer holds |
| `limited` | held, `semantic_reading_limited` | A goal carries a limitation that no reviewed notice can state |
| `unverified` | held, `semantic_reading_unverified` | The form was invalid, or the blind review found it unfaithful |
| `unavailable` | held, `semantic_reading_unavailable` | The path timed out, failed, never started for this turn, or a goal could not bind its data, such as an incomplete anchor read |

A turn for which the form path never started, such as a bound-resource or document-evidence read,
also ends as `unavailable` instead of falling through to the legacy path. Direct social responses,
one-shot general knowledge, adaptive knowledge answers, and action drafts keep their paths. A
misclassified operational question on those paths remains a known gap that R9 promotion measures.
With the flag off, the planner behaves exactly as before. Deployed venues keep the current path until
each family is promoted in R9, and R10 deletes the lexical helpers of promoted families only after a
rollback release.

When the first reading fails only as a form, because it was invalid, clarified by an unused mention or a
competing reading, not faithful to the blind review, or mislabeled one mention's kind, the path reads the
question once more. The second sample passes the same admission, grounding, review, and selection
rules and never lowers the bar; a reading with an unsupported atom is never resampled, and no turn takes
more than two samples.

A selected compilation may carry only reviewed limitations that the answer states as catalog notices:
the applied, default, or model-judged history window, a cause that is not established, and an impact
that is possible rather than observed. The compiler
records each as a frame evidence requirement, so the frame, plan digest, and rendered notice agree. Any
other limitation keeps the compilation from answering.

### Causal context

A question such as why aks-app is stopped is a `cause` want about one named Resource. Admission
accepts it only as an `explain_cause` goal with `want: cause` over one anchor, with an optional state
measure and time window; any other combination of the operation and the want is a structural fault
with one repair.

The current-state reader reports when a state was observed, not when it changed, and local
state-transition coverage is often missing. Timing alone therefore cannot even support an
`association` grade here. Until transition coverage, a mechanism catalog, and refutation queries
exist, the compiler answers such a goal as causal context, never as candidate causes. The plan reads
the anchor's current state through `query.resource_current_state` and the control-plane operations
recorded on the anchor within the stated or default window through `query.resource_change_activity`,
each row with its recorded status. The frame uses the compiler-only `cause_context` output shape,
which the frame model's schema never offers, so the legacy frame path cannot propose it.

The answer leads with the reviewed notice that the cause is not established and restates the window.
It shows both verified tables with their completeness, names no operation as a cause, and assigns no
evidence grade. An incomplete read, such as an activity read that reached its row bound, stays marked
incomplete. A history goal uses the compiler-only `change_activity` shape the same way, so its
operations are never shown as a Resource list. State-transition change points, paging the full window
with a pinned continuation, dependency-neighbourhood context, mechanism fit, refutation checks,
evidence grades, and model-authored cause claims gated by V-CLAIM remain R7 and R8 work. No new
FunctionType is added, so the ontology release does not change.

| Critique finding | Revision |
|------------------|----------|
| Temporal precedence to a state observation is not association | Causal context only; no candidates and no evidence grade |
| Activity records include failed and read-only events | Each row keeps its recorded status; none is ranked |
| No `no_known_cause` baseline | The answer leads with "cause not established" |
| Bounded activity reads drop rows | Incomplete tables stay incomplete; full paging is remaining work |
| Typed-only fails open for turns without a ticket | Such a turn ends `unavailable` |
| Moving compilation before pre-frame guards skips safety checks | The order is unchanged; only the post-decision fallthrough changes |
| Decline codes too coarse | Tagged decisions with a typed outcome each |
| History and cause goals always carry limitations | Reviewed limitations become frame evidence requirements with notices |
| A new FunctionType changes the global release | No new FunctionType |
| Two encodings of a cause question | One canonical `explain_cause` with `want: cause` |

### Reading reliability and incomplete coverage

Typed-only probe rounds T4 to T11 on 28 to 30 live Console questions answered 19 to 21 each. The
remaining holds came from three families: readings that failed only as forms, reads the compiler did
not bind, and inventory states that made every anchored read incomplete. This stage addresses each
family; code still reads no meaning from words.

**Readings**

- **Direction majority**: The proposer states both relation roles, and one blind reader of another
  model family answers which role the named anchor plays. When that reading is clear and differs, a
  third blind reader answers the same closed question. The third reader belongs to neither the first
  reader's family nor the proposer's, because the proposer's role is already one vote; without such a
  family, the dispute holds. Two agreeing concrete readings decide. Either the form stands, or its two roles swap to
  the readers' reading and the form is admitted again. A mutual, unclear, or missing third reading
  holds the turn. Settlement runs before compilation, so a swapped reading is compiled, reviewed, and
  verified like any other.
- **Quote occurrence**: A mention whose stated occurrence lies inside another mention moves to the
  only occurrence of the same words that no other mention holds. When no such occurrence exists,
  admission rejects the overlap.
- **Measure words**: A concept mention that only names an ungrouped measure, such as the word for
  events, and that nothing else cites becomes that measure's cue. A named resource, a literal, and a
  state, health, or metric value always stay mentions. Code moves a quote between two fields of the
  form and reads no word.
- **Aligned contracts**: The form contract defines each measure kind, and the extraction contract
  lists events and operations among measures, so the two blind readers classify the same words the
  same way. A thing the extractor finds named still needs a mention. A count measure may restate the
  type filter of a goal that has no subject.
- **Bounded retries**: An unusable extraction, such as one quoting words the question lacks, is read
  once more by the same extractor under the same review rules. A reading whose only fault is a
  concept that no reviewed value matches is resampled like other mislabels.

**Reads**

- **Collection history**: "What changed" over Resources in general, or with no subject stated, reads
  `query.recent_resource_changes` over the typed window, bounded by the reader's declared row
  maximum, and renders as `resource_changes`. A stated kind is unsupported because that reader cannot
  restrict it. A window with more changed Resources than the bound, or with unverified change
  coverage, stays incomplete.
- **Event history**: An anchored history with an `event` measure reads `query.resource_event_history`
  for every reviewed event family within the reader's declared lookback maximum. A longer window is
  unsupported.
- **Verification**: V-SEM derives the one read each history goal requires: collection changes,
  events, or activity. V-PROV requires the collection read's absolute window to end at the trusted
  compile clock, to span the expected lookback, and to use the declared row bound.
- **Declared bounds**: Builders read row and lookback bounds from the FunctionType input schema
  instead of keeping their own copies.
- **Union fan-in**: Every union reads at most seven dependencies, the most one Console intent goal
  can show, and a wider fan-in becomes parts that are united again. A relation count reads at most
  eleven sides, so its union tree and aggregate still fit one intent graph, and a plan whose intent
  graph the Console cannot show holds before it answers.
- **Answer tables**: A causal context table leads with the state reader's declared measure fields,
  such as the running status, before receipt fields.

**Incomplete coverage**

- **Scoped exact reads**: The inventory marks every Resource read incomplete while any observation
  is unprojected, such as a provider-managed load balancer that is written every few minutes. An
  exact-id object read without relationships now counts only the pending observations of the
  requested ids, including a pending creation of one of them. Every other gap stays global.
- **Unproven uniqueness**: Under incomplete coverage, one verified name match binds with its
  uniqueness unproven. The answer is partial and states the reviewed notice that another resource with
  the same name may not be reflected yet. No match never proves absence, and a truncated read never
  binds. The
  exact-case name read is pushed to the store, so it still returns its match when the
  case-insensitive scan returns nothing under incomplete coverage.
- **Typed reasons**: An anchor that stays unbound reports `candidate_limit`, `source_incomplete`,
  `generation_changed`, or `extensions_unread`.

**Diagnostics**

- dev discuss keeps the closed code prefix of a server reason that ends in a span, and the local
  prompt-source check writes its diagnostics to standard error, so an input digest on standard output
  stays parseable.

The design critique of this stage raised eight findings, five High and three Medium.

| Critique finding | Revision |
|------------------|----------|
| A mutual or unclear third direction reading counted for the proposer | Only a concrete role joins a side; any other third reading holds |
| The tie-break could reuse the proposer's model family | The tie-break family is neither the first reader's nor the proposer's; without one, the dispute holds |
| Moving a measure mention to its cue could erase a named resource | Only a concept mention moves; a thing named in a measure cue still needs a mention |
| Reading a scope written as a value as a name could change its meaning | Removed; an anchor written as a value is resampled as a mislabel |
| A released reading overrode a real ambiguity the judgment found | Removed; the judgment's clarification still wins until a closed ambiguity reader exists |
| An absolute history window was not tied to trusted time | V-PROV requires the window to end at the compile clock |
| Twelve counted sides exceeded one intent graph once unions became a tree | Eleven sides at most, and the node budget is checked after the tree is built |
| An answer read from an anchor with unproven uniqueness was labeled verified | Such an answer is partial |

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
