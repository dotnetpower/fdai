# Fork Seam Recipes implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Fork-marker and runtime-axis independence | implemented | `scripts/quality/architecture/check-fork-runtime-independence.py`; `scripts/verify.sh`; `tests/integration/scripts/test_fork_runtime_independence.py`; focused checks (`32 passed`) | The deterministic guard uses Git's tracked and nonignored file set to scan current and future top-level runtime sources, downstream fork code, local launch topology, committed configuration, infrastructure, migration, extension, policy, evidence validator, composite action, deployment workflow, executable scenario, deployed design-mock input, and root deployment-input paths. It recognizes fork markers in UTF-8, UTF-16, UTF-32, and Latin-1 text, while ignored local, any tracked path with a symlink component, and marker-free binary artifacts do not affect the result. The focused parity regression requires the scoped repository gate to cover every declared path family. |
| Recipe-by-recipe executable seam coverage | not-started | `docs/roadmap/fork-and-sequencing/downstream-fork-seam-recipes.md` | The cookbook identifies the intended seams and test approach, but this package did not reconcile a concrete implementation path and passing focused check for every recipe from 5.1 through 5.16. |
| Downstream-specific adapters and promotion evidence | not-applicable | `.github/instructions/generic-scope.instructions.md`; `docs/roadmap/fork-and-sequencing/downstream-fork-guide.md` | Customer-specific adapters, environment bindings, promotion, and operational receipts belong to each downstream distribution rather than this upstream recipe ledger. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | not-started | Adopted the delegated ledger; earlier provenance was not reconstructed. | current change; `docs/roadmap/fork-and-sequencing/downstream-fork-seam-recipes.md`. | Assess bounded source and test evidence before raising any scope state. |
| 2026-09-12 | in-progress | Replaced the unassessed placeholder with verified fork-marker/runtime-axis independence and separated downstream-owned operational evidence from the not-yet-assessed per-recipe implementation surface. | `current change`; `python3 scripts/quality/architecture/check-fork-runtime-independence.py`; focused integration tests (`32 passed`). | Map recipes 5.1-5.16 to their current implementations and execute each cited focused check before raising their individual scope. |

### Remaining work

- [x] Record a passing fork-marker/runtime-axis independence check and its focused regression
  (`32 passed`).
- [ ] For every recipe from 5.1 through 5.16, record the current implementation path, execute the
  recipe's cited focused check, and split the combined recipe row into independently deliverable
  evidence-backed rows.
