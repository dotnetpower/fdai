# Operational diagnostic conversations implementation ledger

This ledger owns delivery status for the bilingual operational diagnostic conversation contract.
It separates coordinating-session reports from retained final-snapshot and interactive evidence.

> **Evidence boundary:** Checkpoint `6ba5c91d3` is already merged into local `main`, followed by the
> latency checkpoints recorded below. The current hardening change is uncommitted and isolated from
> unrelated work. Exact focused results below were run against that
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
| Standard interactive acceptance | in-progress | Warm standard Browser Entra variants: F1 answer TTFT 3.810 seconds, F2 answer TTFT 4.254 seconds, F3 clarification 6.559 seconds, and post-fix F4 clarification 5.800 seconds. | F1 and F2 pass the latency sub-gate only. F1 had no artifact; complete F2 history was not established; F3/F4 lacked exact identities and emitted no answer token. Cold-start semantic-consumer readiness remains open. |
| Formal critique and hardening | implemented | `current change`; R01-R26 below; the latest 238 focused cases, targeted Ruff, and strict mypy passed | Eleven additional Medium findings were fixed in R13-R26. No unresolved Medium-or-higher finding is known in the edited component paths. Interactive acceptance gaps remain explicit. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-06 | in-progress | Adopted the four-family contract and this ledger without reconstructing earlier provenance or commits. Recorded reported component progress separately from unsuccessful interactive observations. | `current change`; `docs/roadmap/interfaces/operational-diagnostic-conversations.md` and `operational-diagnostic-conversations-ko.md`; source locations and bounded reported outcomes in the scope table. This documentation task ran no executable checks. | Close scope and compound-wiring gaps, retain exact final-snapshot evidence, obtain accepted interactive answers/artifact, and complete at least 10 formal rounds. |
| 2026-09-07 | implemented | Revalidated the merged checkpoint, completed R01-R12, added all six APIM gateway/backend status observations, removed provider response bodies from Metrics API errors, bypassed adaptive planning for explicit operational turns, and separated known operational framing into a 2,173-character prompt with a 64 KiB complete-request ceiling. | `current change`; 43 hardening cases, 137 gateway/metric tests, 1,237 final component tests, Console typecheck, targeted Ruff, and strict mypy passed. | Retain successful standard interactive evidence for all four families and the F1 download. |
| 2026-09-07 | implemented | Held configuration and gateway comparisons for exact Resource identity before frame planning when typed judgment supplied no source-grounded Resource name or id. | `current change`; 210 focused semantic planning tests, targeted Ruff, and strict mypy passed. | Re-run F2-F4 with exact deployment or gateway identity and retain the 5-second TTFT result. |
| 2026-09-07 | implemented | Built the exact-target one-hour F2 configuration frame directly from accepted typed judgment instead of allowing the frame model to degrade it to a generic property listing. | `current change`; 176 focused semantic planning tests, targeted Ruff, and strict mypy passed. | Retain an F2 standard-stack receipt with complete configuration history and answer TTFT at or below 5 seconds. |
| 2026-09-07 | implemented | Added a provenance-bound operational-family proposal to compact preflight and reused it as candidate-only judgment for verified F1-F4 requests, removing one serial model call. Added fail-closed confidence, context, family-shape, source-span, one-hour, and Resource identity checks. | `current change`; 177 conversation, prompt-registry, and adapter tests passed with targeted Ruff and strict mypy. | Restart the standard local Core and retain authenticated F1-F4 answer-token TTFT, evidence, and artifact outcomes. |
| 2026-09-07 | implemented | Corrected live-model source-span and canonical-identity assumptions. A mismatched offset is repaired only for one unique exact value in the current utterance, and F2 ARM IDs remain unsupported instead of being queried as names. | `current change`; 179 focused tests passed with targeted Ruff and strict mypy. Standard Browser Entra traces reproduced the pre-fix fallback. | Restart Core and verify that a new exact F2 variant omits the full semantic-judgment call and meets the 5-second answer-token gate. |
| 2026-09-07 | in-progress | Batched local PLAINTEXT consumer commits, compressed preflight while retaining exact schema field names, blocked generic product labels as exact identities, and terminated ambiguous targetless gateway judgments before frame-model I/O. | `current change`; 238 focused tests, targeted Ruff, and strict mypy passed. Warm Browser Entra F1/F2 TTFT passed at 3.810/4.254 seconds; F3/F4 returned no-read clarification. | Deliver the F1 artifact, retain complete F2 history, test exact F3/F4 targets, and make Core readiness wait for the semantic logical consumer rather than preceding it by about 28 seconds. |

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
- [x] Completed R01-R26 below and fixed all accepted Medium findings in the edited component paths.
- [ ] Before claiming all gaps closed, confirm every family meets its contract, all accepted
  findings are resolved, and final-snapshot and standard interactive evidence are retained.

## Formal critique and hardening rounds

