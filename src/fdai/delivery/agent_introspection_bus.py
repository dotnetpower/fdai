"""Bounded event-bus bridge for cross-process agent introspection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fdai.agents import PANTHEON_NAMES, PANTHEON_SPECS, agent_state_evidence_ref
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)

AGENT_INTROSPECTION_REQUEST_TOPIC = "service.agent-introspection.request"
AGENT_INTROSPECTION_RESPONSE_TOPIC = "service.agent-introspection.response"
AGENT_INTROSPECTION_TOPICS = frozenset(
    {AGENT_INTROSPECTION_REQUEST_TOPIC, AGENT_INTROSPECTION_RESPONSE_TOPIC}
)

_WIRE_VERSION = 1
_MAX_ID_CHARS = 128
_MAX_AGENT_CHARS = 64
_MAX_QUESTION_CHARS = 2_000
_MAX_ANSWER_CHARS = 16_000
_MAX_RESULT_BYTES = 64 * 1024
_MAX_CONTRIBUTORS = 8
_MAX_CACHE_ENTRIES = 1_024
_MAX_PENDING_REQUESTS = 256
_DEFAULT_CACHE_TTL_SECONDS = 300.0
_PROBE_INTERVAL_SECONDS = 1.0
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
_AGENT_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_AT_AGENT = re.compile(r"@([A-Za-z][A-Za-z0-9-]*)")
_ASK_AGENT = re.compile(r"\bask\s+([A-Za-z][A-Za-z0-9-]*)\b", re.IGNORECASE)
_EXPECTED_CONVERSATION_POLICY = {spec.name: spec.conversation_policy() for spec in PANTHEON_SPECS}
_SERVER_GROUP_ID = "fdai-agent-introspection-server"


def agent_introspection_server_group_id(
    *,
    local_process: bool,
    process_id: int | None = None,
) -> str:
    """Return a fresh local group while preserving production load balancing."""
    if not local_process:
        return _SERVER_GROUP_ID
    resolved_process_id = os.getpid() if process_id is None else process_id
    if resolved_process_id <= 0:
        raise ValueError("process_id MUST be positive")
    return f"{_SERVER_GROUP_ID}.local-{resolved_process_id}"


class PantheonConversationRuntime(Protocol):
    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        allow_action_proposal: bool,
        materialize_handoff: bool,
    ) -> Any: ...


def _bounded_id(value: object) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= _MAX_ID_CHARS:
        return None
    return value if _SAFE_ID.fullmatch(value) else None


def _salted_ref(salt: str, value: str) -> str:
    return hashlib.sha256(f"{salt}\0{value}".encode()).hexdigest()


def addressed_agent(prompt: str) -> str | None:
    canonical = {name.casefold(): name for name in PANTHEON_NAMES}
    for pattern in (_AT_AGENT, _ASK_AGENT):
        match = pattern.search(prompt)
        if match is not None:
            agent = canonical.get(match.group(1).casefold())
            if agent is not None:
                return agent
    return None


def _target_from_prompt(prompt: str) -> str | None:
    explicit = addressed_agent(prompt)
    if explicit is not None:
        return explicit
    canonical = {name.casefold(): name for name in PANTHEON_NAMES}
    for token in _AGENT_TOKEN.findall(prompt):
        agent = canonical.get(token.casefold())
        if agent is not None:
            return agent
    return None


def _handoff(agent: str, reason: str) -> dict[str, Any]:
    return {
        "primary_agent": "Bragi",
        "answer": None,
        "facts": {},
        "contributors": [],
        "handoff_from": agent,
        "handoff_reason": reason[:128],
    }


def normalize_pantheon_answer(raw: object, *, target_agent: str) -> dict[str, Any] | None:
    """Return a bounded public delegation result from one Pantheon turn answer."""
    if not isinstance(raw, Mapping):
        return None
    primary = raw.get("primary_agent")
    answer = raw.get("answer")
    if not isinstance(primary, str) or primary not in PANTHEON_NAMES:
        return _handoff(target_agent, "agent_response_invalid")
    if not isinstance(answer, str) or not answer.strip():
        reason = raw.get("handoff_reason") or raw.get("abstain_reason")
        handoff_from = raw.get("handoff_from")
        source_agent = (
            handoff_from
            if isinstance(handoff_from, str) and handoff_from in PANTHEON_NAMES
            else primary
        )
        return _handoff(
            source_agent,
            str(reason or "agent_abstained_without_evidence"),
        )
    if len(answer) > _MAX_ANSWER_CHARS:
        return _handoff(target_agent, "agent_response_too_large")
    if primary != target_agent:
        return _handoff(target_agent, "agent_response_owner_mismatch")
    raw_policy = raw.get("conversation_policy")
    expected_policy = _EXPECTED_CONVERSATION_POLICY[target_agent]
    if not isinstance(raw_policy, Mapping) or dict(raw_policy) != expected_policy:
        return _handoff(target_agent, "agent_response_policy_invalid")
    facts = raw.get("facts")
    safe_facts = dict(facts) if isinstance(facts, Mapping) else {}
    refs = safe_facts.get("evidence_refs")
    valid_refs = (
        [ref for ref in refs if isinstance(ref, str) and 0 < len(ref) <= 1_024]
        if isinstance(refs, list | tuple)
        else []
    )
    factual_leaves = {key: value for key, value in safe_facts.items() if key != "evidence_refs"}
    if not valid_refs and not factual_leaves:
        return _handoff(target_agent, "agent_response_evidence_absent")
    if valid_refs:
        safe_facts["evidence_refs"] = valid_refs
    else:
        safe_facts["evidence_refs"] = [agent_state_evidence_ref(target_agent, safe_facts)]
    contributors = raw.get("contributors")
    safe_contributors = (
        [
            item
            for item in contributors[:_MAX_CONTRIBUTORS]
            if isinstance(item, str) and item in PANTHEON_NAMES
        ]
        if isinstance(contributors, list)
        else []
    )
    result: dict[str, Any] = {
        "primary_agent": primary,
        "answer": answer,
        "facts": safe_facts,
        "contributors": safe_contributors,
    }
    result["conversation_policy"] = dict(expected_policy)
    trace_ref = raw.get("trace_ref")
    if isinstance(trace_ref, str) and trace_ref:
        result["trace_ref"] = trace_ref[:256]
    try:
        encoded = json.dumps(result, ensure_ascii=False, default=str).encode()
    except (TypeError, ValueError):
        return _handoff(target_agent, "agent_response_invalid")
    if len(encoded) > _MAX_RESULT_BYTES:
        return _handoff(target_agent, "agent_response_too_large")
    if scan_text(encoded.decode("utf-8")):
        return _handoff(target_agent, "agent_response_sensitive")
    normalized = json.loads(encoded)
    return dict(normalized) if isinstance(normalized, Mapping) else None


@dataclass(slots=True)
class EventBusAgentIntrospectionServer:
    """Consume bounded requests and invoke Bragi's local conversational port."""

    event_bus: EventBus
    runtime: PantheonConversationRuntime
    group_id: str = _SERVER_GROUP_ID
    max_concurrency: int = 16
    cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS
    clock: Callable[[], float] = time.monotonic
    _cache: OrderedDict[str, tuple[str, dict[str, Any], float]] = field(default_factory=OrderedDict)
    _inflight: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _tasks: set[asyncio.Task[None]] = field(default_factory=set)

    async def run(self) -> None:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        _LOGGER.info(
            "agent_introspection_server_started",
            extra={"group_id": self.group_id},
        )
        try:
            async for envelope in self.event_bus.subscribe(
                AGENT_INTROSPECTION_REQUEST_TOPIC,
                self.group_id,
            ):
                task = asyncio.create_task(self._bounded_handle(dict(envelope.payload), semaphore))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
            _LOGGER.info("agent_introspection_server_stopped")

    async def _bounded_handle(
        self,
        payload: Mapping[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            await self.handle_request(payload)

    async def handle_request(self, payload: Mapping[str, Any]) -> None:
        if payload.get("kind") == "probe":
            request_id = _bounded_id(payload.get("request_id"))
            reply_to = _bounded_id(payload.get("reply_to"))
            if (
                payload.get("v") == _WIRE_VERSION
                and request_id is not None
                and reply_to is not None
            ):
                await self.event_bus.publish(
                    AGENT_INTROSPECTION_RESPONSE_TOPIC,
                    request_id,
                    {
                        "v": _WIRE_VERSION,
                        "kind": "probe",
                        "request_id": request_id,
                        "reply_to": reply_to,
                    },
                )
                _LOGGER.info("agent_introspection_server_probe_replied")
            return
        request = _parse_request(payload)
        if request is None:
            _LOGGER.warning("agent_introspection_request_rejected")
            return
        request_id = request["request_id"]
        fingerprint = _request_fingerprint(request)
        owner = False
        response: dict[str, Any] | None = None
        future: asyncio.Future[dict[str, Any]] | None = None
        async with self._lock:
            cached = self._cache.get(request_id)
            if cached is not None:
                cached_fingerprint, cached_response, cached_at = cached
                if self.clock() - cached_at > self.cache_ttl_seconds:
                    self._cache.pop(request_id, None)
                    cached = None
                else:
                    response = (
                        cached_response
                        if cached_fingerprint == fingerprint
                        else _response(
                            request,
                            _handoff(request["target_agent"], "request_id_conflict"),
                        )
                    )
            if cached is None:
                active = self._inflight.get(request_id)
                if active is None:
                    future = asyncio.get_running_loop().create_future()
                    self._inflight[request_id] = (fingerprint, future)
                    owner = True
                else:
                    active_fingerprint, future = active
                    if active_fingerprint != fingerprint:
                        response = _response(
                            request,
                            _handoff(request["target_agent"], "request_id_conflict"),
                        )
                    else:
                        response = None
        if response is None and not owner:
            if future is None:
                return
            response = await future
        elif response is None:
            response = await self._invoke(request)
            async with self._lock:
                self._cache[request_id] = (fingerprint, response, self.clock())
                self._cache.move_to_end(request_id)
                while len(self._cache) > _MAX_CACHE_ENTRIES:
                    self._cache.popitem(last=False)
                pending = self._inflight.pop(request_id, None)
                if pending is not None and not pending[1].done():
                    pending[1].set_result(response)
        await self.event_bus.publish(
            AGENT_INTROSPECTION_RESPONSE_TOPIC,
            request_id,
            response,
        )
        _LOGGER.info(
            "agent_introspection_response_published",
            extra={"target_agent": request["target_agent"]},
        )

    async def _invoke(self, request: dict[str, str]) -> dict[str, Any]:
        target_agent = request["target_agent"]
        try:
            turn = await self.runtime.ask(
                session_id=f"remote-{request['session_ref']}",
                user_id=request["user_ref"],
                question=request["question"],
                allow_action_proposal=False,
                materialize_handoff=False,
            )
            result = normalize_pantheon_answer(
                getattr(turn, "answer", None),
                target_agent=target_agent,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            result = _handoff(target_agent, "agent_conversational_port_error")
        return _response(
            request,
            result or _handoff(target_agent, "agent_abstained_without_evidence"),
        )


def _request_fingerprint(request: Mapping[str, str]) -> str:
    canonical = "\0".join(
        request[field]
        for field in ("reply_to", "target_agent", "question", "user_ref", "session_ref")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _response(request: Mapping[str, str], result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "v": _WIRE_VERSION,
        "kind": "response",
        "request_id": request["request_id"],
        "reply_to": request["reply_to"],
        "result": dict(result),
    }


def _parse_request(payload: Mapping[str, Any]) -> dict[str, str] | None:
    request_id = _bounded_id(payload.get("request_id"))
    reply_to = _bounded_id(payload.get("reply_to"))
    target_agent = payload.get("target_agent")
    question = payload.get("question")
    user_ref = payload.get("user_ref")
    session_ref = payload.get("session_ref")
    if (
        payload.get("v") != _WIRE_VERSION
        or request_id is None
        or reply_to is None
        or not isinstance(target_agent, str)
        or target_agent not in PANTHEON_NAMES
        or not isinstance(question, str)
        or not 1 <= len(question) <= _MAX_QUESTION_CHARS
        or not isinstance(user_ref, str)
        or not re.fullmatch(r"[0-9a-f]{64}", user_ref)
        or not isinstance(session_ref, str)
        or not re.fullmatch(r"[0-9a-f]{64}", session_ref)
    ):
        return None
    return {
        "request_id": request_id,
        "reply_to": reply_to,
        "target_agent": target_agent,
        "question": question,
        "user_ref": user_ref,
        "session_ref": session_ref,
    }


@dataclass(slots=True)
class EventBusAgentIntrospectionClient:
    """Read API adapter that correlates bounded agent-introspection replies."""

    event_bus: EventBus
    instance_id: str
    startup_timeout_seconds: float = 20.0
    response_timeout_seconds: float = 20.0
    max_pending_requests: int = _MAX_PENDING_REQUESTS
    fallback_delegate: Any = None
    _consumer_task: asyncio.Task[None] | None = None
    _ready: asyncio.Event = field(default_factory=asyncio.Event)
    _pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _privacy_salt: str = field(default_factory=lambda: uuid.uuid4().hex)

    async def start(self) -> None:
        async with self._start_lock:
            if self._consumer_task is not None and not self._consumer_task.done():
                if self._ready.is_set():
                    return
            else:
                self._ready.clear()
                self._consumer_task = asyncio.create_task(
                    self._consume(),
                    name=f"agent-introspection-client:{self.instance_id}",
                )
            deadline = time.monotonic() + self.startup_timeout_seconds
            probe_id = f"probe-{uuid.uuid4().hex}"
            while not self._ready.is_set() and time.monotonic() < deadline:
                await self.event_bus.publish(
                    AGENT_INTROSPECTION_REQUEST_TOPIC,
                    probe_id,
                    {
                        "v": _WIRE_VERSION,
                        "kind": "probe",
                        "request_id": probe_id,
                        "reply_to": self.instance_id,
                    },
                )
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    await asyncio.wait_for(
                        self._ready.wait(),
                        timeout=min(_PROBE_INTERVAL_SECONDS, remaining),
                    )
                except TimeoutError:
                    continue
            if self._ready.is_set():
                _LOGGER.info("agent_introspection_client_ready")
            else:
                _LOGGER.warning("agent_introspection_client_startup_unavailable")

    async def stop(self) -> None:
        task = self._consumer_task
        self._consumer_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._ready.clear()

    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        target_agent = _target_from_prompt(prompt)
        if target_agent is None:
            fallback = getattr(self.fallback_delegate, "delegate", None)
            if callable(fallback):
                fallback_result = await fallback(
                    prompt=prompt,
                    user_id=user_id,
                    session_id=session_id,
                )
                return dict(fallback_result) if isinstance(fallback_result, Mapping) else None
            return None
        if len(prompt) > _MAX_QUESTION_CHARS:
            return _handoff(target_agent, "agent_question_too_long")
        if self._consumer_task is None or self._consumer_task.done() or not self._ready.is_set():
            await self.start()
        if not self._ready.is_set():
            return _handoff(target_agent, "agent_conversational_port_unavailable")
        if len(self._pending) >= self.max_pending_requests:
            return _handoff(target_agent, "agent_request_capacity_exceeded")
        request_id = f"request-{uuid.uuid4().hex}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.event_bus.publish(
                AGENT_INTROSPECTION_REQUEST_TOPIC,
                request_id,
                {
                    "v": _WIRE_VERSION,
                    "request_id": request_id,
                    "reply_to": self.instance_id,
                    "target_agent": target_agent,
                    "question": prompt,
                    "user_ref": _salted_ref(self._privacy_salt, user_id),
                    "session_ref": _salted_ref(
                        self._privacy_salt,
                        f"{user_id}\0{session_id}",
                    ),
                },
            )
            response = await asyncio.wait_for(future, timeout=self.response_timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            return _handoff(target_agent, "agent_conversational_port_unavailable")
        finally:
            self._pending.pop(request_id, None)
        result = response.get("result")
        return normalize_pantheon_answer(
            result,
            target_agent=target_agent,
        )

    def should_delegate(self, prompt: str, view_context: dict[str, Any]) -> bool:
        fallback = getattr(self.fallback_delegate, "should_delegate", None)
        if callable(fallback):
            return bool(fallback(prompt, view_context))
        return True

    async def delegate_with_progress(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        progress_observer: Any,
    ) -> dict[str, Any] | None:
        if _target_from_prompt(prompt) is not None:
            return await self.delegate(prompt=prompt, user_id=user_id, session_id=session_id)
        fallback = getattr(self.fallback_delegate, "delegate_with_progress", None)
        if callable(fallback):
            fallback_result = await fallback(
                prompt=prompt,
                user_id=user_id,
                session_id=session_id,
                progress_observer=progress_observer,
            )
            return dict(fallback_result) if isinstance(fallback_result, Mapping) else None
        return await self.delegate(prompt=prompt, user_id=user_id, session_id=session_id)

    async def _consume(self) -> None:
        group_id = f"fdai-agent-introspection-client.{self.instance_id}"
        async for envelope in self.event_bus.subscribe(
            AGENT_INTROSPECTION_RESPONSE_TOPIC,
            group_id,
        ):
            payload = envelope.payload
            if payload.get("reply_to") != self.instance_id or payload.get("v") != _WIRE_VERSION:
                continue
            if payload.get("kind") == "probe":
                self._ready.set()
                _LOGGER.info("agent_introspection_client_probe_received")
                continue
            request_id = _bounded_id(payload.get("request_id"))
            if request_id is None:
                continue
            future = self._pending.get(request_id)
            if future is not None and not future.done():
                future.set_result(dict(payload))


__all__ = [
    "AGENT_INTROSPECTION_REQUEST_TOPIC",
    "AGENT_INTROSPECTION_RESPONSE_TOPIC",
    "AGENT_INTROSPECTION_TOPICS",
    "EventBusAgentIntrospectionClient",
    "EventBusAgentIntrospectionServer",
    "addressed_agent",
    "agent_introspection_server_group_id",
    "normalize_pantheon_answer",
]
