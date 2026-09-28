---
title: Ontology Reasoning Coverage
---
# Ontology Reasoning Coverage

This document defines what 100% coverage means for ontology-grounded question answering, records
the measured capacity, catalog, and data limits that block it today, and owns the closure program
that reaches the achievable guarantees. It extends the
[Ontology Reasoning Compiler](ontology-reasoning-compiler.md).

> **Status:** Proposed plan, 2026-09-28. The Owner approved the eight compiler decisions on the same
> date. The decisions at the end of this document still need approval. Nothing here is implemented.
>
> **Honesty boundary:** FDAI never claims that every question receives a complete, correct answer.
> Coverage guarantees apply to declaration accounting, compile rules, and terminal behavior. Support
> ratios and answer coverage are measured quantities reported by cohort.

## Design at a glance

| Guarantee | Target | Proof |
|-----------|--------|-------|
| G1 Declaration accounting | 100% accounted | Every applicable declaration and dimension is `supported`, `excluded` under governance, or `missing`; `missing` must be zero, and the support ratio is reported |
| G2 Form closure | 100% accounted | Every admissible factor cell compiles or returns a typed unsupported reason; the supported ratio per family is reported and may not regress |
| G3a Terminal invariants | 100% | The verifier proves operand provenance, level fit, restrictive-atom blocking, the causal-claim rule, and zero execution authority on every emitted terminal |
| G3b Interpretation fidelity | 0 observed, bounded | Wrong-question answers are reported as `0/n` with a one-sided 95% upper bound over admitted ontology turns |
| M1 Answer coverage | Measured | The share of answerable questions answered correctly, per domain, locale, and evidence cohort |

Answer coverage cannot reach 100% by design:

1. **Model classification**: T1 form accuracy is statistical, and identical configurations varied
   between measured runs.
2. **Data and readers**: A question about an object without an instance source has no answer.
3. **Retention and scope**: Provider history retention, archive boundaries, inventory scope, and
   principal visibility bound every answer.
4. **Open language**: Paraphrases are unbounded, and only English and Korean catalogs exist.
5. **Authority**: An action request ends as a governed draft, never as an executed answer.

G3a turns each failure in these areas into a visible limitation, clarification, or hold. G3b cannot
prove a true zero; restatement makes a residual misreading visible, and sampled audits bound it.
Social, knowledge, and advisory turns carry `not_applicable` for G3b instead of entering its
denominator.

## Measured baseline

These values were measured on 2026-09-28 against the active release and the local development graph.

| Dimension | Current | Target |
|-----------|---------|--------|
| Declarations with descriptors | 316 of 316: 89 ObjectTypes, 127 LinkTypes, 39 FunctionTypes, 54 ActionTypes, 7 Interfaces | 316 |
| Declarations visible to semantic judgment per turn | At most 96; 93 slots hold every ActionType and FunctionType, and five sampled questions saw no LinkType and at most two ObjectTypes | Not required after form judgment |
| Judgment capability projection of the complete manifest | 273 of 316 kept at 32,530 of 32,768 bytes; the tail is dropped silently | Not required after form judgment |
| LinkTypes with reviewed relation semantics | 15 with traits, 18 with both roles, 3 transitive, of 127 | 127 accounted |
| ObjectTypes reached by a LinkType | 79 of 89; `Incident` has no LinkType | 89 accounted |
| Declarations with Korean terms | 0 of 89 ObjectTypes and 0 of 127 LinkTypes; 112 of 114 `Resource.type` values have terms | Every operator-facing declaration |
| ObjectTypes with an instance source | 14 of 89 have instances in the local store; 56 of 89 have a lifecycle classification | 89 accounted |
| FunctionType argument contracts | 23 of 39 mark dependency-only inputs; none declares provenance for literal arguments or applicable anchor types | 39 |
| Structural coverage gate | 10 deterministic fixture questions with `production_ready=false` | One receipt per dimension |
| Finite question universe | 3,072 cases at the default grammar; 15,360 with all five evidence postures, above the 10,000-case cap | Sharded and closed |

## Limit register

Each row is a measured or code-derived constraint. A blocking limit makes a class of questions
unanswerable or wrong; a degrading limit makes answers partial.

