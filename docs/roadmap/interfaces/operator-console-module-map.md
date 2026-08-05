---
title: Operator Console Module Map and Boundaries
---
# Operator Console Module Map and Boundaries

This document maps the Operator Console conversation modules, routes, channels, and provider
boundaries. It keeps source ownership discoverable without expanding the main console contract.

## Core and delivery map

- [`src/fdai/core/conversation/`](../../../src/fdai/core/conversation)
  - `coordinator.py` owns the Layer 2 `ConversationCoordinator` orchestration.
  - `tool_arguments.py` owns pure canonical-verb argument parsing and grants no tool authority.
  - `read_plan.py` owns bounded-plan validation, serial read execution, result aggregation, and
    identity-scoped high-signal conflict detection.
  - `contextual_translation.py` owns scalar argument provenance over current and prior turn text.
  - `grounded_answer_validation.py` owns conservative canonical-ID, numeric, timestamp, freshness,
    and exact-reference checks over narration and immutable tool authority.
  - `tools.py` defines `SystemConsoleTool` and implementations that delegate to Layer 1 modules.
  - `narrator.py` defines synchronous intent, contextual, proposal-only read-plan,
    zero-execution clarification, and presentation-only grounded-answer protocols.
  - `session.py` provides the disposable core/CLI `ConversationSession` projection. The
    principal-scoped `ConversationHistoryStore` owns production transcripts.
- [`cli/`](../../../cli)
  - `src/repl.ts` is the IME-safe stdin/stdout channel for the shared `POST /chat` coordinator.
  - `src/cockpit.ts` is the live SSE presentation that publishes a self-describing screen snapshot
    to the same coordinator.
- [`src/fdai/core/conversation/channel_gateway.py`](../../../src/fdai/core/conversation/channel_gateway.py)
  authenticates senders, claims message idempotency keys, calls the coordinator, and persists the
  complete response before provider send when durable delivery is configured.
- [`src/fdai/delivery/channels/`](../../../src/fdai/delivery/channels)
  - `teams.py` normalizes Bot Framework activities after bearer-token verification and uses an
    injected reply publisher. It never trusts a payload-supplied reply URL.
  - `slack.py` verifies timestamped signatures, rejects replayed or bot-authored events, normalizes
    messages, and uses an injected reply publisher.
  - Slack, Teams, and web attachment contracts converge through
    [conversation attachments](conversation-attachments.md). A dedicated WebSocket adapter remains
    optional.
- [`chat_current_time.py`](../../../src/fdai/delivery/operator_api/routes/chat_current_time.py)
  resolves current-time questions from an injected aware clock and principal IANA timezone.

## Operator API route ownership

- `chat_stream_setup.py` owns authenticated request, evidence, history, and answer-plan validation.
- `chat_stream_terminal.py` owns pure terminal verification-frame and replay-payload assembly.
- `chat_trajectory_detail.py` owns bounded final progress projection for durable trajectory replay.
- `chat_knowledge_context.py` reads exact prior-turn runbooks, source freshness, consented memory,
  and materialized learning without writing state.
- `chat_vision_prompt.py` projects validated images.
- `chat_verification_text.py` and `chat_verification_rendering.py` own terminal integrity and prose.
- `read_investigation_responder.py` renders registered Heimdall read intents from typed evidence.
  Missing evidence produces an explicit unavailable answer. `read_investigation_catalog.py` blocks
  startup when catalog IDs, ownership, or plan bindings drift.

English and Korean presentation literals use NFC UTF-8. Escaped Hangul is accepted only for exact,
rationale-bearing code-point behavior. This representation does not change machine values,
evidence authority, locale selection, or typed-pipeline decisions.

Scheduler Runs, Automation Blueprints, Scheduled Continuations,
[governed trajectory datasets](governed-trajectory-datasets.md), and
[execution backend status](execution-backends.md) expose read-only metadata. These views contain no
enable, submit, retry, cancel, cleanup, execute, or approval controls. They omit credentials and
Thor's identity and keep commands outside the SPA.

[`tools/chat.py`](../../../tools/chat.py) is the headless JSONL development harness for the core
coordinator, not a second policy implementation.

## Boundary invariant

`core/conversation/` imports protocols only. Azure SDK, HTTP, Bot Framework, and provider calls live
under `delivery/`. Conversation presentation never becomes execution authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Console framing, tools, RBAC, and safety | [Operator Console](operator-console.md) |
| Runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Durable channel delivery | [Durable conversation delivery](durable-conversation-delivery.md) |
