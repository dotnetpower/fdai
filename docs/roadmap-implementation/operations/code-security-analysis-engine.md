# Code Security Analysis Engine implementation ledger

This delivery ledger tracks the evidence-gated implementation of FDAI's owned common code graph
and interprocedural analysis engine. Existing scanner and findings behavior remains owned by its
current ledgers until a package below produces source and focused evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Graph, rule, and path-evidence contracts | implemented | `analysis_contracts.py`; `test_analysis_contracts.py` (7 passed); Ruff, strict mypy, and editor diagnostics | Strict version 1 models reject unknown fields, dangling graph references, duplicate identities, invalid path order, context-free sanitizers, and unexplained uncertainty; canonical JSON and SHA-256 are stable. |
| License and benchmark baseline | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-0-contracts-licenses-and-benchmark-baseline) | No dependency or corpus is approved by this plan alone. |
| Python interprocedural SQL injection slice | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-1-python-sql-injection-vertical-slice) | The implemented single-function Python verifier remains the baseline. |
| TypeScript frontend and parity slice | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-2-typescript-parity) | Current Opengrep evidence remains independent. |
| Context, alias, and incremental analysis | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-3-precision-and-incremental-analysis) | Limits and widening require measured evidence. |
| Product and verified-fix integration | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-4-product-integration-and-verified-repair) | Existing findings and remediation contracts remain authoritative. |
| Additional language frontends | not-started | [Owning design](../../roadmap/operations/code-security-analysis-engine.md#package-5-additional-languages) | Java and C# follow only after separate prerequisites and gates. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-15 | implemented | Added strict, frozen graph, rule, and path-evidence contracts with deterministic canonical JSON and content digests. | `current change`; `analysis_contracts.py`; `test_analysis_contracts.py` (7 passed); Ruff, strict mypy, and editor diagnostics. | Complete the component-license inventory and benchmark baseline before closing Package 0. |
| 2026-10-15 | not-started | Adopted the owned analysis-engine design and its evidence-gated package sequence. No runtime or catalog implementation is claimed. | `current change`; owning English and Korean design, roadmap and code-map links, design-route checks, document-size, punctuation, translation, and translation-quality checks. | Complete Package 0 contracts, license inventory, and benchmark baseline before adding a frontend. |

### Remaining work

- [x] Freeze strict version 1 graph, rule, and path-evidence schemas. Focused contract tests reject
  malformed and dangling records and prove deterministic replay and stable content identities.
- [ ] Record a pinned dependency, grammar, benchmark, and data-license inventory; exit with SPDX,
  redistribution, linkage, source revision, and release-decision fields for every adopted item.
- [ ] Establish per-language and per-weakness `dev` and `holdout` baselines; exit with precision,
  recall, unsupported coverage, full-scan time, incremental time, and peak-memory receipts.
- [ ] Deliver the Python multi-file SQL injection slice in shadow; exit with vulnerable and safe
  twins, complete path evidence, explicit unknown dispatch, and equivalent-coverage fix rescans.
- [ ] Deliver the TypeScript slice through the same graph contract; exit with separate held-out and
  resource receipts and no language branch in common graph traversal.
- [ ] Add context, alias, and incremental analysis; exit with deterministic widening, full versus
  incremental finding equivalence, and stable unchanged path identities.
- [ ] Integrate bounded path evidence and optional LLM repair review; exit with proof that no
  model-only outcome can suppress a finding or bypass tests, diff guard, and rescan verification.
- [ ] Add Java, C#, or another language only after its frontend, framework, benchmark, and license
  prerequisites pass and its promotion receipt remains disaggregated.