| Limit | Evidence | Observed pressure | Effect | Resolution |
|-------|----------|-------------------|--------|------------|
| Descriptor selection keeps 96 candidates | `ManifestDescriptorIndex` `candidate_limit=96` with English lexical ranking | 93 of 96 slots are ActionTypes and FunctionTypes; Korean utterances share no tokens with English descriptors | Blocking: LinkTypes and most ObjectTypes are invisible to judgment | Form judgment needs no catalog; concept resolution reads complete catalogs deterministically |
| Judgment capability byte bound | `_MAX_JUDGMENT_CAPABILITY_BYTES` 32 KiB; the loop stops without a hold | 43 of 316 declarations drop from the complete manifest | Blocking and silent | Remove the catalog from form judgment; make any remaining overflow an explicit hold |
| Judgment model attempts | `_MAX_SCHEMA_ATTEMPTS_PER_BINDING=3` per binding | Up to 8 judgment calls in one probed turn | Degrading: latency and cost | One form call plus at most one schema repair per turn |
| Terminal evidence references | `MAX_SEMANTIC_EVIDENCE_REFS=12`; `doc:` references share the field | An ObjectSet emits 2, each typed-path step 2 plus 1 output, each function 1: an anchor with a five-step path needs 13, and the 11-node gateway plan computes to about 16 | Blocking: multi-hop and multi-goal answers hold as `too_many_evidence_refs` | Typed goal manifests and document references in a versioned terminal contract |
| Plan size | `_MAX_PLAN_NODES=32` and at most 8 outputs per plan | Four goals share one plan | Blocking for large compound questions | Compile-time budget; `question_too_complex` with a split suggestion |
| Execution time | 8 concurrent nodes, 30 seconds per node, 90-second request lifetime | Multi-wave plans | Degrading: deadline holds | Critical-path budgeting at compile time and a typed `deadline_budget_exceeded` |
| Wire and presentation | 256 KiB wire payload; Operator tables at 6 columns, 40 rows, and 512 characters per cell; answer output 48,000 bytes | Wide or long results | Degrading: presentation omission | Declared projections, shown-of-total counts, and handle paging |
| ObjectSet result limit | `ObjectSetDefinition.limit` at most 1,000 | 1,037 selectable Resources locally, 1,332 with role assignments | Blocking for inventory-wide counts and group counts | Secured aggregate pushdown with exact authorized counts |
| Traversal limits | Typed path default 100 and maximum 1,000 per step; at most 1,000 roots | One container has 191 direct children; attachment fan-in reaches 57 | Degrading: truncated relations | Compiled per-step limits and store-side path pushdown with lineage |
| Current-state gateway | Secured reads accept `as_of` only at the cutoff with at most 5 seconds of skew | Version and diff questions | Blocking for historical paths | Historical paths read retained topology revisions, never the current gateway |
| Exact-name anchors | Name equality only | 63 names are shared by 219 Resources, up to 30 per name | Degrading: frequent clarification | Qualified mentions that resolve through a container or type |
| Lexical group membership | `parent_id contains <group name>` | Differs from `contains` links for 31 of 63 groups: 73 extra and 209 missing members, from 11 name-substring pairs and letter-case differences in 23 groups | Blocking: wrong members in current answers | Exact group anchor plus `contains` closure |
| Lexical signal lists | `inventory-query-language.yaml` and 17 `query_signal_matches` calls | More than 50 reviewed term lists | Degrading: paraphrases miss | Retire after form promotion |
| Question universe cap | `question_universe.py` `_MAX_CASES=10_000` | 15,360 cases with all evidence postures | Blocking for full closure | Sharded universe with a root receipt |
| Judgment output reserve | Active profile `reserved_output_tokens=2048` | Estimated 700 tokens for a full form and 2,900 with three full alternatives | Degrading: truncated output | Alternatives as atom diffs and a serialized-size cap |
| Context windows | Preflight 4,000 characters; planning 8 turns and 12,000 characters; wire 12 turns | Long sessions | Degrading: lost referents | Typed result handles |
| History windows | Activity and recent changes at most 7 days; empty local topology history | Month-scale questions | Blocking beyond retention | Per-source time coverage and an `outside_retention` status |
| Value-domain groups | `property_values.py`: 512 values, 192 groups, 64 terms per group | 114 types in about 117 groups | Future blocking | Budget monitoring and a versioned increase |
| Canonical property values | The capability projection omits canonical values above 32 properties | `Decision` has 31 properties | Future silent loss | Unused by form judgment; gated on the bound meanwhile |

