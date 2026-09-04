# WARA Evidence-Governed Assessment implementation ledger

This delivery ledger records the implementation state for the scope-aware, shadow-only WARA
assessment without duplicating the normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Active recommendation crosswalk and applicability map | implemented | `rule-catalog/collected/wara-aprl/assessment/crosswalk.json`; `test_wara_assessment_catalog.py` | The derived catalog accounts for 393 active GUIDs and 80 normalized resource types without changing the source catalog; all 63 disabled records stay outside active evaluation. |
| Query review and manual evidence requirements | implemented | `rule-catalog/collected/wara-aprl/assessment/{queries,evaluator-bindings}.json`; `wara_assessment.py`; `wara_evaluator_binding.py`; focused catalog tests | All 143 automated recommendations have exact bodies, digests, and safety classifications. A separate exact-digest overlay binds three reviewed matching-row evaluators without editing the generated crosswalk; the remaining recommendations retain explicit blockers. All 250 non-automated recommendations have typed evidence contracts. |
| Exact Azure observation provider | implemented | `delivery/azure/wara_observation.py`; `tests/delivery/azure/test_wara_observation.py` | The adapter accepts only approved Azure management origins and audiences, exact ARM resource ids and provider types, bounded pages/bytes/rows, advancing cursors, and in-scope result rows. Matching rows deterministically mean failed and zero rows mean satisfied, with no action authority. |
| Shadow assessment and deterministic replay | implemented | `fdai/core/wara/runtime.py`; `test_runtime.py` | Exact scope and pin checks are deterministic. Missing, stale, incomplete, conflicting, truncated, provider-failed, or synthetic evidence remains unknown. |
| Ontology authority boundary | implemented | `FrameworkControl.yaml`; `framework_projection.py`; `test_framework_projection.py` | Mapping state and crosswalk digest are projected, while framework-derived observations remain disconnected from every authority path. |
| Operator API and Console | implemented | `wara_projection.py`; `family_adapters.py`; `wara-controls.model.ts`; `wara-controls.tsx`; focused Operator and Console checks | The shadow-event consumer merges exact active coverage into the read-only lifecycle projection. The surface separates catalog, mapping, applicability, evaluation, and satisfaction, displays exact public source provenance, exact evaluator identity, and structured manual-evidence requirements, pages 50 rows at a time, and rejects any execution-authority payload. |
| Review-only source updates | implemented | `wara_review.py`; `test_wara_review.py` | Semantic diffs are content-addressed and deterministic; invalid generations preserve the last valid generation and cannot change active authority. |
| Governed live-Azure receipt | deferred | [Issue #401](https://github.com/dotnetpower/fdai/issues/401) | Requires explicit live-Azure authorization after local focused checks pass. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-04 | implemented | Hardening round 3 rejected nonstandard Azure management ports and capped configured WARA ARG response bytes at 4 MiB per page and 16 MiB per observation. Deployment configuration can lower but cannot remove these bounds. | `current change`; focused endpoint-port and response-ceiling regressions, Ruff, and strict mypy. | Retain the separately authorized live-Azure shadow receipt. |
| 2026-09-04 | implemented | Hardening round 2 fixed a paginated deadline expansion: `timeout_seconds` now bounds the complete WARA observation instead of resetting for every ARG page. | `current change`; focused multi-page deadline regression, Azure adapter tests, Ruff, and strict mypy. | Retain the separately authorized live-Azure shadow receipt. |
| 2026-09-04 | implemented | Added a content-addressed exact-evaluator overlay and a bounded Azure Resource Graph observation adapter for three reviewed violation queries. Request, read-plan, observation, evidence, result, and replay identities pin the overlay digest. The adapter rejects unapproved token targets, scope escapes, truncation, pagination loops, and non-deterministic result ordering. | `current change`; focused overlay, WARA runtime, Azure adapter, catalog materialization, Ruff, and strict mypy checks. | Bind the provider into an authorized scheduled assessment worker and retain the separately authorized live-Azure shadow receipt. |
| 2026-09-04 | implemented | Preserved exact evaluator identity and all six bounded manual-evidence requirement fields in the authoritative Operator catalog projection and Console detail view. Manual recommendations now state `manual_evidence_required` instead of a generic unevaluated limitation, while old projections decode the additive fields as unavailable. | `current change`; focused catalog materialization, Operator workflow, WARA projection, Console model, localization, type, and build checks. | Keep receipt creation outside the read-only Console and retain the separately authorized live-Azure shadow receipt. |
| 2026-09-01 | in-progress | Adopted the implementation ledger and fixed the advisory, shadow-only, evidence, scope, query, ontology, and Operator boundaries before implementation. | `current change`; [WARA assessment design](../../roadmap/rules-and-detection/wara-assessment.md); [Issue #401](https://github.com/dotnetpower/fdai/issues/401) | Implement and run the focused checks, then request separate authorization for the governed live-Azure receipt. |
| 2026-09-01 | implemented | Completed the derived crosswalk, external query catalog, conservative evidence contracts, admitted bounded read plan, shadow runtime and replay, ontology mapping projection, wired Operator event projection, API and Console, and review-only update package. | `current change`; focused Python suite (`164 passed`, `1 skipped` optional PDF extra), Console model suite (`10 passed`), strict mypy, targeted Ruff, isolated production build, design/docs/localization checks, deterministic regeneration, three-viewport browser review, and `validate-catalog-full.py --only best_practice_deep` passed. | Obtain separate live-Azure authorization and retain one governed multi-resource shadow receipt before claiming validated. |
| 2026-09-01 | implemented | Exposed exact APRL and Learn provenance and replaced the 456-row DOM with URL-addressable 50-row pages and a two-column responsive control table. | `current change`; focused Python (`45 passed`) and Console (`4 passed`) checks, typecheck, production build, catalog parity, and live 1440 x 900, 993 x 641, and 390 x 844 browser measurements passed with no document, main, table, or drawer overflow. | Retain the separately authorized live-Azure shadow receipt before claiming validated. |
| 2026-09-03 | implemented | Corrected the shared Operator revisioned-proposal transaction so an existing state can advance beyond revision 1 while preserving the same atomic proposal and compare-and-set boundary. WARA behavior and authority are unchanged. | `current change`; focused Operator and local-start checks, strict mypy, Ruff, and an authenticated Runtime Settings revision 1 to 2 save passed. | Retain the separately authorized live-Azure shadow receipt before claiming validated. |

### Remaining work

- [x] Recorded passing focused schema, importer, crosswalk, query-safety, runtime, replay, ontology,
  Operator API, Console, localization, update-diff, and WARA full-catalog-stage checks for the
  current change.
- [ ] After separate live-Azure authorization, retain one governed multi-resource shadow assessment
  receipt with exact scope and no remediation authority.
