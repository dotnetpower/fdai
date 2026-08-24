# Evolving System Prompt implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Catalog registry, composer, tools, and runtime skills | implemented | [`test_composer.py`](../../../services/core-control-plane/tests/core/prompts/test_composer.py) | Catalog loading, deterministic layer assembly, tool manifests, skills, canaries, and startup fallback have focused coverage. |
| Approved external skill-source fetch | implemented | [`skill_source.py`](../../../services/core-control-plane/src/fdai/delivery/github/skill_source.py); [`test_skill_source.py`](../../../services/core-control-plane/tests/delivery/github/test_skill_source.py) | The GitHub delivery adapter resolves immutable commits and returns only bounded exact files. Fetch never grants prompt eligibility; quarantine, publisher verification, approval, and disabled-first installation remain authoritative. |
| Operator memory, debate, and QualityGate integration | implemented | [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py), [`test_gate.py`](../../../services/core-control-plane/tests/core/quality_gate/test_gate.py) | Bounded memory and one-round Critic/Judge debate feed the deterministic verifier without granting authority. |
| Reviewed web search and core T2 prompt integration | in-progress | [`test_web_search.py`](../../../services/core-control-plane/tests/core/web_search/test_web_search.py), [Wave 5 alpha](../../roadmap/decisioning/prompt-composition.md#wave-5-alpha---what-shipped) | The safe provider seam and reviewed adapter exist, but snippets are not threaded into the core T2 tool manifest. |
| Fork-first second-approval channel | in-progress | [`hil_pipeline.py`](../../../services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py), [`test_hil_pipeline.py`](../../../services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py) | The upstream domain step now proves distinct-principal, no-self-approval, a bounded approval window, and replay: a redelivered approval refuses with `already_materialized` instead of planting a second entry, and an unprovable or expired window never materializes. The channel that invokes it stays fork-first and unbuilt, so the pipeline slice remains disabled. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the former fully-live T2 claim. | `current change`; current source and focused tests listed in the scope table. | Complete core T2 web grounding, second approval, and governed runtime evidence. |
| 2026-08-14 | implemented | Added the bounded GitHub skill-source delivery adapter without changing quarantine, approval, or runtime prompt eligibility. | `current change`; concrete adapter and focused rejection-path tests listed in the scope table. | Compose the scheduled source owner and retain governed refresh, approval, and revocation evidence. |
| 2026-08-14 | implemented | Hardened external source delivery with strict ETag validation and redacted credential-provider failures while preserving quarantine and disabled-first prompt eligibility. | `current change`; focused skill-source adapter tests `28 passed`. | Scheduled composition and governed lifecycle evidence remain open. |
| 2026-08-14 | in-progress | Added the upstream second-approval evidence the fork-first channel depends on: a bounded approval window, a replay-safe entry identity derived from the approval, and exhaustive no-self-approval coverage. | `current change`; [`hil_pipeline.py`](../../../services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py), [`test_hil_pipeline.py`](../../../services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py); focused operator-memory and bridge checks passed 76 cases; strict mypy and task-scoped Ruff passed. | Build the fork-first channel that invokes the materializer, then enable the pipeline slice. |

### Remaining work

- [ ] Thread sanitized, allowlisted web snippets into the core T2 tool manifest with exact source
  receipts, prompt digest replay, and negative injection tests.
- [x] The upstream second-approval step proves distinct-principal, no-self-approval, a bounded
  approval window, and replay: a redelivery refuses with `already_materialized` and materializes
  exactly once.
- [ ] Build the fork-first channel that invokes the second-approval step, then enable that pipeline
  slice.
- [ ] Retain a governed end-to-end T2 receipt proving the composed prompt, debate, citations, final
  verifier result, and zero execution authority on one pinned catalog revision.