## Coverage dimensions

A `ReasoningCoverageReceipt` extends the structural coverage receipt. It is keyed by release, role,
purpose, and locale, and records one state per applicable declaration and dimension: `supported`,
`excluded`, `missing`, or `not_applicable`. Applicability derives from the declaration kind, so D3
applies only to LinkTypes and D5 only to FunctionTypes.

| Dimension | Applies to | Supported when | Typical exclusion |
|-----------|------------|----------------|-------------------|
| D1 Descriptor | Every declaration | A principal-scoped descriptor exists | Unreadable for the role |
| D2 Language surface | ObjectTypes, LinkType roles, Interfaces, ActionTypes, operator-facing Properties | Reviewed English and Korean terms exist | `no_operator_surface` for internal types |
| D3 Relation semantics | LinkTypes | Traits, both roles, transitivity, and cardinality are reviewed | `relation_internal` |
| D4 Instance source | ObjectTypes | The type binds the instance store, a dedicated reader, or an owner projection | `schema_only` with the owning design |
| D5 Function contract | FunctionTypes | Each argument declares provenance: `span`, `anchor`, `handle`, `server`, or `default`; anchors declare applicable types | `not_conversational` |
| D6 Property semantics | Properties | Type, operators, unit, and value domain or free-text status are declared | `not_filterable` |
| D7 Evidence semantics | Instance sources | Completeness proof, freshness, time axes, and retention boundary are declared | None; a gap blocks D4 |
| D8 Presentation | Output kinds | A bilingual renderer handles the kind, truncation, and continuation | None |

Exclusion governance keeps G1 honest:

- **Budget**: The default budget for new exclusions per release is zero; raising it is a reviewed
  catalog change.
- **Record**: Each exclusion names its reason, owning design, and expiry, and needs approval from the
  source owner plus a reviewer independent of the author.
- **Audit**: Every release audits a random 10% of exclusions, at least 20 or all when fewer, and
  reverts unjustified ones.
- **Reporting**: Receipts publish the support ratio, supported over applicable, per dimension; an
  exclusion never counts as support.

Coverage work is catalog-as-code, and each change is a reviewed declaration revision that grants no
authority.

## Form closure

The closure test does not enumerate the Cartesian product of the grammar. It enumerates each factor
exhaustively and tests their interactions:

| Factor table | Cells | Each cell yields |
|--------------|-------|------------------|
| Relation sense by anchor ObjectType and position | 89 x 9 x 3 = 2,403 | LinkType sides or `no_link_of_sense` |
| Operation by subject scope, want, and time kind | 16 x 4 x 4 x 7 = 1,792 | Node pattern or typed unsupported reason |
| Filter role by operator-facing property | One cell per property and role | Predicate template or `not_filterable` |
| Function by measure and anchor type | 39 functions by applicable types | Function node or `no_applicable_function` |
| Interactions | Every factor pair, risk-selected triples, and every dependency topology of at most 4 goals | One plan within 32 nodes and 8 outputs, or `question_too_complex` |

Every form maps to a canonical normalized-form identity, so shards and factor tables provably
partition the admissible space. The tables run without I/O in the focused gate for every catalog or
compiler change, and a new declaration without its cells fails the gate. Each family keeps an
unsupported-cell budget and a no-regression rule, so returning unsupported everywhere cannot pass.

`draft_action` stays outside G2. It compiles only to the existing governed action-draft handoff,
choosing an ActionType through reviewed bilingual action terms and target-type compatibility; any
ambiguity clarifies, and the draft grants no execution authority.

### Question taxonomy closure

The 400-question bank is the empirical denominator. Of its questions, 300 carry a result shape and
335 a temporal scope; the rest are annotated from their wording.

| Question-bank shape or scope | Count | Form mapping |
|------------------------------|-------|--------------|
| Assessment | 124 | `diagnose` or `lookup` with health and state measures |
| List | 84 | `select` |
| Ranked list | 48 | `rank` |
| Graph | 20 | `traverse` or `path` |
| Comparison | 12 | `compare_entities` or `compare_windows` |
| Timeline | 12 | `history` |
| Historical scope | 94 | `history`, `diff_versions`, or `compare_windows` |
| Forecast scope | 33 | `lookup` with a `forecast` measure and `future` time |

