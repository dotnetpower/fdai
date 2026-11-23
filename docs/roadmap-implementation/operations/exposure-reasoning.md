# Exposure Reasoning implementation ledger

This delivery ledger tracks the evidence-gated implementation of FDAI's ontology-based exposure
reasoning. The design is proposed; no runtime, catalog, or ontology declaration is claimed.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Competency questions and labeled corpus | not-started | Design only: [Exposure Reasoning](../../roadmap/operations/exposure-reasoning.md) | The APIM sign-up case and its negative controls are specified but not frozen as a test. |
| `Endpoint` and `ExposureMechanism` declarations | not-started | None | Each ObjectType waits for its frozen competency test to fail on existing objects. |
| Entry-point inventory and child-resource reads | not-started | None | Child resources such as identity providers and products are not in Resource Graph. |
| T0 invariant mechanisms in shadow | not-started | None | Five invariants are designed; none has a rule or evaluator. |
| Non-mutating probe contract (E3) | not-started | None | Requires a separate opt-in scope, audit receipts, and a no-mutation proof. |
| T1 fingerprint generalization and T2 hypothesis lane | not-started | None | Gated on a measured T0 baseline. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-11-23 | not-started | Adopted the proposed exposure-reasoning design as a documentation-only change. | `current change`; owning English and Korean design documents. | Freeze competency tests and the labeled corpus before any declaration or code. |

### Remaining work

- [ ] Freeze competency questions E1-E6 and a labeled corpus with the APIM sign-up case and negative controls, then show the existing objects fail them.
- [ ] Verify classic and v2 API Management developer-portal behavior against Microsoft documentation and an owned test instance before encoding tier facts.
- [ ] Declare `Endpoint`, `ExposureMechanism`, and the new LinkTypes in shadow, with `execution_authority: false`.
- [ ] Collect entry-point and child-resource evidence with lane, tier, and freshness metadata.
- [ ] Implement the five T0 mechanisms with refutation checks and report corpus recall and false-clear results.
- [ ] Define the E3 probe contract and prove no mutation through audit receipts before any live use.
- [ ] Add T1 candidate suggestion and the T2 verified-hypothesis lane; promote nothing without Mimir evidence.
