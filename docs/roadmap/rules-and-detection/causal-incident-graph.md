---
title: Causal Incident Graph
---
# Causal Incident Graph

This document defines how FDAI represents, evaluates, and closes causal claims for operational
incidents. It extends event correlation and root-cause analysis (RCA) with an ontology-grounded,
time-consistent graph while keeping execution authority in the existing control loop.

> **Authority boundary:** A causal graph is evidence for a decision, not permission to act. The
> rule verifier, safety check, approval policy, executor, and audit ledger remain authoritative.
>
> **Implementation status (2026-08-01):** The typed hypothesis lifecycle, weakest-link scoring,
> bounded time-consistent graph materializer, support/refutation and closure links, immutable
> ontology projector, lagged temporal analyzer, runtime coordinator, shadow control-loop caller,
> independent closure classifier, and regression tests are implemented. The control loop analyzes
> and audits in shadow but does not write the ontology as Forseti. Deployments bind bounded temporal
> series, a Forseti-owned projection publisher, independent outcome provider, and causal receipt
> resolver. Pre-routing temporal analysis has a bounded timeout, and only a scope- and time-matched
> verified intervention receipt can confirm closure. No causal result grants execution.

## Design at a glance

FDAI builds an incident subgraph as of one evidence cutoff, generates bounded root-cause
hypotheses, actively searches for evidence that both supports and refutes each hypothesis, and
records one of four causal evidence grades. Timing alone can show association; only controlled
intervention or an equivalent recovery reversal can establish interventional evidence.

![Design at a glance. The main stages are Events and observations, Correlated incident, Dependency topology, Time-consistent incident graph, CausalHypothesis candidates, Supporting evidence, Refuting evidence, Deterministic causal verifier, DecisionCase, Recovery plan, Observed outcome.](../../diagrams/generated/fdai-roadmap-rules-and-detection-causal-incident-graph-01.en.svg)

## Competency questions

The graph should answer these questions deterministically or return an explicit unknown:

1. Which change, failure, or external condition can explain the observed symptoms?
2. Which dependency path could propagate that cause to the affected service objective?
3. Which evidence contradicts each candidate cause?
4. What observation would discriminate between the remaining candidates?
5. Did an approved recovery action reverse the predicted effects within the declared window?
6. Did an approved chaos intervention reproduce the predicted effects without exceeding scope?

These questions define the required graph and query tests. New ontology types or links should not
be added only to improve visualization.

## Ontology contract

The design reuses `Incident`, `Finding`, `Observation`, `Change`, `Experiment`, `Resource`,
`Workload`, `BusinessService`, `ServiceObjective`, `DecisionCase`, `ActionRun`, and
`ObservedOutcome` from the operating ontology. It adds one durable semantic object.

### `CausalHypothesis` ObjectType

`CausalHypothesis` is an immutable revision of one machine-evaluable causal claim. A later
observation creates a new revision instead of rewriting the claim used by an earlier decision.

| Property | Type | Meaning |
|----------|------|---------|
| `id` | string | Stable id derived from incident, claimed cause, claimed effect, method version, and evidence cutoff. |
| `incident_id` | string | Incident whose symptoms the hypothesis explains. |
| `status` | string | `candidate`, `supported`, `refuted`, `inconclusive`, or `closed`. |
| `cause_ref` | string | Typed object or event claimed as the cause. |
| `effect_ref` | string | Finding, objective breach, or incident effect being explained. |
| `mechanism` | string | Bounded mechanism code from a reviewed catalog, not free-form authority. |
| `evidence_grade` | string | `association`, `predictive_precedence`, `quasi_experimental`, or `interventional`. |
| `confidence` | number | Score in `[0, 1]` after ambiguity and evidence-completeness penalties. |
| `ambiguity` | integer | Number of materially competitive root candidates at the cutoff. |
| `graph_revision` | string | Inventory and operating-model revision used for traversal. |
| `evidence_cutoff` | datetime | Latest event time eligible for the claim. |
| `method_version` | string | Deterministic scorer or reviewed reasoner version. |
| `created_at` | datetime | Time FDAI accepted this revision. |
| `closure` | string | Optional terminal result: `confirmed`, `refuted`, `inconclusive`, or `unsafe`. |

