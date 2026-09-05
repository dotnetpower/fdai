# Ontology-Grounded FinOps Package Architecture implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and
resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Extractable FinOps guard baseline | implemented | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `services/core-control-plane/tests/core/verticals/test_finops.py`; 11 focused tests | Pure candidate and guard logic exists inside Core. This does not prove package composition. |
| Independent distribution | implemented | `extensions/cost-governance/`; wheel, source distribution, and package-resource checks | The typed `fdai-cost-governance` package loads 38 digest-bound resources through `importlib.resources`; built-wheel and source-distribution rebuild checks load the same candidates without package source paths. |
| Ontology-bound vertical manifest and bundle | implemented | `core/vertical_packages/`; package and Core focused tests | Immutable generic contracts reuse `ExtensionManifest` and the trusted `extension` artifact kind, pin the exact ontology and semantic profile, and expose no approval, execution, or promotion authority. |
| Atomic activation and provider binding | implemented | `VerticalPackageManager`; `cost_governance_activation.py`; `test_cost_governance_runtime.py`; package boundary tests | Install starts disabled. Availability derives from host, ontology, and provider requirements. An enabled package is discovered through one package-neutral entry point, and bounded retained observations rebuild Njord evidence after restart without importing the optional package into Core or granting authority. |
| Compatibility cutover and rollback | implemented | `fdai_cost_governance.parity`; `VerticalPackageManager`; frozen parity and N-1 lifecycle tests | Dual-read single-publish parity, package-owned catalog cutover, disable, failed-upgrade preservation, and local previous-version rollback are implemented. The deprecated Core facade remains inert because governed production cutover and live previous-version rollback evidence do not exist. |
| Operator PostgreSQL projection compatibility | implemented | `services/operator-service/src/fdai_operator_service/postgres_cost_governance.py`; `services/operator-service/tests/test_postgres_cost_governance.py`; current change | The reader uses JSON scope membership, normalizes SQLAlchemy-style psycopg DSNs for direct driver use, selects analytics with static parameterized SQL, and passed the focused Operator suite. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | implemented | Confirmed that the shared Operator handover proposal decorator is isolated to web conversation proposals and does not wrap Cost Governance routes, activation, or data access. | `current change`; focused Operator handover and service migration checks passed. | No Cost Governance package work remains for this host-seam clarification. |
| 2026-08-31 | implemented | Added Owner-controlled exact-revision activation, immutable analytics snapshots, package-neutral provider discovery, and bounded restart hydration from complete retained USD observations. Core reconstructs Njord's advisory baseline and conversational evidence without republishing historical findings or importing the optional package. | `current change`; activation and analytics migration, `cost_governance_activation.py`, PostgreSQL Cost Governance stores, Njord runtime binding, package entry point, focused package-boundary and hydration tests (`30 passed`), strict mypy and Ruff. | Retain governed live lifecycle, production cutover, and previous-version rollback receipts before removing the compatibility facade. |
| 2026-08-29 | in-progress | Aligned the Operator Cost Governance projection with its JSON scope representation and direct psycopg connection contract. | `current change`; Operator reader and focused test paths. | Record the focused Operator test result before raising the implementation-scope state. |
| 2026-08-29 | implemented | Confirmed that restoring the shared authoritative conversation fallback stream and the Azure Monitor contracts facade does not alter optional Cost Governance activation, publication, or ownership. | `current change`; focused semantic composition, Azure Monitor, and facade-only checks (`12 passed`). | No package-boundary work remains for this host correction. |
| 2026-08-29 | implemented | Advanced the package semantic profile and W6 parity corpus to the new active ontology release after additive Approval and Decision `1.1.0` declarations changed the release identity. Refreshed package-resource, profile, manifest, and parity digests together. | `current change`; Cost Governance semantic profile, package manifest, W0 inventory, F1-F8 and W6 fixtures; focused semantic-profile, convergence, and authoritative-catalog checks (`45 passed`). | Governed W7 lifecycle and rollback evidence remains unchanged. |
| 2026-08-29 | implemented | Clarified that shared service-contract exports, Operator composition, and Console catalogs remain multi-capability host seams. An independent Azure Monitor binding cannot activate or become owned by the optional Cost Governance package. | `current change`; rebased platform integration paths and the Cost Governance design owner; design-route, translation, and pre-push checks. | No additional package-boundary implementation is required for this host-seam clarification. |
| 2026-08-28 | in-progress | Corrected the stale W6 scope row and recorded the first protected W7 deployment attempt. The hardened implementation merged to `main`, exact main CI and the image publication passed, but protected model capability quorum failed before Terraform planning. | PR #328; merge `6b638db7c6fb928372cd31b4ad8371e3f9ea683a`; main CI `33175385098`; container publication `33175384996`; protected run `33175771735`. | Restore protected model capability quorum under a new hypothesis, then retain live lifecycle, production cutover, and previous-version rollback receipts before facade removal. |
| 2026-08-28 | implemented | Completed W2 with the independent package, inert candidate assets, generic immutable Core contracts, disabled-first atomic activation, and a supply-chain-selected Core distribution image profile. | `current change`; 17 package and Core lifecycle tests passed; 21 image and supply-chain tests passed; Ruff and strict mypy passed; wheel and source distribution built; direct wheel and source-distribution rebuild each loaded 38 verified resources. | Keep compatibility cutover, parity, upgrade, and previous-version rollback in W6; retain governed image and lifecycle receipts in W7. |
| 2026-08-24 | not-started | Defined the ontology-grounded package boundary and adopted an evidence-bounded ledger without claiming package implementation. | `current change`; owner document, paired translation, route, size, link, and roadmap tracking checks. | Deliver W0-W7 in the linked delivery plan and retain exact-revision lifecycle evidence. |

### Remaining work

- [x] Complete the W0 asset and identifier inventory with exactly one future owner per item.
- [x] Build `fdai-cost-governance` wheel and source distributions that load all 38 resources without
  repository-relative package reads.
- [x] Implement ontology-bound vertical manifest and bundle validation that leaves the active
  runtime unchanged on every tested installation and activation failure.
- [x] Prove local atomic upgrade and previous-version rollback on one exact package and ontology
  release during W6.
- [ ] Retain governed live lifecycle, production cutover, and previous-version rollback receipts
  during W7 before removing the compatibility facade.
