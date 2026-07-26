"""Bounded contributor fanout for Bragi conversational answers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fdai.agents._framework.pantheon import PANTHEON_NAMES
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

AnswerFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_ANSWER_CHARS = 16_000
_IDENTITY_KEYS = ("resource_id", "scope_ref", "id", "correlation_id")
_HIGH_SIGNAL_KEYS = ("state", "status", "verdict", "mode", "health", "outcome")
_MAX_CONFLICTS = 8
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REF_SHA256 = re.compile(r"(?<=:sha256:)[0-9a-f]{64}")


def normalize_responder_answer(
    agent_name: str,
    raw: object,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return one bounded, owner-attributed, sensitivity-screened response."""
    if agent_name not in PANTHEON_NAMES or not isinstance(raw, Mapping):
        return None, "response_invalid"
    primary = raw.get("primary_agent", agent_name)
    if primary != agent_name:
        return None, "owner_mismatch"
    answer = raw.get("answer")
    if answer is not None and (not isinstance(answer, str) or len(answer) > _MAX_ANSWER_CHARS):
        return None, "answer_invalid"
    facts = raw.get("facts")
    safe_facts = dict(facts) if isinstance(facts, Mapping) else {}
    normalized_input = {
        "primary_agent": agent_name,
        "answer": answer,
        "facts": safe_facts,
        "abstain_reason": raw.get("abstain_reason"),
        "conversation_policy": raw.get("conversation_policy"),
        "trace_ref": raw.get("trace_ref"),
    }
    if raw.get("requires_typed_pipeline") is True:
        normalized_input["requires_typed_pipeline"] = True
    try:
        encoded = json.dumps(
            normalized_input,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None, "response_invalid"
    if len(encoded) > _MAX_RESPONSE_BYTES:
        return None, "response_too_large"
    sensitivity_input = json.dumps(
        _mask_structured_digests(normalized_input),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if scan_text(sensitivity_input):
        return None, "sensitive_output"
    normalized = json.loads(encoded)
    return (
        (dict(normalized), None) if isinstance(normalized, Mapping) else (None, "response_invalid")
    )


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
            raw_result = await asyncio.wait_for(
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
        result, normalization_error = normalize_responder_answer(agent_name, raw_result)
        return agent_name, result, normalization_error

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
            evidence_refs = _evidence_refs(facts)
            contribution = {
                "agent": agent_name,
                "answer": result["answer"],
                "facts": dict(facts) if isinstance(facts, dict) else {},
            }
            if evidence_refs:
                contribution["evidence_refs"] = evidence_refs
            answers.append(contribution)
    return answers, errors


def evidence_conflicts(
    primary_agent: str,
    primary: Mapping[str, Any],
    contributors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return bounded conflicts for equal identities and high-signal fields."""
    rows = [(primary_agent, primary.get("facts"))] + [
        (str(item.get("agent") or ""), item.get("facts")) for item in contributors
    ]
    conflicts: list[dict[str, str]] = []
    for left_index, (left_agent, left_raw) in enumerate(rows):
        if not isinstance(left_raw, Mapping):
            continue
        for right_agent, right_raw in rows[left_index + 1 :]:
            if not isinstance(right_raw, Mapping):
                continue
            identity = next(
                (
                    str(left_raw[key])
                    for key in _IDENTITY_KEYS
                    if key in left_raw and left_raw.get(key) == right_raw.get(key)
                ),
                None,
            )
            if identity is None:
                continue
            for key in _HIGH_SIGNAL_KEYS:
                left_value = left_raw.get(key)
                right_value = right_raw.get(key)
                if left_value is None or right_value is None or left_value == right_value:
                    continue
                conflicts.append(
                    {
                        "identity": identity,
                        "field": key,
                        "left_agent": left_agent,
                        "right_agent": right_agent,
                    }
                )
                if len(conflicts) >= _MAX_CONFLICTS:
                    return conflicts
    return conflicts


def _evidence_refs(facts: object) -> list[str]:
    if not isinstance(facts, Mapping):
        return []
    raw = facts.get("evidence_refs")
    return [str(item) for item in raw[:20] if str(item)] if isinstance(raw, list | tuple) else []


def _mask_structured_digests(value: object, *, key: str = "") -> object:
    if isinstance(value, Mapping):
        return {
            str(item_key): _mask_structured_digests(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_mask_structured_digests(item, key=key) for item in value]
    if isinstance(value, str):
        if key.endswith("sha256") and _SHA256.fullmatch(value):
            return "<sha256>"
        if key == "evidence_refs":
            return _REF_SHA256.sub("<digest>", value)
    return value


__all__ = [
    "AnswerFn",
    "ask_contributors",
    "evidence_conflicts",
    "introspect_agent",
    "normalize_responder_answer",
]