The object stores identifiers and scores only. Evidence bodies remain in their authoritative
stores and are cited through opaque references.

### Causal LinkTypes

The current LinkType schema can represent these relationships with typed endpoints and
`is_causal` or `temporal_order` flags.

| LinkType | Endpoints | Flags | Meaning |
|----------|-----------|-------|---------|
| `hypothesis_explains_finding` | CausalHypothesis -> Finding | `is_causal` | The effect the hypothesis attempts to explain. |
| `hypothesis_claims_change` | CausalHypothesis -> Change | `is_causal` | A change claimed as the root or contributing cause. |
| `hypothesis_claims_experiment` | CausalHypothesis -> Experiment | `is_causal` | An intervention used to test the mechanism. |
| `evidence_supports_hypothesis` | EvidenceArtifact -> CausalHypothesis | - | Evidence consistent with the predicted mechanism. |
| `evidence_refutes_hypothesis` | EvidenceArtifact -> CausalHypothesis | - | Evidence that contradicts a required prediction. |
| `hypothesis_precedes_hypothesis` | CausalHypothesis -> CausalHypothesis | `temporal_order` | Revision or narrowing order, never causal proof by itself. |
| `outcome_tests_hypothesis` | ObservedOutcome -> CausalHypothesis | `is_causal` | Independent post-action or experiment observation used for closure. |

Physical LinkType declarations keep one concrete source and target ObjectType. A deployment does
not use an untyped `caused_by` edge between arbitrary objects.

## Time-consistent incident subgraph

Muninn materializes the graph at the incident's evidence cutoff. The bounded traversal includes:

- the affected service, workload, and resource;
- incoming and outgoing `depends_on`, `runs_on`, `implemented_by`, and `contains` links;
- correlated findings, observations, changes, deployments, experiments, and action runs;
- active service and recovery objectives;
- topology freshness, source provenance, and unresolved conflicts.

The default traversal is depth 2 from the failing workload or resource. A configuration can lower
the depth or node cap but cannot silently raise it. Hitting a node, edge, time, or byte cap marks
the graph `truncated`; a truncated graph cannot support autonomous recovery.

Late events create a new graph revision. Replay always resolves the original catalog versions,
topology revision, and evidence cutoff.

## Candidate generation

Candidate generation is deterministic-first and bounded:

1. **T0 direct cause:** A matched rule contributes its declared mechanism and remediation.
2. **T1 temporal path:** A preceding change on the same resource or a dependency path becomes a
   candidate when it falls inside the configured mechanism window.
3. **T1 resolved-case reuse:** A prior incident contributes a candidate only when resource type,
   signal fingerprint, topology role, and mechanism still match.
4. **T2 grounded proposal:** When T0 and T1 remain ambiguous, the reasoner can rank only candidates
   and citations present in the bounded graph. It cannot invent an object, link, or action.

Every path retains a `no_known_cause` option. Candidate generation stops at the configured count;
overflow keeps the highest deterministic scores and records truncation.

## Adaptive observation selection

When two or more causal hypotheses remain active, FDAI can select the next observation that best
separates them. The selector receives only pre-verified, read-only query candidates. It performs no
provider read and cannot authorize a query, action, mutation, or promotion.

One immutable discrimination frame pins the incident, graph revision, evidence cutoff, active
hypothesis set, active-set receipt, and cost-model digest. Each content-addressed candidate predicts
whether the same observation would support, refute, or remain neutral for every active hypothesis.
Candidates from another frame or candidates that omit an active hypothesis remain explicit rejected
evidence.

