# Console Read Boundary implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Read data-source declaration completeness | validated | `fdai_operator_service/composition.py`, `console/src/routes/dashboard.loading.ts`, their focused tests (`49 passed`, `3 passed`), and an authenticated run of all six Overview screens with no error alert and no request that can only `404` | Every read route the console consults is declared in `/system/data-sources`, including routes this distribution does not serve. Unserved measurement surfaces are declared unavailable rather than answered with a synthesized value. |
| Catalog-backed reference projections | validated | `test_materialize_authoritative_catalogs.py`; authenticated Workflow builder and Agent oversight loads | Reviewed ActionType, Workflow, and ownership declarations reach their read projections without creating runtime or action evidence. |
| Unavailable-surface presentation | validated | Focused Operator and Console checks plus authenticated passes over the affected panels | Unserved routes retain server-owned reasons, and panels do not expose raw transport status or nonexistent configuration symbols. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-18 | implemented | Declared `/kpi/promotion-gates` as an explicitly unavailable read source. The workflow family reads the `promotion-gate.list` projection, but nothing writes it, so the route answered `503` on every Overview and Control assurance load and the console kept requesting it. Declaring the absence lets the client short-circuit and lets the panel state a reason about itself. No gate value is synthesized in either direction. | `current change`; operator suite `406 passed, 1 skipped`; Ruff check and format clean. Measured: the local store holds `rule.list`, `workflow.action-type-list`, and `workflow.catalog` under `operator-projection:workflow:` and zero rows matching `promotion-gate`, and no writer for that key exists in the tree. Mutation-verified by emptying the declared routes, which fails both unavailable-source tests. | Remove the declaration if a promotion-gate producer is introduced. |
| 2026-08-18 | validated | Adopted this focused owner for the Console read boundary and moved its current scope, remaining work, and normative read contract out of the oversized parity document. | `current change`; the six earlier implementation transitions remain unchanged in `dev-and-deploy-parity.md`, and the focused document, translation, route, and size gates pass. | Complete the observable items below without widening the Operator API's authority. |

### Remaining work

- [ ] Decide whether the onboarding probe, configuration baseline, and conversation delivery
  capabilities are rebuilt behind the service boundary. The pre-split routes imported Core
  providers directly, which the independent-service boundary no longer permits.
- [ ] Materialize or retire the `operator-projection:workflow:promotion-gate.list` projection. The
  workflow family reads it and `/kpi/promotion-gates` answers `503`, but no component in this
  distribution writes it.
