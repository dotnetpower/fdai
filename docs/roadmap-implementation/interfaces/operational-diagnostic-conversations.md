# Operational diagnostic conversations implementation ledger

This ledger owns delivery status for the bilingual operational diagnostic conversation contract.
It separates coordinating-session reports from retained final-snapshot and interactive evidence.

> **Evidence boundary:** The implementation checkpoint is `6ba5c91d3`. The current hardening change
> is uncommitted and isolated from unrelated work. Exact focused results below were run against that
> working tree and use `current change` rather than a guessed commit. Component checks do not certify
> the standard interactive runtime or provider evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Four-family acceptance contract | not-applicable | `current change`; bilingual [design owner](../../roadmap/interfaces/operational-diagnostic-conversations.md) | Design-only acceptance, paraphrases, boundaries, and gap coverage; not executable completion. |
| Fresh inventory document component | implemented | `current change`; 1,237 focused component tests and the R01-R10 43-case matrix passed | Principal binding, complete and empty rows, row limits, and same-turn artifact source passed component checks. Interactive acceptance remains open. |
| Native metric concepts | implemented | `current change`; 137 gateway/metric tests and the final 1,237-test component slice passed | APIM gateway and backend `429`, `500`, and `503` remain distinct. Counts overlap and are not additive. |
| Scoped configuration comparison | implemented | `current change`; source-isolation, time-boundary, capacity-semantics, and configuration-plan cases in the 43-case matrix and final component slice | Values, object scope, history references, and aggregate provenance remain filtered before presentation. Interactive history evidence remains open. |
| Compound gateway metric/configuration wiring | implemented | `current change`; gateway compiler, reducer, APIM status, deadline, and scoped configuration tests in the 742-test slice | Component composition is complete. Standard interactive metric and configuration evidence remains open. |
| Standard interactive acceptance | in-progress | Reported document request: action draft, no artifact, about 39.9 seconds. Reported gateway question: held with `semantic_frame_unavailable`. | Neither observation is an answer-quality pass; no successful interactive evidence is claimed for any of the four families. |
| Formal critique and hardening | implemented | `current change`; R01-R12 below; 43 focused cases and 1,237 expanded component cases passed | Four Medium findings were fixed. No unresolved Medium-or-higher component finding was confirmed. Interactive gaps remain outside this claim. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-06 | in-progress | Adopted the four-family contract and this ledger without reconstructing earlier provenance or commits. Recorded reported component progress separately from unsuccessful interactive observations. | `current change`; `docs/roadmap/interfaces/operational-diagnostic-conversations.md` and `operational-diagnostic-conversations-ko.md`; source locations and bounded reported outcomes in the scope table. This documentation task ran no executable checks. | Close scope and compound-wiring gaps, retain exact final-snapshot evidence, obtain accepted interactive answers/artifact, and complete at least 10 formal rounds. |
| 2026-09-07 | implemented | Revalidated the merged checkpoint, completed R01-R12, added all six APIM gateway/backend status observations, removed provider response bodies from Metrics API errors, bypassed adaptive planning for explicit operational turns, and separated known operational framing into a 2,173-character prompt with a 64 KiB complete-request ceiling. | `current change`; 43 hardening cases, 137 gateway/metric tests, 1,237 final component tests, Console typecheck, targeted Ruff, and strict mypy passed. | Retain successful standard interactive evidence for all four families and the F1 download. |
| 2026-09-07 | implemented | Held configuration and gateway comparisons for exact Resource identity before frame planning when typed judgment supplied no source-grounded Resource name or id. | `current change`; 210 focused semantic planning tests, targeted Ruff, and strict mypy passed. | Re-run F2-F4 with exact deployment or gateway identity and retain the 5-second TTFT result. |

### Remaining work

- [x] Retained a final working-tree result for current-turn/principal document binding, complete and
  zero-row export, and row limits in the 43-case matrix and 1,237-test component slice.
- [x] Retained a final working-tree native-metric result: 137 gateway/metric tests passed, followed
  by the 1,237-test component slice. These overlapping results are not added together.
- [x] Verified configuration scope filtering for unrelated identities, provider payloads, history
  references, and aggregate provenance in the hardening matrix and final component slice.
- [x] Verified component wiring for independently attributed metrics and scoped configuration
  outputs, including all APIM gateway/backend status combinations.
- [ ] Retain standard interactive receipts for each family's canonical request and three generic
  paraphrases in English and Korean. Record exact scope/time, terminal state, goal coverage,
  evidence completeness, latency, and F1 artifact retrieval. Resolve the observed document action
  draft and gateway semantic-frame hold; do not infer a pass from component checks.
- [ ] Retain safe negative outcomes for ambiguity, missing/denied evidence, pagination limits,
  stale history, unavailable metric dimensions, zero versus no samples, and no-mutation boundaries.
- [x] Completed R01-R11 below and fixed all three accepted Medium findings.
- [ ] Before claiming all gaps closed, confirm every family meets its contract, all accepted
  findings are resolved, and final-snapshot and standard interactive evidence are retained.

## Formal critique and hardening rounds

Each round reviewed checkpoint `6ba5c91d3` plus the current isolated hardening change. R01-R10 used
one exact 43-case pytest invocation and passed in 0.69 seconds. R11 used 41 prompt/composition cases
and a bounded live Core startup.