Selection maximizes the number of hypothesis pairs with different predicted outcomes. Equal
candidates use the lower comparable cost and then content identity. Fewer than two active
hypotheses, no eligible candidate, or no separating observation produces a typed held result. The
replay receipt binds the complete candidate set, rejections, pair counts, selected candidate or hold
reason, schema, and method version. A caller must separately use the verified read-query path to run
the selected observation.

## Adaptive investigation session

An adaptive investigation is a bounded, read-only `Process` that repeats observation selection
without creating a second causal or execution system. Forseti is accountable for the workflow, while
a mechanical recorder advances the Process with revision compare-and-set. Heimdall alone supplies
observation and completeness evidence, Forseti alone accepts hypothesis revisions and the terminal
causal judgment, and Saga audits each terminal transition through its existing event boundary.

Each iteration binds this immutable lineage:
`Process and round -> frame digest -> selection receipt -> candidate digest -> verification receipt
-> OntologyQueryPlan digest -> execution receipt and result digest -> Forseti revision`. The chain
also pins workflow and reducer versions, ontology and query-manifest digests, principal scope, role,
purpose, evidence cutoff, source generation, completeness, truncation, scorer version, and actual
resource usage. Verification and dispatch form one fail-closed gateway operation, and no provider I/O
starts before validation succeeds.

Every Forseti revision cites the prior active-set receipt, prior frame, exact observation receipt,
scorer version, new graph revision, and new evidence cutoff. The Process revision compare-and-set
accepts one complete next active set. Late or competing revisions remain audit evidence and cannot
advance the session.

The session stops when the Forseti-owned scorer leaves one materially supported hypothesis, every
candidate is refuted, no query can distinguish the remaining candidates, or its round, query, time,
or cost budget is exhausted. Creation pins an absolute UTC deadline, monotonic elapsed-time policy,
all limits and units, and a budget-policy digest. The gateway reserves query count and estimated cost
before dispatch and reconciles actual usage once. Cancellation blocks new rounds, signals the
in-flight query, and competes through terminal Process compare-and-set. Late results can be audited
but cannot advance a cancelled or terminal session. Process `cancelled` and `timed_out` remain
distinct from investigation holds such as `cost_exhausted`.

A replay reducer reconstructs the same session from append-only `Process` evidence events and
rejects changed lineage, order, receipt, configuration, or terminal digest. Replay uses retained
content-addressed results only. It never calls a provider, executes a query, consumes a budget,
publishes a learning candidate, starts planning, or changes authority.

The active selector is the only policy whose observation may be executed. A challenger runs on the
same frozen frame in shadow mode, where the system measures agreement, pair separation, cost, and
held outcomes without returning the challenger selection to the query path. Separation and cost are
counterfactual predictions when the policies select different queries; realized evidence counts only
when they select the same query or come from separate governed active-policy cohorts. Saga records
comparisons, Muninn seals balanced cohorts, Norns alone compiles and publishes an inert
investigation-strategy candidate, and Mimir reviews it. Activation uses a reviewed immutable
configuration release, applies only to new sessions, and cannot replace the running session's pinned
selector.

After an eligible session closes, it may emit an authority-free typed planning-request event that
references the terminal session digest and evidence. Forseti starts a separate planning Process,
refreshes current context and target revisions, constructs the mandatory `no_action` baseline, and
owns treatment candidates, constraints, and simulations. Cancelled, timed-out, all-refuted,
incomplete, or truncated investigations do not request treatment planning. Investigation evidence
never bypasses Operational Planning, the safety check, human approval, Thor execution, independent
effect observation, Saga audit, or Vidar recovery.

The Operator API projects adaptive session events through a GET-only, RBAC-, tenant-, purpose-, and
principal-scoped Process reader. It returns bounded redacted summaries and opaque evidence
references, not raw query results. The projection includes Process revision, evidence cutoff, source
watermarks, release digest, freshness, truncation, unavailable receipts, and explicit
`mutation_controls: false`. The Console renders an Investigation Room inside Process detail with
active hypotheses, support and refutation counts, missing evidence, selected observation, shadow
comparison, budgets, and terminal reason.

