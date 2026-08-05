---
title: Operator Console Module Map and Boundaries
translation_of: operator-console-module-map.md
translation_source_sha: 81c684735daa8d97c2460341f3016c41c87e801c
translation_revised: 2026-08-05
---
# Operator Console Module Map and Boundaries

이 문서는 Operator Console conversation module, route, channel 및 provider boundary를 매핑합니다.
Main console contract를 확장하지 않고 source ownership을 찾을 수 있게 유지합니다.

## Core 및 delivery map

- [`src/fdai/core/conversation/`](../../../src/fdai/core/conversation)
  - `coordinator.py`는 Layer 2 `ConversationCoordinator` orchestration을 소유합니다.
  - `tool_arguments.py`는 pure canonical-verb argument parsing을 소유하며 tool authority를 부여하지 않습니다.
  - `read_plan.py`는 bounded-plan validation, serial read execution, result aggregation 및
    identity-scoped high-signal conflict detection을 소유합니다.
  - `contextual_translation.py`는 current/prior turn text의 scalar argument provenance를 소유합니다.
  - `grounded_answer_validation.py`는 narration과 immutable tool authority 사이의 conservative
    canonical-ID, numeric, timestamp, freshness 및 exact-reference check를 소유합니다.
  - `tools.py`는 `SystemConsoleTool`과 Layer 1 module에 delegate하는 implementation을 정의합니다.
  - `narrator.py`는 synchronous intent, contextual, proposal-only read-plan, zero-execution
    clarification 및 presentation-only grounded-answer protocol을 정의합니다.
  - `session.py`는 disposable core/CLI `ConversationSession` projection을 제공합니다. Production
    transcript는 principal-scoped `ConversationHistoryStore`가 소유합니다.
- [`cli/`](../../../cli)
  - `src/repl.ts`는 shared `POST /chat` coordinator용 IME-safe stdin/stdout channel입니다.
  - `src/cockpit.ts`는 self-describing screen snapshot을 같은 coordinator에 publish하는 live SSE
    presentation입니다.
- [`src/fdai/core/conversation/channel_gateway.py`](../../../src/fdai/core/conversation/channel_gateway.py)는
  sender를 인증하고 message idempotency key를 claim하며 coordinator를 호출합니다. Durable delivery가
  구성되면 provider send 전에 complete response를 저장합니다.
- [`src/fdai/delivery/channels/`](../../../src/fdai/delivery/channels)
  - `teams.py`는 bearer-token verification 이후 Bot Framework activity를 normalize하고 injected reply
    publisher를 사용합니다. Payload-supplied reply URL을 신뢰하지 않습니다.
  - `slack.py`는 timestamped signature를 검증하고 replay 또는 bot-authored event를 차단하며 message를
    normalize하고 injected reply publisher를 사용합니다.
  - Slack, Teams 및 web attachment contract는
    [conversation attachment](conversation-attachments-ko.md)를 통해 수렴합니다. Dedicated WebSocket
    adapter는 optional입니다.
- [`chat_current_time.py`](../../../src/fdai/delivery/operator_api/routes/chat_current_time.py)는 injected
  aware clock과 principal IANA timezone에서 current-time 질문을 resolve합니다.

## Operator API route ownership

- `chat_stream_setup.py`는 authenticated request, evidence, history 및 answer-plan validation을 소유합니다.
- `chat_stream_terminal.py`는 pure terminal verification-frame 및 replay-payload assembly를 소유합니다.
- `chat_trajectory_detail.py`는 durable trajectory replay용 bounded final progress projection을 소유합니다.
- `chat_knowledge_context.py`는 state write 없이 exact prior-turn runbook, source freshness, consented
  memory 및 materialized learning을 읽습니다.
- `chat_vision_prompt.py`는 validated image를 projection합니다.
- `chat_verification_text.py`와 `chat_verification_rendering.py`는 terminal integrity와 prose를 소유합니다.
- `read_investigation_responder.py`는 registered Heimdall read intent를 typed evidence에서 렌더링합니다.
  Evidence가 없으면 explicit unavailable answer를 반환합니다. `read_investigation_catalog.py`는 catalog
  ID, ownership 또는 plan binding drift 시 startup을 차단합니다.

영어 및 한국어 presentation literal은 NFC UTF-8을 사용합니다. Escaped Hangul은 정확한 rationale이 있는
code-point behavior에만 허용됩니다. 이 표현은 machine value, evidence authority, locale selection 또는
typed-pipeline decision을 변경하지 않습니다.

Scheduler Runs, Automation Blueprints, Scheduled Continuations,
[관리형 trajectory dataset](governed-trajectory-datasets-ko.md),
[execution backend status](execution-backends-ko.md)는 read-only metadata를 제공합니다. 이 view에는 enable,
submit, retry, cancel, cleanup, execute 또는 approval control이 없습니다. Credential 및 Thor identity를
제외하고 command를 SPA 밖에 유지합니다.

[`tools/chat.py`](../../../tools/chat.py)는 core coordinator용 headless JSONL development harness이며 별도
policy implementation이 아닙니다.

## Boundary invariant

`core/conversation/`은 protocol만 import합니다. Azure SDK, HTTP, Bot Framework 및 provider call은
`delivery/` 아래에 있습니다. Conversation presentation은 execution authority가 되지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Console framing, tool, RBAC 및 safety | [Operator Console](operator-console-ko.md) |
| Runtime model 및 DI seam | [Operator Console runtime model](operator-console-runtime-model-ko.md) |
| Durable channel delivery | [Durable conversation delivery](durable-conversation-delivery-ko.md) |
