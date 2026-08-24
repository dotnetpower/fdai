# Pantheon Conversational Deliberation implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Immutable charters and situational prompt composition | implemented | `services/core-control-plane/src/fdai/agents/_framework/charters.py`, `services/core-control-plane/src/fdai/agents/_framework/conversation_prompt.py`, and the focused prompt composition tests | The server-owned baseline, selected layers, prompt digests, and untrusted-context boundary are deterministic and covered by focused checks. |
| Bounded T1 deliberation and authority isolation | implemented | `services/core-control-plane/src/fdai/agents/_framework/deliberation.py`, `services/core-control-plane/src/fdai/agents/_framework/deliberation_evaluation.py`, `services/core-control-plane/src/fdai/agents/bragi.py`, `services/core-control-plane/src/fdai/agents/_framework/runtime.py`, and `services/core-control-plane/tests/agents/test_prompt_deliberation.py` | Position and critique rounds remain read-only, reject action intent, evaluate bounded high-signal facts, and return presentation-only outcomes. |
| Optional T2 contract and guarded composition seam | implemented | `T2ConversationSynthesizer`, `LlmBindings`, runtime bootstrap wiring, and the focused deliberation and composition binding tests | T2 requests enforce participant identity, prompt provenance, bounded output, budget reservation, pricing, and metering prerequisites. |
| Production invocation and governed runtime validation | in-progress | `services/core-control-plane/src/fdai/runtime/bootstrap.py` forwards an optional binding to `PantheonRuntime`, but no concrete upstream synthesizer, Operator API route, console route, or governed runtime receipt is present. | The tested core can run T1 and a supplied T2 implementation. Repository evidence does not prove a deployed T2 call, live cost charge, or operator-facing invocation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Classified the tested charter, prompt, T1, and guarded T2 seams as implemented without treating deterministic tests as operational validation. | Current change; source listed in the scope table and the focused command below (`6 passed in 0.11s`). | Bind and exercise a concrete metered T2 synthesizer, invoke the discussion path through an approved runtime boundary, and record governed runtime evidence. |
| 2026-08-14 | implemented | Replaced unconditional optional T2 synthesis with deterministic evaluation of bounded T1 answer signals. | `current change`; `deliberation_evaluation.py` and 36 focused deliberation tests prove conflict-free and uncomparable T1 claims make zero T2 calls while a structured conflict makes one bounded call. | Retain governed runtime evidence for both the no-escalation and conflict-escalation branches. |

### Remaining work

- [ ] Bind a concrete `T2ConversationSynthesizer` with `conversation_metering`,
  `conversation_pricing`, and `conversation_t2_model_key` in a deployed composition, then record a
  focused integration result that proves successful synthesis and the exact budget and metering
  charge.
- [ ] Invoke `PantheonRuntime.deliberate` through an approved operator or runtime boundary and
  attach governed runtime evidence that covers conflict-free T1 completion, structured-conflict T2
  use, presentation-only authority, abstention, and provider failure.
