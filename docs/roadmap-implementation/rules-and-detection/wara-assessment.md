# WARA Evidence-Governed Assessment implementation ledger

This delivery ledger records the implementation state for the scope-aware, shadow-only WARA
assessment without duplicating the normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Active recommendation crosswalk and applicability map | implemented | `rule-catalog/collected/wara-aprl/assessment/crosswalk.json`; `test_wara_assessment_catalog.py` | The derived catalog accounts for 393 active GUIDs and 80 normalized resource types without changing the source catalog; all 63 disabled records stay outside active evaluation. |
| Query review and manual evidence requirements | implemented | `rule-catalog/collected/wara-aprl/assessment/queries.json`; `wara_assessment.py`; focused catalog tests | All 143 automated recommendations have exact bodies, digests, safety classifications, and blocked evaluator reasons; all 250 non-automated recommendations have typed evidence contracts. |
| Shadow assessment and deterministic replay | implemented | `fdai/core/wara/runtime.py`; `test_runtime.py` | Exact scope and pin checks are deterministic. Missing, stale, incomplete, conflicting, truncated, provider-failed, or synthetic evidence remains unknown. |
| Ontology authority boundary | implemented | `FrameworkControl.yaml`; `framework_projection.py`; `test_framework_projection.py` | Mapping state and crosswalk digest are projected, while framework-derived observations remain disconnected from every authority path. |
| Operator API and Console | implemented | `wara_projection.py`; `family_adapters.py`; `wara-controls.model.ts`; `wara-controls.tsx`; focused Operator and Console checks | The shadow-event consumer merges exact active coverage into the read-only lifecycle projection. The surface separates catalog, mapping, applicability, evaluation, and satisfaction and rejects any execution-authority payload. |
| Review-only source updates | implemented | `wara_review.py`; `test_wara_review.py` | Semantic diffs are content-addressed and deterministic; invalid generations preserve the last valid generation and cannot change active authority. |
| Governed live-Azure receipt | deferred | [Issue #401](https://github.com/dotnetpower/fdai/issues/401) | Requires explicit live-Azure authorization after local focused checks pass. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-01 | in-progress | Adopted the implementation ledger and fixed the advisory, shadow-only, evidence, scope, query, ontology, and Operator boundaries before implementation. | `current change`; [WARA assessment design](../../roadmap/rules-and-detection/wara-assessment.md); [Issue #401](https://github.com/dotnetpower/fdai/issues/401) | Implement and run the focused checks, then request separate authorization for the governed live-Azure receipt. |
| 2026-09-01 | implemented | Completed the derived crosswalk, external query catalog, conservative evidence contracts, admitted bounded read plan, shadow runtime and replay, ontology mapping projection, wired Operator event projection, API and Console, and review-only update package. | `current change`; focused Python suite (`164 passed`, `1 skipped` optional PDF extra), Console model suite (`10 passed`), strict mypy, targeted Ruff, isolated production build, design/docs/localization checks, deterministic regeneration, three-viewport browser review, and `validate-catalog-full.py --only best_practice_deep` passed. | Obtain separate live-Azure authorization and retain one governed multi-resource shadow receipt before claiming validated. |

### Remaining work

- [x] Recorded passing focused schema, importer, crosswalk, query-safety, runtime, replay, ontology,
  Operator API, Console, localization, update-diff, and WARA full-catalog-stage checks for the
  current change.
- [ ] After separate live-Azure authorization, retain one governed multi-resource shadow assessment
  receipt with exact scope and no remediation authority.
