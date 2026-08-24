# Downstream Fork Guide implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Framework-surface and integrity protection | implemented | [`framework-surface.txt`](../../../scripts/lib/framework-surface.txt), [`check-protected-paths.sh`](../../../scripts/integrity/check-protected-paths.sh), [`check-integrity.sh`](../../../scripts/integrity/check-integrity.sh) | The machine-readable locked set drives the fork guard and offline integrity check. |
| Supported seam recipes and example vertical | implemented | [Fork Seam Recipes](../../roadmap/fork-and-sequencing/downstream-fork-seam-recipes.md), [Example Vertical](../../roadmap/fork-and-sequencing/downstream-fork-example-vertical.md), [`test_change_summary_example.py`](../../../services/core-control-plane/tests/verticals/test_change_summary_example.py) | The guide routes concrete downstream work through existing seams and a tested generic example. |
| Deployment-specific adapters and promotion evidence | not-applicable | [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md) | These belong to each downstream distribution and deployment, not this upstream procedural guide. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Adopted the implementation ledger without reconstructing earlier provenance and aligned the guide with the machine-readable framework surface, current seam cookbook, and historical standard-set compatibility boundary. | `current change`; the sources and focused checks listed in the scope table. | No implementation work is owned by this guide; downstream distributions supply their own adapters and evidence. |

### Remaining work

- [x] No implementation remains in this procedural guide. The machine-readable framework surface,
  focused integrity checks, seam cookbook, and tested example provide its executable evidence.