## Causal scoring and refutation

Each candidate is scored over four independent factors:

- **Temporal precedence:** The cause occurred before the effect within the mechanism window.
- **Topological reachability:** A typed dependency path connects cause and effect.
- **Mechanism fit:** The observed direction and symptom pattern match a reviewed mechanism.
- **Intervention consistency:** A prior or current action changed the effect as predicted.

The chain score is the weakest hop score multiplied by evidence completeness and an ambiguity
penalty. A high average cannot hide one unsupported hop. Thresholds and weights are versioned
configuration and are replayed with the hypothesis.

For every supporting query, the verifier runs at least one refutation query. Examples include:

| Candidate | Supporting check | Refuting check |
|-----------|------------------|----------------|
| Bad deployment caused errors | Error rise followed deployment on affected instances. | Unchanged instances show the same rise before deployment. |
| Database saturation caused latency | Query latency and CPU rose before service latency along a dependency path. | Service latency rose while database latency and connections remained normal. |
| Network delay caused gateway latency | Internal and external path difference matches the affected edge. | Both paths changed equally or the dependency edge was healthy. |
| Quota pressure caused 429s | Requests exceeded the observed quota window. | 429s occurred below quota or another provider-wide failure explains them. |

Missing refutation data is `unknown`, not evidence in favor of the candidate.

## Evidence grades

FDAI reuses the existing `CausalEvidenceGrade` values:

| Grade | Minimum evidence | Maximum use |
|-------|------------------|-------------|
| `association` | Correlation or temporal co-occurrence only. | Explanation and investigation planning. |
| `predictive_precedence` | The candidate repeatedly precedes the effect and predicts its direction. | Recovery proposal in shadow or with human approval. |
| `quasi_experimental` | Comparable untreated cohort, natural experiment, or difference-in-differences evidence. | Bounded recovery eligibility when all other safety checks pass. |
| `interventional` | Approved chaos intervention or recovery reversal reproduces or removes the predicted effect. | Input to promotion evidence; never a standalone permission grant. |

An evidence grade can decrease when refuting evidence arrives. A lower grade creates a new
hypothesis revision and can demote the related action or chaos scenario to shadow mode.

Closure applies a deterministic, monotonic demotion rule. Only a `confirmed` closure backed by a
verified interventional receipt may raise a grade; every other closure keeps or lowers it.

| Closure | Resulting grade | Related action or experiment mode |
|---------|-----------------|-----------------------------------|
| `confirmed` | `interventional` | `gated`: eligible to enter the ordinary risk, approval, execution, and rollback gates. |
| `refuted` | `association` | `shadow` |
| `unsafe` | `association` | `shadow` |
| `inconclusive` | Unchanged, never raised | `shadow` |

The mode is derived from the immutable revision instead of being stored as authority. A revision
with any refuting reference, an unresolved status, or a grade below `quasi_experimental` stays in
`shadow`. `gated` is an eligibility statement for the existing safety path, never a permission
grant.

## Closure through recovery and chaos

A recovery or experiment declares expected observations before execution. Heimdall independently
measures the effect after Thor executes or Loki's approved experiment runs. Closure compares the
observed direction, magnitude, affected set, and time window with those predictions.
The verified intervention execution time must be strictly later than the hypothesis evidence
cutoff. Equality remains inconclusive because the pre-intervention evidence window is not separated.

- **Confirmed:** Required effects match and prohibited effects do not occur.
- **Refuted:** A required effect moves in the opposite direction or does not appear with complete
  telemetry.
- **Inconclusive:** Evidence is stale, incomplete, censored, or outside the declared window.
- **Unsafe:** The observed affected set or objective degradation exceeds the approved envelope.

An unsafe result triggers the experiment stop condition and Vidar's recovery path. It also blocks
promotion regardless of whether the original causal hypothesis was correct.

