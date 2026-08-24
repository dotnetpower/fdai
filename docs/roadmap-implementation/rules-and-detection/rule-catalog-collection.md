# Rule Catalog Collection implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Source manifest/fetch/snapshot/watcher core; rule, Rego, Azure
> Policy, and kube-bench parsers; strict Rule/ActionType/resource-vocabulary loaders; collected
> Azure and kube-bench catalogs; continuous pipeline stages; and CandidateGuard are implemented.
> `BestPractice` also has a strict schema, loader, typed-reference catalog validation, and the
> complete Azure WAF Reliability and Operational Excellence control set. Dedicated
> config-baseline and measurement-baseline schemas, loaders, and repository stores are also
> implemented; both stores ship empty. The versioned
> MCSB catalog imports all 86 v1 controls and all 81 v2 preview controls, pins every source
> document, and validates each version's independent implementation crosswalk.
> Not every external connector/parser, production discovery schedule/PR delivery, or
> compliance/threat crosswalk listed below is complete.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Manifest, collection, snapshot, and watcher pipeline | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/collect/`; `watcher.py`; focused `tests/rule_catalog/pipeline/test_collect.py`; `test_watcher.py` | On-demand and cadence evaluation are implemented with deterministic snapshots and fail-closed collection. |
| Shipped parsers and collected Rule corpora | implemented | `services/core-control-plane/src/fdai/rule_catalog/pipeline/parse/`; `rule-catalog/collected/`; focused parser and full-catalog tests | Rule YAML, Rego, Azure Policy, and kube-bench paths are implemented; reserved parsers remain explicit failures. |
| Best practices and MCSB catalogs | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/best_practice_catalog.py`; `mcsb_catalog.py`; `rule-catalog/best-practices/`; `rule-catalog/compliance/mcsb/` | Strict loaders and current versioned catalogs are implemented. |
| Configuration and measurement baselines | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/baseline_catalog.py`; `configuration_baseline.schema.json`; `measurement_baseline.schema.json`; `rule-catalog/baselines/`; `services/core-control-plane/tests/rule_catalog/test_baseline_catalog.py` | Separate schemas, id namespaces, and stores. Both loaders are fail-closed and a missing store loads as empty. Upstream ships both stores empty, so no collected baseline content exists yet. |
| Declared reference-only collection and repository guard | implemented | [`collector.py`](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/collect/collector.py), [`check-reference-only-sources.py`](../../../scripts/quality/repository/check-reference-only-sources.py), and focused collector and checker tests | Non-dry collection cannot materialize a reference-only tree, and the Git-index gate rejects a force-added body beside a declared reference-only snapshot. Arbitrary unclassified text remains outside this declaration-bound claim. |
| Production discovery schedule and pull-request delivery | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/watcher_cli.py`; `promotion.py`; [Open decisions](../../roadmap/rules-and-detection/rule-catalog-collection.md#open-decisions) | Core stages exist; deployment scheduling, credentials, and governed pull-request delivery remain integration work. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the unsupported repository-wide licensing enforcement claim. | `current change`; current source, catalogs, and focused tests listed in the scope table. | Add the missing baseline contracts, focused restricted-content gate, and production delivery binding. |
| 2026-08-14 | implemented | Blocked persistent reference-only collection and added a staged-snapshot repository gate with synthetic fixtures. | Current change; `test_collect.py` and `test_check_reference_only_sources.py`. | Keep source classification under review; the gate enforces declared manifests and doesn't infer licensing from arbitrary text. |
| 2026-08-15 | implemented | Added dedicated `ConfigurationBaseline` and `MeasurementBaseline` contracts, strict schemas, fail-closed directory loaders, and the separate `rule-catalog/baselines/` stores. | `current change`; `services/core-control-plane/src/fdai/rule_catalog/schema/baseline_catalog.py`; `rule-catalog/baselines/`; `pytest services/core-control-plane/tests/rule_catalog/test_baseline_catalog.py` (22 passed). | Collect or author real baseline content and bind the stores to a T0 drift consumer. |

### Remaining work

- [x] Dedicated `ConfigurationBaseline` and `MeasurementBaseline` contracts, strict schemas, fail-closed loaders, and the separate `rule-catalog/baselines/configuration/` and `rule-catalog/baselines/measurement/` stores are implemented, proven by `services/core-control-plane/tests/rule_catalog/test_baseline_catalog.py`.
- [x] Add a focused repository gate with reviewable fixtures that rejects prohibited reference-only source bodies without storing restricted examples.
- [ ] Land reviewed baseline content in the shipped stores and bind the configuration store to a T0 drift consumer, evidenced by a focused drift evaluation over a loaded baseline.
- [ ] Bind watcher cadence, source credentials, snapshot storage, and catalog pull-request publication in a deployment and retain one replayable update receipt.
