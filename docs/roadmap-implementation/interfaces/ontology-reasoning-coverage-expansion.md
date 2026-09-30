# Ontology Reasoning Coverage Expansion and Current-Path Convergence implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The [owner design](../../roadmap/interfaces/ontology-reasoning-coverage-expansion.md) was recorded
on 2026-10-01 after an independent critique, and its decisions await Owner approval. Parts of E2,
E5, and E7 exist: the current path holds a declaration-only plan for an instance answer kind,
schema questions answer from compiled schema goals in the local typed-only profile, and
`Incident.status` is a reviewed lifecycle domain, as the [compiler ledger](ontology-reasoning-compiler.md)
records. The open items below moved here from the compiler ledger with their progress notes; their
earlier history stays in that ledger.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| E1 Typed constraint slots | not-started | Design only | Judgment and frame contracts gain slots under a minor version |
| E2 Operand provenance | in-progress | The instance-versus-schema hold in [`semantic_plan_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_plan_coverage.py) | Binding receipts are not started |
| E3 Relations on the current path | not-started | Design only | The shared relation compiler and closed T2 meaning axes |
| E4 Standalone questions | not-started | Design only | Routing needs a bound reference |
| E5 Turn budget reservation | in-progress | Compiled schema goals in the local typed-only profile | The per-path reservation plan is not started |
| E6 Grouping by container kind | not-started | Design only | Nearest-root lineage and `ambiguous_membership` |
| E7 Health, history, and lifecycle | in-progress | The `Incident.status` lifecycle domain and health-filtered lists | Single-target health, state history, and other domains |
| E8 Causal change points | not-started | Causal context only | Needs H5, the causal-grade receipt, and P3 |
| E9 Remaining operators and senses | not-started | Typed unsupported reasons in the coverage receipt | Each row waits for its prerequisite |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-01 | in-progress | Recorded the design after an independent critique, moved eight open items here from the compiler ledger with their progress notes, and added the E9 operators item. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-coverage-expansion.md`; `docs/roadmap/interfaces/ontology-reasoning-coverage-expansion-ko.md` | Implement E5 and E7 in Wave 1. |

### Remaining work

- [ ] Finish R2: enforce interim operand-provenance and instance-versus-schema checks on the current
  path, with zero invented identity literals and zero schema answers to instance targets on both
  corpora.
  Note 2026-09-30: a check that required every identity operand of a model-proposed plan to appear in
  the utterance, earlier turns, or the bound context was tried and withdrawn before commit, because
  59 planner tests showed that server-grounded identities, such as an exact name binding's resource
  id, also reach model plans; the check must first trust the grounding receipts that bound them.
  Progress 2026-09-30: the instance-versus-schema half is enforced: a current-path plan that reads only
  ontology declarations is held as `semantic_reading_unverified` when the blind reading asks for a
  state, value, location, history, or cause, as
  `test_a_schema_answer_to_an_instance_question_holds_as_an_unverified_reading` shows. Operand
  provenance and the zero counts on both corpora remain.
- [ ] Compile a Resource Health lookup of one bound Resource through a reviewed single-target health
  read and the state history of one Resource through state transitions, and declare reviewed
  lifecycle domains for other ObjectTypes whose `status` the ontology projects. Exit:
  `check-reasoning-coverage.py` no longer reports `measure_unsupported:health` or
  `measure_unsupported:state`, and a stated state on each projected ObjectType grounds.
- [ ] On the current path, give relationship questions about one named instance a typed plan through the relation compiler, and
  compare the T2 state review on meaning axes rather than facet tokens, so neither holds a question the ontology can answer.
- [ ] Keep standalone questions on the verified path inside long conversations: a live probe after the current-path fixes saw the
  router mark standalone service-health and Key Vault questions as thread-dependent, which sent one to an ambiguous hold and one to
  an advisory reading, and saw one judgment type `인시던트` as a Resource subtype instead of the Incident ObjectType. Exit: the same
  questions asked late in a 20-turn conversation reach the same verified answers as in a fresh one across two repeats.
- [ ] Carry typed constraint slots in the judgment and frame contracts, mapped one-to-one from the
  blind reading's `ConstraintRole` values: time window, location or property predicate, lifecycle
  status per ObjectType, group-by measure, relation path, and prior-result or ordinal reference, each
  grounded by closed-choice selection against the ontology. Exit: zero uncovered-constraint holds for
  the traced window, region, and incident-status questions across two repeats.
- [ ] Answer ObjectType-schema questions through a closed ontology-schema form instead of selecting
  every declaration descriptor, and reserve frame budget before adaptive planning spends the turn
  budget. Exit: no judgment token-budget or adaptive budget-exceeded event on the traced schema and
  change-window questions.
  Progress 2026-09-30: with typed-only answering in the local profile, a schema question answers only
  from a compiled schema goal, as `test_schema_goal_reads_declarations_and_never_instances` and
  `test_typed_only_ends_a_declined_read_with_its_decision_and_never_the_legacy_cascade` show, and a
  `declares` word now needs no span beside schema goals; the frame budget reservation for the current
  path and the traced live events remain.
- [ ] Let a count grouped by container name the group's kind, such as resource group, and group
  members by the nearest ancestor of that kind through `contains` closure. Exit: the traced per-group
  count answers with one count per resource group instead of a hold.
- [ ] Give causal context an effect change point and complete accounting: read state-transition change
  points once trusted coverage exists, page the full activity window with a pinned continuation, and
  add a reviewed mechanism catalog and refutation queries before any evidence grade is shown. Exit: a
  why question about a state change lists the change point and every operation in its window, and
  no answer states a cause below the `predictive_precedence` grade.
- [ ] Compile each remaining operation and relation sense in E9 once its prerequisite exists: rank
  and non-count aggregates, window and entity comparisons, versions and `as_of`, evidence
  verification, diagnose recipes, paths, and the composition, ownership, authorization, and
  classification senses. Exit: each row's cells compile in `check-reasoning-coverage.py` with hard
  zeros on the holdout, or keep a typed unavailability reason where the data doesn't exist.