| Round | Hypothesis and result | Resolution | Focused evidence | Remaining blocker |
|-------|-----------------------|------------|------------------|-------------------|
| R01 | Unselected objects or global history references might survive scoped configuration projection. No defect was reproduced. | Rejected after tracing issued scope through snapshot and comparison output. | `test_scoped_source_never_returns_unselected_facts_payloads_or_global_refs` passed. | Standard interactive principal receipt remains open. |
| R02 | Paraphrases might route by wording or drop typed meaning. No component defect was reproduced. | Rejected; English/Korean inventory, gateway, and configuration variants produced the same typed plans or safe holds. | Inventory, gateway-plan, and configuration-plan parametrized cases passed. | Live model variation evidence remains open. |
| R03 | Unequal, future, naive, or uncovered history windows might appear comparable. No defect was reproduced. | Rejected; aware, ordered, equal-duration, bounded windows and explicit missing baselines remained enforced. | Configuration time-boundary and gateway-window cases passed. | Provider history availability remains open. |
| R04 | Capacity units might be converted to TPM or conflated with consumed tokens. No defect was reproduced. | Rejected; desired/current capacity, authoritative TPM, and token observations remain distinct. | `test_capacity_drop_preserves_desired_current_and_authoritative_tpm` passed. | Live quota evidence is not supplied by this component. |
| R05 | AppGW total, connect, first-byte, and last-byte semantics might be subtracted or relabeled. No defect was reproduced. | Rejected; native concepts, units, aggregations, and aligned windows remained independent. | `test_gateway_profiles_use_verified_type_and_identical_windows` passed. | Live backend metrics remain open. |
| R06 | APIM gateway/backend status attribution might be incomplete. **Medium confirmed:** gateway-side `429` and `503` were omitted. | Added both observations, retained distinct dimensions, and raised the finite maximum from 70 to 74 reads. | New APIM separation and maximum-profile cases passed in the 137-test slice. | Request-level APIM-to-GPT correlation remains unavailable. |
| R07 | Pagination, duplicate, row, column, byte, or empty-result limits might still permit a complete document claim. No defect was reproduced. | Rejected; incomplete sources and exceeded bounds prevent artifact materialization. | Complete bounded inventory cases passed for 0, 41, 120, and 1000 rows. | Standard interactive download remains open. |
| R08 | Missing data might become zero, and provider errors might disclose payload details. **Medium confirmed:** Metrics API errors included a bounded response-body snippet. | Removed response content from the error while retaining HTTP status and metric identity; zero/missing behavior was unchanged. | Missing/mismatched, observed-zero, and redacted HTTP-error cases passed. | Provider-side missing dimensions remain runtime evidence. |
| R09 | A fresh inventory artifact might reuse another request or principal. No defect was reproduced. | Rejected; same-turn request identity and principal-scoped replay remain mandatory. | Foreign-source rejection and current-answer artifact cases passed. | Standard interactive retrieval remains open. |
| R10 | Compound reads might overclaim causation, mutate state, retry, or leak pending work after deadlines. No defect was reproduced. | Rejected; outputs retain `execution_authority=false`, no causal support, finite concurrency, and cancellation. | Gateway deadline and no-retry cases passed. | Standard interactive compound answers remain open. |
| R11 | The final runtime composition might reject the newly governed prompts despite component tests. **Medium confirmed:** the 32,865-character frame prompt exceeded the 32,768-character adapter limit and disabled operational semantic composition. | Restored immutable v40, allowed its exact legacy size under a 33,000-character ceiling, and added a 2,173-character prompt selected only for accepted operational families. | Prompt selection, request-budget, and scenario cases passed. | The already-running standard Core has not been restarted; standard browser validation remains open. |
| R12 | First-turn operational requests might pay for adaptive explanation planning and then send the complete 308-descriptor manifest to frame planning. **Medium confirmed:** live evidence showed 11-16 seconds in adaptive planning and a 248,854-byte complete descriptor payload. | Run compact preflight on the first turn, bypass adaptive planning for explicit/contextual operational signals, then narrow F1/F2/F3-F4 to 1/3/5 descriptors and the compact operational frame prompt. | 1,237 expanded component tests, targeted Ruff, and strict mypy passed. | Standard-stack TTFT and transport qualification remain open. |

R01-R10 do not authorize live mutations. Authorized live reads and model questions remain bounded;
TPM reduction and chaos injection remain outside scope. Stop the attempt on unexpected model
fallback, HTTP `429`/`503`, provider timeout, or deadline expiry.

## Documentation handoff

Only this ledger and the bilingual design owner belong to this documentation change. Existing
implementation edits remain untouched. Refresh only the owned translation:

```bash
python3 scripts/quality/localization/refresh-translation-sha.py \
  docs/roadmap/interfaces/operational-diagnostic-conversations-ko.md
```

Suggested narrow translation review command for the coordinating session; **not run here**:

```bash
python3 scripts/quality/localization/check-translation-quality.py \
  docs/roadmap/interfaces/operational-diagnostic-conversations-ko.md
```

## Related docs

| To learn about | Read |
|----------------|------|
| Acceptance contract | [Operational diagnostic conversations](../../roadmap/interfaces/operational-diagnostic-conversations.md) |
| Korean contract | [Operational diagnostic conversations (Korean)](../../roadmap/interfaces/operational-diagnostic-conversations-ko.md) |
| Existing planner boundary | [Hierarchical conversation planning](../../roadmap/interfaces/hierarchical-conversation-planning.md) |
| Existing document boundary | [Production A3 channel runtime](../../roadmap/interfaces/production-a3-channel-runtime.md) |
