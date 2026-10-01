# Ontology Reasoning Result Handles and Continuations implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The [owner design](../../roadmap/interfaces/ontology-reasoning-result-handles.md) was recorded on
2026-10-01 after an independent critique, and its decisions await Owner approval. The shadow
binding core and the exact remaining count of a cut change read exist, as the
[compiler ledger](ontology-reasoning-compiler.md) records. No handle is persisted, no request
carries a reference, and no continuation exists. The open items below moved here from the compiler
ledger with their progress notes; their earlier history stays in that ledger.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| H1 Contracts | implemented | `current change`; [`reasoning_handles.py`](../../../packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py); [`test_reasoning_handles.py`](../../../packages/service-contracts/tests/test_reasoning_handles.py); focused checks: `.venv/bin/python -m pytest -q --no-cov packages/service-contracts/tests/test_reasoning_handles.py`, `.venv/bin/ruff check packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py packages/service-contracts/tests/test_reasoning_handles.py packages/service-contracts/src/fdai_service_contracts/__init__.py`, `.venv/bin/ruff format --check packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py packages/service-contracts/tests/test_reasoning_handles.py packages/service-contracts/src/fdai_service_contracts/__init__.py`, `.venv/bin/python -m mypy packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py` | Versioned handle, evidence manifest, aggregate and typed-path pushdown, and continuation records with rollout-safe N/N-1 version rules; contracts only, with no Core or Operator runtime wiring |
| H2 Handle store | not-started | Design only; the in-process binding core is in [`semantic_reasoning_handles.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_reasoning_handles.py) | Core-owned bodies, opaque Operator references, and the threat review |
| H3 Property follow-ups | not-started | Design only | A property mention domain over reviewed Property semantics |
| H4 Ordinal follow-ups | in-progress | Ordinals bind to the most recent in-process handle in shadow | Binding across turns needs H2 |
| H5 Change continuation | in-progress | The exact remaining count in [`postgres_recent_resource_changes.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_recent_resource_changes.py) | The keyset continuation is not started |
| H6 Successive relation plans | not-started | Design only | Batches with `remaining_batches` and a listed-endpoint digest |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-01 | in-progress | Recorded the design after an independent critique and moved five open items here from the compiler ledger with their progress notes. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-result-handles.md`; `docs/roadmap/interfaces/ontology-reasoning-result-handles-ko.md` | Implement H1, then the H2 threat review. |
| 2026-10-01 | implemented | Implemented H1 Contracts as versioned service-contract models for opaque handle references, Core-only result handles, evidence manifests, aggregate and typed-path pushdown requests, and query continuations with row and batch progress accounts. | `current change`; `packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py`; `packages/service-contracts/src/fdai_service_contracts/__init__.py`; `packages/service-contracts/tests/test_reasoning_handles.py`; focused checks: `.venv/bin/python -m pytest -q --no-cov packages/service-contracts/tests/test_reasoning_handles.py` (pass), `.venv/bin/ruff check packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py packages/service-contracts/tests/test_reasoning_handles.py packages/service-contracts/src/fdai_service_contracts/__init__.py` (pass), `.venv/bin/ruff format --check packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py packages/service-contracts/tests/test_reasoning_handles.py packages/service-contracts/src/fdai_service_contracts/__init__.py` (pass), `.venv/bin/python -m mypy packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py` (pass) | H2 threat review and runtime persistence remain separate work; this change intentionally does not wire Core or Operator behavior. |

### Remaining work

- [x] Finish R1: add the handle, evidence-manifest, and aggregate and path pushdown contracts with
  N/N-1 codec tests. Evidence: `current change`; `packages/service-contracts/src/fdai_service_contracts/reasoning_handles.py`;
  `packages/service-contracts/tests/test_reasoning_handles.py`; focused checks listed in the H1
  scope row pass; no Core or Operator runtime behavior is wired in this package.
- [ ] Persist result handles with the durable Operator turn and carry at most four recent handle
  references in the semantic request contract, with the rendered-order digest, `snapshot_reference`,
  explicit selection of an older handle, and zero cross-conversation bindings in a threat-review test.
- [ ] Read an all-kinds neighbourhood that exceeds one intent graph as bounded successive plans with
  exact accounting and a pinned continuation, never as a decline. Exit: the traced connected-resources
  question lists every reached endpoint with its LinkType across the successive plans.
- [ ] Answer a property of a named resource, such as a storage account SKU, from reviewed Property
  declarations with a property mention domain, and bind ordinal follow-ups to Operator-persisted
  result handles. Exit: the traced ordinal SKU follow-up answers with the exact property value.
- [ ] List the changes a cut `query.recent_resource_changes` window leaves out through a continuation
  pinned to principal, scope, snapshot cutoff, cursor, expiry, and remaining count. Exit: a 24-hour
  window with more than 20 changes lists every change across the continuation with exact accounting.
