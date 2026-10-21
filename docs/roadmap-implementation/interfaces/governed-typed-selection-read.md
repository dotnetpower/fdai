# Governed typed selection read implementation ledger

This ledger tracks only the selected A implementation of #2275 under #2034 and #2256.
Local synthetic evidence cannot qualify or activate a deployed model.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Selected A design | implemented | Parent adjudication and #2275 design comment; paired owner document. | No network access or inference classification is added to the ordinary Function runner. |
| Governed pointer and read stage | implemented | 145 focused local tests pass in the worktree's own locked environment; production/default payload validator enabled. | No activation or live evidence. |
| Real production consumer | implemented | `composition/wire_semantic_query.py` uses `prepared_function_handler`; bootstrap composes the current-model stage and actual source resolver. | Hosted calls remain outside the ordinary Function registry. |
| Fixed-role promotion and demotion | implemented | Real Forseti, Var, Thor, Saga and Vidar in the local validated bus; exact current approval readback, independent admission, audited CAS and scripted rollback. | Unknown/failed qualification and unavailable current human authorization deny. |
| Governed failure diagnosis and evaluation isolation | implemented | Producer reason codes, gold-independent driver, disposable evaluation registry and deterministic regressions. | Local mechanics only; no model qualification or human authority is asserted. |
| Paged proposal and membership scale | implemented | `8fec8d423ca4`; `semantic_planning_config.py`, `semantic_candidate_proposal.py`, `ontology_candidate_selection.py`, `ontology_governed_selection_read.py` and 209 focused context/selection/proposal/governed-read checks. | Partitions >500-enum builds into deterministic <=300-instance schema/context pages and pages >100-ID / >1,000-row membership reads through `SecuredObjectSetQueryGateway` in 100-ID batches without truncation or lexical prefiltering. |
| Fresh governed answer-path qualification | validated | Exact merged commit `8fec8d423ca4dfbcca2802516dd5454bb8cd0352`; `governed-typed-selection-answer-window.v3` and `governed-typed-selection-answer-latency.v3` passed 256/256 decisions (0 wrong, 0 unavailable, EN 1.0, KO 1.0, p50 2.662 s, p95 4.013 s, p99 5.369 s, lag p99 0.897 ms; private decisions digest `sha256:66848cbeb7779b14c70082f927a299c37ac999fc116f8e6287ecf84cb6d3f45f`). | Durable PostgreSQL development promotion and independent effect observation completed (`sha256:72b8038ef7be188e00eac79eb718375b0a38bed85656e5f182f46da545658e4b`). |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-21 | validated | Executed the pre-registered `v3` governed answer-path window and latency protocols on exact merged commit `8fec8d423ca4dfbcca2802516dd5454bb8cd0352`: 256/256 decisions completed with 0 wrong selections (pooled 95% upper bound 1.16%), EN 64/64 answerable correct (1.0) and 64/64 held, KO 64/64 answerable correct (1.0) and 64/64 held, 0 unavailable, p50 2,662.11 ms, p95 4,013.36 ms, p99 5,368.58 ms, and event-loop lag p99 0.897 ms. Admitted the qualification into durable PostgreSQL (`sha256:5cc8ddcff2eade07f4d78b0ca75eab7471644e47a5c0a89ab6aed5bebeccaab8`), executed explicit Var Owner approval, Thor registry promotion (`sha256:00eb61e1ad411992488d4b1c3689eaa585538f525f248518c269a378cfc938a3`) and Saga audit, verified the effect through an independent reader (`sha256:86b007820c49049d451ef8628aa2f45077f8da12ae321db87b22f6825c362967`), and repaired initial `expected_revision=0` absent-row promotion in `StateStoreTypedSelectionRead.promote`. | `current change`; `8fec8d423ca4dfbcca2802516dd5454bb8cd0352`; decisions digest `sha256:66848cbeb7779b14c70082f927a299c37ac999fc116f8e6287ecf84cb6d3f45f`; promotion/effect receipt `sha256:72b8038ef7be188e00eac79eb718375b0a38bed85656e5f182f46da545658e4b`; `state_store_typed_selection_read.py` and 210 focused tests. | #2034 exit criteria are satisfied in the development profile; #2256 continues to track broader cross-service Console and elapsed-window items. |
| 2026-10-21 | in-progress | Diagnosed and repaired the two producer/resolver defects behind historical answerable and negative holds (`ReadSelectionSource` now preserves `resource_type_query_terms` for `Resource` membership revalidation, and `GovernedTypedSelectionRead` holds with `no_candidate_match` instead of saving empty candidate evidence when both proposals agree on zero matches). Added deterministic multi-page schema/context partitioning and 100-ID gateway membership paging across 600- and 1,200-instance scopes, and pre-registered disjoint `governed-read-window.v3.json` under `v3` protocols. | `current change`; `ontology_governed_selection_read.py`, `ontology_selection_errors.py`, `semantic_planning_config.py`, `semantic_candidate_proposal.py`, `ontology_candidate_selection.py`, `ontology_governed_selection_campaign.py`, `eval/ontology-retrieval/governed-read-window.v3.json`; 205 focused context, selection, proposal, diagnostics, composition, asset and campaign tests passed. | Merge and run `v3` once on the exact merged commit, then perform explicit Owner-approved registry promotion and independent effect observation. |
| 2026-10-20 | implemented | Classified the historical evidence limit without attributing holds to the model. Added bounded producer diagnoses, gold-independent observed outcomes, strict candidate output, required negative holds, grouped-error retention, immediate backpressure/deadline stop and an exact-bound disposable evaluation registry. Both spent windows are blocked before live setup. | Current change; `test_governed_selection_diagnostics.py`, `test_governed_typed_selection_campaign.py`, candidate-selection/protocol/composition regressions; sixteen distinct hypotheses below. | No live quality result, independent installation admission, current Owner approval, promotion or effect observation. Keep #2034/#2256 G03 open and obtain a fresh reviewed protocol before live work. |
| 2026-10-20 | in-progress | The exact-merge v1 governed run reached 13 decisions with no provider error, then stopped after the current mini binding held six answerable cases. V1 is spent and has no quality outcome. Pre-registered v2 with unchanged thresholds, a new independently authored/reviewed disjoint window, and an exact `t2.ontology.council.alpha` Sol pin; composition now fails closed on capability, family, version, target or prompt drift. | `current change`; private v1 partial evidence digest `sha256:0142d05f28ac8807ca8817a898eba73e3cccfec25e53503673c01cf3b771c7e0`; v2 asset/config/protocol/composition regressions. | Merge and run v2 once on the exact merged commit. Never reuse v1 for tuning or qualification. |
| 2026-10-20 | in-progress | The first exact-merge governed live attempt stopped before any provider call because the evidence driver passed a `Path` object to the production resolved-model loader's string contract. The repair preserves the validated string path and adds a focused regression; the aborted attempt has no quality outcome. | `current change`; merged `ba8672d188`; `test_runtime_container_preserves_the_loader_string_path`. | Merge the bounded evidence-tooling repair and rerun once on that exact merged commit. |
| 2026-10-20 | in-progress | Pre-registered the fresh governed answer-path window and latency protocols, added a disjoint independently authored/reviewed 64-case asset, and added a bounded driver over the actual preparation and deterministic consumption path. The fake-path run exposed and repaired a current-source validation defect: separately observed projection digests legitimately differ when their cutoffs differ, while document/generation equality and both receipt-bound identities remain mandatory. | `current change`; governed campaign protocol, driver, asset, source-context repair and 64 focused fake-path/protocol/asset/context checks. | Merge, execute once on the exact merged commit, independently adjudicate the private rows, then use explicit Owner approval for one persistent development promotion and effect observation. |
| 2026-10-19 | in-progress | Recorded selected A design, twelve pre-code critiques and revised pre-Function boundary before implementation. | #2275; paired design owner; current change. | Implement and verify the fixed-role authority lifecycle and actual read consumer. |
| 2026-10-19 | implemented | Wired the registered read promotion, immutable single-use read evidence, real pre-Function consumer and Vidar revocation/regression/rollback. Narrowed the model stage to 24 seconds plus the existing five-second deterministic read. | Current change; 145 focused tests pass, including production/default validation, actual Var approvals and scripted rollback; Ruff and 23-source-file focused mypy checks. | No live qualification, promotion, deployment, elapsed observation or full G03 completion is claimed; later delivery gates remain separate. |

