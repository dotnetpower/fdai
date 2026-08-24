# Benchmark Adapters implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status:** Dormant. The independently packageable SDK and external driver
> packages remain implemented and focused-tested. The `EvaluationHost`, evaluation runtime entry
> points, focused host suite, and legacy compatibility facade were removed during the 2026-08-08
> service extraction and have no replacement in the current tree.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Evaluation SDK package | implemented | `evaluation-sdk/src/fdai_evaluation_sdk/`; `evaluation-sdk/tests/`; evaluation-package CI job | Versioned contracts and runner lifecycle remain focused-tested and independently buildable while runtime integration is dormant. |
| FDAI evaluation host integration | deferred | Current-tree absence of `services/core-control-plane/src/fdai/evaluation/`; this document's [dormant-status decision](../../roadmap/interfaces/benchmark-adapters.md#dormant-status) | No public host, runtime entry point, or focused host suite exists. Reactivation requires a new reviewed implementation and evidence boundary. |
| SREGym driver package | implemented | `benchmarks/sregym/`; `benchmarks/sregym/tests/` | Adapter mechanics remain tested. No current FDAI host can run the adapter. |
| CyberGym package and independent shadow runner | implemented | `benchmarks/cybergym/`; `benchmarks/cybergym/tests/`; `scripts/benchmarking/run_cybergym.py` | Adapter mechanics remain tested, and the explicit repository shadow runner remains separate from FDAI host integration. |
| Evaluation dependency and boundary gates | implemented | Root `pyproject.toml`; `uv.lock`; `scripts/quality/architecture/check-evaluation-boundaries.py` | Runtime and root development dependencies omit the dormant packages; all-package CI preserves their isolated contracts and boundaries. |
| Governed live benchmark evidence | deferred | [Dormant status](../../roadmap/interfaces/benchmark-adapters.md#dormant-status) | No new live benchmark evidence is required while host integration remains dormant. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; package source, focused suites, and boundary checks listed in the scope table. | Retain governed readiness and benchmark-run evidence without raising execution authority. |
| 2026-08-21 | deferred | Corrected the stale active-host claim after service extraction had removed the host, runtime entry points, host tests, and compatibility facade. Removed the three dormant packages from the root `dev` dependency surface while retaining workspace package tests and builds. | `current change`; `pyproject.toml`; `uv.lock`; package READMEs; 68 package tests passed; lock check and all-package frozen sync passed. | Keep the integration dormant until a reviewed host design, focused host suite, and governed end-to-end evidence are approved together. |

### Remaining work

- [x] Remove dormant SDK and benchmark packages from the root FDAI `dev` dependency surface while
  retaining independent workspace package tests and wheel builds.
- [ ] Before reactivation, implement a service-owned `EvaluationHost`, focused ingress, custody,
  attenuation, cleanup, and failure tests, an explicit runtime entry point, and one governed
  end-to-end receipt on the same reviewed revision.
- [ ] Keep conversational semantic regression under `eval/golden-dataset/`; do not route that
  corpus through this dormant host integration.
