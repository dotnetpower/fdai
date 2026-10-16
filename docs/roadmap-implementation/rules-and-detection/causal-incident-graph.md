# Causal Incident Graph implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status (2026-08-01):** The typed hypothesis lifecycle, weakest-link scoring,
> bounded time-consistent graph materializer, support/refutation and closure links, immutable
> ontology projector, lagged temporal analyzer, runtime coordinator, shadow control-loop caller,
> independent closure classifier, and regression tests are implemented. The control loop analyzes
> and audits in shadow but does not write the ontology as Forseti. Deployments bind bounded temporal
> series, a Forseti-owned projection publisher, independent outcome provider, and causal receipt
> resolver. Pre-routing temporal analysis has a bounded timeout, and only a scope- and time-matched
> verified intervention receipt can confirm closure. No causal result grants execution.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Hypothesis lifecycle and ontology projection | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `projection.py`; `tests/core/rca/test_hypothesis.py`; `test_hypothesis_lineage_projection.py` | Immutable revisions, closure states, and evidence-only graph projection are covered by focused tests. |
| Time-consistent incident graph | implemented | `services/core-control-plane/src/fdai/core/rca/incident_graph.py`; `tests/core/rca/test_incident_graph.py` | Bounded traversal preserves source metadata and excludes invalid relationship evidence. A current-store traversal explicitly reports `historical_topology_unavailable` instead of claiming a historical snapshot; secured topology history remains the historical query path. |
| Candidate generation and causal scoring | implemented | `services/core-control-plane/src/fdai/core/rca/t0.py`; `t1.py`; `evidence.py`; `tests/core/rca/test_coordinator.py`; `test_evidence.py` | Deterministic candidates, weakest-link scoring, support, and refutation paths are implemented. |
| Adaptive observation selection | implemented | `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; `tests/core/rca/test_discrimination.py` | Exact-frame candidates are content-addressed and ranked by pair separation without granting query or execution authority. |
| Adaptive investigation session and review surface | implemented | `core/read_investigation/adaptive*.py`; `core/rca/discrimination*.py`; `core/operational_learning/investigation_strategy*.py`; `core/operational_planning/investigation_handoff.py`; `runtime/adaptive_investigation_runtime.py`; Operator Process projection; Console Investigation Room; focused tests | The bounded, replay-stable session, exact verified-query handoff, active/challenger shadow comparison, Norns-owned inert learning candidate, separate planning handoff, durable Process journal, and read-only UI are implemented without authority. Deployment-owned candidate sources, Forseti reviser binding, governed live cohorts, and selector promotion evidence remain operational work; this is not a governed live validation claim. |
| Shadow runtime and independent closure | implemented | `services/core-control-plane/src/fdai/core/rca/runtime.py`; `tests/core/rca/test_runtime.py`; `test_temporal_causality.py` | The upstream path remains shadow and evidence-only; no result grants execution authority. |
| Grade demotion and shadow retention | implemented | `services/core-control-plane/src/fdai/core/rca/hypothesis.py` (`close_causal_hypothesis`, `causal_action_mode`); `runtime.py` (`CausalRuntimeResult.action_mode`); `tests/core/rca/test_hypothesis.py`; `test_runtime.py` | Unsafe and refuting closure lowers the grade to `association`, no closure except verified `confirmed` may raise a grade, and every unresolved or contested revision resolves to `shadow`. The runtime exposes the derived mode; no promotion or execution consumer binds it yet, because the causal path is still shadow-only. |
| Azure T1 deployment binding | implemented | `delivery/azure/deployment_history.py`; `runtime/rca_bindings.py`; topology-history, Azure, runtime, and control-loop tests | Event-time inventory identity and bitemporal topology history produce one matching-generation Incident context. Canonical lifecycle matching, dedicated read identity, sovereign-cloud binding, and one complete deadline fail closed. |
| Deployment causal evidence binding | implemented | `runtime/causal_bindings.py`; `runtime/control_loop.py`; `delivery/persistence/state_store_causal_receipts.py`; `core/rca/{runtime,hypothesis}.py`; `tests/integration/test_causal_deployment_binding.py`; `tests/persistence/test_state_store_causal_receipts.py` | A deployment that binds bounded temporal series through `bind_azure_operational_evidence` now gets Forseti's `CausalHypothesis` projection over the runtime ontology store and the Thor ActionRun receipt resolver, instead of a startup failure. An independent `ObservedOutcome` of a verified intervention confirms only through the exact declared ActionRun receipt; adverse, incomplete, or unresolved outcomes stay refuted, unsafe, or inconclusive, and every mode stays `shadow` without a current admission. |
| Operational causal closure evidence | in-progress | [Delivery slices](../../roadmap/rules-and-detection/causal-incident-graph.md#delivery-slices); deployment integration test above | The seams are bound and exercised locally; no governed replay from a deployed revision yet proves that a verified intervention closes or refutes a hypothesis. |
| Investigation boundary hardening | implemented | [Issue #2184](https://github.com/dotnetpower/fdai/issues/2184); compiler-to-handler, causal topology, adaptive telemetry, incident graph, temporal scorer, ActionRun receipt, and deployment-binding regressions | Sixteen critique rounds repaired the five reproduced defects and additional replay, temporal validity, statistical identity, comparison scope, and intervention target gaps. The final independent review found no actionable Medium-or-higher issue in its reviewed scope. Local checks do not establish deployed causal accuracy. |
| W0-W2 historical incident context | implemented | `core/rca/historical_graph.py`; `runtime/rca_bindings.py`; `test_historical_graph.py`; `test_topology_history.py`; runtime/T1 checks | Retained event/knowledge time, equal-time conflicts, effective-time baseline/generation, deletion, exact release/source receipts, bounded neighborhood and audit identity are checked. Current-state traversal remains explicitly non-historical. Actual provider refresh and dropped-relationship disposition remain W1 operational work. |
| W3 independent competitor accounting | implemented | `core/read_investigation/telemetry_adaptive.py`; `test_telemetry_adaptive.py` | Scorer v2 does not treat one positive recipe as refutation of unobserved competitors. It retains those candidates and holds. Complete domain-specific support/refutation evidence still requires reviewed sources; weights do not establish measured causality. |
| W4 independent closure intake | implemented | `core/rca/runtime.py`; `composition/_helpers.py`; `runtime/causal_bindings.py`; `test_causal_deployment_binding.py` | A bounded source is consumed by the existing shadow runtime, including outcome-only composition. Entire-batch identity/time/duplicate checks precede projection; conflicting same-predecessor outcomes cannot create contradictory sibling closures. A deployment must supply an independently authenticated source; no Event body substitutes for one. |
| W5 actual local PostgreSQL reliability | implemented | `tests/runtime/test_causal_postgres_reliability.py`: 4 passed using the isolated validation database | Independent replicas serialize duplicate investigation, preserve terminal timeout/restart replay, release an exactly identified lost backend lock, and reconstruct bitemporal/tombstone history. Random task-owned schemas are cleaned up. The minimal adapter schema and static telemetry fixture do not prove deployed migration or latency qualification. |
| W6 causal quality evaluation | implemented | `core/rca/evaluation.py`; `test_evaluation.py`: 57 passed | Immutable source/revision-bound receipts expose denominators, citation membership, missing results, wrong causes, and justified/unjustified holds. A five-case synthetic cohort runs the actual join/analyzer: 5/5 label matches, one cause claim, four holds, 15 valid citation memberships; always-held and omitted-cause baselines score 4/5 with zero cause recall. This is not operational accuracy or semantic entailment evidence. |
| W7 bilingual compiler contract | implemented | `test_bilingual_causal_plan_contract.py`; compiler-to-handler regressions | Independently annotated English/Korean fixtures preserve target, direction, time, and competitors. Live model comprehension, independent 400-question annotation, and full user-facing qualification remain separate, unclaimed work. |
| W8-W9 deployment and intervention qualification | deferred | Residual program in the owning design; operational RCA and hypothesis-loop ledgers | No target, exact source, live-read/deployment/intervention scope, or actual 14-day observation interval is supplied by the implementation request. These exits remain open; no rollout, provider mutation, model call, promotion, or fabricated operational receipt is used to close them. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-04 | implemented | Replaced startup-pinned T1 topology with one event-cutoff `IncidentRcaContext`. Historical inventory identity, append-only topology, lifecycle reopen intervals, and provider members must share one generation, while one timeout covers read, analysis, and audit. | `current change`; focused topology, provider, lifecycle, timeout, identity hydration, plan guard, Ruff, strict mypy, and Terraform checks. | Bind the broader temporal-series closure path and retain governed interventional evidence. |
| 2026-09-04 | implemented | Added the Azure T1 change-root binding and current dependency-generation guard. Provider identity remains inside delivery, only successful exact-scope mutations become change events, and graph drift disables T1 instead of enabling unscoped correlation. | `current change`; focused deployment-history, dependency-generation, member-source, and control-loop tests (`28 passed`), Ruff, and strict mypy. | Bind the broader temporal-series closure path and retain governed interventional evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Bind the production evidence path and retain governed interventional closure evidence. |
| 2026-08-16 | implemented | Made unsafe closure demote the evidence grade, blocked any non-confirmed closure from raising a grade, and added the deterministic `causal_action_mode` derivation that keeps refuted, unsafe, inconclusive, contested, and weakly graded revisions in `shadow`. | `current change`; `services/core-control-plane/src/fdai/core/rca/hypothesis.py`; `services/core-control-plane/tests/core/rca/test_hypothesis.py`; focused run `pytest services/core-control-plane/tests/core/rca` passed 215 tests. | Bind the deployment evidence path and retain one governed interventional replay. |
| 2026-08-16 | implemented | Exposed the derived mode as `CausalRuntimeResult.action_mode` so the shadow decision is observable on the runtime path, and qualified the scope row: no promotion or execution consumer binds the mode yet. | `current change`; `services/core-control-plane/src/fdai/core/rca/runtime.py`; `services/core-control-plane/tests/core/rca/test_runtime.py`; focused run `pytest services/core-control-plane/tests/core/rca` passed 216 tests. | Bind the deployment evidence path and retain one governed interventional replay. |
| 2026-08-30 | implemented | Added replay-stable adaptive observation selection over exact-frame, pre-verified read-only candidates. Selection maximizes hypothesis-pair separation, records stale or incomplete candidates, and returns authority-free selected or held receipts. | `current change`; `services/core-control-plane/src/fdai/core/rca/discrimination_contract.py`; `discrimination.py`; focused discriminator tests, Ruff, and strict mypy. | Bind candidate production to the verified ontology query path and retain governed investigation evidence before claiming operational validation. |
| 2026-08-30 | implemented | Added the bounded adaptive investigation runtime, Process journal, exact verified-query gateway, active/challenger comparison, Norns-to-Mimir inert strategy review path, separate planning proposal, Operator projection, and Console Investigation Room. | `current change`; focused core, agent, runtime, Operator, Console, and Playwright checks. | Bind deployment-owned candidate and revision sources and retain governed live evidence before selector promotion. |
| 2026-08-30 | implemented | Completed 22 tracked critique and hardening rounds plus a final independent release review. The rounds hardened immutable identity, deadlines, cancellation, query authority, Process replay, shadow isolation, learning cohorts, planning handoff, Operator projection, Console overflow, large-result hashing, cold import, and at-least-once deduplication until only Low or no findings remained. | `current change`; 646 Core tests, 46 Operator tests, 19 Console tests, three Playwright viewport scenarios, Ruff, strict mypy, and the final task-only review. | Retain governed live evidence before selector promotion; local implementation evidence does not claim deployed validation. |
| 2026-08-30 | implemented | Connected adaptive selection into a bounded Process-backed investigation session. The runtime re-verifies exact query lineage before I/O, blocks late or incomplete results, records active/challenger shadow evidence, routes balanced Muninn cohorts through Norns and Mimir's existing inert review queue, emits only an authority-free proposal to a separate planning Process, and exposes a read-only Investigation Room. | `current change`; adaptive RCA, read-investigation, operational-learning, planning, runtime, Operator, Console, and agent tests; focused validation. | Bind deployment-owned round and Forseti revision sources, retain a governed live cohort, and promote a selector only through a reviewed immutable configuration release. |
| 2026-08-30 | implemented | Closed 22 tracked critique and hardening rounds and one final independent release review with only Low or no findings remaining. | `current change`; 646 Core tests, 46 Operator tests, 19 Console tests, three Playwright viewport scenarios, Ruff, strict mypy, cold import, documentation gates, and final task-only review. | Retain governed live evidence before selector promotion; no deployed validation is claimed. |
| 2026-09-29 | in-progress | Moved the authoritative ledger out of the design owner with `migrate-roadmap-implementation-ledgers.py --merge-existing`, which kept every owner and prior ledger history row, and folded the two superseded prior scope rows into their current owner rows. No implementation or runtime state changed. | `current change`; this ledger, `docs/roadmap/rules-and-detection/causal-incident-graph.md` and its Korean pair; `check-roadmap-implementation-tracking.py`, translation, and doc-link checks. | Bind the causal evidence seams in a deployment integration test, then retain one governed interventional replay. |
| 2026-09-29 | implemented | Bound the deployment causal path. `build_causal_runtime_coordinator` completes bounded temporal series with Forseti's `CausalHypothesisProjector` over the runtime ontology store and `StateStoreCausalInterventionReceiptVerifier`, which accepts a receipt only from Thor's exact declared, non-shadow, succeeded ActionRun whose effect verification falls between intervention and observation. `CausalClosureObservation` gained the ActionRun reference. The deployment integration test found and fixed a defect: open revisions projected `closure: null`, which every validating ontology store rejected, so the projection now omits the optional property. No execution authority changed. | `current change`; `runtime/causal_bindings.py`, `runtime/control_loop.py`, `delivery/persistence/state_store_causal_receipts.py`, `core/rca/{runtime,hypothesis}.py`, design owner EN/KO; `uv run pytest -q --no-cov tests/integration/test_causal_deployment_binding.py services/core-control-plane/tests/persistence/test_state_store_causal_receipts.py services/core-control-plane/tests/core/rca services/core-control-plane/tests/core/test_control_loop_temporal_causality.py services/core-control-plane/tests/core/test_causal_recovery_projection.py tests/integration/test_composition_azure_operational_evidence.py services/core-control-plane/tests/composition/test_wire_azure_operational_evidence.py`: 359 passed; runtime and control-loop selection: 186 passed; `tests/integration/services/test_core_service_package.py`: 4 passed after registering `runtime/causal_bindings.py`; Ruff, format, and mypy passed. Owning docs (project structure, runtime deployment profiles, standing authority, channels) record that causal revisions stay evidence-only. | Retain one governed replay from a deployed revision that proves a verified intervention closes or refutes a hypothesis. |

| 2026-10-16 | implemented | Repaired compiled evidence cutoffs, delayed-event budgets, source completeness and edge validity, exact historical dependency paths, competing-explanation accounting, statistical claim identity and lag correction, and independent Resource target matching. Subsequent critique added distributed duplicate serialization and reserved timeout finalization. | `current change`; #2184; final seven-file focused command below: 144 passed; broader focused regression: 710 passed before the last three added cases; task-owned Ruff and strict mypy over 11 source files passed. | Retain governed deployed intervention and PostgreSQL latency evidence; local implementation does not establish live causal accuracy. |

| 2026-10-16 | implemented | Reconciled the first exact-head CI failure: the ontology-platform source changes invalidated the generated CQAS source commitment. Regenerated the complete artifact with its official generator and made the existing parity assertion identify stale source commitments before expanding the full inventory diff. Only source and aggregate digests changed; coverage and scorecard data did not. | CI run `38869557198`, attempt 1, head `9a206531f8238235e54120a2a45da9d7de038ec4`, regression job `116870254723`, step `Run regression shard`; local `python -m pytest -q --no-cov tests/integration/evaluation/test_semantic_intent_coverage.py`: 4 passed; Ruff passed. | Obtain authoritative checks for the repaired PR head; no runtime behavior or operational qualification changed. |

### Critique and hardening rounds for #2184

| Round | Boundary and finding | Outcome and falsifying evidence |
|-------|----------------------|---------------------------------|
| 1 | Valid compiled metric samples were rejected by a start-of-window cutoff. | Repaired to the window end; compiler-to-real-handler regressions cover normal and truly future samples plus comparison identity. |
| 2 | Delayed events expired immediately; the first deadline repair exposed replay drift. | Execution starts at investigation creation, while terminal replay restores the original persisted deadline and performs no new provider work. |
| 3 | The incident materializer discarded source completeness and generation. | Source metadata is retained; current-store historical unavailability stays explicit. |
| 4 | Future, stale, unverified, synthetic, malformed, or disconnected graph evidence could survive as complete. | Seventy focused graph cases cover metadata, time, bounds, reachability, and replay identity. |
| 5 | An unrelated topology diff could support a causal claim. | Exact typed dependency direction and one retained historical view are required; reverse and mixed-time paths hold. |
| 6 | Relationship verification and freshness could be ignored by causal joins. | Missing, malformed, unverified, partial, synthetic, stale, future, and late-recorded evidence variants hold. |
| 7 | Failed correlation was labeled mechanism refutation; competitors did not constrain support. | Both remain unresolved without stronger mechanism or refutation evidence. |
| 8 | Claim identity omitted changed evidence/configuration; lag searches omitted multiplicity; excessive differencing raised. | Input-bound identities, all-lag correction, and insufficient-transformed-sample regressions pass. |
| 9 | The intervention receipt verifier did not match the independently observed Resource. | Missing or changed Resource targets cannot confirm; deployment-binding and receipt regressions pass. |
| 10 | Independent critique reproduced two additional Medium gaps. | Accepted late-created topology and concurrent initial-deadline findings for rounds 11-12. |
| 11 | A path introduced after measurements could explain earlier effects. | Dependency edges must be effective before the metric window begins; the late-edge counterexample now holds. |
| 12 | Concurrent duplicate sessions chose different initial deadlines. | Existing ResourceLock backends serialize deadline selection and execution; two-instance replay performs one read and lock waiting is bounded. |
| 13 | Independent follow-up found supervisory cancellation could prevent replayable timeout persistence. | Accepted for round 14; the prior two Medium findings were resolved. |
| 14 | Active-query timeout lacked a durable terminal result. | Policy 1.1.0 reserves bounded finalization time inside the original ceiling; blocked-query replay returns the exact timeout without another read. |
| 15 | Relaxed thresholds could classify zero-lag or constant data as predictive precedence. | Constant, symmetric, and zero-lag inputs remain association regardless of relaxed thresholds. |
| 16 | Final independent residual review. | No actionable Medium-or-higher findings in reviewed corrections. The remaining Low limitation is unmeasured distributed PostgreSQL lock and terminal-write latency; no live services were used. |
| 17 | Exact-head CI exposed a stale generated CQAS source commitment not selected by the earlier focused cohort. | Official full regeneration and the existing, now more diagnostic parity regression pass all four checks; only source and inventory digests change. No production code changed after the final independent review. |

The final focused command, using the selected local Python environment, passed **144 tests**:

```bash
python -m pytest -q --no-cov \
  services/core-control-plane/tests/conversation/test_causal_investigation_execution.py \
  services/core-control-plane/tests/core/ontology_platform/test_causal_topology.py \
  services/core-control-plane/tests/core/rca/test_incident_graph.py \
  services/core-control-plane/tests/core/rca/test_temporal_causality.py \
  services/core-control-plane/tests/persistence/test_state_store_causal_receipts.py \
  tests/integration/test_causal_deployment_binding.py \
  services/core-control-plane/tests/runtime/test_adaptive_telemetry.py
