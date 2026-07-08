"""Chat endpoint - a screen-aware conversational proxy for the console
CommandDeck.

Contract:

- Read-only. The endpoint accepts ``POST /chat`` with a JSON body
  ``{prompt: str, view_context: object, history: [...]}`` and returns
  ``{answer: str, model: str}``. It NEVER issues a privileged call and
  NEVER touches the executor identity - it is a translator that grounds
  its reply on the ``view_context`` the browser captured from the
  currently rendered page (``console/src/deck/context.tsx``).
- Fork extension seam. The route is only registered when a
  :class:`ChatBackend` is wired at the composition root
  (``ReadApiConfig.chat``). Upstream ships two backend implementations:

    * :class:`OpenAiCompatibleChatBackend` - a generic OpenAI /
      Azure-OpenAI proxy that reads ``FDAI_NARRATOR_*`` env vars
      (matching the CLI narrator in
      ``cli/src/narrator/index.ts``) so a dev / operator that already
      has the CLI narrator configured gets the console deck for free.
    * :class:`DisabledChatBackend` - returns ``501`` so the FE deck can
      cleanly fall back to its built-in deterministic answerer.

- No secret leakage. API keys are read from env at construction and
  never echoed. The endpoint bounds request bodies at
  ``max_body_bytes`` and truncates the ``view_context`` sent to the
  model to ``max_context_bytes`` so a malicious or accidental page
  cannot inflate token cost.

Prompt strategy: the deck's own ``ViewSnapshot`` (facts + records) is
serialised into the system prompt with strict grounding instructions.
The model MUST answer from that JSON only, in the operator's language.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

DEFAULT_ROUTE_PATH: Final[str] = "/chat"
DEFAULT_MAX_BODY_BYTES: Final[int] = 200_000
DEFAULT_MAX_CONTEXT_BYTES: Final[int] = 60_000
DEFAULT_MAX_HISTORY_TURNS: Final[int] = 8

_LOG = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the FDAI console assistant, part of a read-only operator surface.

You answer questions about the FDAI (Fully Deterministic AI) control plane -
an autonomous cloud-ops system whose console the operator is looking at
right now. A structured snapshot of the currently rendered page is provided
below as JSON. Ground every answer STRICTLY in that snapshot.

Rules:
- Reply in the operator's language (Korean, English, Japanese, etc.). Mirror the language of their question.
- Cite exact numbers/labels from the snapshot; NEVER invent facts.
- If the snapshot lacks the information, say so plainly and suggest which route (Live / Dashboard / Audit / HIL Queue / Ontology / Blast Radius / Promotion / Trace) probably has it.
- Explain FDAI concepts using the glossary below when the operator asks "what is X" / a translated equivalent in their language.
- Be concise: default to 1-4 short sentences. Expand only if the question asks for detail.
- Do NOT propose actions, approvals, or writes. The console is read-only; the assistant is a translator, not a judge.
- Do NOT wrap replies in markdown code fences unless quoting code.

FDAI glossary (use only when asked to explain):
- ActionType / action kind: the ontology entry that classifies what an autonomous action does (e.g. `remediate.tag-add`, `remediate.enable-tde`, `ops.publish-change-summary`). Each ActionType binds five agent roles: initiators, judge, executor, approver, auditor.
- Tier T0 / T1 / T2: trust-router routing tier. T0 = deterministic policy (target 70-80% coverage). T1 = lightweight similarity / small-model classifier (15-20%). T2 = frontier LLM reasoning (~5-10%, novel cases only).
- Gate decision: risk-gate verdict per finding. `auto` = execute (allowed by policy), `hil` = needs human approval, `deny` = refused, `abstain` = no rule matched (fail-safe no-op).
- Shadow vs enforce mode: new actions ship in shadow (judge-and-log, no mutation) and are explicitly promoted to enforce after their promotion_gate passes.
- HIL (human-in-the-loop): high-risk approvals flow through Teams / ChatOps Adaptive Cards - never a console button.
- Verticals: Change safety, Resilience, Cost governance.
- Safety invariants (every autonomous action requires all four): stop-condition, tested rollback path, blast-radius cap, audit-log entry.
- Rule catalog: versioned rules discovered from upstream sources + operational signals; every rule carries provenance and passes the quality gate before shipping.

Current view snapshot (JSON):
{snapshot_json}
"""


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


