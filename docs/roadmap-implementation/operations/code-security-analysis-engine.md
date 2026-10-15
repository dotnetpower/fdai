# Code Security Analysis Engine implementation ledger

This delivery ledger tracks the evidence-gated implementation of FDAI's owned common code graph
and interprocedural analysis engine. Existing scanner and findings behavior remains owned by its
current ledgers until a package below produces source and focused evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Graph, rule, and path-evidence contracts | implemented | `analysis_contracts.py`; `test_analysis_contracts.py` (7 passed); Ruff, strict mypy, and editor diagnostics | Strict version 1 models reject unknown fields, dangling graph references, duplicate identities, invalid path order, context-free sanitizers, and unexplained uncertainty; canonical JSON and SHA-256 are stable. |
| License and benchmark baseline | implemented | `analysis-components.yaml`; split Python, TypeScript, and Java SQL-injection corpora; strict loaders and evaluators; recorded receipts | Active, planned, and research-only terms are distinct. Each frozen four-case `dev` and `holdout` baseline records precision and recall 1.0 with unsupported 0; this proves only those synthetic corpora. |
| Python interprocedural SQL injection slice | implemented | `python_graph.py`, `python_analysis.py`, owned rule catalog, SARIF adapter, scan-job/replay/Kata wiring; 21 new tests and 32 focused scan/replay regressions | Bounded files, functions, call depth, contexts, paths, recursion, parse failures, aliases, safe parameter binding, stable graph/path digests, and canonical issue ingestion are covered. The lane remains a reported deterministic producer, not an automatic `verified` grant. |
| TypeScript frontend and parity slice | implemented | TypeScript 5.9.3 Compiler API process, root-confined CompilerHost, strict adapter, scan/replay/Kata binding, split receipt, resource observation, rebuilt image, and container load smoke test | Frozen `dev` and `holdout` each record TP 1, TN 1, precision/recall/F1 1.0, and unsupported 0. This is not broader parity or production promotion. |
| Context, alias, and incremental analysis | implemented | Python call-context separation, import aliases, deterministic work limits, strict snapshots, exact unchanged reuse, reverse-call invalidation, and full-versus-incremental byte equivalence | Changed inputs conservatively run a full analysis after dependency planning. Field-sensitive heap aliases and partial graph recomputation remain future precision work, not hidden completion claims. |
| Product and verified-fix integration | implemented | Owned SARIF passes through bounded ingestion, canonical issues, receipts, review packages, exports, prepared-result replay, and Kata reconstruction; an owned baseline/fix/rescan test proves the final gate | A model claim cannot verify a fix without passing tests and equivalent-coverage path disappearance; diff guard remains mandatory before the remediation commit. |
| Additional language frontends | implemented | Experimental tree-sitter Java SQL frontend, rule, scan dispatch, safe/vulnerable tests, and disaggregated `dev`/`holdout` resource receipt | The slice reports ambiguity and parse limits as incomplete. Java compiler-backed symbols, broader frameworks, and production promotion remain future work. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-15 | implemented | Completed TypeScript split/resource evaluation, strict incremental snapshots, verified-fix gating, an experimental Java SQL frontend with held-out evidence, and actual analysis-runtime image execution. | `current change`; TypeScript and Java receipts; focused Python/Node tests; image build and container load of TypeScript 5.9.3. | Broader real-code corpora, field-sensitive heap precision, partial graph recomputation, Java compiler types, and production promotion remain future gated work. |
| 2026-10-15 | implemented | Completed two further ten-lens hardening cycles over the remaining scope and repaired bounded-read, resource, dispatch, SARIF, evaluation, fix-gate, and image-runtime defects. | `rule-catalog/code-security/evaluation/analysis-hardening-remaining-20261015.json`; final review: 0 Critical, 0 High, 0 Medium, 0 Low. | No residual hardening finding in the implemented scope. |
| 2026-10-15 | implemented | Completed 20 critique rounds over the implemented analysis scope and repaired four evidence-backed input, graph-budget, output-scope, and failure-isolation defects. | `current change`; `rule-catalog/code-security/evaluation/analysis-hardening-20261015.json`; focused Python, TypeScript, Node, scan orchestration, Ruff and strict mypy checks. Final review: 0 Critical, 0 High, 0 Medium, 0 Low. | Open packages remain implementation work rather than residual hardening findings. |
| 2026-10-15 | in-progress | Added the pinned TypeScript Compiler API frontend, root-confined reads, strict adapter, scan/Kata replay binding, runtime image package contract, and Python/TypeScript graph rules for SQL, command, path, and XSS flows. | `current change`; Node frontend tests, Python adapter and scan orchestration tests, Docker source contract, Ruff and strict mypy. | Add TypeScript split evaluation and actual rebuilt-image evidence; implement incremental invalidation and verified repair. |
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
- [x] Deliver the TypeScript slice through the same graph contract; exit with separate held-out and
  resource receipts and no language branch in common graph traversal.
- [x] Add context, alias, and incremental analysis; exact unchanged inputs reuse strict snapshots,
  while changed inputs use dependency-aware invalidation and conservative full recomputation with
  byte-equivalent findings and stable unchanged path identities.
- [x] Integrate bounded path evidence and optional LLM repair review; exit with proof that no
  model-only outcome can suppress a finding or bypass tests, diff guard, and rescan verification.
- [x] Add an experimental Java SQL frontend after its parser, framework-selector, benchmark, and
  license prerequisites pass; keep its receipt disaggregated and its production promotion false.