## Agent ownership

The fixed pantheon keeps single-writer ownership:

| Agent | Responsibility |
|-------|----------------|
| Huginn | Normalize event, observation, change, and experiment receipts. |
| Heimdall | Emit findings and independent support/refutation observations. |
| Forseti | Own `CausalHypothesis` revisions and the decision that consumes them. |
| Loki | Propose bounded experiments; never grade its own experiment outcome. |
| Thor | Execute only an approved action or experiment plan. |
| Vidar | Own rollback and forward-recovery control, request Thor execution, and record recovery outcome. |
| Saga | Append hypothesis, evidence, decision, action, and closure references. |
| Muninn | Materialize the time-consistent graph revision. |
| Mimir | Govern mechanism, rule, and action catalog versions. |

No synchronous agent call is introduced. Each write travels through typed pub/sub and remains safe
to retry.

## Failure behavior

The causal path chooses the safer result under uncertainty:

- stale topology, missing objectives, truncated traversal, conflicting ownership, or incomplete
  telemetry lowers the evidence grade and blocks automatic recovery;
- no candidate with sufficient support returns `inconclusive` and requests investigation;
- a reasoner citation outside the graph is rejected as fabricated;
- projection failure cannot erase the authoritative event or audit record;
- a graph query timeout records a bounded failure and does not fall back to an unbounded search.

## Delivery slices

Implementation can proceed in independently testable slices:

1. Add `CausalHypothesis` and the seven LinkTypes with loader and competency-query tests.
2. Project existing structured T1 causal chains into immutable hypothesis revisions.
3. Add support/refutation query contracts and evidence-completeness scoring.
4. Bind `IncidentMemberSource` and the dependency graph in production composition.
5. Add independent closure from `ObservedOutcome` and demotion on refutation or unsafe impact.
6. Feed eligible causal evidence into recovery and chaos promotion without raising autonomy.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Hypothesis lifecycle and ontology projection | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `projection.py`; `tests/core/rca/test_hypothesis.py`; `test_hypothesis_lineage_projection.py` | Immutable revisions, closure states, and evidence-only graph projection are covered by focused tests. |
| Time-consistent incident graph | implemented | `services/core-control-plane/src/fdai/core/rca/incident_graph.py`; `tests/core/rca/test_incident_graph.py` | Traversal is bounded by depth, count, time, and size and reports truncation. |
| Candidate generation and causal scoring | implemented | `services/core-control-plane/src/fdai/core/rca/t0.py`; `t1.py`; `evidence.py`; `tests/core/rca/test_coordinator.py`; `test_evidence.py` | Deterministic candidates, weakest-link scoring, support, and refutation paths are implemented. |
| Adaptive observation selection | implemented | `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; `tests/core/rca/test_discrimination.py` | Exact-frame candidates are content-addressed and ranked by pair separation without granting query or execution authority. |
| Adaptive investigation session and review surface | implemented | `core/read_investigation/adaptive*.py`; `core/rca/discrimination_shadow.py`; `core/operational_learning/investigation_strategy*.py`; `core/operational_planning/investigation_handoff.py`; `runtime/adaptive_investigation_runtime.py`; Operator and Console Process projections | The integrated session is bounded, replay-stable, shadow-aware, authority-free, and visible through the existing authenticated Process route. This is implementation evidence, not a governed live validation claim. |
| Shadow runtime and independent closure | implemented | `services/core-control-plane/src/fdai/core/rca/runtime.py`; `tests/core/rca/test_runtime.py`; `test_temporal_causality.py` | The upstream path remains shadow and evidence-only; no result grants execution authority. |
| Grade demotion and shadow retention | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py` (`close_causal_hypothesis`, `causal_action_mode`); `runtime.py` (`CausalRuntimeResult.action_mode`); `tests/core/rca/test_hypothesis.py`; `test_runtime.py` | Unsafe and refuting closure lowers the grade to `association`, no closure except verified `confirmed` may raise a grade, and every unresolved or contested revision resolves to `shadow`. The runtime exposes the derived mode; no promotion or execution consumer binds it yet, because the causal path is still shadow-only. |
| Deployment binding and operational evidence | in-progress | [Delivery slices](#delivery-slices); current change source audit | Provider and publisher seams exist, but each deployment must bind them and retain governed closure receipts before validation can be claimed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Bind the production evidence path and retain governed interventional closure evidence. |
| 2026-08-16 | implemented | Made unsafe closure demote the evidence grade, blocked any non-confirmed closure from raising a grade, and added the deterministic `causal_action_mode` derivation that keeps refuted, unsafe, inconclusive, contested, and weakly graded revisions in `shadow`. | `current change`; `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `services/core-control-plane/tests/core/rca/test_hypothesis.py`; focused run `pytest services/core-control-plane/tests/core/rca` passed 215 tests. | Bind the deployment evidence path and retain one governed interventional replay. |
| 2026-08-16 | implemented | Exposed the derived mode as `CausalRuntimeResult.action_mode` so the shadow decision is observable on the runtime path, and qualified the scope row: no promotion or execution consumer binds the mode yet. | `current change`; `services/core-control-plane/src/fdai/core/rca/runtime.py`; `services/core-control-plane/tests/core/rca/test_runtime.py`; focused run `pytest services/core-control-plane/tests/core/rca` passed 216 tests. | Bind the deployment evidence path and retain one governed interventional replay. |
| 2026-08-30 | implemented | Added replay-stable adaptive observation selection over exact-frame, pre-verified read-only candidates. Selection maximizes hypothesis-pair separation, records stale or incomplete candidates, and returns authority-free selected or held receipts. | `current change`; `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; focused discriminator tests, Ruff, and strict mypy. | Bind candidate production to the verified ontology query path and retain governed investigation evidence before claiming operational validation. |
| 2026-08-30 | implemented | Added the bounded adaptive investigation runtime, Process journal, exact verified-query gateway, active/challenger comparison, Norns-to-Mimir inert strategy review path, separate planning proposal, Operator projection, and Console Investigation Room. | `current change`; focused core, agent, runtime, Operator, Console, and Playwright checks. | Bind deployment-owned candidate and revision sources and retain governed live evidence before selector promotion. |
| 2026-08-30 | implemented | Completed 22 tracked critique and hardening rounds plus a final independent release review. The rounds hardened immutable identity, deadlines, cancellation, query authority, Process replay, shadow isolation, learning cohorts, planning handoff, Operator projection, Console overflow, large-result hashing, cold import, and at-least-once deduplication until only Low or no findings remained. | `current change`; 646 Core tests, 46 Operator tests, 19 Console tests, three Playwright viewport scenarios, Ruff, strict mypy, and the final task-only review. | Retain governed live evidence before selector promotion; local implementation evidence does not claim deployed validation. |

### Remaining work

- [ ] Bind bounded temporal series, the Forseti-owned projection publisher, independent outcomes, and causal receipt resolution in a deployment integration test.
- [ ] Retain one governed replay that proves a verified intervention closes or refutes a hypothesis without granting action authority.
- [x] Unsafe or refuting evidence lowers the hypothesis grade and keeps the related action or experiment in `shadow`, evidenced by `close_causal_hypothesis` and `causal_action_mode` in `services/core-control-plane/src/fdai/core/rca/hypothesis.py` and the focused cases in `services/core-control-plane/tests/core/rca/test_hypothesis.py`.

## Related docs

| To learn about | Read |
|----------------|------|
| Shared operational objects and ownership | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Detection, correlation, and current RCA | [Observability and Detection](observability-and-detection.md) |
| Action safety and execution contracts | [Action Ontology](../decisioning/action-ontology.md) |
| Multi-step governed execution | [Process Automation](../decisioning/process-automation.md) |