| 2026-10-19 | implemented | Repaired delivery registration and extracted the unchanged Function-node construction into the existing typed-read composition owner. Closed the exact owning-doc advisories and regenerated SKS only through its official CLI. | Current change; 64 targeted extraction/registration/production-validator/parity tests pass; one exact packaged-catalog equality test passes; focused two-source-file mypy passes; design impact and roadmap parity pass. `wire_semantic_query.py` is 799 lines against the unchanged 800 ceiling. | Prior 145 focused results are reused only for unchanged executable inputs. Full bootstrap, actual database, operational qualification, activation, publication and G02 base integration remain explicitly unverified or deferred. |
| 2026-10-19 | implemented | Serialized G02 and current-base integration without losing either Vidar subscription or approval export. Added current-authorizer, original-action replay, direct shadow/no-approval, invalid-input, denied-admission and demotion guards to the existing focused tests. Registered conditional source-grounded runtime support for the new ActionType and refreshed all four synthetic structural fixture commitments from the actual Reader manifest. | Current change; combined G02/G03 selection 197 passed, including the actual private-intent PostgreSQL cases and production/default validator. Expanded governed-read file: 40 passed, six-module branch-inclusive coverage 90.73%; Core contracts 95%, deterministic Function 100%, lifecycle 93%. | Coverage is not live qualification. Full installed bootstrap, actual deployed read-registry database qualification, normal authenticated conversation and promotion remain unverified; raw embedding calibration remains failed and selection stays disabled. |
| 2026-10-19 | implemented | Kept typed-source resolution in the existing governed-read owner and composed Thor's exact read lane in the existing execution-binding owner, preserving ordinary fallback, rollback and simulator bindings. Kept the existing governance-HIL action set in the execution-port owner and enumerated both new runtime payload modules in the exact wheel test. | Current change; 60 source/bootstrap tests passed with 91.07% seven-module branch-inclusive coverage; five-source strict mypy passed; four actual wheel tests passed; the broader extraction selection passed 131 tests before the final alias removal, then the affected bootstrap owner was rechecked. Enforced LOC, fanout and document links pass with no raised thresholds. | Wheel-copy coverage was measured separately because counting installed temporary wheel copies as additional source modules distorts the denominator. No live qualification, model call, read activation or installed operational-effect claim. |
| 2026-10-19 | implemented | Reconciled the exact catalog-dependent CI failures: canonical governance inventory and its fourth direct pointer-promotion exception, source-only Cost and existing authored rule-surface release commitments, both registered admission boundaries, and composed Function inventory. Split absent-admission rejection from explicit shared assessment so every positive return is statically dominated by the assessor; added wrong-purpose-only negative cases for qualification and demotion. | Current change; 156 focused cases pass across all failed owners, followed by 62 source/bootstrap cases with 91.19% seven-module branch-inclusive coverage; two-source strict mypy and the unchanged decision-boundary checker pass. Official release-derived refresh actually measured the seven unchanged existing retrieval cases and sixteen F1-F8 fixtures, retained their corpus/policy/lifecycle, and then reported zero drift. New exact source checksum is calculated by the existing canonical boundary function. | The lexical source-only receipt is not the failed raw embedding calibration and cannot qualify or activate this read. No changed held-out corpus, lowered threshold, new model call, operational promotion or admission bypass is claimed. |

