# Code Security Analysis Engine implementation ledger

This delivery ledger tracks the evidence-gated implementation of FDAI's owned common code graph
and interprocedural analysis engine. Existing scanner and findings behavior remains owned by its
current ledgers until a package below produces source and focused evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Graph, rule, and path-evidence contracts | implemented | `analysis_contracts.py`; `test_analysis_contracts.py` (7 passed); Ruff, strict mypy, and editor diagnostics | Strict version 1 models reject unknown fields, dangling graph references, duplicate identities, invalid path order, context-free sanitizers, and unexplained uncertainty; canonical JSON and SHA-256 are stable. |
| License and benchmark baseline | implemented | `analysis-components.yaml`; split Python SQL-injection corpus; strict loaders and evaluator; `test_analysis_evaluation.py` (4 passed) | Active, planned, and research-only terms are distinct. Synthetic `dev` and `holdout` each record precision and recall 1.0 with unsupported 0; this proves the frozen four-case baseline only. |
| Python interprocedural SQL injection slice | implemented | `python_graph.py`, `python_analysis.py`, owned rule catalog, SARIF adapter, scan-job/replay/Kata wiring; 21 new tests and 32 focused scan/replay regressions | Bounded files, functions, call depth, contexts, paths, recursion, parse failures, aliases, safe parameter binding, stable graph/path digests, and canonical issue ingestion are covered. The lane remains a reported deterministic producer, not an automatic `verified` grant. |
| TypeScript frontend and parity slice | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-2-typescript-parity) | Current Opengrep evidence remains independent. |
| Context, alias, and incremental analysis | in-progress | Python call-context separation, import aliases, deterministic work limits, and explicit unresolved coverage are implemented and tested. | Field-sensitive heap aliases, widening receipts, and dependency-based incremental invalidation remain. |
| Product and verified-fix integration | in-progress | Owned SARIF passes through existing bounded ingestion, canonical issues, receipts, review packages, exports, prepared-result replay, and Kata reconstruction. | Bounded Console path projection and isolated LLM patch validation remain. |
| Additional language frontends | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-5-additional-languages) | Java and C# follow only after separate prerequisites and gates. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-15 | implemented | Completed Package 0 and the Python SQL-injection vertical slice: strict component terms and split corpus, deterministic AST graph, bounded interprocedural paths, owned SARIF, canonical findings, and scan/replay/Kata composition. | `current change`; 21 new focused tests, 32 existing scan/replay regressions, Ruff, strict mypy, and diff checks. | Implement TypeScript parity, incremental invalidation, additional weakness classes, bounded UI path evidence, and verified LLM repair. |
| 2026-10-15 | implemented | Added strict, frozen graph, rule, and path-evidence contracts with deterministic canonical JSON and content digests. | `current change`; `analysis_contracts.py`; `test_analysis_contracts.py` (7 passed); Ruff, strict mypy, and editor diagnostics. | Complete the component-license inventory and benchmark baseline before closing Package 0. |
| 2026-10-15 | not-started | Adopted the owned analysis-engine design and its evidence-gated package sequence. No runtime or catalog implementation is claimed. | `current change`; owning English and Korean design, roadmap and code-map links, design-route checks, document-size, punctuation, translation, and translation-quality checks. | Complete Package 0 contracts, license inventory, and benchmark baseline before adding a frontend. |

### Remaining work

- [x] Freeze strict version 1 graph, rule, and path-evidence schemas. Focused contract tests reject
  malformed and dangling records and prove deterministic replay and stable content identities.
- [x] Record the initial component and license inventory with active, planned, and research-only
  status, version, source, license, redistribution, and integration boundaries.
- [x] Establish the Python SQL-injection `dev` and `holdout` synthetic baseline. Both splits record
  precision and recall 1.0 with unsupported 0; larger public and real-code corpora remain required
  before promotion or parity claims.
- [x] Deliver the Python multi-file SQL injection slice as a deterministic reported producer with
  vulnerable and safe twins, complete path evidence, explicit unknown dispatch, stable replay,
  canonical SARIF ingestion, and scan-job coverage integration.
- [ ] Deliver the TypeScript slice through the same graph contract; exit with separate held-out and
  resource receipts and no language branch in common graph traversal.
- [ ] Add context, alias, and incremental analysis; exit with deterministic widening, full versus
  incremental finding equivalence, and stable unchanged path identities.
- [ ] Integrate bounded path evidence and optional LLM repair review; exit with proof that no
  model-only outcome can suppress a finding or bypass tests, diff guard, and rescan verification.
- [ ] Add Java, C#, or another language only after its frontend, framework, benchmark, and license
  prerequisites pass and its promotion receipt remains disaggregated.
