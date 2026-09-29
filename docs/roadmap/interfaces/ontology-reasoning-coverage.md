---
title: Ontology Reasoning Coverage
---
# Ontology Reasoning Coverage

This document defines what complete, exact coverage means for ontology-grounded question answering,
records the measured limits that block it today, and owns the closure program and the Azure SRE
Agent quality bar. It extends the [Ontology Reasoning Compiler](ontology-reasoning-compiler.md).

> **Status:** Proposed plan, 2026-09-28. The Owner approved the eight compiler decisions and the four
> directives below on that date. The decisions at the end of this document still need approval.
> Nothing here is implemented.
>
> **Honesty boundary:** FDAI never claims that every question receives a complete, correct answer.
> It claims that every answer it gives is exact and verified, and that every gap is stated.

## Why answers come from the ontology

Retrieval-augmented generation with a frontier model answers fluently, but its facts come from
retrieved text and model memory, so nothing proves a count, identity, relation, or cause. FDAI uses
the model to understand the question and to phrase the answer, and uses the ontology to supply every
fact: typed identities, relations, states, and time from authoritative observation, checked claim by
claim. The goal is an answer that is exact, complete within its verified scope, and hallucination
free, and that is at least as useful as Azure SRE Agent on the same question.

## Design at a glance

| Guarantee | Target | Proof |
|-----------|--------|-------|
| G1 Declaration accounting | 100% accounted | Every applicable declaration and dimension is `supported`, `excluded` under governance, or `missing`; `missing` must be zero, and the support ratio is reported |
| G2 Form closure | 100% accounted | Every admissible factor cell compiles or returns a typed unsupported reason; the supported ratio per family is reported and may not regress |
| G3a Terminal invariants | 100% | Verification proves operand provenance, level fit, restrictive-atom blocking, V-CLAIM, the causal-claim rule, and zero execution authority on every emitted terminal |
| G3b Interpretation fidelity | 0 observed, bounded | Wrong-question answers are reported as `0/n` with a one-sided 95% upper bound over admitted ontology turns |
| M1 Answer coverage | Measured | The share of answerable questions answered correctly, per domain, locale, and evidence cohort |
| M2 SRE Agent parity | At least equal | Parity rubric v1 holds for every matched question and family in both locales, with zero FDAI hard failures |

Answer coverage cannot reach 100% by design:

1. **Model classification**: T1 form accuracy is statistical, and identical configurations varied
   between measured runs.
2. **Data and readers**: A question about an object without an instance source has no answer.
3. **Retention and scope**: Provider history retention, archive boundaries, inventory scope, and
   principal visibility bound every answer.
4. **Open language**: Paraphrases are unbounded, and only English and Korean catalogs exist.
5. **Authority**: An action request ends as a governed draft, never as an executed answer.

G3a turns each failure in these areas into a visible limitation, clarification, or hold. G3b cannot
prove a true zero; the model-authored restatement makes a misreading visible, and sampled audits
bound it. Social, knowledge, and advisory turns carry `not_applicable` for G3b.

## Owner directives

The Owner set these directives on 2026-09-28. The
[conversation grounding instruction](../../../.github/instructions/conversation-grounding.instructions.md)
makes them binding for code.

1. **No hard-coded or template answers**: The model authors every answer and restatement from
   verified evidence, and V-CLAIM checks every claim. Only catalog notices and verified data views
   render without the model, and they add no operational fact.
2. **No lexical meaning**: Regular expressions, keyword, alias, or phrase tables, and lexical ranking
   never decide meaning. The model decides from complete catalogs, and code validates.
3. **Nothing dropped by a bound**: Every finite set is processed in bounded batches with exact
   accounting.
4. **SRE Agent bar**: Answers match or exceed Azure SRE Agent, verified by side-by-side comparison of
   the question, the derivation, and the answer in the session browser.

