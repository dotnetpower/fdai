# Ontology-Grounded FinOps Package Architecture implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and
resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Extractable FinOps guard baseline | implemented | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `services/core-control-plane/tests/core/verticals/test_finops.py`; 11 focused tests | Pure candidate and guard logic exists inside Core. This does not prove package composition. |
| Independent distribution | not-started | [Owner design](../../roadmap/architecture/finops-package-architecture.md) | No `fdai-cost-governance` wheel, source distribution, namespace, or package-resource manifest exists. |
| Ontology-bound vertical manifest and bundle | not-started | [Owner design](../../roadmap/architecture/finops-package-architecture.md#target-package-contracts) | `VerticalPackageManifest` and `VerticalPackageBundle` are design contracts only. |
| Atomic activation and provider binding | not-started | Existing generic `CapabilityBundle` and extension lifecycle | The existing lifecycle does not install a vertical, semantic profile, detector, or rule source. |
| Compatibility cutover and rollback | not-started | [Delivery plan](../../roadmap/fork-and-sequencing/finops-package-delivery-plan.md#w6-shadow-parity-ownership-cutover-and-rollback) | No dual-read parity, package cutover, N-1 rollback, or facade retirement evidence exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | not-started | Defined the ontology-grounded package boundary and adopted an evidence-bounded ledger without claiming package implementation. | `current change`; owner document, paired translation, route, size, link, and roadmap tracking checks. | Deliver W0-W7 in the linked delivery plan and retain exact-revision lifecycle evidence. |

### Remaining work

- [ ] Complete the W0 asset and identifier inventory with exactly one future owner per item.
- [ ] Build reproducible `fdai-cost-governance` wheel and source distributions that load all
  resources without repository-relative paths.
- [ ] Implement ontology-bound vertical manifest and bundle validation that leaves the active
  runtime unchanged on every failure.
- [ ] Prove disabled install, atomic enable, incompatible hold, disable, upgrade, and previous-
  version rollback on one exact package and ontology release.
