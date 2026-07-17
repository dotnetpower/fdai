"""Bounded contributor fanout for Bragi conversational answers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

AnswerFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


async def introspect_agent(
    responders: dict[str, AnswerFn],
    agent_name: str,
    question: str,
    *,
    requester: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    responder = responders.get(agent_name)
    if responder is None:
        return {
            "primary_agent": agent_name,
            "answer": None,
            "facts": {},
            "abstain_reason": "responder_not_registered",
            "requester": requester,
            "trace_ref": str(context.get("correlation_id") or ""),
        }
    answer = dict(await responder(question, context))
    answer.setdefault("primary_agent", agent_name)
    answer["requester"] = requester
    return answer


async def ask_contributors(
    responders: dict[str, AnswerFn],
    contributors: tuple[str, ...],
    *,
    question: str,
    session_id: str,
    limit: int,
    timeout_seconds: float,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Call bounded secondary responders without risking the primary reply."""

    async def call(agent_name: str) -> tuple[str, dict[str, Any] | None, str | None]:
        responder = responders.get(agent_name)
        if responder is None:
            return agent_name, None, "responder_not_registered"
        try:
            result = await asyncio.wait_for(
                responder(question, {"session_id": session_id, "contributor": True}),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return agent_name, None, "timeout"
        except Exception as exc:  # noqa: BLE001 - isolate one secondary responder
            logger.warning(
                "bragi_contributor_failed",
                extra={"agent": agent_name, "error_type": type(exc).__name__},
            )
            return agent_name, None, "responder_error"
        return agent_name, result, None

    results = await asyncio.gather(*(call(name) for name in contributors[:limit]))
    answers: list[dict[str, Any]] = []
    errors: list[str] = []
    for agent_name, result, error in results:
        if error is not None:
            errors.append(f"{agent_name}:{error}")
        elif not isinstance(result, dict) or not isinstance(result.get("answer"), str):
            errors.append(f"{agent_name}:abstained")
        else:
            facts = result.get("facts")
            answers.append(
                {
                    "agent": agent_name,
                    "answer": result["answer"],
                    "facts": dict(facts) if isinstance(facts, dict) else {},
                }
            )
    return answers, errors


__all__ = ["AnswerFn", "ask_contributors", "introspect_agent"]