#### Focused command and exact boundary

```bash
uv run --no-sync pytest -q --no-cov --tb=short \
  services/core-control-plane/tests/delivery/catalog_search/test_governed_typed_selection_read.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidate_context.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidate_selection.py \
  services/core-control-plane/tests/delivery/azure/llm/test_ontology_candidate_proposal.py \
  services/core-control-plane/tests/agents/test_framework_layout.py \
  services/core-control-plane/tests/agents/test_pantheon_doc_parity.py
```

Result: **145 passed**. The test bus explicitly uses the production
`default_payload_validator`; no permissive payload fixture substitutes for it. The read-revocation
command uses the existing owned Event `attributes` contract and a closed typed command model.
The public agent facade exposes read-only identity/approval codecs; external code does not import
private framework modules or call another agent directly.

Production wiring is `bootstrap_semantics.compose_typed_selection_read` ->
`wire_semantic_query.prepared_function_handler` -> two bounded proposals -> immutable evidence ->
`OntologyFunctionRegistry` -> deterministic secured consumption. Authority wiring is the existing
Forseti candidate/preparation, Var final approval, Thor executor and Saga audit path;
`bootstrap_pantheon` binds Vidar's qualified revocation callback and scripted action rollback.

#### Final distinct critique rounds

| Round | Hypothesis and evidence | Outcome |
|-------|-------------------------|---------|
| 1 | A hosted call could hide inside a deterministic Function. | Real Function-node test proves two preceding calls and no additional call during Function consumption; network remains false. |
| 2 | Caller flags could qualify the model. | Independent exact admission is required on save and use; revoked admission makes zero model calls. |
| 3 | A named actor could substitute for human approval. | Actual Var decisions, retained original Action, current authorization/TTL readback and exact identity are required. |
| 4 | Model binding changes could reuse an old selection. | Model-drift test denies. |
| 5 | Code/source changes could reuse evidence. | Source-drift test denies. |
| 6 | Another principal scope could consume evidence. | Scope-drift test denies. |
| 7 | One receipt could be replayed. | Atomic pointer/request-fenced single-use consumption denies replay. |
| 8 | Expired evidence could remain usable. | Thirty-second expiry test denies. |
| 9 | Cancellation could complete inference after the turn. | Task-group sibling cancellation and durable request cancellation prevent consumption. |
| 10 | Revocation or regression could race consumption. | Actual Vidar typed-event tests disable the higher pointer revision and permanently withdraw qualification. |
| 11 | A failed post-effect observation could leave promotion active. | Actual Thor failure triggers Vidar's registered scripted rollback and Saga audit. |
| 12 | Wrong publisher/actor could promote. | Production bus ownership and non-Thor mutation tests deny. |
| 13 | Helper imports or subscriptions could bypass fixed contracts. | Public facade repair, all fourteen layout checks and bilingual/instruction subscription parity pass. |
| 14 | The initial 45-second stage could exceed the existing node ceiling. | Revised to 24 seconds total, two calls of at most 20 seconds, followed by the unchanged five-second Function. |
| 15 | Outbox publication revision could invalidate a legitimate approval. | Bind the immutable approved payload rather than mutable publication metadata. |
| 16 | Old promotion could resurrect withdrawn qualification. | Withdrawal tombstones and pointer CAS reject it; no raw ranking or old Sol qualification is enabled. |
| 17 | A layout/size repair could drop invocation safeguards or weaken a bound. | Moved the same context, receipt authority, presentation-read setting and pending-state ledger into the existing binder; registered only the two actual modules. No ceiling, authority, schema validator or feature was weakened. The fresh 64-test subset includes the production/default-validator lifecycle. |

