# Azure Resource Discovery Command Coverage implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Resource vocabulary and Azure type discrimination | implemented | [`resource-types.yaml`](../../../rule-catalog/vocabulary/resource-types.yaml), [`resource_type.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/resource_type.py), and focused catalog and ARG tests | Query terms, category terms, stable mapping digests, and reviewed Azure `kind` discrimination exist for cataloged types only. |
| Inventory-language registry | implemented | [`inventory_query_language.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/inventory_query_language.py) and [`test_inventory_query_language.py`](../../../services/core-control-plane/tests/rule_catalog/test_inventory_query_language.py) | The validated registry and digest exist. This is not an `InventoryQuery` or `DiscoveryQueryPlan` compiler. |
| Selective Azure inventory adapters | implemented | [`arg_query.py`](../../../services/core-control-plane/src/fdai/delivery/azure/arg_query.py), [`inventory.py`](../../../services/core-control-plane/src/fdai/delivery/azure/inventory.py), [`arm_inventory.py`](../../../services/core-control-plane/src/fdai/delivery/azure/arm_inventory.py), and their focused tests | ARG and ARM adapters query catalog-resolved resource types with bounded pagination and fail-closed behavior. No central discovery-plan router is implied. |
| Selective operator inventory filtering | implemented | [`_system_inventory_tool.py`](../../../services/core-control-plane/src/fdai/core/conversation/_system_inventory_tool.py) and [`test_system_tools.py`](../../../services/core-control-plane/tests/conversation/test_system_tools.py) | The tool filters a supplied snapshot by neutral type, id substring, and resource group. It does not compile general discovery intent. |
| Conversational read-intent boundary | implemented | [`semantic_judgment.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_judgment.py), [`routing.py`](../../../services/core-control-plane/src/fdai/core/read_investigation/routing.py), and focused semantic-judgment and read-investigation routing tests | Shared candidate-only semantic judgment proposes English, Korean, and mixed-language meaning and source-grounded targets. Deterministic code retains exact registered-intent, resource-identity, budget, and evidence-authority checks. This boundary is not the `DiscoveryIntent` compiler or discovery backend router. |
| Console provider-execution parsing | implemented | [`inventory-execution-display.ts`](../../../console/src/deck/inventory-execution-display.ts) and its focused test | The Console displays only structurally valid, redacted, bounded `provider_execution` records and keeps them separate from IQL. |
| Provider-execution receipt emission | implemented | [`discovery_receipts.py`](../../../services/core-control-plane/src/fdai/delivery/azure/discovery_receipts.py), [`discovery_evidence.py`](../../../packages/service-contracts/src/fdai_service_contracts/discovery_evidence.py), and focused Python and Console parser tests | The producer accepts an exact registered plan and bounded result summary, never raw argv, credentials, continuation tokens, resource ids, or provider errors. |
| Comprehensive discovery contracts and profiles | implemented | [`discovery.py`](../../../packages/service-contracts/src/fdai_service_contracts/discovery.py), [`discovery_profiles.py`](../../../services/core-control-plane/src/fdai/delivery/azure/discovery_profiles.py), [`discovery_observations.py`](../../../services/core-control-plane/src/fdai/delivery/azure/discovery_observations.py), and focused contract and delivery tests (`44 passed`) | Frozen digest-bound intents, plans, profiles, and mapped or unmapped provider observations reject executable text and unresolved modifiers. Plans pin normalization, ARG or ARM API, Azure CLI, and extension versions. |
| Central routing, command explanation, and coverage proof | in-progress | [`router.py`](../../../services/core-control-plane/src/fdai/core/discovery/router.py), [`discovery_explanation.py`](../../../services/core-control-plane/src/fdai/delivery/azure/discovery_explanation.py), [`discovery_coverage.py`](../../../services/core-control-plane/src/fdai/delivery/azure/discovery_coverage.py); focused discovery cohort `60 passed` | Component checks bind plan schema `1.2.0`, expected result sets, scope, budgets, and result semantics. A production conversational binding and exact collector qualification remain open; aggregate CLI canaries do not establish either claim. |
| Historical aggregate canaries | validated | [`azure-discovery-live-evidence.json`](../../../config/azure-discovery-live-evidence.json) | The retained 2026-08-29 counts qualify only the recorded aggregate commands, scope, and platform. They do not establish current freshness, runtime integration, or restricted-network recovery. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted this implementation ledger and corrected the previous baseline summary; earlier provenance was not reconstructed. | Current change; focused checks: catalog registries `38 passed`, Azure adapters `116 passed`, system tools `19 passed`, and Console parser `2 passed`. | Implement the open contracts, receipt producer, routing, explanation, coverage, and governed runtime evidence below. |
| 2026-08-14 | in-progress | Added immutable discovery contracts and Azure profiles, preserved unmapped provider observations, implemented exact-equivalent routing and canonical merge, and generated sanitized execution and command-explanation evidence with live-only coverage reconciliation. | `current change`; focused discovery tests `34 passed`, Console parser `6 passed`, task-scoped Ruff, strict mypy over eight production files, and Console typecheck passed. | Retain fresh governed read-only canary receipts for the claimed resource-container and ARM-resource universes. |
| 2026-08-14 | in-progress | Added the documented `unmapped` coverage state and rejected environment assignments in server and Console command evidence. | `current change`; focused discovery tests `36 passed`, Console parser `7 passed`, task-scoped Ruff, strict contract mypy, and Console typecheck passed. | Retain fresh governed read-only canary receipts for the claimed resource-container and ARM-resource universes. |
| 2026-08-14 | in-progress | Pinned normalization and observed ARG, ARM, Azure CLI, and Resource Graph extension versions in additive profile and plan revision `1.1.0`, and proved three reviewed English and Korean scenario pairs produce identical typed routing and authority checks. | `current change`; focused discovery tests `40 passed`, task-scoped Ruff, strict mypy, and the Core import boundary gate passed. | Retain fresh governed read-only canary receipts for the claimed resource-container and ARM-resource universes. |
| 2026-08-14 | in-progress | Hardened command evidence after independent review so placeholders remain valid while redirects, control characters, and executable shell words are rejected by both server and Console boundaries. | `current change`; focused discovery tests `44 passed`, Console parser tests `11 passed`, strict mypy, Ruff, and Console typecheck passed. | Retain fresh governed read-only canary receipts for the claimed resource-container and ARM-resource universes. |
| 2026-08-14 | validated | Recorded governed aggregate-only Azure CLI canaries for the subscription-scoped resource-container and ARM-resource claims, retained only counts and provider-type set digests, and reconciled both claims without gaps or execution authority. | `current change`; [`record-azure-discovery-canary.py`](../../../scripts/automation/record-azure-discovery-canary.py), [`azure-discovery-live-evidence.json`](../../../config/azure-discovery-live-evidence.json), focused recorder tests `4 passed`, offline evidence validation passed, and centralized validation receipts passed for the recorder commits. | No remaining work for the two declared discovery-profile claims; add separate claims and evidence before validating broader universes. |
| 2026-08-29 | validated | Refreshed the governed aggregate-only Azure discovery canary over the private network with Azure CLI `2.89.1`. The two declared universes reconciled as complete with 46 resource containers, 554 ARM resources, 70 ARM provider types, no gaps, and no execution authority. | `current change`; [`record-azure-discovery-canary.py`](../../../scripts/automation/record-azure-discovery-canary.py), [`azure-discovery-live-evidence.json`](../../../config/azure-discovery-live-evidence.json), and focused recorder tests `4 passed`. | Add separate reviewed claims and governed receipts before validating broader discovery universes. |
| 2026-08-18 | implemented | Recognized a Korean state request phrased without one of the four fixed noun pairs. A resource-kind noun before `상태`, or `상태` followed by a request verb, now classifies as a current-state read, and the peering, health, history, and attribution routes keep their precedence. | `current change`; `core/read_investigation/routing.py`, `tests/core/read_investigation/test_routing.py`; 1269 focused read-investigation and agent cases passed; task-scoped Ruff and format passed. | The deterministic route still informs agent selection only; the Console semantic turn does not consult it. |
| 2026-08-21 | implemented | Superseded the preceding language-specific classifier with shared candidate-only semantic judgment. Read-investigation routing now performs only exact identifier parsing after an accepted judgment, while deterministic registered-intent, plan-ownership, evidence-budget, and provider-authority checks remain unchanged. | Commit `8fd040a7`; [`semantic_judgment.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_judgment.py), [`routing.py`](../../../services/core-control-plane/src/fdai/core/read_investigation/routing.py), and [`check-chat-semantic-routing.py`](../../../scripts/quality/architecture/check-chat-semantic-routing.py); focused read-investigation checks passed 9 cases and the semantic-routing guard reported no migration paths. | Discovery-profile compilation and backend selection remain a separate deterministic boundary. |

| 2026-09-19 | in-progress | Hardened discovery failure semantics, profile ceilings, exact-plan merge, plan-bound execution receipts, expected scope/platform reconciliation, and ARG reproduction semantics. Consolidated duplicate owner ledgers without deleting history and separated aggregate canaries from runtime qualification. | `current change`; contract, router, delivery, coverage, and recorder cohort `60 passed`; focused Ruff and mypy. | Bind and verify the production discovery path, complete the remaining inventory hardening register, and retain separately authorized exact-revision collector and failover evidence. |

| 2026-09-19 | implemented | Unified current CLI pins under profile revision `1.2.0`, retained exact `1.1.0` reconstruction, rejected unvalidated explanation versions, and separated historical integrity from explicit current-catalog, plan-binding, and freshness qualification. Added a bounded support matrix without claiming new runtime bindings. | `current change`; recorder, delivery, and coverage cohort `35 passed`; retained historical canary validates offline unchanged. | Runtime discovery binding and exact collector/failover receipts remain open. |

| 2026-09-19 | implemented | First hardening rounds rejected scalar predicate ambiguity, operation substitution, and execution or merge result-limit overruns. ARM transport now streams bounded bodies, caps accumulated rows and bytes, and respects bounded provider retries. Snapshot policies match the current graph capacity, apply source constructor limits, and drive replay-stable bounded jitter. | Commits `52ce9079d`, `b0e63c152`, `d42551f94`, `06f44f708`, `2e8c476f0`, `33abbd360`, `6855827fd`; focused ARG 155, ARM 31, inventory/scheduling 305, discovery contract 55, qualification 35, and policy 13 passing checks at their respective checkpoints. | This is partial campaign evidence, not closure of all 36 findings. See the review register below. |

### Review register

The numbered items refer to the 2026-09-19 review. `local-verified` does not mean deployed.

| Findings | Local disposition | Remaining exit condition |
|----------|-------------------|--------------------------|
| 01, 03, 06, 23 | local-verified | Exact deployed collector qualification is separate. |
| 02 | open | Give ARM fallback an equivalent admitted coverage universe before promotion; do not bypass the subset guard. |
| 04 | partial | Independent subscription queries reject wholly inaccessible subscriptions; effective resource-level visibility and authorization drift still require qualification. |
| 05 | local-verified | Per-native-type accounting prevents supplemental ARM children from masking missing native Resources. |
| 07, 08, 09, 10, 24 | local-verified | Exercise these contracts through the eventual runtime binding. |
| 11 | open | Connect the authenticated production discovery path with current scope and completeness evidence. |
| 12 | open | Execute actual bounded recovery probes and carry concurrency decisions into each run. |
| 13 | partial | Page, record and source concurrency bounds are composed; shared rolling request/byte budgets remain open. |
| 14 | partial | ARM exceptions retain retry instants; persist and consume cooldown across scheduled attempts. |
| 15, 18, 29 | local-verified | Retain scoped database execution and deployed measurements separately. |
| 16 | partial | Concurrent coordinator hardening adds total deadline and cancellation closure; validate the whole CLI setup and post-run boundary. |
| 17 | open | Bound aggregate generation memory before allocation and verify the deployed memory envelope. |
| 19 | partial | Source page limits follow policy; adaptive partitioning of oversized shards remains open. |
| 20 | open | Refresh coordinator no-progress state on actual page progress, not only shard completion. |
| 21, 22 | local-verified | ARM bounded retry and streamed byte/row/cycle guards have focused regressions. |
| 25, 26, 27 | partial | ARG scope, aggregation, and CLI page limits are verified; fully reproducible ARM query rendering remains open. |
| 28, 30 | live-evidence-required | Exact-revision workload identity, collection, promotion, failover and recovery receipts require separately authorized live work. |
| 31 | open | Share equivalent provider reads within one generation without caching across freshness boundaries. |
| 32 | partial | Production jitter is bound; stable-cycle adaptation still needs measured state. |
| 33, 34, 35, 36 | local-verified | Current pins, explicit freshness qualification, support matrix and one authoritative ledger are implemented. |

### Hardening review rounds

Round 1 reviewed scope admission, identity, paging, partial results, clocks, fallback equivalence,
budgets, deadlines, cancellation, restart/replay, receipt binding, and deployment qualification.
It found and fixed normal receipt-limit and operation-substitution gaps. The open register still
contains High and Medium issues, so this round does not establish the requested Low-only endpoint.

Round 2 repeated those 12 checks on the corrected discovery slice. It found and fixed ambiguous
scalar predicates and result-limit overruns during merge. Shared-budget, runtime-binding, memory,
and live-qualification gaps remain open; they are not downgraded to make the campaign appear done.

### Remaining work

- [ ] Verify the production discovery binding from an authenticated typed intent through exact-plan execution and evidence projection; component tests alone do not close this item.
- [ ] Retain exact-revision workload-identity, pagination, normalization, promotion, and restricted-network failover/recovery receipts before claiming collector qualification.

- [x] Add bounded `DiscoveryIntent` and immutable `DiscoveryQueryPlan` contracts plus profile-schema tests that reject executable text and unresolved modifiers.
- [x] Preserve unknown Azure provider types as bounded `mapping_status=unmapped` observations, with focused tests proving they are not dropped or promoted into the neutral ontology.
- [x] Implement a server-owned `provider_execution` receipt producer and prove that credentials, pagination tokens, raw resource ids, and provider errors cannot reach the Console record.
- [x] Implement central backend eligibility, equivalent fallback, per-plan completeness, and canonical merge tests without weakening scope or predicates.
- [x] Generate sanitized `CommandExplanation` records from registered plans and pass property and golden tests for shell controls, identifiers, redaction, and equivalent-command labeling.
- [x] Record coverage reconciliation and governed read-only live canary receipts for each claimed universe before promoting any corresponding row to `validated`; the retained artifact validates both profile revision `1.1.0` claims with zero gaps and no execution authority.