| Step | Model | Code |
|------|-------|------|
| Understand the question | Proposes the logical form with source spans | Validates schema, spans, and enums |
| Select concepts and values | Chooses schema concepts and values from complete catalog shards | Validates identity, domain, and level, and accounts every shard |
| Bind identity and scope | None | Binds principal, scope, instances by exact lookup, handles, LinkTypes, paths, and FunctionTypes |
| Normalize time | Proposes typed temporal values with spans | Computes trusted instants and checks bounds |
| Resolve references | Points mentions at typed result handles | Validates handle scope and range |
| Plan and execute | None for compiled forms | Compiles, verifies, and executes |
| Compose the answer | Authors structured claims and prose from evidence | Runs V-CLAIM and accounts every row |
| Review | An independent model checks entailment | Holds or regenerates once |

## Measured baseline

These values were measured on 2026-09-28 against the active release and the local development graph.

| Dimension | Current | Target |
|-----------|---------|--------|
| Declarations with descriptors | 316 of 316: 89 ObjectTypes, 127 LinkTypes, 39 FunctionTypes, 54 ActionTypes, 7 Interfaces | 316 |
| Declarations visible to semantic judgment per turn | At most 96; 93 slots hold every ActionType and FunctionType, and five sampled questions saw no LinkType and at most two ObjectTypes | Every candidate of the grounded domain |
| Judgment capability projection of the complete manifest | 273 of 316 kept at 32,530 of 32,768 bytes; the tail is dropped silently | Not required after form judgment |
| LinkTypes with reviewed relation semantics | 15 with traits, 18 with both roles, 3 transitive, of 127 | 127 accounted |
| ObjectTypes reached by a LinkType | 79 of 89; `Incident` has no LinkType | 89 accounted |
| Declarations with Korean labels | 0 of 89 ObjectTypes and 0 of 127 LinkTypes; 112 of 114 `Resource.type` values have terms | Every operator-facing declaration |
| ObjectTypes with an instance source | 14 of 89 have instances in the local store; 56 of 89 have a lifecycle classification | 89 accounted |
| FunctionType argument contracts | 23 of 39 mark dependency-only inputs; none declares provenance for literal arguments or applicable anchor types | 39 |
| Structural coverage gate | 10 deterministic fixture questions with `production_ready=false` | One receipt per dimension |
| Finite question universe | 3,072 cases at the default grammar; 15,360 with all five evidence postures, above the 10,000-case cap | Sharded and closed |

## Limit register

Each row is a measured or code-derived constraint. A blocking limit makes a class of questions
unanswerable or wrong; a degrading limit makes answers partial.