#### Bounded delivery-repair evidence

The repair ran in this same worktree and preserved the staged authority slice. The SKS command
was initially missing; only then was this worktree's locked workspace environment restored.
No other checkout's environment, provider call, activation, force/reset/stash or push was used.

```bash
uv run --no-sync pytest -q --no-cov --tb=short \
  tests/integration/test_composition_package_split.py \
  services/core-control-plane/tests/delivery/catalog_search/test_governed_typed_selection_read.py \
  services/core-control-plane/tests/agents/test_pantheon_doc_parity.py
uv run --no-sync pytest -q --no-cov --tb=short \
  services/system-knowledge-service/tests/test_catalog_search.py::test_packaged_catalog_matches_current_reviewed_sources
uv run --no-sync mypy --follow-imports=silent \
  services/core-control-plane/src/fdai/composition/semantic_query_typed_selection_read.py \
  services/core-control-plane/src/fdai/composition/wire_semantic_query.py
uv run --no-sync --package fdai-system-knowledge-service fdai-system-knowledge-build-catalog \
  --repo-root . --protected-main-ref refs/remotes/origin/main \
  --output services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json
python3 scripts/quality/localization/check-derived-sources.py --cached
python3 scripts/quality/architecture/check-design-doc-impact.py --cached
python3 scripts/quality/architecture/check-roadmap-implementation-tracking.py --cached
```

Results: 64 passed; one catalog-equality test passed; two source files passed mypy; the official
generator produced 14 records; derived-source validation passed for six documents and sixteen
System Knowledge sources. All exact reported owning-doc routes and eight owner-ledger checks
passed. No generated catalog content was hand-edited. Existing raw-ranking qualification remains
failed, no earlier Sol pin is reused, and no full G03 or production-ready claim is made.

#### Session 1 bounded diagnostic critique