```

| 2026-10-16 | implemented | Completed the locally executable residual infrastructure and repeated critique. Retained bitemporal history now feeds T1 with active-generation and graph audit identity; exact-time conflict and tombstone checks preserve uncertainty; independently supplied closure batches are consumed in shadow with canonical replay; positive telemetry does not discard untested competitors. Added immutable causal quality receipts and paired typed English/Korean compilation checks. | `current change`; final owning selection: 375 passed; actual isolated PostgreSQL reliability: 4 passed; regenerated semantic-source parity: 4 passed; strict mypy over 12 task-owned sources and Ruff passed. The final independent review found no actionable Medium-or-higher issue in its reviewed corrections. | Supply selected authenticated provider/outcome sources and governed operational cohorts. Deployment, live Azure/model, intervention and actual recurrence observation remain unperformed and cannot be represented by local fixtures. |

### Residual critique and hardening

These are new rounds after #2185, not a reuse of its seventeen earlier rounds.

| Round | Boundary | Finding, repair, and evidence |
|-------|----------|-------------------------------|
| 1 | Historical source | A current-state read cannot prove past completeness. Added retained-history materialization; current-state candidates remain explicitly incomplete. |
| 2 | Actual T1 consumer | A standalone helper would leave runtime unchanged. T1 now consumes the historical materializer and audits graph revision and source references. |
| 3 | Question neighborhood | Unrelated invalid properties should not poison a scoped read. Filter to the bounded candidate neighborhood and recompute after evidence rejection; ambiguous source-level gaps still hold. |
| 4 | Competing explanations | One positive recipe discarded unobserved alternatives. Scorer v2 keeps them active and holds instead of inventing refutation. |
| 5 | Outcome intake | A callable closure method alone did not consume independent outcomes. Added bounded source-driven and outcome-only composition, keeping the Event as a lookup trigger only. |
| 6 | Persisted replay | Datetime objects versus stored JSON strings caused false immutable-content conflicts. Canonical JSON comparison now preserves exact closure replay. |
| 7 | Real database mechanics | Four actual isolated PostgreSQL tests cover independent replicas, single-read duplicates, persisted query timeout/restart, precise backend loss, and historical reads. Static telemetry and minimal adapter schemas are explicitly labeled. |
| 8 | Equal-time values | A deterministic lexical winner could conceal conflicting retained facts. Detect conflicting object/link revisions and lower completeness. |
| 9 | Bilingual typed meaning | Added independently annotated English/Korean compiler checks for exact target, direction, cutoff and competitors. This is not model comprehension qualification. |
| 10 | Outcome payload bounds | Bound endpoint count, nesting and bytes before processing independent closure batches. Oversize observations fail explicitly. |
| 11 | Endpoint types | Retained link endpoint declarations must match selected object types, not only endpoint ids. A mismatch keeps history incomplete. |
| 12 | Independent critique | Reviewer reproduced hidden competing baselines/deleted paths and contradictory sibling closures. Accepted both Medium findings for repair. |
| 13 | Hidden historical alternatives | Preserve competing same-time complete snapshots and tombstone paths before winner selection/pruning can hide them. New counterexamples now hold. |
| 14 | Contradictory outcomes | Reject multiple outcomes for one predecessor revision across the complete batch before projection; distinct outcome ids cannot bypass this check. |
| 15 | Evidence identity and bounds | Canonical retained revisions and complete source-reference byte accounting bind the receipt, including discarded conflict evidence. |
| 16 | Evaluation anti-gaming | Fixed denominators, unknown/missing/duplicate outputs, wrong causes, unjustified holds and fabricated citations are covered by 57 evaluator checks, including actual analyzer/join execution. |
| 17 | Synchronous deadline | An async timeout alone cannot preempt synchronous graph work. Check the overall monotonic deadline before returning success. |
| 18 | Superseded deletion | Independent review found that old live-link revisions were validated against endpoints deleted later. Validate only winning live revisions; surviving unrelated dependencies remain complete. |
| 19 | Late baseline chronology | Choose the baseline by effective/recorded time, not arrival order, and preserve later-effective deltas recorded before a late baseline. Two exact chronology regressions pass. |
| 20 | Active generation | The last-arriving generation may be older than the incident state. Derive the active generation by effective time and match T1 member evidence to it. |
| 21 | Final independent review | No actionable Medium-or-higher issue remained in reviewed history, closure, replay and T1 corrections. Remaining limitations are the explicitly open operational-source, model, deployment and intervention qualification below. |

Final commands, using the selected local Python environment:

```bash
python -m pytest -q --no-cov \
  services/core-control-plane/tests/core/rca/test_historical_graph.py \
  services/core-control-plane/tests/core/rca/test_incident_graph.py \
  services/core-control-plane/tests/core/rca/test_evaluation.py \
  services/core-control-plane/tests/core/rca/test_runtime.py \
  services/core-control-plane/tests/core/rca/test_hypothesis.py \
  services/core-control-plane/tests/core/rca/test_hypothesis_lineage_projection.py \
  services/core-control-plane/tests/core/rca/test_causal_chain.py \
  services/core-control-plane/tests/core/ontology_platform/test_topology_history.py \
  services/core-control-plane/tests/core/ontology_platform/test_causal_topology.py \
  services/core-control-plane/tests/core/ontology_platform/test_metric_semantics.py \
  services/core-control-plane/tests/runtime/test_rca_bindings.py \
  services/core-control-plane/tests/runtime/test_adaptive_telemetry.py \
  services/core-control-plane/tests/core/read_investigation/test_telemetry_adaptive.py \
  services/core-control-plane/tests/core/read_investigation/test_adaptive_session.py \
  services/core-control-plane/tests/core/test_control_loop_t1_wire.py \
  services/core-control-plane/tests/core/test_control_loop_temporal_causality.py \
  services/core-control-plane/tests/core/test_causal_recovery_projection.py \
  services/core-control-plane/tests/conversation/test_bilingual_causal_plan_contract.py \
  services/core-control-plane/tests/conversation/test_causal_investigation_execution.py \
  tests/integration/test_causal_deployment_binding.py \
  services/core-control-plane/tests/delivery/persistence/test_postgres_topology_history.py \
  services/core-control-plane/tests/delivery/test_inventory_topology_history.py