| Limit | Evidence | Observed pressure | Effect | Resolution |
|-------|----------|-------------------|--------|------------|
| Descriptor selection keeps 96 candidates | `ManifestDescriptorIndex` `candidate_limit=96` with English lexical ranking | 93 of 96 slots are ActionTypes and FunctionTypes; Korean utterances share no tokens with English descriptors | Blocking: LinkTypes and most ObjectTypes are invisible to judgment | Form judgment needs no catalog; the model grounds each mention over its complete domain catalog |
| Judgment capability byte bound | `_MAX_JUDGMENT_CAPABILITY_BYTES` 32 KiB; the loop stops without a hold | 43 of 316 declarations drop from the complete manifest | Blocking and silent | Remove from form judgment; shard any remaining catalog |
| Judgment model attempts | `_MAX_SCHEMA_ATTEMPTS_PER_BINDING=3` per binding | Up to 8 judgment calls in one probed turn | Degrading: latency and cost | One form call plus at most one schema repair per pass |
| Terminal evidence references | `MAX_SEMANTIC_EVIDENCE_REFS=12`; `doc:` references share the field | An anchor with a five-step path needs 13; the 11-node gateway plan computes to about 16 | Blocking: multi-hop and multi-goal answers hold as `too_many_evidence_refs` | Typed goal manifests and document references in a versioned terminal contract |
| Plan size | `_MAX_PLAN_NODES=32` and at most 8 outputs per plan | Four goals share one plan | Blocking for large compound questions | Ordered plan batches with a bounded continuation |
| Execution time | 8 concurrent nodes, 30 seconds per node, 90-second request lifetime | Multi-wave plans | Degrading: deadline holds | Critical-path budgeting and a typed continuation |
| Wire and presentation | 256 KiB wire payload; Operator tables at 6 columns, 40 rows, and 512 characters per cell; 48,000-byte answer output | Wide or long results | Degrading: presentation omission | Shown-of-total counts, handle paging, and the complete table as a document |
| ObjectSet result limit | `ObjectSetDefinition.limit` at most 1,000 | 1,037 selectable Resources locally, 1,332 with role assignments | Blocking for inventory-wide counts and group counts | Secured aggregate pushdown with exact authorized counts |
| Traversal limits | Typed path default 100 and maximum 1,000 per step; at most 1,000 roots | One container has 191 direct children; attachment fan-in reaches 57 | Degrading: truncated relations | Compiled per-step limits and store-side path pushdown with lineage |
| Current-state gateway | Secured reads accept `as_of` only at the cutoff with at most 5 seconds of skew | Version and diff questions | Blocking for historical paths | Historical paths read retained topology revisions |
| Exact-name anchors | Name equality only | 63 names are shared by 219 Resources, up to 30 per name | Degrading: frequent clarification | Qualified mentions that resolve through a container or type |
| Lexical group membership | `parent_id contains <group name>` | Differs from `contains` links for 31 of 63 groups: 73 extra and 209 missing members; a reviewed member term with a particle can compete with the group anchor | Blocking: wrong members or unsupported membership answers | Exact group anchor plus `contains` closure in round R2; ground member filters from the group-only subjects |
| Assurance subject typing | Assurance projection must classify subject operands as reviewed declaration identifiers | Free text beside a group, such as Korean pluralized VM wording, can otherwise enter a terminal subject and fail contract validation | Blocking: turn crash instead of a typed hold or verified answer | Accept only ASCII declaration identifiers as assurance subject types; leave free text to the typed constraint and grounding checks |
| Lexical signals and regular expressions | `inventory-query-language.yaml` term lists, 17 `query_signal_matches` calls, and 16 `re.compile` sites in semantic modules | More than 50 reviewed term lists | Blocking under the directives | Model grounding and typed values; removal in lane L5 |
| Template answer renderers | Shape-specific answer text in `semantic_turn_processor.py` | Every compiled shape | Blocking under the directives | Evidence-bound composition with V-CLAIM |
| Question universe cap | `question_universe.py` `_MAX_CASES=10_000` | 15,360 cases with all evidence postures | Blocking for full closure | Sharded universe with a root receipt |
| Judgment output reserve | Active profile `reserved_output_tokens=2048` | Estimated 700 tokens for a full form and 2,900 with three full alternatives | Degrading: truncated output | Atom-diff alternatives and successive passes |
| Context windows | Preflight 4,000 characters; planning 8 turns and 12,000 characters; wire 12 turns | Long sessions | Degrading: lost referents | Typed result handles |
| History windows | Activity and recent changes at most 7 days; empty local topology history | Month-scale questions | Blocking beyond retention | Per-source time coverage and an `outside_retention` status |
| Value-domain groups | `property_values.py`: 512 values, 192 groups, 64 terms per group | 114 types in about 117 groups | Future blocking | Budget monitoring and a versioned increase |

## Exhaustive bounded processing

Every bound becomes a batch size. Each pass records what it covered, and the turn completes only when
the processed count equals the total or a typed continuation names the rest.

