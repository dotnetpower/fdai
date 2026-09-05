# Recorded Resource State implementation ledger

This ledger tracks the shared read-only state contract used by Dashboard v2 and Ontology Instances.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shared recorded-state API and bounded paging | implemented | `services/operator-service/src/fdai_operator_service/families/operations/instance_states.py`; `recorded_state.py`; focused state, page, instance, route, and composition tests (`187 passed`) | Immutable source reads, independent recorded facts and same-generation continuation; no provider reads, new writer, or execution authority. |
| Common Console decoder and state presentation | implemented | `console/src/recorded-resource-state.ts`; `console/src/components/recorded-state-facts.tsx`; `console/src/routes/dashboard-v2.loading.ts`; focused Console tests (`150 passed`) and native Dashboard E2E (`10 passed`) | Both screens use one fact contract. Source values remain visible with unknown/stale metadata rather than being recast as health. Typecheck and build passed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | in-progress | Started the approved shared recorded-state query after confirming state values were retained in instance properties but lost by the graph/status projection. | `current change`; implementation paths above; local read-only source inspection from the originating Dashboard work. | Finish API contract, paging, native consumers and focused validation. |
| 2026-09-05 | implemented | Added the common recorded-state projection to instance directory/detail and a paged authenticated state route. Dashboard now loads that route without graph fallback; both screens show the same separate facts and metadata. | `current change`; 187 backend checks, 150 Console checks, 10 native browser scenarios, typecheck and build passed. Read-only local checks read one generation in two bulk pages without provider calls. | Retain authenticated operator-screen evidence before live-readiness claims. |
| 2026-09-05 | implemented | Isolated the complete recorded-state change from concurrent document-ingestion edits and documented source declaration and assessment-evidence boundaries. | `current change`; 258 backend checks passed with one optional PDF check skipped; 95 Console checks, typecheck, and build passed; entry gzip is 143109 bytes under the unchanged 150000-byte ceiling. Roadmap tracking and document-size checks passed. | The base snapshot contains an unregistered `test_power_platform_connector.py`; the service-ownership suite reports nine related failures independently of the two new state-test registrations. Preserve that separate connector repair and complete the recorded-state follow-up items below. |

### Remaining work

- [x] Pass backend tests for independent state axes, evidence gaps and cursor/generation/principal isolation.
- [x] Pass common frontend decoder, multi-page loader, instance rendering and Dashboard browser tests.
- [x] Verify the local read path uses stored instance records without Azure or model calls.
- [ ] Retain authenticated operator-screen evidence before claiming live deployment readiness.
- [ ] Diagnose remaining missing operational values by canonical ResourceType and source field using
  one generation, separating applicability, collection, mapping, and display gaps before changing
  the Unknown presentation.