Two annotators label every question independently with one of four route classes: one form, a
composite route, a non-ontology path (general knowledge, governed document, advisory, social, or
action draft), or `unmapped`. A composite route joins a form with a document or advisory goal, such
as a recommendation grounded in live data. Optimization and simulation questions use the declared
`optimize` and `simulate` logic capabilities only through reviewed advisory paths; until those exist
they are `unmapped`. The target is zero `unmapped` questions, and scope cardinality and locale
transitions are coverage axes of the annotation.

### Universe sharding

The finite question universe keeps its 10,000-case bound per shard. Shards are keyed by declaration
kind, perspective or operation family, and locale, and a root receipt binds every shard digest. Full
closure requires a passed epistemic receipt for every shard. Campaign selection stays at 100 cases
per run.

## Calibrated admission

- **Restatement**: Every compiled answer starts with a deterministic restatement of the admitted form
  in the operator's locale. An independent form-to-text check proves that every atom appears in both
  locales.
- **Backoff lattice**: Accuracy is estimated per cell, then per operation family and locale, then
  globally. A one-sided 95% lower bound of 0.97 needs about 100 adjudicated cases without error, so a
  cell uses its family estimate until it has at least 30 own cases.
- **Confirm-first**: A cell whose applicable bound is below its risk tier's floor returns the
  restatement and one confirmation instead of results. Operator confirmations are recorded but never
  count as gold.
- **Cold start**: New cells collect shadow evidence before they may answer directly.
- **Rate cap**: If confirm-first exceeds 15% of a family's admitted turns, the family stays in shadow
  instead of shipping a confirmation-heavy experience.

## Capacity strategy

| Mechanism | Contract |
|-----------|----------|
| Aggregate pushdown | The secured gateway filters vertices, edges, predicates, and group keys by access policy before counting inside the store over the pinned generation, and returns exact counts within the authorized view |
| Path pushdown | The store executes one reviewed path grammar per call over one authorized pinned generation, keeps per-root lineage, applies per-step fan-out and memory limits, and reports completeness; historical paths read retained topology revisions |
| Non-interference | Hidden entities contribute neither totals nor connectivity, answers state only completeness within the authorized view, and hidden or redacted counts are never surfaced; differential tests compare principals that differ only in hidden data |
| Paging | Result handles support continuation within one pinned generation, a generation change ends the cursor with a typed `result_generation_changed` status, and every list states shown and total counts |
| Evidence manifests | A versioned terminal contract carries typed `goal_manifests` and `document_refs`; each manifest binds principal, purpose, goal, plan, generation, and retention, leaf receipts outlive the turn and its handles, and retrieval reauthorizes and holds on a missing leaf |
| Qualified mentions | A mention can cite a qualifier mention and sense; qualifier, relation, and target bind in one authorized pinned generation |
| Output budget | Alternatives are atom diffs, at most 3 diffs of at most 6 atoms, and a form above 6 KiB returns `question_too_complex` |

Capacity tests use a synthetic fixture graph at ten times the local graph. Synthetic data proves
mechanics only and never serves as live readiness evidence.

## Data and reader program

Reader priority combines unique question-bank demand with source readiness, risk, and cost. Each
reader is a read-only projection consumed through a typed FunctionType, has one accountable agent,
and creates no new object ownership.

| Gap | Question-bank demand | Authoritative source | Accountable agent |
|-----|----------------------|----------------------|-------------------|
| Workload and service mappings | 60 BusinessService and 15 Workload targets | Reviewed deployment mappings joined to inventory | Muninn |
| Incident collection | 50 Incident targets | Records written by the composition-owned `IncidentRegistry` | Heimdall, the declared Incident lifecycle owner |
| Alerts | Alert questions in the detection domain | Provider alert records with source completeness | Heimdall |
| Causal joins | 23 CausalHypothesis targets and 56 root-cause questions | Metric windows and change evidence | Heimdall |
| Forecasts | 19 Forecast targets and 33 forecast-scope questions | `Forecast` records | Heimdall |
| Capacity forecasts | Capacity questions in the forecast domain | `CapacityForecast` records | Freyr |
| Cost observations | 14 CostObservation targets and 26 cost questions | Provider cost observations with currency and completeness | Njord |
| Topology history | Version and diff questions | Retained revisions per inventory generation | Muninn |
| `Resource.location` | Region questions | Declared property and existing inventory projection | Mimir |