| Finite set | Bound | Pass rule | Accounting |
|------------|-------|-----------|------------|
| Domain catalog for grounding | Grounding prompt budget | Present every candidate in shards and evaluate all shards | Shard digests cover the domain digest exactly |
| Goals of one question | 4 goals and 16 mentions per pass | Judge successive passes over the remaining goals | Every goal has one admitted form |
| Plan nodes | 32 nodes and 8 outputs per plan | Ordered plan batches, then a bounded continuation | Every goal has a terminal status |
| Result rows | 1,000 per read and 40 per table view | Pushdown counts, paged reads, and the complete table as a document | Shown plus remaining equals the total |
| Evidence references | 12 terminal references | Typed goal manifests | Every leaf receipt is retained and reachable |
| Answer evidence | One author call | Author chunks, then synthesize | Every row is named, aggregated, or listed once |
| Question universe | 10,000 cases per shard | Shards under a root receipt | Every shard holds a passed receipt |
| Question-bank annotation and parity runs | 10 questions per batch | Batches until the catalog is exhausted | Every question has a record |

Each turn reserves its budget before work starts, and a batch starts only when its worst case fits:

| Stage | Model calls reserved | Notes |
|-------|---------------------:|-------|
| Preflight | 1 | Unchanged |
| Form judgment | 2 per pass | One call and at most one schema repair |
| Concept selection | 1 per shard | Shards of one domain run concurrently |
| Answer composition | 2 per chunk | One author call and at most one regeneration |
| Independent review | 1 per answer | Required before display |

When the reservation cannot fit the 90-second request lifetime or the per-turn model ceiling, the
turn returns the verified part and a continuation pinned to principal, scope, snapshot cutoff,
catalog digests, cursor, expiry, and remaining count. Automatic continuation stays within a per-turn
total ceiling, and beyond it the operator resumes explicitly.

## Coverage dimensions

A `ReasoningCoverageReceipt` extends the structural coverage receipt. It is keyed by release, role,
purpose, and locale, and records one state per applicable declaration and dimension: `supported`,
`excluded`, `missing`, or `not_applicable`. Applicability derives from the declaration kind.

| Dimension | Applies to | Supported when | Typical exclusion |
|-----------|------------|----------------|-------------------|
| D1 Descriptor | Every declaration | A principal-scoped descriptor exists | Unreadable for the role |
| D2 Language surface | ObjectTypes, LinkType roles, Interfaces, ActionTypes, operator-facing Properties | Reviewed English and Korean labels and descriptions exist as model context | `no_operator_surface` |
| D3 Relation semantics | LinkTypes | Traits, both roles, transitivity, and cardinality are reviewed | `relation_internal` |
| D4 Instance source | ObjectTypes | The type binds the instance store, a dedicated reader, or an owner projection | `schema_only` with the owning design |
| D5 Function contract | FunctionTypes | Each argument declares provenance: `span`, `anchor`, `handle`, `server`, or `default`; anchors declare applicable types | `not_conversational` |
| D6 Property semantics | Properties | Type, operators, unit, and value domain or free-text status are declared | `not_filterable` |
| D7 Evidence semantics | Instance sources | Completeness proof, freshness, time axes, and retention boundary are declared | None; a gap blocks D4 |
| D8 Presentation | Output kinds | Composition handles the kind, truncation, and continuation in both locales | None |

Exclusion governance keeps G1 honest. The default budget for new exclusions per release is zero.
Each exclusion names its reason, owning design, and expiry, and needs approval from the source owner
plus a reviewer independent of the author. Every release audits a random 10% of exclusions, at least
20 or all when fewer, and receipts publish the support ratio per dimension; an exclusion never counts
as support. Coverage work is catalog-as-code and grants no authority.

## Form closure

The closure test enumerates each factor exhaustively and tests their interactions instead of the
grammar's Cartesian product.

| Factor table | Cells | Each cell yields |
|--------------|-------|------------------|
| Relation sense by anchor ObjectType and position | 89 x 9 x 3 = 2,403 | LinkType sides or `no_link_of_sense` |
| Operation by subject scope, want, and time kind | 16 x 4 x 4 x 7 = 1,792 | Node pattern or typed unsupported reason |
| Filter role by operator-facing property | One cell per property and role | Predicate template or `not_filterable` |
| Function by measure and anchor type | 39 functions by applicable types | Function node or `no_applicable_function` |
| Interactions | Every factor pair, risk-selected triples, and every dependency topology of at most 4 goals | Plan batches within 32 nodes and 8 outputs each |

