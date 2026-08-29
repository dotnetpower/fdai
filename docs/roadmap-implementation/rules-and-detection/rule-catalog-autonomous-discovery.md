# Autonomous Rule Discovery implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Candidate grounding and poisoning guard | implemented | `services/core-control-plane/src/fdai/agents/_framework/candidate_guard.py`; `services/core-control-plane/tests/agents/test_candidate_guard.py` | Mimir quarantines ungrounded, malformed, or flooding candidates without granting promotion authority. |
| Norns consensus | implemented | `services/core-control-plane/src/fdai/agents/_framework/norns_consensus.py`; `services/core-control-plane/tests/agents/test_norns_consensus.py` | All three deterministic perspectives must agree before Norns publishes an inert candidate. |
| Candidate review and catalog compilation | implemented | `services/core-control-plane/src/fdai/core/operational_learning/catalog.py`; `review.py`; `services/core-control-plane/tests/agents/test_mimir_catalog_review.py` | Review packages and bounded publication state are implemented; activation still requires the ordinary catalog-as-code path. |
| Override and operational-signal intake | implemented | `services/core-control-plane/src/fdai/core/operational_learning/discovery_contracts.py`; focused cycle and Norns override tests | Normalized override signals enter the bounded source window without creating an unsupported bus topic. |
| Per-candidate shadow-dwell evidence and threshold gate | implemented | `services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py`; `services/core-control-plane/tests/agents/test_discovery_shadow_{dwell,review}.py` | Var, Saga, and Norns close a distinct human review by stable observation id without duplicating the sample or changing its policy-escape fact. |
| Long-horizon discovery cycle | implemented | `services/core-control-plane/src/fdai/core/operational_learning/discovery_cycle.py`; focused cycle tests | The scheduler persists bounded observe, hypothesize, verify, and integrate stages with stable bucket identity, revision fencing, timeout, retention, and terminal replay. |
| Mixed-model cross-check | implemented | `discovery_contracts.py`; `discovery_cycle.py`; focused cycle tests | Distinct model identities and families are mandatory; disagreement and digest substitution stay held for human review. |
| Loop throughput metrics | implemented | `DiscoveryCycleMetrics`; focused cycle persistence tests | Each completed cycle stores an audited no-authority projection for candidates per cycle, gate pass rate, override-trigger rate, and retirement rate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Complete the scheduled loop, shadow evidence, override intake, and mixed-model gate. |
| 2026-08-15 | in-progress | Implemented per-candidate shadow-dwell retention and the fail-closed threshold gate, and split the former combined scheduler/dwell row. | `current change`; `services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/operational_learning services/core-control-plane/tests/agents` passed (1214 tests). | Scheduler, mixed-model cross-check, loop metrics, and an audit-entry producer for operator review outcomes. |
| 2026-08-29 | implemented | Added the replayable bounded cycle, independent-family candidate re-approval, override-aware audited metrics, and distinct human shadow-review closure. | `current change`; discovery cycle, persistence, shadow dwell, Var, and Saga paths; `uv run pytest -q --no-cov services/core-control-plane/tests/core/operational_learning services/core-control-plane/tests/agents/test_discovery_shadow_dwell.py services/core-control-plane/tests/agents/test_discovery_shadow_review.py services/core-control-plane/tests/agents/test_wave2_governance.py services/core-control-plane/tests/agents/test_wave3_pipeline.py services/core-control-plane/tests/agents/test_quorum.py services/core-control-plane/tests/agents/test_framework_layout.py services/core-control-plane/tests/agents/test_pantheon_doc_parity.py` passed 309 tests. | Retain a governed deployed cycle and live review cohort before claiming `validated`. |
| 2026-08-29 | implemented | Hardening round 1 rejected authority-bearing keys at any nesting depth in model-produced candidate payloads. | `current change`; `discovery_contracts.py`; `test_discovery_cycle.py`; 8 focused tests, Ruff, and strict mypy passed. | Continue the hardening campaign; deployed evidence remains separate. |

### Remaining work

- [x] Complete the bounded implementation scope and prove replayable cycle identity, non-duplicating
  human review, override-aware mixed-model holds, and audited throughput metrics with
  `services/core-control-plane/tests/core/operational_learning/test_discovery_cycle.py` and
  `services/core-control-plane/tests/agents/test_discovery_shadow_review.py`.
