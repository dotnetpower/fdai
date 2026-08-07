"""Recover input content-policy blocks with bounded history reduction."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from fdai.delivery.operator_api.application.conversation.backend import ChatContentPolicyError
from fdai.delivery.operator_api.application.conversation.request_preparation.history import (
    ChatHistoryCompressor,
    ChatHistoryPolicy,
    ResolvedChatHistory,
    compact_history_for_content_policy,
)

AnswerInvoker = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]
StreamInvoker = Callable[[list[dict[str, str]]], AsyncIterator[dict[str, Any]]]
_LOG = logging.getLogger(__name__)


async def answer_with_content_policy_recovery(
    *,
    invoke: AnswerInvoker,
    history: Sequence[dict[str, str]],
    compressor: ChatHistoryCompressor,
    policy: ChatHistoryPolicy,
) -> tuple[dict[str, Any], ResolvedChatHistory | None]:
    """Retry input-policy blocks with less history; never retry output blocks."""

    try:
        return await invoke(list(history)), None
    except ChatContentPolicyError as initial:
        if initial.stage == "output":
            raise
        try:
            async with asyncio.timeout(policy.content_policy_recovery_timeout_seconds):
                return await _recover_answer_after_input_block(
                    invoke=invoke,
                    history=history,
                    compressor=compressor,
                    policy=policy,
                    initial=initial,
                )
        except TimeoutError as exc:
            raise ChatContentPolicyError(stage=initial.stage) from exc


async def _recover_answer_after_input_block(
    *,
    invoke: AnswerInvoker,
    history: Sequence[dict[str, str]],
    compressor: ChatHistoryCompressor,
    policy: ChatHistoryPolicy,
    initial: ChatContentPolicyError,
) -> tuple[dict[str, Any], ResolvedChatHistory | None]:
    compacted = await compact_history_for_content_policy(
        history=history,
        compressor=compressor,
        policy=policy,
    )
    if compacted.messages:
        try:
            reply = await invoke(list(compacted.messages))
            _log_recovery(compacted)
            return reply, compacted
        except ChatContentPolicyError as compacted_error:
            if compacted_error.stage == "output":
                raise
    try:
        reply = await invoke([])
    except ChatContentPolicyError as empty_error:
        stage = empty_error.stage if empty_error.stage != "unknown" else initial.stage
        raise ChatContentPolicyError(stage=stage) from empty_error
    return (
        reply,
        _logged(
            ResolvedChatHistory(
                (),
                "empty",
                omitted_turn_count=len(history),
                content_policy_stage="input",
            )
        ),
    )


async def collect_stream_with_content_policy_recovery(
    *,
    invoke: StreamInvoker,
    history: Sequence[dict[str, str]],
    compressor: ChatHistoryCompressor,
    policy: ChatHistoryPolicy,
) -> tuple[tuple[dict[str, Any], ...], ResolvedChatHistory | None]:
    """Buffer one provider stream until its terminal filter decision is known."""

    async def collect(candidate_history: list[dict[str, str]]) -> tuple[dict[str, Any], ...]:
        return tuple([event async for event in invoke(candidate_history)])

    try:
        return await collect(list(history)), None
    except ChatContentPolicyError as initial:
        if initial.stage == "output":
            raise
        try:
            async with asyncio.timeout(policy.content_policy_recovery_timeout_seconds):
                return await _recover_stream_after_input_block(
                    collect=collect,
                    history=history,
                    compressor=compressor,
                    policy=policy,
                    initial=initial,
                )
        except TimeoutError as exc:
            raise ChatContentPolicyError(stage=initial.stage) from exc


async def _recover_stream_after_input_block(
    *,
    collect: Callable[[list[dict[str, str]]], Awaitable[tuple[dict[str, Any], ...]]],
    history: Sequence[dict[str, str]],
    compressor: ChatHistoryCompressor,
    policy: ChatHistoryPolicy,
    initial: ChatContentPolicyError,
) -> tuple[tuple[dict[str, Any], ...], ResolvedChatHistory | None]:
    compacted = await compact_history_for_content_policy(
        history=history,
        compressor=compressor,
        policy=policy,
    )
    if compacted.messages:
        try:
            events = await collect(list(compacted.messages))
            _log_recovery(compacted)
            return events, compacted
        except ChatContentPolicyError as compacted_error:
            if compacted_error.stage == "output":
                raise
    try:
        events = await collect([])
    except ChatContentPolicyError as empty_error:
        stage = empty_error.stage if empty_error.stage != "unknown" else initial.stage
        raise ChatContentPolicyError(stage=stage) from empty_error
    return (
        events,
        _logged(
            ResolvedChatHistory(
                (),
                "empty",
                omitted_turn_count=len(history),
                content_policy_stage="input",
            )
        ),
    )


def _logged(receipt: ResolvedChatHistory) -> ResolvedChatHistory:
    _log_recovery(receipt)
    return receipt


def _log_recovery(receipt: ResolvedChatHistory) -> None:
    _LOG.info(
        "chat.content_policy_recovery",
        extra={
            "history_mode": receipt.mode,
            "omitted_turn_count": receipt.omitted_turn_count,
            "content_policy_stage": receipt.content_policy_stage,
        },
    )


__all__ = [
    "AnswerInvoker",
    "StreamInvoker",
    "answer_with_content_policy_recovery",
    "collect_stream_with_content_policy_recovery",
]