Every form maps to a canonical normalized-form identity, so shards and factor tables provably
partition the admissible space. The tables run without I/O in the focused gate, and a new declaration
without its cells fails the gate. Each family keeps an unsupported-cell budget and a no-regression
rule. `draft_action` stays outside G2 and compiles only to the governed action-draft handoff; the
model grounds the ActionType from the complete ActionType catalog, and ambiguity clarifies.

### Question taxonomy closure

The 400-question bank is the empirical denominator; 300 questions carry a result shape and 335 a
temporal scope.

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

Two annotators label every question independently as one form, a composite route that joins a form
with a document or advisory goal, a non-ontology path, or `unmapped`. Optimization and simulation use
the declared `optimize` and `simulate` logic capabilities only through reviewed advisory paths; until
then they are `unmapped`. The target is zero `unmapped` questions.

### Universe sharding

The finite question universe keeps its 10,000-case bound per shard. Shards are keyed by declaration
kind, perspective or operation family, and locale, and a root receipt binds every shard digest.

## Calibrated admission

- **Restatement**: Every compiled answer starts with a model-authored restatement of the admitted form
  in the operator's locale; V-CLAIM proves that every form atom appears.
- **Backoff lattice**: Accuracy is estimated per cell, then per operation family and locale, then
  globally. A one-sided 95% lower bound of 0.97 needs about 100 adjudicated cases without error, so a
  cell uses its family estimate until it has at least 30 own cases.
- **Confirm-first**: A cell below its risk tier's floor returns the restatement and one confirmation
  instead of results. Operator confirmations never count as gold.
- **Rate cap**: If confirm-first exceeds 15% of a family's admitted turns, the family stays in shadow.

## Capacity strategy

| Mechanism | Contract |
|-----------|----------|
| Aggregate pushdown | The secured gateway filters vertices, edges, predicates, and group keys by access policy, then counts in the store over the pinned generation |
| Path pushdown | The store executes one reviewed path grammar per call over one authorized pinned generation with per-root lineage, fan-out and memory limits, and completeness |
| Non-interference | Hidden entities contribute neither totals nor connectivity, and answers never surface hidden or redacted counts; differential tests compare principals that differ only in hidden data |
| Paging | Handles continue within one pinned generation; a generation change ends the cursor with `result_generation_changed` |
| Evidence manifests | A versioned terminal contract carries typed `goal_manifests` and `document_refs`; leaf receipts outlive the turn and its handles, and retrieval reauthorizes |
| Qualified mentions | Qualifier, relation, and target bind in one authorized pinned generation |

Capacity tests use a synthetic fixture graph at ten times the local graph. Synthetic data proves
mechanics only and never serves as live readiness evidence.

## Data and reader program

Reader priority combines unique question-bank demand with source readiness, risk, and cost. Each
reader is a read-only projection consumed through a typed FunctionType with one accountable agent.

| Gap | Question-bank demand | Authoritative source | Accountable agent |
|-----|----------------------|----------------------|-------------------|
| Workload and service mappings | 60 BusinessService and 15 Workload targets | Reviewed deployment mappings joined to inventory | Muninn |
| Incident collection | 50 Incident targets | Records written by the composition-owned `IncidentRegistry` | Heimdall, the declared lifecycle owner |
| Alerts | Alert questions in the detection domain | Provider alert records with source completeness | Heimdall |
| Causal joins | 23 CausalHypothesis targets and 56 root-cause questions | Metric windows and change evidence | Heimdall |
| Forecasts | 19 Forecast targets and 33 forecast-scope questions | `Forecast` records | Heimdall |
| Capacity forecasts | Capacity questions in the forecast domain | `CapacityForecast` records | Freyr |
| Cost observations | 14 CostObservation targets and 26 cost questions | Provider cost observations with currency and completeness | Njord |
| Topology history | Version and diff questions | Retained revisions per inventory generation | Muninn |
| `Resource.location` | Region questions | Declared property and existing inventory projection | Mimir |