# 375 passed
python3 scripts/automation/with-local-test-database.py python -m pytest -q --no-cov \
  services/core-control-plane/tests/runtime/test_causal_postgres_reliability.py
# 4 passed against isolated local PostgreSQL
python -m pytest -q --no-cov tests/integration/evaluation/test_semantic_intent_coverage.py
# 4 passed; official regeneration changed source commitments only
```

### Remaining work

- [x] Implement the locally executable residual infrastructure: retained-history T1 context,
  bounded independent-outcome intake, conservative competitor handling, actual isolated PostgreSQL
  mechanics, typed quality evaluation, and bilingual annotated compilation checks.
- [ ] Bind the independent closure observation source to the selected deployment's authenticated,
  exact-artifact outcome reader and retain a non-synthetic replay. The generic intake is implemented,
  but an arbitrary payload or a fixture cannot become this source.
- [ ] Refresh a selected authorized provider generation, adjudicate its retained missing endpoints,
  type mismatches and unresolved references, and verify the newly reviewed ResourceTypes. This is
  source-specific operational evidence, not proof supplied by the local graph implementation.
- [ ] Retain independently reviewed support/refutation and cross-resource evidence for the
  selected mechanisms. Unobserved competitors stay held, not silently refuted.
- [ ] Run the fixed evaluator on a governed exact-revision operational cohort, including T0/T1/T2,
  verified citations, justified abstention and independently observed outcomes. Synthetic cohort
  measurements remain explicitly labeled and cannot qualify production.
- [ ] Retain live bilingual semantic/Console evidence and independent question-bank annotation;
  typed fixture compilation does not establish model-language accuracy.
- [ ] Complete separately authorized deployment, intervention, rollback, and real recurrence-window
  evidence. No deployment or live Azure/model action was performed in this local implementation.

- [x] Repair the five reproduced local defects and complete at least ten critique rounds for
  #2184. Sixteen rounds and the final focused checks above establish this bounded local scope.

- [x] Bind bounded temporal series, the Forseti-owned projection publisher, independent outcomes, and causal receipt resolution in a deployment integration test. `tests/integration/test_causal_deployment_binding.py` composes `bind_azure_operational_evidence` with the runtime binding, projects into the governed ontology store, and closes through an independent `ObservedOutcome` and Thor's ActionRun receipt (10 passed).
- [ ] Retain one governed replay that proves a verified intervention closes or refutes a hypothesis without granting action authority.
- [x] Unsafe or refuting evidence lowers the hypothesis grade and keeps the related action or experiment in `shadow`, evidenced by `close_causal_hypothesis` and `causal_action_mode` in `services/core-control-plane/src/fdai/core/rca/hypothesis.py` and the focused cases in `services/core-control-plane/tests/core/rca/test_hypothesis.py`.
