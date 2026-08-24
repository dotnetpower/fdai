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
| Override and operational-signal intake | in-progress | `services/core-control-plane/src/fdai/agents/norns.py`; focused Norns learning tests | Several deterministic signals can produce candidates, but the override-specific governance artifact is not implemented. |
| Per-candidate shadow-dwell evidence and threshold gate | implemented | `services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py`; `services/core-control-plane/tests/core/operational_learning/test_shadow_dwell.py`; `services/core-control-plane/tests/agents/test_discovery_shadow_dwell.py` | Norns retains shadow observations and Mimir refuses promotion without sufficient, self-consistent, target-matched evidence. No producer stamps operator review outcomes on audit entries yet, so live evidence stays review-empty and therefore ineligible. |
| Long-horizon discovery cycle | not-started | [Loop](../../roadmap/rules-and-detection/rule-catalog-autonomous-discovery.md#loop); [Safety and trust](../../roadmap/rules-and-detection/rule-catalog-autonomous-discovery.md#safety-and-trust) | No production scheduler runs or retains a complete observe-to-integrate cycle. |
| Mixed-model cross-check | not-started | [Loop](../../roadmap/rules-and-detection/rule-catalog-autonomous-discovery.md#loop) | The required independent model-family cross-check is design-only for this discovery loop. |
| Loop throughput metrics | not-started | [Safety and trust](../../roadmap/rules-and-detection/rule-catalog-autonomous-discovery.md#safety-and-trust) | Candidates per cycle, gate pass rate, override-trigger rate, and retirement rate are not measured. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Complete the scheduled loop, shadow evidence, override intake, and mixed-model gate. |
| 2026-08-15 | in-progress | Implemented per-candidate shadow-dwell retention and the fail-closed threshold gate, and split the former combined scheduler/dwell row. | `current change`; `services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/operational_learning services/core-control-plane/tests/agents` passed (1214 tests). | Scheduler, mixed-model cross-check, loop metrics, and an audit-entry producer for operator review outcomes. |

### Remaining work

- [ ] Implement a bounded scheduler that persists one complete observe, hypothesize, verify, and integrate cycle with replayable identities.
- [x] Retain per-candidate shadow duration, sample size, accuracy, and zero-escape evidence and enforce the configured thresholds, proven by `services/core-control-plane/tests/agents/test_discovery_shadow_dwell.py`.
- [ ] Stamp operator review outcome and policy-escape flags on shadow `object.audit-entry` payloads so retained dwell evidence can reach a non-zero reviewed count; until then every live candidate stays ineligible for lack of reviewed samples.
- [ ] Bind override events and the independent model-family cross-check, then prove disagreement holds for human review.
- [ ] Publish governed cycle throughput, gate pass, override-trigger, and retirement metrics.