## Assurance and SRE Agent parity

### Evaluation cohort

| Aspect | Contract |
|--------|----------|
| Types | Closure, relations, reviewed paths, containment, time and versions, cause versus correlation, evidence verification, relational aggregation, follow-up, and schema versus instance |
| Size | Per type, at least 12 development and 8 locked holdout cases split by locale, including honest negative and multi-turn cases |
| Gold | Two reviewers adjudicate form atoms, grounded concepts, LinkType set and side, node kinds, epistemic status, and forbidden outcomes |
| Levels | L1 measures live T1 form and grounding accuracy; L2 runs admission, compilation, execution, and V-CLAIM over the frozen fixture graph |
| Hard zeros | Silent semantic loss, operands without provenance, wrong-level answers, V-CLAIM escapes, unsupported causal claims, and unauthorized execution |

The session-local 68-case corpus moves into the repository with level, forbidden-function, and
required-atom checks. An A/A run differed by 1.5 points, so paired comparisons use three repeats,
bootstrap confidence intervals, and a 3-point noise band.

### SRE Agent parity

Azure SRE Agent answers with a frontier model and live Azure tools, which makes it the external bar
for usefulness. The [SRE Agent parity skill](../../../.github/skills/sre-agent-parity/SKILL.md) is
the procedure; the [comparison ledger](../../internals/sre-agent-comparison-ledger.md) already holds
39 matched runs over 120 seed questions.

- **Setup**: One Azure SRE Agent covers the same Owner-named subscription and resource scope as
  FDAI, with read-only role assignments and no action approval. The operator signs in to the session
  browser; the evaluator never handles credentials.
- **Matched run**: Each question goes to a new SRE Agent thread and a new FDAI conversation in the same
  locale within minutes. Both answers and both derivations are captured: SRE Agent tool steps and
  queries, and FDAI restatement, grounding, plan, receipts, and claims.
- **Truth**: A read-only truth query runs immediately after both answers, or an independent reviewer
  adjudicates. A question whose relevant state changed between the runs is inconclusive.
- **Attempts**: Each product answers each question once per parity run; FDAI stability comes from the
  repeated L1 cohort runs.
- **Records**: Redacted runs extend the ledger with the rubric version, raw captures stay private and
  expire, and SRE Agent output never becomes FDAI evidence.

Parity rubric v1 scores both products from 0 to 4 per criterion, and any unsupported or invented claim
is a hard failure:

| Criterion | A score of 4 means | Parity rule |
|-----------|--------------------|-------------|
| Correctness | Every material claim agrees with the independent truth | FDAI is never lower on any question |
| Completeness | Every item in the requested scope is present, with the exact total | FDAI is never lower on any question |
| Freshness | Time-sensitive claims use current evidence and state their observation time | FDAI is never lower on any question |
| Evidence integrity | Every claim is attributable to a named source the reader can trace | FDAI is never lower on any question |
| Safety | Read and action authority stay explicit and constrained | FDAI is never lower on any question |
| Process transparency | The derivation is visible and reproducible from the recorded steps | Family mean at least equal, and no question more than 1 point lower |
| Actionability | The answer gives a useful next check or governed action when appropriate | Family mean at least equal, and no question more than 1 point lower |
| Clarity | The answer is direct, well structured, and natural in the requested locale | Family mean at least equal, and no question more than 1 point lower |

M2 holds for a family when every matched question in both locales has no FDAI hard failure and every
parity rule holds. An inconclusive question never counts as a pass.

## Closure program

Lanes gate the compiler rounds per operation family, so one family can promote while another waits.