R01-R12 reviewed checkpoint `6ba5c91d3` plus its isolated hardening change. R01-R10 used
one exact 43-case pytest invocation and passed in 0.69 seconds. R11 used 41 prompt/composition cases
and a bounded live Core startup. R13-R22 reviewed the preflight judgment reuse change and concluded
with 177 focused cases, targeted Ruff, and strict mypy. R23 used retained standard Browser Entra
trace structure and concluded with 179 focused cases. R24-R26 combined code tracing with standard
Browser Entra variations and concluded with 238 focused cases.

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
| R13 | A low-confidence family proposal might be treated as accepted operational meaning. **Medium confirmed.** | Required confidence of at least 0.90 before promotion. | Low-confidence negative case passed in the 177-test slice. | Live confidence distribution remains unmeasured. |
| R14 | A context-dependent or mixed proposal might skip the full judgment needed to resolve prior meaning. **Medium confirmed.** | Restricted promotion to explicit, context-independent requests. | Schema and promotion negative paths passed. | Contextual requests still pay for full judgment by design. |
| R15 | A family label with missing or extra targets and facets might silently drop requested meaning. **Medium confirmed.** | Added exact inventory, configuration, and gateway target/facet shapes with reviewed allowlists. | Family-shape and planner cases passed. | Unsupported facets use full judgment. |
| R16 | Reused meaning might bypass the principal capability manifest or ordinary plan verifier. No defect was reproduced. | Rejected after tracing promotion through descriptor selection, manifest-owned declarations, deterministic frame checks, and the existing verifier. | Inventory integration test fails if full judgment runs and still produces the verified server-owned plan. | Standard interactive principal receipt remains open. |
| R17 | Arbitrary text such as "last day" might be labeled `duration.PT1H`. **Medium confirmed.** | Required an exact source span and a deterministic supported one-hour expression before accepting the typed canonical duration. | False-canonicalization case passed. | Other intervals use full judgment. |
| R18 | A stale or constructed preflight result might be reused for another utterance. **Medium confirmed.** | Bound successful results to input, proposal, model-config, and prompt digests and rechecked them before promotion. | Stale-input and changed-proposal cases passed. | Runtime receipt retention remains part of interactive evidence. |
| R19 | An ARM resource ID might be passed to the F2 compiler as `Resource.name`. **Medium confirmed.** | Required `Resource.name` for F2; gateway diagnostics retain explicit `Resource.name` or `Resource.id`. | Canonical target checks and configuration planner tests passed. | F2 ID support requires an explicit compiler extension. |
| R20 | The expanded compact prompt might erase the model-call latency gain. No defect was reproduced. | Retained the complete prompt and generated schema at about 1.5K estimated tokens, below the removed full judgment prompt alone. | Prompt-registry and adapter tests passed; local size measurement recorded. | Standard answer-token TTFT remains open. |
| R21 | Prompt v2 might regress v1 social ambiguity rules. **Medium confirmed.** | Restored conversation-interface, acknowledgement, quoted-social, and uncertainty rules in compact form. | Prompt registry and conversation preflight cases passed. | Live multilingual variation remains open. |
| R22 | Normalizing full and preflight judgments might reject a valid accepted test boundary. A compatibility defect was reproduced in focused tests, but no production enum path was affected. | Preserved the boundary's explicit `accepted` decision instead of inferring it from a synthetic receipt. | All 177 focused cases passed after the fix. | No Medium-or-higher blocker remains from this round. |
| R23 | Live preflight might classify F2 but still miss promotion. **Medium confirmed:** the model returned one-based-like offsets and a canonical resource value rather than a property field, so every observed request paid for full judgment. | Corrected only one uniquely occurring model-proposed value to its exact zero-based span, clarified the prompt contract, and rejected F2 ARM IDs by source value rather than misusing `canonical_value`. | Standard Browser Entra traces reproduced both mismatches; 179 focused cases, targeted Ruff, and strict mypy passed. | Re-measure the restarted standard stack; no latency pass is claimed yet. |
| R24 | Multiplexed local Kafka catch-up might pay one broker commit per unrelated physical event. **Medium confirmed in code:** PLAINTEXT committed every event while SASL used the declared record/time batch. | Applied the existing bounded batch policy to PLAINTEXT and preserved no-commit redelivery when processing closes early. | Event Bus and multiplex tests passed in the 238-case final slice. | Batching did not resolve the separate 28-second delayed semantic-consumer startup. |
| R25 | Prompt compression might trigger schema repair and erase the latency gain. **Medium confirmed live:** abbreviated `targets` and `facets` produced two preflight calls and 7.404-second TTFT. | Restored exact schema field names in a 2,615-character, about 654-token prompt body. | Prompt tests passed; warm F2 used one preflight call and emitted its answer token in 4.254 seconds. | Retain a larger bilingual latency cohort. |
| R26 | Generic product words might be accepted as exact gateway, backend, and model identities. **Medium confirmed live:** APIM/backend/GPT were promoted and caused a 38.5-second frame path. | Rejected reviewed generic category labels in preflight and pre-frame checks; ambiguous or targetless gateway judgments now return `resource_identity` clarification before frame/provider I/O. | Two new negative cases passed; post-fix F4 trace contained preflight and judgment only, no frame call or read. | Exact-target F3/F4 evidence remains unvalidated. |

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
