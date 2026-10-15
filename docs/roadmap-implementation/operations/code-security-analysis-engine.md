# Code Security Analysis Engine implementation ledger

This delivery ledger tracks the evidence-gated implementation of FDAI's owned common code graph
and interprocedural analysis engine. Existing scanner and findings behavior remains owned by its
current ledgers until a package below produces source and focused evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Graph, rule, and path-evidence contracts | implemented | `analysis_contracts.py`; `test_analysis_contracts.py` (7 passed); Ruff, strict mypy, and editor diagnostics | Strict version 1 models reject unknown fields, dangling graph references, duplicate identities, invalid path order, context-free sanitizers, and unexplained uncertainty; canonical JSON and SHA-256 are stable. |
| License and benchmark baseline | in-progress | `analysis-components.yaml`; split Python, TypeScript, and Java SQL-injection corpora; strict loaders and evaluators; recorded receipts | Component terms and synthetic mechanics exist. Same-condition comparison with the current verifier and Opengrep, repository-scale throughput, graph size, framework coverage, and independent real-code holdout evidence remain open. |
| Python interprocedural SQL injection slice | in-progress | `python_graph.py`, `python_analysis.py`, owned rule catalog, SARIF adapter, scan-job/replay/Kata wiring; focused cross-file and fix-rescan tests | Three-file paths, bounded contexts, aliases, safe parameter binding, and explicit unknowns work. Real control-flow reachability, terminating guards, field-sensitive aliases, and a promotion-sized corpus remain open. |
| TypeScript frontend and parity slice | in-progress | TypeScript 5.9.3 Compiler API process, root-confined CompilerHost, strict adapter, split SQL receipt, rebuilt image, and container load smoke test | The frontend owns a separate traversal instead of the common analysis core. Opengrep comparison, Package 1 depth, framework coverage, and non-SQL weakness receipts remain open. |
| Context, alias, and incremental analysis | in-progress | Python call-context separation, import aliases, strict snapshots, exact unchanged reuse, reverse-call invalidation planning, and full-recompute byte equivalence | The scan job does not consume snapshots. Frontend/schema identity, partial graph recomputation, field-sensitive heap facts, deterministic widening, and per-analysis time and memory receipts remain open. |
| Product and verified-fix integration | in-progress | Owned SARIF passes through bounded ingestion, canonical issues, receipts, review packages, exports, prepared-result replay, and Kata reconstruction; baseline/fix/rescan tests cover the final verdict | Console detail currently reduces paths to source and sink. Full ordered steps, graph gaps and versions, a minimized optional repair request, isolated candidate validation, and displayed-path replay remain open. |
| Additional language frontends | in-progress | Experimental tree-sitter Java SQL frontend, rule, scan dispatch, safe/vulnerable tests, and disaggregated synthetic receipt | Java remains syntax-only and C# is absent. Compiler-backed symbols, typed framework models, separate held-out gates, and production promotion remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-15 | in-progress | Connected strict Python snapshots to the real scan job, separated source revision from build configuration identity, and bound reuse to frontend and graph-schema versions. | `current change`; `analysis_build_context.py`, `analysis_incremental.py`, `code_security_scan_job.py`; 16 focused tests; Ruff, strict mypy, and diff check. | Implement partial graph recomputation and promotion-sized incremental measurements. |
| 2026-10-15 | in-progress | Corrected the scope states after auditing the implementation against the original Package 0-5 exit criteria rather than the narrower completed implementation batch. | `current change`; owning design package and measurement sections; current source, focused tests, and receipts. | Complete the reopened observable items below before claiming the original plan complete. |
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
- [ ] Complete Package 0 with one same-condition comparison runner for the current verifier, the
  owned engine, and Opengrep; record corpus digest, repository scale, duration, peak memory, graph
  size, analyzed-function share, framework coverage, and disaggregated `dev` and unseen `holdout`.
- [ ] Complete Package 1 with reachable control-flow and terminating-guard evidence in addition to
  the existing three-file Python path, aliases, recursion, unknown dispatch, safe binding, SARIF,
  and equivalent-coverage fix rescan.
- [ ] Complete Package 2 by moving TypeScript flow traversal onto the common analysis core, proving
  the full Package 1 scenario, and recording same-condition Opengrep plus weakness-specific split
  receipts without automatic promotion.
- [ ] Complete Package 3 with field-sensitive aliases, deterministic widening, command/path/XSS
  promotion receipts, scan-job snapshot reuse, frontend/schema/rule/build-context invalidation,
  partial recomputation, stable path identities, and full-versus-incremental equivalence.
- [ ] Complete Package 4 by preserving every ordered path step, call context, sanitizer, graph gap,
  and version through Operator and Console; add a minimized optional repair candidate path whose
  isolated diff, tests, same-or-newer rescan, and displayed-path replay all fail closed.
- [ ] Complete Package 5 with compiler-backed Java and C# symbols, typed framework models, separate
  benchmark and license evidence, explicit unsupported constructs, and disaggregated shadow
  promotion receipts.
- [ ] Run at least ten independent hardening lenses over the completed Package 0-5 surface, repair
  every Critical, High, and Medium finding, and repeat until only Low-or-lower findings remain.