| # | Hypothesis | Inspection or deterministic regression and disposition |
|---|------------|-------------------------------------------------------|
| 1 | Zero provider errors proves a model-meaning defect. | Rejected: v1/v2 contain only coarse `answer_unavailable`; producer cause cannot be reconstructed. Originals remain unchanged. |
| 2 | Gold labels influence observed execution status. | Confirmed and repaired: identical exceptions now yield identical outcomes for positive and negative labels. |
| 3 | A grouped proposer error escapes partial evidence handling. | Confirmed and repaired: known errors become one bounded diagnosis; the sibling is cancelled and no evidence is saved. |
| 4 | Evaluation adapters can admit another installation tuple. | Repaired: a separately constructed disposable registry admits only its exact qualification, binding, purpose and source revision. Installation/source state receives no evaluation pointer. |
| 5 | Spent windows can run live again. | Repaired: v1/v2 live setup is rejected before runtime or provider construction. Fake regression remains available. |
| 6 | Source/time drift looks like a semantic defect. | Typed source and membership-time diagnoses preserve the hold and expose no content. |
| 7 | Citation, clarification and agreement failures share one cause. | Separated fixed reasons; quote/count/input/selection and disagreement regressions preserve the evidence fence. |
| 8 | Membership denials or partial evidence can become candidates. | Existing ACL/completeness checks retained, with distinct denial/incomplete/contract reasons and passing candidate-selection regressions. |
| 9 | Demotion, replay, expiry or restart can restore authority. | Existing fixed-role, single-use, expiry and rollback tests remain passing; no registry-authority relaxation. |
| 10 | HTTP 503 or timeout can continue the same attempt. | Repaired: 429/503, adapter timeout and stage deadlines stop with the first partial row. |
| 11 | A Function failure can pass as a semantic negative. | Repaired: malformed Function output has a fixed contract reason; other unclassified errors remain unavailable regardless of expected labels. The ordinary composition/Function wrapper is unchanged, so this repair changes no integration seam or shared structure document. |
| 12 | Evaluation approval or actor text is Owner/promotion evidence. | Rejected: evaluation output explicitly denies independent admission/current Owner authority; ordinary registry activation is refused by the evaluation helper. |
| 13 | Malformed output can become an empty success. | Repaired: absent/non-list candidates, invalid identities and duplicates raise an explicit failure. |
| 14 | A returned empty result satisfies a required negative hold. | Repaired: the evaluator emits `negative-case-not-held`; numeric thresholds are unchanged. |
| 15 | Schema/context adapter failures count as provider outages. | Repaired: content-free adapter fields distinguish proposal contract, context, provider and unknown adapter failures. |
| 16 | Membership or Function deadlines are mislabeled model timeouts. | Separate proposal, membership, Function and whole-stage timeout codes; all stop the attempt. |

This is a bounded diagnostic/evaluation review, not a whole-product Low-only certification.

#### Session 1 local verification

The final source selection passed 163 deterministic cases:

```bash
python -m pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_governed_selection_diagnostics.py \
  services/core-control-plane/tests/delivery/catalog_search/test_governed_typed_selection_read.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidate_selection.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidate_context.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_governed_selection_campaign.py \
  services/core-control-plane/tests/composition/test_typed_selection_read_composition.py \
  tests/integration/scripts/test_governed_typed_selection_campaign.py
```

Separately, the unchanged L01-L04/A01-A04 source/preference/context/retained-Pattern,
outcome/Release/provider-fence/kill-switch selection passed 220 cases, recorded on #2256.
Those checks prove neither complete source history nor live current-Owner, intervention, recurrence,
release-admission or provider-commit evidence. Shared readiness/structure/catalog documents remain
untouched; session 3 owns serial aggregation. No Console stack or live provider was invoked.

### Remaining work

- [x] Complete positive and negative local integration and ten or more final critiques: 210 focused tests and sixteen recorded rounds above.
- [x] Register a fresh independently authored and separately reviewed window (`governed-read-window.v3.json`) after the producer diagnoses established the `resource_type_query_terms` and `no_candidate_match` repairs, and pass `governed-typed-selection-answer-window.v3` and `governed-typed-selection-answer-latency.v3` on exact merged commit `8fec8d423ca4dfbcca2802516dd5454bb8cd0352` (`sha256:66848cbeb7779b14c70082f927a299c37ac999fc116f8e6287ecf84cb6d3f45f`).
- [x] Retain independent qualification admission, explicit Var Owner approval, Thor registry promotion, Saga audit, and independent effect observation in the development profile (`sha256:72b8038ef7be188e00eac79eb718375b0a38bed85656e5f182f46da545658e4b`).
- [ ] Complete separate production installation qualification and browser/elapsed-time items tracked under #2256 before enabling governed typed selection outside the development profile.
