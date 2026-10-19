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

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-19 | in-progress | Recorded selected A design, twelve pre-code critiques and revised pre-Function boundary before implementation. | #2275; paired design owner; current change. | Implement and verify the fixed-role authority lifecycle and actual read consumer. |
| 2026-10-19 | implemented | Wired the registered read promotion, immutable single-use read evidence, real pre-Function consumer and Vidar revocation/regression/rollback. Narrowed the model stage to 24 seconds plus the existing five-second deterministic read. | Current change; 145 focused tests pass, including production/default validation, actual Var approvals and scripted rollback; Ruff and 23-source-file focused mypy checks. | No live qualification, promotion, deployment, elapsed observation or full G03 completion is claimed; later delivery gates remain separate. |

| 2026-10-19 | implemented | Repaired delivery registration and extracted the unchanged Function-node construction into the existing typed-read composition owner. Closed the exact owning-doc advisories and regenerated SKS only through its official CLI. | Current change; 64 targeted extraction/registration/production-validator/parity tests pass; one exact packaged-catalog equality test passes; focused two-source-file mypy passes; design impact and roadmap parity pass. `wire_semantic_query.py` is 799 lines against the unchanged 800 ceiling. | Prior 145 focused results are reused only for unchanged executable inputs. Full bootstrap, actual database, operational qualification, activation, publication and G02 base integration remain explicitly unverified or deferred. |

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

### Remaining work

- [x] Complete positive and negative local integration and ten or more final critiques: 145 focused tests and sixteen recorded rounds above.
- [ ] Retain actual immutable model/source qualification and exact human approval before any deployment activation; this task performs neither.
- [ ] Keep larger-scope schema/membership, live answer latency and production promotion gates open under #2034.
