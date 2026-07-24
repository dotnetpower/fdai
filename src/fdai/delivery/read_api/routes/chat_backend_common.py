"""Shared contracts and transport helpers for chat backends."""

from __future__ import annotations

import logging
import re
from typing import Any, Final, NoReturn, Protocol

import httpx
from starlette.exceptions import HTTPException

from fdai.core.metering.context import current_invocation_scope
from fdai.core.metering.records import InvocationScope
from fdai.core.metering.usage import TokenUsage
from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE

_LOG = logging.getLogger(__name__)


def _default_chat_http_client() -> httpx.AsyncClient:
    """Build the fallback :class:`httpx.AsyncClient` for chat backends.

    Explicit per-phase timeouts (httpx's global default 5s is too short
    for LLM completion streams) and ``follow_redirects=False`` (an
    OpenAI-compatible endpoint should not silently 3xx to elsewhere).
    Read timeout accommodates reasoning models (gpt-5, o1/o3/o4) that
    can take 60-90s to emit the first token; the streaming route layers
    an SSE heartbeat on top to keep HTTP intermediaries from closing an
    idle connection. Centralised so the two fallback sites in this
    module stay in sync.

    Long-lived-process hardening: a chat backend outlives many idle
    gaps, and Azure OpenAI closes an idle keep-alive connection after
    ~a few minutes. Reusing a server-closed socket surfaces as a
    ``RemoteProtocolError`` that the router scores as a failure, so a
    dev server left running for hours slowly degrades every candidate.
    A bounded ``keepalive_expiry`` recycles idle sockets before the
    server drops them, and transport ``retries`` transparently re-opens
    a connection that was closed underneath a fresh request.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=15.0, pool=5.0),
        follow_redirects=False,
        limits=httpx.Limits(
            max_keepalive_connections=8,
            max_connections=16,
            keepalive_expiry=30.0,
        ),
        transport=httpx.AsyncHTTPTransport(retries=2),
    )


_CONTENT_FILTER_MARKERS: Final[tuple[str, ...]] = (
    "content_filter",
    "responsibleaipolicy",
    "jailbreak",
    "content management policy",
)


_DIRECT_OVERRIDE: Final = re.compile(
    r"\bignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|rules?|system)\b"
    r"|\bdisregard\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|rules?|system)\b"
    "|모든\\s+지시\\s+무시"
    "|이전\\s+지시\\s+무시",
    re.IGNORECASE,
)


def _reject_direct_override(prompt: str) -> None:
    """Block explicit attempts to replace the trusted instruction hierarchy."""

    if _DIRECT_OVERRIDE.search(prompt):
        raise HTTPException(status_code=422, detail="chat request blocked by content policy")


def _raise_upstream_error(status_code: int, body_text: str) -> NoReturn:
    """Map an upstream ``>=400`` to an :class:`HTTPException`.

    A content-policy block (a jailbreak / disallowed prompt the upstream filter
    refused) is distinguished from a genuine upstream fault: the former is
    expected and safe, so it is logged at ``info`` and surfaced as ``422`` with
    a clear reason; the latter stays a ``502`` outage. Either way the deck falls
    back to its deterministic answerer, so the operator is never left blank -
    the distinction is for honest telemetry and messaging, not control flow.
    """
    snippet = body_text[:200]
    if status_code == 400 and any(m in snippet.lower() for m in _CONTENT_FILTER_MARKERS):
        _LOG.info("chat request blocked by upstream content policy")
        raise HTTPException(status_code=422, detail="chat request blocked by content policy")
    _LOG.warning("chat backend upstream returned %s (body=%s)", status_code, snippet)
    raise HTTPException(status_code=502, detail="chat upstream error")


class ChatBackend(Protocol):
    """Async chat backend seam.

    The backend receives the user's prompt, the current view context
    (arbitrary JSON), and a short conversation history. It returns a
    payload that MUST include ``answer`` (str) and ``model`` (str); it
    MAY include additional JSON-safe fields (e.g. ``router`` metadata
    from :class:`LatencyRoutedChatBackend`).
    """

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]: ...


class ChatBackendUnavailableError(Exception):
    """Raised by a backend when no upstream LLM is configured."""


class DisabledChatBackend:
    """No-op backend that always raises. Wired when no LLM env is set."""

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002 - required by Protocol
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        raise ChatBackendUnavailableError("no chat backend configured")


_COMPLETION_TOKEN_PARAM_MODELS: Final[tuple[str, ...]] = ("gpt-5", "o1", "o3", "o4")


def _completion_body_params(model: str, *, temperature: float, max_tokens: int) -> dict[str, Any]:
    """Build the token/temperature fields for a chat-completions body.

    Returns ``{"max_completion_tokens": N}`` for models that require it
    (gpt-5*, o-series reasoning) - which also reject a custom ``temperature`` -
    and the legacy ``{"temperature": t, "max_tokens": N}`` for classic chat
    models (gpt-4o*, gpt-4.1*).
    """
    normalized_model = model.lower().removeprefix("narrator-")
    if normalized_model.startswith(_COMPLETION_TOKEN_PARAM_MODELS):
        return {"max_completion_tokens": max_tokens}
    return {"temperature": temperature, "max_tokens": max_tokens}


_COGNITIVE_SCOPE: Final[str] = COGNITIVE_SERVICES_SCOPE


def _usage_summary(raw: Any) -> dict[str, int] | None:
    """Normalise an OpenAI/Azure ``usage`` block to prompt/completion/total ints.

    Returns ``None`` when no token counts are present, so callers can omit the
    field entirely rather than reporting zeros.
    """
    if not isinstance(raw, dict):
        return None

    def _count(key: str) -> int | None:
        value = raw.get(key)
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    prompt = _count("prompt_tokens")
    completion = _count("completion_tokens")
    total = _count("total_tokens")
    if prompt is None and completion is None and total is None:
        return None
    out: dict[str, int] = {}
    if prompt is not None:
        out["prompt_tokens"] = prompt
    if completion is not None:
        out["completion_tokens"] = completion
    if total is not None:
        out["total_tokens"] = total
    elif prompt is not None and completion is not None:
        out["total_tokens"] = prompt + completion
    return out


def _token_usage(summary: dict[str, int] | None) -> TokenUsage | None:
    """Return a measured token value when both provider components exist."""
    if summary is None:
        return None
    prompt = summary.get("prompt_tokens")
    completion = summary.get("completion_tokens")
    if prompt is None or completion is None:
        return None
    return TokenUsage(prompt_tokens=prompt, completion_tokens=completion)


def _metering_scope() -> InvocationScope:
    """Return the workload scope explicitly bound by the calling route."""
    return current_invocation_scope()