# ---------------------------------------------------------------------------
# Disabled backend - explicit 501 so the FE falls back to deterministic
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# OpenAI-compatible backend
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenAiCompatibleChatBackendConfig:
    """Endpoint + auth binding for the OpenAI-compatible chat backend."""

    provider: str  # "openai" or "azure"
    base_url: str
    api_key: str
    model: str  # deployment name for provider=azure
    api_version: str = "2024-08-01-preview"
    temperature: float = 0.2
    max_tokens: int = 800
    timeout_seconds: float = 30.0


class OpenAiCompatibleChatBackend:
    """Chat backend that proxies to any OpenAI-compatible chat/completions.

    Auth is API-key only (``Authorization: Bearer`` for OpenAI,
    ``api-key`` header for Azure). Keyless (managed-identity) auth is
    intentionally deferred to a future revision to keep the console
    slice small; a fork that needs it can inject its own backend.
    """

    def __init__(
        self,
        *,
        config: OpenAiCompatibleChatBackendConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if config.provider not in {"openai", "azure"}:
            raise ValueError("provider MUST be 'openai' or 'azure'")
        if not config.base_url.startswith(("https://", "http://")):
            raise ValueError("base_url MUST be an absolute URL")
        if not config.api_key:
            raise ValueError("api_key MUST NOT be empty")
        if not config.model:
            raise ValueError("model MUST NOT be empty")
        self._config = config
        self._http = http_client if http_client is not None else httpx.AsyncClient()

    def _url(self) -> str:
        base = self._config.base_url.rstrip("/")
        if self._config.provider == "azure":
            return f"{base}/openai/deployments/{self._config.model}/chat/completions"
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._config.provider == "azure":
            h["api-key"] = self._config.api_key
        else:
            h["Authorization"] = f"Bearer {self._config.api_key}"
        return h

    def _params(self) -> dict[str, str]:
        if self._config.provider == "azure":
            return {"api-version": self._config.api_version}
        return {}

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        snapshot_json = json.dumps(view_context, ensure_ascii=False, indent=None)
        # Bound the payload we send to the model.
        if len(snapshot_json) > DEFAULT_MAX_CONTEXT_BYTES:
            snapshot_json = snapshot_json[:DEFAULT_MAX_CONTEXT_BYTES] + "...(truncated)"
        system = _SYSTEM_PROMPT.format(snapshot_json=snapshot_json)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for turn in history[-DEFAULT_MAX_HISTORY_TURNS:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                messages.append({"role": role, "content": content[:4000]})
        messages.append({"role": "user", "content": prompt[:4000]})

        body: dict[str, Any] = {
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        if self._config.provider == "openai":
            body["model"] = self._config.model

        try:
            response = await self._http.post(
                self._url(),
                params=self._params(),
                headers=self._headers(),
                json=body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            _LOG.warning("chat backend HTTP error: %s", exc)
            raise HTTPException(status_code=502, detail="chat upstream unreachable") from exc
        if response.status_code >= 400:
            _LOG.warning(
                "chat backend upstream returned %s (body=%s)",
                response.status_code,
                response.text[:200],
            )
            raise HTTPException(status_code=502, detail="chat upstream error")
        try:
            envelope = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="chat upstream returned non-JSON") from exc

        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HTTPException(status_code=502, detail="chat upstream returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise HTTPException(status_code=502, detail="chat upstream returned no content")
        return {"answer": content.strip(), "model": self._config.model}


# ---------------------------------------------------------------------------
# Env-var factory (matches CLI FDAI_NARRATOR_* convention)
# ---------------------------------------------------------------------------


def backend_from_env(env: dict[str, str] | None = None) -> ChatBackend:
    """Resolve a ChatBackend from environment variables.

    Resolution order (first match wins):

    1. **API-key config** - ``FDAI_NARRATOR_BASE_URL`` +
       ``FDAI_NARRATOR_API_KEY`` + ``FDAI_NARRATOR_MODEL``
       (+ optional ``FDAI_NARRATOR_PROVIDER=openai|azure``,
       ``FDAI_NARRATOR_API_VERSION``). Same convention as the CLI
       narrator in ``cli/src/narrator/index.ts``.
    2. **Keyless Azure via ``az login``** - if ``resolved-models.json``
       (found by walking up from cwd) has a ``narrator`` block AND the
       Azure CLI is present, we build an :class:`AzureAdChatBackend`
       that mints a token per request. Matches the CLI's
       ``resolveDiskLlmConfig`` path so a dev that already runs the
       CLI narrator gets the console deck for free.
    3. **Fallback** - :class:`DisabledChatBackend`; the FE falls back
       to its built-in deterministic answerer.
    """
    src = env if env is not None else dict(os.environ)
    # 1) API-key config.
    base_url = src.get("FDAI_NARRATOR_BASE_URL")
    api_key = src.get("FDAI_NARRATOR_API_KEY")
    model = src.get("FDAI_NARRATOR_MODEL")
    if base_url and api_key and model:
        provider = "azure" if src.get("FDAI_NARRATOR_PROVIDER") == "azure" else "openai"
        return OpenAiCompatibleChatBackend(
            config=OpenAiCompatibleChatBackendConfig(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                model=model,
                api_version=src.get("FDAI_NARRATOR_API_VERSION", "2024-08-01-preview"),
            )
        )
    # 2) Keyless Azure via resolved-models.json + az CLI.
    disk = _resolve_disk_azure_backend(src)
    if disk is not None:
        return disk
    return DisabledChatBackend()


def _resolve_disk_azure_backend(env: dict[str, str]) -> ChatBackend | None:
    """Look up ``resolved-models.json`` and build an Azure AD backend.

    Two shapes are recognised:

    - **Single narrator** - ``resolved-models.json`` has a top-level
      ``narrator`` object (``{endpoint, deployment, api_version}``).
      Returns a plain :class:`AzureAdChatBackend`.
    - **Multi-candidate router** - ``resolved-models.json`` has a
      top-level ``narrator_candidates`` array with two or more objects
      of the same shape. Returns a :class:`LatencyRoutedChatBackend`
      that picks the fastest candidate per request. When both fields
      are present, ``narrator_candidates`` wins (routed backend is a
      superset of the single case).
    """
    path = _find_resolved_models(env)
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # 1) Multi-candidate router (preferred when present).
    routed = _build_routed_backend(data.get("narrator_candidates"))
    if routed is not None:
        return routed
    # 2) Single narrator.
    return _build_single_azure_backend(data.get("narrator"))


def _build_single_azure_backend(narrator: Any) -> AzureAdChatBackend | None:
    if not isinstance(narrator, dict):
        return None
    endpoint = narrator.get("endpoint")
    deployment = narrator.get("deployment")
    api_version = narrator.get("api_version")
    if not (isinstance(endpoint, str) and isinstance(deployment, str)):
        return None
    return AzureAdChatBackend(
        endpoint=endpoint,
        deployment=deployment,
        api_version=api_version if isinstance(api_version, str) else "2024-08-01-preview",
    )


def _build_routed_backend(raw: Any) -> LatencyRoutedChatBackend | None:
    """Build the latency-routed backend from a ``narrator_candidates`` list.

    Silently drops malformed entries; refuses to build the router if
    fewer than two well-formed candidates remain (single or zero
    candidates fall back to the single-narrator path so we never lose
    an existing wiring on a partial config).
    """
    if not isinstance(raw, list):
        return None
    candidates: list[tuple[str, ChatBackend]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        endpoint = entry.get("endpoint")
        deployment = entry.get("deployment")
        api_version = entry.get("api_version")
        if not (isinstance(endpoint, str) and isinstance(deployment, str)):
            continue
        if deployment in seen:
            continue
        seen.add(deployment)
        candidates.append(
            (
                deployment,
                AzureAdChatBackend(
                    endpoint=endpoint,
                    deployment=deployment,
                    api_version=api_version
                    if isinstance(api_version, str)
                    else "2024-08-01-preview",
                ),
            )
        )
    if len(candidates) < 2:
        return None
    return LatencyRoutedChatBackend(candidates=candidates)


def _find_resolved_models(env: dict[str, str]) -> str | None:
    """Locate ``resolved-models.json`` in a CWD-independent way.

    Resolution order (first hit wins):

    1. ``LLM_RESOLVED_MODELS_PATH`` env override (respected verbatim;
       returns ``None`` when the path does not exist so tests stay
       hermetic).
    2. Walk up from :func:`os.getcwd` (dev harness convenience).
    3. Walk up from the ``fdai`` package directory to find the project
       root - this makes the LLM default work regardless of where
       ``uvicorn`` was started from.
    """
    explicit = env.get("LLM_RESOLVED_MODELS_PATH")
    if explicit is not None:
        return explicit if os.path.exists(explicit) else None
    for start in _search_roots():
        here = start
        for _ in range(6):
            candidate = os.path.join(here, "resolved-models.json")
            if os.path.exists(candidate):
                return candidate
            parent = os.path.dirname(here)
            if parent == here:
                break
            here = parent
    return None


def _search_roots() -> list[str]:
    """Return roots to walk up from when looking for the JSON file."""
    roots = [os.getcwd()]
    # Fall back to the fdai package location so a caller that starts
    # uvicorn from anywhere still finds the shipped resolved-models.json.
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        roots.append(here)
    except OSError:
        pass
    return roots


# ---------------------------------------------------------------------------
# Backend introspection - used by the /chat/health endpoint so the FE
# can render an accurate "LLM ready" badge before the operator asks.
# ---------------------------------------------------------------------------


def describe_backend(backend: ChatBackend) -> dict[str, Any]:
    """Return a small JSON-safe descriptor of the wired backend.

    Contains only public metadata (provider, model / deployment,
    endpoint host) - never the API key or bearer token.
    """
    if isinstance(backend, DisabledChatBackend):
        return {"available": False, "mode": "disabled", "model": None, "endpoint": None}
    if isinstance(backend, LatencyRoutedChatBackend):
        # The router is warm-up-driven; expose the current candidate stats
        # so the deck header can show ``LLM · auto(3) · fastest gpt-5.4-mini``
        # from a single ``GET /chat/health`` call, before any turn.
        stats = backend.stats()
        chose = backend.current_pick_name()
        return {
            "available": True,
            "mode": "azure-ad-routed",
            "model": chose,
            "endpoint": _host_of(backend.endpoints()[0]) if backend.endpoints() else None,
            "router": {
                "chose": chose,
                "candidates": stats,
            },
        }
    if isinstance(backend, AzureAdChatBackend):
        return {
            "available": True,
            "mode": "azure-ad",
            "model": backend._deployment,  # noqa: SLF001 - deliberate readonly peek
            "endpoint": _host_of(backend._endpoint),  # noqa: SLF001
        }
    if isinstance(backend, OpenAiCompatibleChatBackend):
        cfg = backend._config  # noqa: SLF001 - deliberate readonly peek
        return {
            "available": True,
            "mode": f"openai-compat:{cfg.provider}",
            "model": cfg.model,
            "endpoint": _host_of(cfg.base_url),
        }
    return {"available": True, "mode": type(backend).__name__, "model": None, "endpoint": None}


def _host_of(url: str) -> str:
    """Extract host from a URL, defensively - never returns None."""
    from urllib.parse import urlparse

    try:
        return urlparse(url).netloc or url
    except ValueError:
        return url


def make_chat_health_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    path: str = "/chat/health",
) -> Route:
    """Return a ``GET`` health-check route describing the chat backend.

    The FE polls this once at deck-open time so the header can render
    ``LLM ready · gpt-4o-mini`` (or the disabled/fallback equivalent)
    without having to speculatively hit ``/chat`` first.
    """

    async def handler(request: Request) -> JSONResponse:
        await authorize(request)
        return JSONResponse(describe_backend(backend))

    return Route(path, handler, methods=["GET"])


# ---------------------------------------------------------------------------
# Azure AD backend (az login / managed identity via workload_identity)
# ---------------------------------------------------------------------------


_COGNITIVE_SCOPE: Final[str] = "https://cognitiveservices.azure.com/.default"


class AzureAdChatBackend:
    """Chat backend that authenticates to Azure OpenAI via ``az login``.

    Uses :class:`~fdai.delivery.azure.dev_workload_identity.AzureCliWorkloadIdentity`
    under the hood so no API key needs to be exported; the operator only
    needs a working ``az login`` (or ``AZURE_CONFIG_DIR`` pointing at the
    right profile). Fails-closed on any CLI error so the FE can fall back.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-08-01-preview",
        temperature: float = 0.2,
        max_tokens: int = 800,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint MUST be an absolute URL")
        if not deployment:
            raise ValueError("deployment MUST NOT be empty")
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._api_version = api_version
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._http = http_client if http_client is not None else httpx.AsyncClient()
        # Lazy identity - defer import so this module stays importable
        # in tests that never touch Azure.
        self._identity_cached: Any = None

    def _identity(self) -> Any:
        if self._identity_cached is None:
            from fdai.delivery.azure.dev_workload_identity import AzureCliWorkloadIdentity

            self._identity_cached = AzureCliWorkloadIdentity()
        return self._identity_cached

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        import asyncio

        try:
            token = await asyncio.to_thread(
                self._identity().get_token_sync, _COGNITIVE_SCOPE
            )
        except Exception as exc:  # AzureCliCredentialError, missing binary, etc.
            _LOG.warning("chat backend az-login failed: %s", exc)
            raise HTTPException(status_code=502, detail="chat auth failed") from exc

        snapshot_json = json.dumps(view_context, ensure_ascii=False)
        if len(snapshot_json) > DEFAULT_MAX_CONTEXT_BYTES:
            snapshot_json = snapshot_json[:DEFAULT_MAX_CONTEXT_BYTES] + "...(truncated)"
        system = _SYSTEM_PROMPT.format(snapshot_json=snapshot_json)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for turn in history[-DEFAULT_MAX_HISTORY_TURNS:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                messages.append({"role": role, "content": content[:4000]})
        messages.append({"role": "user", "content": prompt[:4000]})

        body: dict[str, Any] = {
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        url = f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._http.post(
                url,
                params={"api-version": self._api_version},
                headers=headers,
                json=body,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            _LOG.warning("chat backend HTTP error: %s", exc)
            raise HTTPException(status_code=502, detail="chat upstream unreachable") from exc
        if response.status_code >= 400:
            _LOG.warning(
                "chat backend upstream returned %s (body=%s)",
                response.status_code,
                response.text[:200],
            )
            raise HTTPException(status_code=502, detail="chat upstream error")
        try:
            envelope = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="chat upstream returned non-JSON") from exc
        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise HTTPException(status_code=502, detail="chat upstream returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise HTTPException(status_code=502, detail="chat upstream returned no content")
        return {"answer": content.strip(), "model": self._deployment}


# ---------------------------------------------------------------------------
# Latency-routed backend - auto-pick the fastest candidate per request
# ---------------------------------------------------------------------------


_ROUTER_WINDOW_SIZE: Final[int] = 8
"""Rolling window per candidate - short enough to react to a slowdown."""

_ROUTER_WARMUP_SAMPLES: Final[int] = 2
"""Each candidate must serve this many turns before it participates in p50 ranking."""

_ROUTER_FAILURE_PENALTY_MS: Final[int] = 30_000
"""Synthetic sample recorded on a failed call so a broken candidate rotates out."""


class LatencyRoutedChatBackend:
    """Wrap N :class:`ChatBackend`s and route each request to the fastest.

    Selection policy:

    - **Warm-up**: any candidate with fewer than :data:`_ROUTER_WARMUP_SAMPLES`
      recorded samples is picked first (tie-broken by name so tests stay
      deterministic). This guarantees every candidate is measured on real
      traffic before it can be de-selected.
    - **Steady state**: pick the candidate with the lowest p50 latency in
      its rolling window; ties broken by name.

    On any exception the router records a large penalty sample so a
    broken candidate rotates out on the next request. The router itself
    re-raises - the route handler already maps exceptions to the right
    HTTP status.

    Every reply is enriched with a ``router`` block::

        {
          "chose": "gpt-5.4-mini",
          "reason": "lowest-p50" | "warmup",
          "candidates": [
            {"deployment": "gpt-5.4-mini", "p50_ms": 820, "samples": 5},
            ...
          ]
        }

    The FE deck reads this to render "auto-routing between 3 mini models
    · fastest: gpt-5.4-mini · p50 820ms" in the badge tooltip.
    """

    def __init__(self, *, candidates: list[tuple[str, ChatBackend]]) -> None:
        if len(candidates) < 2:
            raise ValueError("LatencyRoutedChatBackend requires >= 2 candidates")
        names = [n for n, _ in candidates]
        if len(set(names)) != len(names):
            raise ValueError("LatencyRoutedChatBackend candidate names MUST be unique")
        self._candidates: list[tuple[str, ChatBackend]] = list(candidates)
        self._samples: dict[str, deque[int]] = {
            name: deque(maxlen=_ROUTER_WINDOW_SIZE) for name, _ in candidates
        }

    # ------------------------------------------------------------------ public
    def stats(self) -> list[dict[str, Any]]:
        """Snapshot of per-candidate p50 + sample count (JSON-safe)."""
        return [
            {
                "deployment": name,
                "p50_ms": _p50(self._samples[name]),
                "samples": len(self._samples[name]),
            }
            for name, _ in self._candidates
        ]

    def current_pick_name(self) -> str:
        """Which candidate would serve the NEXT request (peek, no state change)."""
        name, _ = self._pick()
        return name

    def endpoints(self) -> list[str]:
        """Endpoint hosts (best-effort - only Azure-AD backends expose one)."""
        out: list[str] = []
        for _, be in self._candidates:
            if isinstance(be, AzureAdChatBackend):
                out.append(be._endpoint)  # noqa: SLF001 - deliberate peek
        return out

    # ------------------------------------------------------------------ Protocol
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        name, backend = self._pick()
        started = time.monotonic()
        try:
            reply = await backend.answer(
                prompt=prompt, view_context=view_context, history=history
            )
        except Exception:
            # Penalize so the broken candidate cycles out; still re-raise.
            self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
            raise
        latency = int((time.monotonic() - started) * 1000)
        self._samples[name].append(latency)
        reason = "warmup" if len(self._samples[name]) <= _ROUTER_WARMUP_SAMPLES else "lowest-p50"
        out: dict[str, Any] = dict(reply)
        # Force ``model`` to the router's chosen name - keeps the FE badge
        # consistent even if a backend reports a different deployment id.
        out["model"] = name
        out["router"] = {
            "chose": name,
            "reason": reason,
            "candidates": self.stats(),
        }
        return out

    # ------------------------------------------------------------------ internal
    def _pick(self) -> tuple[str, ChatBackend]:
        # Warm-up: pick the candidate with the fewest samples first, then
        # by name so the pick is deterministic for tests + audit.
        cold = [
            (name, be)
            for name, be in self._candidates
            if len(self._samples[name]) < _ROUTER_WARMUP_SAMPLES
        ]
        if cold:
            cold.sort(key=lambda x: (len(self._samples[x[0]]), x[0]))
            return cold[0]
        # Steady state: min p50, tie-broken by name.
        return min(
            self._candidates,
            key=lambda x: (_p50(self._samples[x[0]]), x[0]),
        )


def _p50(samples: deque[int]) -> float:
    """Median of a small deque; ``inf`` for empty so warm-up sorts last."""
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 == 1 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------


AuthorizeFn = Callable[[Request], Awaitable[str]]


def make_chat_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    path: str = DEFAULT_ROUTE_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Build the ``POST /chat`` route.

    The route is POST because the browser sends a body; it is still
    read-only in the FDAI sense (no state mutation, no privileged call).
    Reader role is required (enforced by the shared ``authorize`` fn).
    """

    async def handler(request: Request) -> JSONResponse:
        await authorize(request)

        # Bound the body up-front so a malicious page cannot inflate cost.
        body_bytes = await request.body()
        if len(body_bytes) > max_body_bytes:
            raise HTTPException(status_code=413, detail="chat body too large")
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="chat body MUST be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="chat body MUST be a JSON object")

        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt MUST be a non-empty string")
        view_context = body.get("view_context")
        if view_context is None:
            view_context = {}
        if not isinstance(view_context, dict):
            raise HTTPException(status_code=400, detail="view_context MUST be an object")
        history_raw = body.get("history", [])
        if not isinstance(history_raw, list):
            raise HTTPException(status_code=400, detail="history MUST be a list")
        history: list[dict[str, str]] = []
        for turn in history_raw:
            if isinstance(turn, dict):
                role = turn.get("role")
                content = turn.get("content")
                if isinstance(role, str) and isinstance(content, str):
                    history.append({"role": role, "content": content})

        # Wall-clock latency around the backend call - surfaced to the FE
        # so the deck can render a "gpt-4o-mini · 830ms" badge next to
        # each turn. Kept out of the backend Protocol so any implementer
        # (real, disabled, or a future latency-routed wrapper) benefits
        # without opting in.
        started = time.monotonic()
        try:
            reply = await backend.answer(
                prompt=prompt.strip(),
                view_context=view_context,
                history=history,
            )
        except ChatBackendUnavailableError:
            raise HTTPException(
                status_code=501,
                detail="chat backend not configured on this deployment",
            ) from None
        latency_ms = int((time.monotonic() - started) * 1000)
        enriched: dict[str, Any] = dict(reply)
        enriched["latency_ms"] = latency_ms
        return JSONResponse(enriched)

    return Route(path, handler, methods=["POST"])