| Lane | Work | Before | After | Exit |
|------|------|--------|-------|------|
| L1a Contract design | Grounding, evidence-manifest, pushdown, qualified-mention, claim, and handle contracts with threat review | R1 | R0 | Reviewed contracts and threat model |
| L1b Capacity implementation | Pushdown, manifests, paging, plan batches, and critical-path budgets | R5 | R1 | Capacity tests at ten times the local graph without silent truncation |
| L2 Catalog completion | D2, D3, D5, and D6 authoring and review per family | That family's R3 to R5 | R0 | Zero `missing` cells for the family |
| L3 Readers and data | The reader program per family | That family's R6 and R7 | R1 | Zero `missing` D4 and D7 cells for the family |
| L4a Corpus and parity baseline | Cohort, holdout, taxonomy annotation, fixture graph, and SRE Agent baseline runs | R0 | Approval | Adjudicated gold and baseline parity records |
| L4b Closure infrastructure | Coverage receipt, factor tables, and sharded universe | R3 | R1 | G1 and G2 accounted with support ratios |
| L4c Calibration and parity | Admission lattice, restatement check, live audits, and parity reruns | R9 | R3 | G3a proven, G3b bounded, and M2 met |
| L5 Legacy removal | Lexical signals, regular expressions, selector-dependent judgment, recipe compilers, and template renderers | Release | R9 | Zero lexical or template paths in promoted families |

A family claims coverage only when G1, G2, G3a, and M2 hold for it, G3b is reported with its bound,
and M1 is reported for its domain.

## Reasoning types

| Type | Closure condition | Current blocker |
|------|-------------------|-----------------|
| Hierarchy and closure | Class concepts ground through closure receipts | No Korean class labels; closure unused by planning |
| Relations and paths | Every LinkType has traits and roles, and paths use reviewed grammars | 112 LinkTypes without traits |
| Containment | Membership uses `contains` closure from an exact anchor | Lexical `parent_id` matching |
| Time and versions | Every temporal source declares retention and time axes | Empty topology history, 7-day windows, current-state gateway |
| Cause and correlation | A cause want requires bound causal providers | Metric providers unbound locally |
| Evidence and completeness | Link evidence projects through the reviewed allowlist | Link evidence redacted |
| Relational aggregation | Aggregate pushdown with lineage | 1,000-row result limit |
| Follow-up | Typed handles with paging | Text-only context |
| Schema versus instance | Domain-restricted model grounding with restatement | No declaration labels |

## Decisions requiring approval

1. Adopt G1, G2, G3a, G3b, M1, and M2 with exclusion governance, and never claim 100% answer coverage.
2. Add aggregate and path pushdown to the secured gateway under the non-interference contract.
3. Replace terminal evidence overloading with typed goal manifests and document references.
4. Add qualified mentions, atom-diff alternatives, successive judgment passes, plan batches with a
   bounded continuation, and the taxonomy additions.
5. Require the model-authored restatement, the calibrated backoff lattice, and the 15% confirm-first
   rate cap.
6. Author bilingual labels and descriptions as model context, relation semantics, function
   provenance, and property semantics for every applicable declaration, with governed exclusions.
7. Shard the question universe and adopt factor and interaction closure tests.
8. Order new readers by demand, readiness, risk, and cost, with one accountable agent each.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-coverage.md) |
| Logical form, compiler, and answer composition | [Ontology Reasoning Compiler](ontology-reasoning-compiler.md) |
| Binding conversation rules | [Conversation grounding instruction](../../../.github/instructions/conversation-grounding.instructions.md) |
| SRE Agent comparison procedure | [SRE Agent parity skill](../../../.github/skills/sre-agent-parity/SKILL.md) |
| Matched SRE Agent runs and the seed catalog | [Comparison ledger](../../internals/sre-agent-comparison-ledger.md) |
| Current structural coverage contract | [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) |
| Finite question universe and campaigns | [Continuous Question Space](continuous-question-space.md) |
| ObjectSet bounds and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Agent ownership | [Agent Pantheon](../agents/agent-pantheon.md) |