## Closure program

Lanes gate the compiler rounds per operation family, not globally, so one family can promote while
another waits for its catalog or reader work.

| Lane | Work | Before | After | Exit |
|------|------|--------|-------|------|
| L1a Contract design | Evidence-manifest, pushdown, qualified-mention, output-budget, and handle contracts with threat review | R1 | R0 | Reviewed contracts and threat model |
| L1b Capacity implementation | Pushdown, manifests, paging, and critical-path budgeting | R5 | R1 | Capacity tests at ten times the local graph pass without silent truncation |
| L2 Catalog completion | D2, D3, D5, and D6 authoring and review per family | That family's R4 and R5 | R0 | Zero `missing` cells for the family |
| L3 Readers and data | The reader program above per family | That family's R6 and R7 | R1 | Zero `missing` D4 and D7 cells for the family |
| L4a Corpus and gold | Cohort, holdout, taxonomy annotation, and fixture graph | R0 | Approval | Adjudicated gold with two annotators |
| L4b Closure infrastructure | Coverage receipt, factor tables, and sharded universe | R3 | R1 | G1 and G2 accounted with support ratios |
| L4c Calibration | Admission lattice, restatement check, and live audits | R9 | R3 | G3a proven and G3b reported with bounds |
| L5 Legacy removal | Lexical signals, selector-dependent judgment, and recipe compilers | Release | R9 | Zero lexical routes in promoted families |

A family claims coverage only when G1, G2, and G3a hold for its declarations and shards, G3b is
reported with its bound, and M1 is reported for its domain.

## Reasoning types

| Type | Closure condition | Current blocker |
|------|-------------------|-----------------|
| Hierarchy and closure | Class concepts resolve through closure receipts | No Korean class terms; closure unused by planning |
| Relations and paths | Every LinkType has traits and roles, and paths use reviewed grammars | 112 LinkTypes without traits |
| Containment | Membership uses `contains` closure from an exact anchor | Lexical `parent_id` matching |
| Time and versions | Every temporal source declares retention and time axes | Empty topology history, 7-day windows, current-state gateway |
| Cause and correlation | A cause want requires bound causal providers | Metric providers unbound locally |
| Evidence and completeness | Link evidence projects through the reviewed allowlist | Link evidence redacted |
| Relational aggregation | Aggregate pushdown with lineage | 1,000-row result limit |
| Follow-up | Typed handles with paging | Text-only context |
| Schema versus instance | Domain-restricted resolution with restatement | No declaration terms |

## Decisions requiring approval

1. Adopt G1, G2, G3a, G3b, and M1 with exclusion governance, and never claim 100% answer coverage.
2. Add aggregate and path pushdown to the secured gateway under the non-interference contract.
3. Replace terminal evidence overloading with typed goal manifests and document references in a
   versioned contract.
4. Add qualified mentions, atom-diff alternatives, the 6 KiB form cap, compile-time plan and
   deadline budgets, and the taxonomy additions.
5. Require restatement on compiled answers, the calibrated backoff lattice, and the 15%
   confirm-first rate cap.
6. Author bilingual terms, relation semantics, function provenance, and property semantics for every
   applicable declaration, with governed exclusions for the rest.
7. Shard the question universe and adopt factor and interaction closure tests.
8. Order new readers by demand, readiness, risk, and cost, with one accountable agent each.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-coverage.md) |
| Logical form, compiler, and verifier | [Ontology Reasoning Compiler](ontology-reasoning-compiler.md) |
| Current structural coverage contract | [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) |
| Finite question universe and campaigns | [Continuous Question Space](continuous-question-space.md) |
| Query contracts and work packages | [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md) |
| ObjectSet bounds and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Relationship coverage accounting | [Ontology Structural Model](../architecture/ontology-structural-model.md) |
| Agent ownership | [Agent Pantheon](../agents/agent-pantheon.md) |
