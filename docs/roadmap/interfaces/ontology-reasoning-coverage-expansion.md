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
relational frame slots must be represented by the verified plan.

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
  aggregate operation over typed lineage rows; it remains shadow/local until promoted.

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

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-coverage-expansion.md) |
| The compiler, its checks, and the delivery rounds | [Ontology Reasoning Compiler](ontology-reasoning-compiler.md) |
| Handles and continuations | [Result Handles and Continuations](ontology-reasoning-result-handles.md) |
| Production shadow, verified answers, and promotion | [Promotion Program](ontology-reasoning-promotion-program.md) |
| Coverage lanes and closure tests | [Ontology Reasoning Coverage](ontology-reasoning-coverage.md) |
