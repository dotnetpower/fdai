---
title: Ontology Reasoning Coverage Expansion and Current-Path Convergence
---
# Ontology Reasoning Coverage Expansion and Current-Path Convergence

This document designs the reads the question-form compiler doesn't cover yet and the fixes that
bring the current judgment path to the same standard. Each package names the traced defect or
unsupported reason it answers, the closed contract it adds, how the independent checks verify it,
and the evidence that ends it. It extends the [Ontology Reasoning Compiler](ontology-reasoning-compiler.md).

> **Status:** Proposed design, 2026-10-01. Delivery state and remaining work live in the
> [implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-coverage-expansion.md).
> Live exits need an explicit Owner request, as the
> [Promotion Program](ontology-reasoning-promotion-program.md#validation-program) describes.

## Design at a glance

The current judgment path is the planner that answers production turns today. The question-form
path is the compiler that reads a closed question form and runs in shadow or locally. Current-path
convergence (E1 to E5) makes that planner carry, check, and hold on the same closed meaning that
the compiler uses. Coverage expansion (E6 to E9) teaches the compiler reads that it declines today.
No package reads meaning from words. Every new read keeps the existing rule: a restriction that
can't compile holds its goal and never widens the answer.

| Package | Answers | Contract change |
|---------|---------|-----------------|
| E1 Typed constraint slots | Uncovered window, region, and incident-status restrictions on the current path | Judgment and frame contracts, versioned |
| E2 Operand provenance | Identity literals that the plan model could invent (the rest of R2) | Binding receipts inside Core |
| E3 Relations on the current path | Relation questions about one named instance, and the T2 state review | None; the shared compiler core |
| E4 Standalone questions | Standalone questions that drift late in long conversations | None; routing evidence only |
| E5 Turn budget reservation | Schema and change-window questions that exhaust the turn budget | A reservation plan per path |
| E6 Grouping by container kind | A per-group count, such as per resource group | Form field and traversal root lineage |
| E7 Health, history, and lifecycle | Single-target health, state history, and other ObjectType lifecycles | Reviewed readers and domains |
| E8 Causal change points | Why questions that need a change point and complete accounting | A verified causal-grade receipt |
| E9 Remaining operators and senses | Rank, comparisons, versions, verification, diagnose, paths, and unmapped relation senses | Reviewed recipes, grammars, and traits |

## Current-path convergence

### E1 Typed constraint slots

Traced turns held as `semantic_constraint_uncovered` because the judgment contract had no field for
a restriction that the blind reading found: a 24-hour window, a region, and an incident status.

- Add typed slots to the judgment and frame contracts, mapped one to one from the blind reading's
  `ConstraintRole` values: time window, location or property predicate, lifecycle status per
  ObjectType, group-by measure, relation path, and prior-result or ordinal reference.
- Each slot value grounds by closed choice against the ontology, through the concept catalogs the
  compiler uses, including reviewed lifecycle domains and region codes. A slot the model can't
  ground stays unbound and holds the turn.
- The coverage review compares the blind reading with the slots, not with free facet tokens.
- Both contracts gain a minor version with the rollout-safe version rules of
  [H1](ontology-reasoning-result-handles.md#h1-contracts). An older payload keeps today's behavior.

**Implementation note (2026-10-01):** The service contracts now define typed constraint slots and
minor-version pins for the judgment and frame records. The production judgment schema only exposes
slots behind a default-off setting, so active model prompts keep their current output schema until
the slot reader is calibrated. Local checks prove grounded slots cover the traced window, region,
and incident-status restrictions, ungrounded slots hold with a typed reason, and grouped or
relational frame slots must be represented by the verified plan. A time-window slot is covered only
by an explicit window argument or by two distinct point-in-time reads, such as a snapshot pair. The
single cutoff that the server stamps on every ObjectSet, traversal, and path read never counts as a
window.
Core now revalidates model-proposed location and lifecycle slot values against the exact manifest's
closed concept catalogs before planning. A label or other non-canonical value becomes an unbound
`out_of_domain` slot and follows the existing typed hold. One explicit historical snapshot satisfies
a point-in-time slot only when its instant is earlier than the evaluation cutoff; a current cutoff
still does not satisfy a window.

**Exit:** zero uncovered-constraint holds for the traced window, region, and incident-status
questions across two repeats.

### E2 Operand provenance through binding receipts

A check that required every identity operand of a model plan to appear in the utterance, earlier
turns, or bound context was withdrawn, because server-grounded identities such as the resource id
of an exact name binding also reach model plans legitimately.

- The judgment's binding step records each identity it binds as a typed receipt: the source span,
  the reviewed lookup, and the bound identity.
- The plan verifier accepts an identity operand only from a span, an earlier turn, trusted bound
  context, a result handle, or such a receipt, and holds the turn as
  `semantic_operand_without_source` otherwise.
- The instance-versus-schema half already holds a declaration-only plan for an instance answer
  kind.
- The local implementation applies this check at the current-path hold seam for model-proposed
  operational plans, while server-built plans remain covered by their own deterministic builders.
  A server-bound resource context now activates provenance enforcement even when no blind coverage
  reader ran, and contributes typed receipts for each exact bound Resource or resource-group
  identity at the planning call site.

**Exit:** zero invented identity literals and zero schema answers to instance targets on the
cohort and the holdout.

### E3 Relations on the current path

Relationship questions about one named instance can't be expressed as frames, so the current path
holds them. When the judgment's reading is a relation about one bound anchor, the planner compiles
it through the shared relation compiler, with its reviewed sides and the V-SEM relation check,
instead of the frame builders. The T2 state review then compares closed meaning axes, such as the
ObjectType, the state concept, the polarity, and the time basis, instead of facet tokens, so a
reading the ontology can answer isn't held because two readers used different words.

**Implementation note (2026-10-01):** The current path consumes released form-path relation
compilations before it asks the frame model, so V-SEM-verified relation plans answer through the
shared compiler. The independent state review compares Resource state readings by closed axes
instead of facet spellings.

**Exit:** the traced relation and state-review questions answer on the current path, and V-SEM
accepts every relation plan it releases.

### E4 Standalone questions in long conversations

A live probe saw the router mark standalone service-health and Key Vault questions as
thread-dependent late in a long conversation. Routing may treat a turn as thread-dependent only
when the typed judgment cites an ordinal, an anaphor, or an explicit prior-result reference that
binds. Conversation length, topic overlap, and earlier answers never imply a reference. The same
closed choice reads an ObjectType, so an incident mention grounds as the Incident ObjectType, not a
Resource subtype.

**Implementation note (2026-10-01):** The preflight router can't see a typed reference, so a
thread dependency it guesses for a turn with an explicit operational or knowledge request is read as
none before routing, and the reviewed family that the guess blocked now promotes. Contextual
follow-ups, social continuity, and pending decisions keep their route. The type closed choice also
offers every ObjectType other than Resource, so an incident word can ground as the Incident
ObjectType, and such a choice never becomes a Resource subtype.

**Exit:** the traced questions asked late in a 20-turn conversation reach the same verified answers
as in a fresh one across two repeats.

### E5 Turn budget reservation

The current path can spend the turn budget in adaptive planning or a large judgment before its
frame call runs. Each path gets a reservation plan that follows the
[shared turn limits](hierarchical-conversation-planning.md#shared-turn-limits):

- The plan lists every stage that can run, including conditional ones: judgment, one repair, the
  blind review, two concept choosers, the conditional direction readers, frame, plan, the answer
  author, one regeneration, the entailment review, and chunk synthesis.
- Each stage reserves its worst case before dispatch, in calls, input and output tokens, wall time,
  cost, and read rows. The shadow reserves from its own capacity.
- A stage that can't reserve returns the typed `budget_reserved_exceeded` hold before any call. A
  failed reservation stays recorded, and actual usage is reconciled after each stage.

**Implementation note (2026-10-01):** `turn_reservations.py` holds the ledger, the reviewed
current-path and shadow plans, and the stage labels the model adapters already record. Every
physical request reserves at the shared provider choke point, and a held stage stops candidate
failover before any request is sent. The shadow binds its own ledger, sized from its pass, repair,
and concept limits, and reports a hold as a typed note. The current path's plan is defined but isn't
bound in production yet, because its per-call worst cases need a calibration round over live
request sizes. Read rows and priced cost are reserved dimensions that no caller charges yet.

**Exit:** tests cover exact budget boundaries, cancellation, and continuations, and the traced
schema and change-window questions record no judgment token-budget or adaptive budget-exceeded
event.

## Coverage expansion

### E6 Grouping by container kind

A count grouped by container groups members by their direct parent today. A question such as "how
many VMs per resource group" needs the nearest ancestor of one kind.

- **Form:** A `group_by: container` measure may name the container kind through a mention that
  grounds to an ObjectType or resource type, such as the resource-group type.
- **Lineage:** A transitive `contains` traversal from every container of that kind records, for each
  reached member, its lineage: the root, the minimum depth, the path evidence, and the generation.
  Roots farther than the nearest are discarded.
- **Ties:** A member with two or more nearest roots at the same depth is excluded from every group
  and counted in a separate `ambiguous_membership` total, so the group counts plus that total
  equal the members read.
- **Verify:** V-SEM requires the lineage grouping whenever the form names a container kind.
- **Implementation note:** The local compiler represents the lineage grouping as a reviewed
  aggregate operation over typed lineage rows. It reads the named container roots, asks secured
  `contains` traversal to emit lineage rows, filters reached members by the stated subject kind,
  and then aggregates the lineage rows. It remains shadow/local until promoted.

**Exit:** exact gold tests pass for direct, indirect, and equal-nearest roots, and the traced
per-group count answers with one count per resource group instead of a hold.

### E7 Single-target health, state history, and lifecycle domains

- **Health lookup:** A health question about one bound Resource compiles to the reviewed
  single-target health assessment, the same shape the current path plans, from one shared module.
  V-PROV recomputes its fixed 30-minute window and its three reviewed metric inputs, and V-SEM
  requires exactly the assessment's reads. The answer restates the fixed window through a reviewed
  notice. A resource with no health evidence stays `UNKNOWN_INCOMPLETE`.
- **State history:** A history of one Resource's state compiles to the reviewed state transitions
  reader over every reviewed transition type and target state in the window. The reader returns its
  coverage proof, so an answer claims a complete history only when that proof is complete for the
  window; otherwise the history is `UNKNOWN_INCOMPLETE`. A collection's state history, or a version,
  `as_of`, or two-window history, keeps its typed unsupported reason.
- **Lifecycle domains:** Each ObjectType whose projection writes a canonical status enum gets a
  reviewed lifecycle value domain, with a contract test that pins the enum values: `Incident`,
  `Process`, `RecoveryPlan`, and `CausalHypothesis`.

**Exit:** `check-reasoning-coverage.py` no longer reports `measure_unsupported:health` or
`measure_unsupported:state`, and a stated state on each projected ObjectType grounds.

### E8 Causal change points and evidence grades

Causal context stays until every part below exists. It shows the current state and the recorded
operations, and never names a cause.

1. State-transition change points, read only under trusted transition coverage.
2. The full activity window, paged with the
   [change continuation](ontology-reasoning-result-handles.md#h5-change-continuation).
3. A reviewed mechanism catalog. Each mechanism names its required evidence and its refutation
   reads, following [Causal Incident Graph](../rules-and-detection/causal-incident-graph.md#evidence-grades).
4. A verified causal-grade receipt. A grade comes only from repeated samples, reverse-direction and
   confounder checks, complete windows, mechanism evidence, and refutation accounting. Missing
   refutation data is unknown, not support.
5. Release through V-CLAIM. A `predictive_precedence` grade renders a graded hypothesis, never a
   definitive cause, and no hypothesis releases before the verified answer authoring in the
   [Promotion Program](ontology-reasoning-promotion-program.md#p3-verified-answer-authoring).
Local implementation now reads state-transition change points in causal context and computes a
deterministic causal-grade receipt from reviewed mechanism evidence and refutation accounting. It
still renders causal context below `predictive_precedence` and does not claim the live exit.

**Exit:** a why question about a state change lists the change point and every operation in its
window. No answer states a cause below `predictive_precedence`, and a single temporal coincidence
stays causal context.

### E9 Remaining operators and relation senses

The coverage receipt still returns typed unsupported reasons for these operations and senses. Each
one compiles only when its prerequisite exists. Until then it keeps the reason, and none borrows
another operation's plan.
The local implementation tightens those missing-prerequisite reasons in the coverage receipt; it
does not compile new cells until the reviewed order, aggregation, comparison, history, evidence,
diagnosis, path, or trait prerequisite exists.
E9b adds the first such compiled cell: `compare_windows` over one reviewed metric uses two typed
windows and the existing metric comparison node. Rank/non-count aggregate and compare-entities keep
typed prerequisite reasons until their reviewed order/aggregation metadata and aligned answer shape
exist.

| Operation or sense | Prerequisite | Compiles to |
|--------------------|--------------|-------------|
| `rank` and non-count `aggregate` | An order node with a bound and a reviewed aggregation per measure | A bounded ordered read with V-SEM order coverage |
| `compare_windows` and `compare_entities` | Two typed windows or two bound anchors over one reviewed measure | Two reads and a comparison, with no causal claim |
| `diff_versions`, `as_of`, and version time | Retained configuration snapshots and topology history | A typed diff, or typed unavailability where history is absent |
| `verify_evidence` | The reviewed link-evidence allowlist through the secured projection (approved decision 7) | Link evidence with its authority, freshness, and completeness |
| `diagnose` | A reviewed recipe per resource type | That recipe only; no recipe borrowed from another type |
| `path` and transitive reach | Reviewed path grammars | A typed path with bounds and exact receipts |
| Composition, ownership, authorization, and classification senses | A trait review of the LinkTypes | Reviewed sides, as for containment and dependency today |

**Exit:** each row's cells compile in the coverage receipt with hard zeros on the holdout, or keep a
typed unavailability reason where the data doesn't exist.

### E10 Collection state and health lists

A question such as "show the connection state of the managed disks" or "are the AKS clusters
healthy" asks for one measure of every member of a collection, with no restriction. The compiler
read state or health only as a filter, so the measure held as `measure_unsupported`.

- **Form:** A `select` goal over a collection may carry a `state` or `health` measure with no filter.
  The same measure on an anchor, a relation, or a schema goal keeps `measure_unsupported`, so it is
  never dropped.
- **Compile:** A state measure compiles to the reviewed state inventory with the observed-state
  concept. A health measure compiles to the reviewed health inventory over every reviewed health
  concept in the manifest; without one, the goal holds as `health_concepts_unavailable`.
- **Verify:** V-PROV re-derives the observed-state concept, or the manifest's complete health
  catalog, from the goal alone.
- **List mode:** The listing sets the state reader's `list_members` argument, added in function
  version 1.3.0. The reader then returns exactly one row per input Resource. A member without fresh,
  conflict-free state evidence has a row with `state_status: unknown_incomplete`, no state concept,
  and a typed `unknown_reason`: `state_not_reported`, `state_metadata_missing`,
  `state_metadata_invalid`, `state_not_observed`, `state_conflicting`, `state_partial`,
  `state_after_cutoff`, or `state_stale`. Such a row keeps the table incomplete, and the assurance
  projection records `resource_state.member_unknown`. The reader fails rather than return a row
  count that differs from its input.
- **Remaining:** The population receipt below, so a set cut at its bound is accounted beyond the
  page it returned.

### Collection population receipt

E10 to E12 read every member of a collection, but an object-set read stops at 1,000 rows and its
receipt says only that it was cut. The population receipt makes the whole logical set accountable.
An independent critique showed that a store count plus keyset pages is not enough today: the store
applies no authorization, each query opens its own snapshot, scoped collections are traversals, and
some predicates run only in memory. The design therefore pins one authorized member manifest.

- **One relation:** Authorized rows, then the selector and type, then every membership predicate,
  then a stable unique order. A definition is pageable only when every predicate and the
  object-visibility rule evaluate inside that relation; otherwise the outcome is
  `population_predicate_not_pageable` and the existing truncation holds.
- **Visibility:** Projection keeps an unreadable object under an alias, so its existence is visible
  but its identity is not. A population that contains any identity-redacted member makes no exact
  claim and returns `population_visibility_indeterminate`. Receipts carry boundary digests, never
  raw identifiers, and adversarial tests prove that hidden rows change no caller-visible count,
  boundary, or completeness.
- **Manifest:** One repeatable-read transaction reads the ordered member identifiers of that relation
  up to a hard cap and Core stores them, with their digest, as the population manifest. Pages read
  members by manifest identifier; a member whose revision changed after the manifest makes the page
  `population_snapshot_unavailable` rather than a silently different set.
- **Traversal populations:** A scoped collection's population is the deduplicated set of reached
  endpoints of the stated kind, excluding roots and intermediate nodes, read completely once into the
  same kind of manifest; a cut traversal returns `population_traversal_incomplete`.
- **Processing:** Per-member readers keep their own processing receipts with a terminal disposition
  for every member: a value, a typed unknown, or pending. The population cursor advances only when
  every member of a page is terminal. Budget is reserved before a page is claimed; if not even one
  page fits, the outcome is `population_budget_no_progress`.
- **Continuation:** A dedicated collection-continuation variant, not the H5 change window, binds the
  deployment scope, principal digest, conversation, purpose, goal, plan, manifest, and query-semantics
  digests, the manifest digest, the cursor, the page size, and the expiry. Claiming leases the
  reference and issues the successor atomically, so a failed page keeps its reference.
- **Versions:** Object-set receipt 1.3.0 adds `population_status`, an optional count, page and
  cumulative counts, and boundary and manifest digests, with invariants that tie them to `complete`
  and `truncated`. A 1.2.0 reader treats any 1.3.0 partial population as an ordinary bounded result.
- **Stages:** P1 reads pageable object-set populations up to the cap within one turn, with no
  cross-turn continuation. P2 adds traversal populations. P3 adds processing receipts and the
  collection continuation.

| Population status | Outcome |
|-------------------|---------|
| `population_complete` | Complete answer over every member |
| `population_partial_resumable` | Partial verified answer with a continuation |
| `population_unknown`, `population_predicate_not_pageable` | Existing bounded result, stated as at least the members read |
| `population_visibility_indeterminate` | Partial answer with no exact count |
| `population_snapshot_unavailable`, `result_generation_changed` | Goal hold |
| `population_traversal_incomplete` | Partial answer with the traversal limitation |
| `population_budget_no_progress` | Hold with the budget reason |
| `population_processing_partial` | Partial answer; pending members are listed as unknown |

### E11 Metric filters and ranking over a collection

Questions such as "VMs with CPU above 90%" or "the VM with the highest CPU" restrict or order a
collection by a metric. Rank and metric filters hold today, and the metric inventory samples at
most 16 members.

- **Form:** A minor version adds a typed metric comparison: comparator and its cue, an exact decimal
  threshold and its span, and a stated unit and its span or an explicit `unit_unstated` status. A
  missing or ambiguous unit clarifies; it never inherits the canonical unit. A rank needs an order
  cue, and its limit needs a stated count; otherwise the answer is the complete ordered collection
  through continuations.
- **Reading:** Qualitative words such as high, low, or underused are not a rank or a threshold. They
  ground only to a reviewed threshold or utilization recipe per resource type; otherwise the goal
  clarifies or holds as `metric_classification_unavailable`.
- **Reader:** A collection metric read runs under a population receipt and an absolute window pinned
  on the first batch: total and processed counts, cursor, generation, cutoff, scope digests, and the
  metric registry digest. It reserves provider calls, series, cost, and wall time before each batch,
  prefers batch or server-side aggregation APIs, and stops on throttling with a typed partial result
  and continuation, never a retry of the same request.
- **Verify:** Input identities times metric concepts equal value-or-unknown rows; ranked identities
  are exactly the members with a complete value; ties order by a stated rule; V-CLAIM checks every
  value, comparison, unit, window, and rank position.
- **First slice:** Question form 1.1.0 adds a `metric` filter role with a typed comparison
  (`gt`, `ge`, `lt`, `le`; the operator's exact digits; `percent`, `ms`, `count`, `nanocores`, or
  `unit_unstated`), and an order limit that needs its quoted count. Admission checks that the value
  span holds exactly those digits, clarifies on `metric_unit_unstated`, and requires an order cue for
  a rank. The compiler checks the unit against the reviewed metric units and adds one metric stage
  to the collection plan. The metric reader, function version 1.2.0, reads every member in batches
  of 16 under one pinned window and a budget of 128 member reads. It filters and ranks only members
  with a complete value; ties order by Resource identifier. A list keeps one typed unknown row for
  each member it could not measure, and a stopped read reports `metric_budget_exhausted` or
  `metric_provider_unavailable` as incomplete. V-PROV re-derives the selection arguments from the
  goal, V-SEM rejects a metric filter the plan does not read, and review counts the typed
  comparison and order spans as stating their constraints. A metric filter with no comparison,
  such as high CPU, clarifies as `metric_threshold_unstated`. The metric reading is evidence scoped
  to the inventory set it reads, like Resource Health, so its authority composes with that set.
- **Remaining:** Reviewed qualitative recipes, the population receipt for sets beyond one page, a
  continuation after a stopped read, and live gold over the bank's metric questions.

### E12 Relations anchored on a collection

Questions such as "which VM is each network interface attached to" relate every member of one kind
to another. A relation needs a named anchor today, so these hold as `relation_anchor_missing`.

- **Form:** A discriminated collection-anchor shape, separate from the instance anchor, names the
  anchor kind and the result kind. It starts with one sense, one hop, and one reviewed LinkType side;
  transitive reach and all kinds keep their typed reasons until E9 prerequisites exist.
- **Compile:** The plan reads the anchor kind's members under a population receipt, then asks the
  secured traversal for per-anchor lineage rows and a per-anchor relation coverage receipt.
- **Negative claims:** An anchor with no related member is `VERIFIED_EMPTY` only with complete
  relation coverage for that anchor; otherwise it is `UNKNOWN_INCOMPLETE`, and hidden endpoints are
  never read as absence.
- **Verify:** Anchor identities equal the receipt's anchors, every edge is accounted once, and
  V-CLAIM rejects a negative relation claim without its coverage receipt.

### Status matrix for E10 to E12

| Condition | Outcome |
|-----------|---------|
| Population continuation required | Partial verified answer with a continuation |
| Population or topology generation changed | Goal hold, `result_generation_changed` |
| Metric threshold or unit missing or ambiguous | Clarification |
| Qualitative metric word without a reviewed recipe | Hold, `metric_classification_unavailable` |
| Metric window incomplete for a member | Member `UNKNOWN_INCOMPLETE`, never ranked or filtered in |
| Metric budget exhausted or provider throttled | Partial verified answer with a continuation |
| Member state or health evidence incomplete | Member `UNKNOWN_INCOMPLETE` with its typed reason |
| Relation coverage incomplete for an anchor | Anchor `UNKNOWN_INCOMPLETE` |
| Unsupported collection reach or sense | Unsupported with its typed reason |

**Exit for E10 to E12:** the matching bank questions answer with exact gold over the local
inventory, adversarial tests cover missing members, duplicate rows, truncated pages, ties, swapped
directions, hidden endpoints, and false empties, and no affected cell keeps
`measure_unsupported:state`, `measure_unsupported:health`, `measure_unsupported:metric`, or
`relation_anchor_missing`.

## Safety and authority

- Every package reads only and adds no execution path. A new slot, domain, recipe, or reader
  grounds by closed choice, and an ungrounded value holds its goal.
- Contract changes are additive minor versions under the rollout-safe version rules.
- Every new read passes V-SEM and V-PROV before it can answer, and each new hold uses a typed reason
  with a reviewed bilingual notice.

## Decisions requiring approval

1. E1 adds typed slots as a minor version of the judgment and frame contracts (proposed), rather
   than a new contract family.
2. E6 excludes equal-nearest members from group counts and reports them in `ambiguous_membership`
   (proposed), rather than counting a membership in each group.
3. E8 keeps `predictive_precedence` as the lowest grade that may name a graded hypothesis
   (proposed).

## Critique and revisions

An independent critique of the first draft found the following issues. This design includes each
revision.

| Finding | Revision |
|---------|----------|
| E8 didn't define how `predictive_precedence` is earned | A verified causal-grade receipt with repeated samples, refutation, and confounder checks; graded hypotheses only, after P3; a negative exit |
| Open R3 to R8 operations and senses had no owner | E9 owns each with its prerequisite and exit |
| E6 multi-root counting was incoherent | Nearest-root lineage, and equal-nearest members reported in a reconciled `ambiguous_membership` total |
| E5 reservation was neither executable nor falsifiable | A per-path reservation plan over every conditional stage and dimension, with boundary tests |
| The linked ledger didn't exist | The ledger exists and owns this document's remaining work |
| E10 to E12 measured completeness only after an upstream bound | A population receipt with counts, cursor, generation, and continuation |
| E10 relied on a state reader that omits members without evidence | Partial answers now; a one-row-per-member list mode before promotion |
| E11 had no provider call, cost, or window envelope | Reserved budgets, a pinned absolute window, batch APIs, and a typed stop on throttling |
| E11 coerced high, low, and underused into ranking | Reviewed thresholds or recipes only; otherwise clarify or hold |
| E11 could not verify comparator, unit, or rounding | A typed comparison operand with spans and an explicit unstated-unit status |
| E12 turned missing edges into none | `VERIFIED_EMPTY` only with complete per-anchor relation coverage |
| E12 reused the instance anchor field | A discriminated collection-anchor shape limited to one sense and one hop |
| New outcomes had no typed status | The E10 to E12 status matrix |
| The population count could reveal hidden members | Visibility inside the population relation, or `population_visibility_indeterminate` |
| One generation didn't pin one population across pages | A manifest read in one repeatable-read transaction, checked by member revision |
| Scoped collections are traversals | Deduplicated endpoint manifests and `population_traversal_incomplete` |
| In-memory predicates made counts and pages inexact | Only fully pushed-down definitions are pageable |
| A partial page could skip or repeat members | Per-member processing receipts and a leased, atomic continuation claim |
| The receipt version and outcomes were undefined | Receipt 1.3.0 invariants and the population status table |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-coverage-expansion.md) |
| The compiler, its checks, and the delivery rounds | [Ontology Reasoning Compiler](ontology-reasoning-compiler.md) |
| Handles and continuations | [Result Handles and Continuations](ontology-reasoning-result-handles.md) |
| Production shadow, verified answers, and promotion | [Promotion Program](ontology-reasoning-promotion-program.md) |
| Coverage lanes and closure tests | [Ontology Reasoning Coverage](ontology-reasoning-coverage.md) |
