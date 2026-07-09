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
The prompt is kept lean for cost/latency (see :func:`_build_messages`):
the base instructions are compact, the FDAI glossary is appended ONLY for
concept questions (:func:`_is_concept_query`, EN + KO), and each ``records``
array is capped to a representative sample (:func:`_trim_view_context`)
with a ``_records_truncated`` hint so the snapshot JSON does not dominate
the token budget - the operator narrows to off-sample rows via the page's
own search/filter.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, NoReturn, Protocol

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

DEFAULT_ROUTE_PATH: Final[str] = "/chat"
DEFAULT_MAX_BODY_BYTES: Final[int] = 200_000
DEFAULT_MAX_CONTEXT_BYTES: Final[int] = 60_000
DEFAULT_MAX_HISTORY_TURNS: Final[int] = 8
DEFAULT_MAX_RECORDS_PER_KEY: Final[int] = 40
"""Cap on how many rows of any one ``records`` array in the view snapshot are
forwarded to the model. The page may render hundreds of rows (e.g. a rule
catalog page); sending them all makes the snapshot JSON - not the static
prompt - dominate per-turn token cost. A representative sample plus a
``_records_truncated`` hint keeps grounding honest while trimming tokens; the
operator narrows to off-sample rows via the page's own search/filter."""
DEFAULT_MAX_HISTORY_ITEMS: Final[int] = 200
"""Hard cap on the number of history entries the route will parse into
memory before slicing to :data:`DEFAULT_MAX_HISTORY_TURNS`. The
body-byte cap already bounds total bytes, but a payload full of tiny
one-character turns could still allocate a large list of dicts; this
cap keeps that pathological shape out of the interpreter."""

_LOG = logging.getLogger(__name__)


def _default_chat_http_client() -> httpx.AsyncClient:
    """Build the fallback :class:`httpx.AsyncClient` for chat backends.

    Explicit per-phase timeouts (httpx's global default 5s is too short
    for LLM completion streams) and ``follow_redirects=False`` (an
    OpenAI-compatible endpoint should not silently 3xx to elsewhere).
    Centralised so the two fallback sites in this module stay in sync.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0),
        follow_redirects=False,
    )


_SYSTEM_PROMPT = """\
You are the FDAI console assistant: a read-only translator over the operator's
current screen in the FDAI (Fully Deterministic AI) control plane. A JSON
snapshot of the rendered page follows; ground every answer STRICTLY in it.

Rules:
- Reply in the operator's language, mirroring their question.
- Cite exact numbers/labels from the snapshot; NEVER invent facts.
- The snapshot may hold a `records` collection (`records.rules`, `records.items`, ...) of rows visible now; search and quote matching rows - do not claim missing info when a row is present. If `_records_truncated` is true, only a sample is shown - point the operator to the page's search/filter for anything not in it.
- If a specific entry is absent but this page has a search/filter (the Rules catalog has a search box plus origin/category/severity/source filters), tell the operator to use it; only point to another route (Live/Dashboard/Audit/HIL/Ontology/Blast Radius/Promotion/Trace) when the topic truly belongs there.
- Be concise: 1-4 short sentences unless asked for detail.
- Read-only: never propose actions, approvals, or writes; you translate, you do not judge.
- No markdown code fences unless quoting code.
{glossary}Current view snapshot (JSON):
{snapshot_json}
"""

# The FDAI glossary is injected into the system prompt ONLY when the operator
# asks to define/explain a term (see :func:`_is_concept_query`). Routine data
# questions - the large majority - get the lean prompt above, which keeps the
# per-turn token cost and latency down without losing concept coverage.
_GLOSSARY = """\
FDAI glossary (use only to define a term on request):
- ActionType: ontology entry classing an autonomous action; binds 5 roles (initiators, judge, executor, approver, auditor).
- Trust router: routes each event to the lowest sufficient tier (T0/T1/T2) by a computed confidence.
- T0/T1/T2: trust-router tiers - deterministic policy (70-80%) / lightweight similarity (15-20%) / frontier-LLM reasoning (5-10%, novel only).
- Gate decision: auto=execute, hil=needs approval, deny=refused, abstain=no rule matched (no-op).
- Shadow vs enforce: new actions ship shadow (log-only), promoted to enforce after their promotion_gate passes.
- HIL: high-risk approvals via Teams/ChatOps cards, never a console button.
- Verticals: change safety, resilience, cost governance.
- Safety invariants: stop-condition, rollback path, blast-radius cap, audit entry.
- Rule catalog: versioned rules with provenance, gated before shipping.
- Provenance: the cited source a rule/finding is grounded in; a candidate without it is rejected.

"""

# Concept-question detection. The Korean markers are written as \\uXXXX escapes
# so the source file stays ASCII (english-only CI gate) while still matching
# Hangul at runtime - the language-policy "quoted data" exception, since we are
# detecting the operator's own-language phrasing. The escapes decode to:
#   intent   = explain / meaning / sense / concept / definition / role /
#              difference / purpose / why
#   phrasing = "what" (interrogative) / what (casual) / which / how / what-kind
_CONCEPT_INTENT: Final = re.compile(
    r"\b(explain|define|definition|glossary|mean|meaning|purpose|difference"
    r"|overview)\b|\bwhy\b|\brole of\b"
    "|\uc124\uba85|\uc758\ubbf8|\ub73b|\uac1c\ub150|\uc815\uc758"
    "|\uc5ed\ud560|\ucc28\uc774|\uc6a9\ub3c4|\uc65c",
    re.IGNORECASE,
)
_CONCEPT_PHRASING: Final = re.compile(
    r"\bwhat\s+(is|are|does|do)\b|\bwhats\b|\bwhat's\b"
    r"|\bhow\s+(does|do|is|are|to)\b"
    "|\ubb34\uc5c7|\ubb50|\ubb54|\uc5b4\ub5bb\uac8c|\ubb34\uc2a8",
    re.IGNORECASE,
)
_DATA_WORD: Final = re.compile(
    # Trailing escapes decode to Korean count markers: how-many / count.
    r"how many|number of|count|share|total|pending|rate|eps|mix"
    r"|distribution|many|loaded|affected|depth|step"
    "|\uba87|\uac1c\uc218",
    re.IGNORECASE,
)


def _is_concept_query(prompt: str) -> bool:
    """True when the prompt asks to define/explain a term (glossary needed).

    Data-metric phrasings ("how many", "share", "count") are excluded so
    routine screen questions get the lean prompt without the glossary block.
    """
    if _CONCEPT_INTENT.search(prompt):
        return True
    return bool(_CONCEPT_PHRASING.search(prompt) and not _DATA_WORD.search(prompt))


def _trim_view_context(
    view_context: dict[str, Any], *, max_records: int = DEFAULT_MAX_RECORDS_PER_KEY
) -> dict[str, Any]:
    """Cap each ``records`` array to a representative sample.

    The rendered page can publish hundreds of rows; forwarding them all lets
    the snapshot JSON dominate the prompt. Trim each array to ``max_records``
    and flag ``_records_truncated`` so the model knows to point the operator at
    the page's search/filter for the rest. Returns the input unchanged when no
    array exceeds the cap (no needless copy).
    """
    records = view_context.get("records")
    if not isinstance(records, dict):
        return view_context
    trimmed: dict[str, Any] = {}
    changed = False
    for key, rows in records.items():
        if isinstance(rows, list) and len(rows) > max_records:
            trimmed[key] = rows[:max_records]
            changed = True
        else:
            trimmed[key] = rows
    if not changed:
        return view_context
    new_ctx = dict(view_context)
    new_ctx["records"] = trimmed
    new_ctx["_records_truncated"] = True
    return new_ctx


def _build_messages(
    prompt: str,
    view_context: dict[str, Any],
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Assemble the chat messages shared by every backend.

    One grounded system message (size-capped snapshot + glossary only when the
    prompt is a concept question) followed by the bounded conversation history
    and the user turn. Centralised so all three backends
    (:class:`OpenAiCompatibleChatBackend`, :class:`AzureAdChatBackend`, and the
    streaming path) build byte-identical, minimal prompts.
    """
    view_context = _trim_view_context(view_context)
    snapshot_json = json.dumps(view_context, ensure_ascii=False)
    # Bound the payload we send to the model.
    if len(snapshot_json) > DEFAULT_MAX_CONTEXT_BYTES:
        snapshot_json = snapshot_json[:DEFAULT_MAX_CONTEXT_BYTES] + "...(truncated)"
    glossary = _GLOSSARY if _is_concept_query(prompt) else ""
    system = _SYSTEM_PROMPT.format(glossary=glossary, snapshot_json=snapshot_json)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in history[-DEFAULT_MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": prompt[:4000]})
    return messages


# Markers Azure OpenAI / OpenAI put in a 400 body when the request or reply is
# refused by the content / jailbreak filter (not an outage - an expected,
# safe policy block). Lower-cased substring match.
_CONTENT_FILTER_MARKERS: Final[tuple[str, ...]] = (
    "content_filter",
    "responsibleaipolicy",
    "jailbreak",
    "content management policy",
)


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


# Newer Azure OpenAI models (gpt-5*, o-series reasoning) reject the legacy
# ``max_tokens`` + custom ``temperature`` and require ``max_completion_tokens``
# with the default temperature. Classic chat models (gpt-4o*, gpt-4.1*) keep
# the legacy shape. Matched by deployment/model name prefix so per-candidate
# config selects the right body automatically.
_COMPLETION_TOKEN_PARAM_MODELS: Final[tuple[str, ...]] = ("gpt-5", "o1", "o3", "o4")


def _completion_body_params(model: str, *, temperature: float, max_tokens: int) -> dict[str, Any]:
    """Build the token/temperature fields for a chat-completions body.

    Returns ``{"max_completion_tokens": N}`` for models that require it
    (gpt-5*, o-series reasoning) - which also reject a custom ``temperature`` -
    and the legacy ``{"temperature": t, "max_tokens": N}`` for classic chat
    models (gpt-4o*, gpt-4.1*).
    """
    if model.lower().startswith(_COMPLETION_TOKEN_PARAM_MODELS):
        return {"max_completion_tokens": max_tokens}
    return {"temperature": temperature, "max_tokens": max_tokens}


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
        self._http = http_client if http_client is not None else _default_chat_http_client()

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
        messages = _build_messages(prompt, view_context, history)

        body: dict[str, Any] = {
            "messages": messages,
            **_completion_body_params(
                self._config.model,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            ),
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
            _raise_upstream_error(response.status_code, response.text)
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
        self._http = http_client if http_client is not None else _default_chat_http_client()
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
            token = await asyncio.to_thread(self._identity().get_token_sync, _COGNITIVE_SCOPE)
        except Exception as exc:  # AzureCliCredentialError, missing binary, etc.
            _LOG.warning("chat backend az-login failed: %s", exc)
            raise HTTPException(status_code=502, detail="chat auth failed") from exc

        messages = _build_messages(prompt, view_context, history)

        body: dict[str, Any] = {
            "messages": messages,
            **_completion_body_params(
                self._deployment,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ),
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
            _raise_upstream_error(response.status_code, response.text)
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

    async def answer_stream(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the answer token by token via Azure OpenAI ``stream=true``.

        Yields ``{"type": "token", "delta": str}`` per content chunk, then a
        terminal ``{"type": "done", "answer": str, "model": str}``. Auth /
        body building mirror :meth:`answer`; only the transport differs.
        Read-only - no state mutation, no privileged call.
        """
        import asyncio

        try:
            token = await asyncio.to_thread(self._identity().get_token_sync, _COGNITIVE_SCOPE)
        except Exception as exc:
            _LOG.warning("chat backend az-login failed: %s", exc)
            raise HTTPException(status_code=502, detail="chat auth failed") from exc

        messages = _build_messages(prompt, view_context, history)

        body: dict[str, Any] = {
            "messages": messages,
            "stream": True,
            **_completion_body_params(
                self._deployment,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ),
        }
        url = f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
        }
        collected: list[str] = []
        try:
            async with self._http.stream(
                "POST",
                url,
                params={"api-version": self._api_version},
                headers=headers,
                json=body,
                timeout=self._timeout,
            ) as response:
                if response.status_code >= 400:
                    err_body = (await response.aread()).decode("utf-8", "replace")
                    _raise_upstream_error(response.status_code, err_body)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    choices = obj.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                    piece = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(piece, str) and piece:
                        collected.append(piece)
                        yield {"type": "token", "delta": piece}
        except httpx.HTTPError as exc:
            _LOG.warning("chat stream HTTP error: %s", exc)
            raise HTTPException(status_code=502, detail="chat upstream unreachable") from exc
        yield {"type": "done", "answer": "".join(collected).strip(), "model": self._deployment}


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
        # Concurrency fairness: N async turns arriving simultaneously during
        # warm-up would all read the same "coldest" candidate from _pick()
        # and stampede one backend. Counting outstanding picks per name lets
        # _pick() treat "in flight" as pseudo-samples so concurrent warm-up
        # turns spread across all candidates.
        self._in_flight: dict[str, int] = {name: 0 for name, _ in candidates}

    # ------------------------------------------------------------------ public
    def stats(self) -> list[dict[str, Any]]:
        """Snapshot of per-candidate rolling latency stats (JSON-safe).

        Each entry carries the raw rolling window (``history_ms``) plus
        precomputed p50 / p95 so the FE can render a sparkline without
        re-doing the maths per repaint.
        """
        return [
            {
                "deployment": name,
                "p50_ms": _p50(self._samples[name]),
                "p95_ms": _p95(self._samples[name]),
                "samples": len(self._samples[name]),
                "history_ms": list(self._samples[name]),
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

    async def benchmark(self, *, prompt: str = "ping", rounds: int | None = None) -> str:
        """Measure every candidate up front so the fastest pick is known
        before the first operator turn.

        Fires ``rounds`` minimal requests at each candidate concurrently and
        records real latency into the same rolling window :meth:`answer`
        uses, so a subsequent ``GET /chat/health`` reports the measured
        fastest. ``rounds`` defaults to :data:`_ROUTER_WARMUP_SAMPLES` so
        every candidate clears warm-up and the returned pick reflects p50
        ranking rather than the deterministic warm-up order. Best-effort: a
        candidate that errors gets the standard failure penalty and rotates
        out, exactly as in steady state. Returns the deployment name the
        router would now pick.
        """
        import asyncio

        effective_rounds = _ROUTER_WARMUP_SAMPLES if rounds is None else max(1, rounds)

        async def _probe(name: str, backend: ChatBackend) -> None:
            started = time.monotonic()
            try:
                await backend.answer(prompt=prompt, view_context={}, history=[])
            except Exception as exc:  # noqa: BLE001 - best-effort probe
                self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
                _LOG.warning(
                    "router.benchmark_candidate_failed",
                    extra={"candidate": name, "error_type": type(exc).__name__},
                )
                return
            self._samples[name].append(int((time.monotonic() - started) * 1000))

        for _ in range(effective_rounds):
            await asyncio.gather(*(_probe(name, be) for name, be in self._candidates))
        return self.current_pick_name()

    async def aclose(self) -> None:
        """Close every candidate's ``httpx.AsyncClient`` (best-effort).

        Idempotent: safe to call multiple times or on a router whose
        backends never opened a client. Never raises - a stuck close
        on one client MUST NOT prevent siblings from cleaning up.
        """
        for _, backend in self._candidates:
            client = getattr(backend, "_http", None)
            aclose = getattr(client, "aclose", None)
            if aclose is None:
                continue
            try:
                await aclose()
            except Exception as exc:  # pragma: no cover - defensive path
                _LOG.warning("router.aclose: candidate client failed to close: %s", exc)

    # ------------------------------------------------------------------ Protocol
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        name, backend = self._pick()
        self._in_flight[name] += 1
        started = time.monotonic()
        try:
            reply = await backend.answer(prompt=prompt, view_context=view_context, history=history)
        except Exception as exc:
            # Penalize so the broken candidate cycles out; still re-raise.
            self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
            _LOG.warning(
                "router.candidate_failed",
                extra={"candidate": name, "error_type": type(exc).__name__},
            )
            self._log_all_penalised_if_saturated()
            raise
        finally:
            self._in_flight[name] = max(0, self._in_flight[name] - 1)
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

    async def answer_stream(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream from the fastest candidate, recording its latency.

        Delegates to the picked candidate's ``answer_stream`` when it
        supports streaming, else falls back to a single-shot ``answer``
        emitted as one token. The terminal ``done`` event is enriched with
        the router snapshot so the FE badge stays consistent.
        """
        name, backend = self._pick()
        self._in_flight[name] += 1
        started = time.monotonic()
        try:
            stream = getattr(backend, "answer_stream", None)
            if stream is not None:
                async for event in stream(
                    prompt=prompt, view_context=view_context, history=history
                ):
                    if event.get("type") == "done":
                        event = dict(event)
                        event["model"] = name
                        event["router"] = {
                            "chose": name,
                            "reason": (
                                "warmup"
                                if len(self._samples[name]) < _ROUTER_WARMUP_SAMPLES
                                else "lowest-p50"
                            ),
                            "candidates": self.stats(),
                        }
                    yield event
            else:
                reply = await backend.answer(
                    prompt=prompt, view_context=view_context, history=history
                )
                answer = reply.get("answer", "")
                if isinstance(answer, str) and answer:
                    yield {"type": "token", "delta": answer}
                yield {
                    "type": "done",
                    "answer": answer,
                    "model": name,
                    "router": {
                        "chose": name,
                        "reason": "lowest-p50",
                        "candidates": self.stats(),
                    },
                }
        except Exception as exc:
            self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
            _LOG.warning(
                "router.stream_candidate_failed",
                extra={"candidate": name, "error_type": type(exc).__name__},
            )
            raise
        finally:
            self._in_flight[name] = max(0, self._in_flight[name] - 1)
        self._samples[name].append(int((time.monotonic() - started) * 1000))

    # ------------------------------------------------------------------ internal
    def _effective_sample_count(self, name: str) -> int:
        """Samples + in-flight picks - used by warm-up fairness."""
        return len(self._samples[name]) + self._in_flight[name]

    def _pick(self) -> tuple[str, ChatBackend]:
        # Warm-up: pick the candidate with the fewest samples first, then
        # by name so the pick is deterministic for tests + audit. In-flight
        # picks count as samples so N concurrent warm-up turns spread
        # across candidates instead of stampeding the first one.
        cold = [
            (name, be)
            for name, be in self._candidates
            if self._effective_sample_count(name) < _ROUTER_WARMUP_SAMPLES
        ]
        if cold:
            cold.sort(key=lambda x: (self._effective_sample_count(x[0]), x[0]))
            return cold[0]
        # Steady state: min p50 (in-flight breaks ties among equal p50s so
        # a burst of requests does not all land on the same candidate),
        # then by name.
        return min(
            self._candidates,
            key=lambda x: (
                _p50(self._samples[x[0]]),
                self._in_flight[x[0]],
                x[0],
            ),
        )

    def _log_all_penalised_if_saturated(self) -> None:
        """Emit an alert-worthy line when every candidate has a penalty on its window.

        Kept separate from the per-call warning so operators see a
        single distinct signal ("all upstreams down") instead of N
        duplicated per-candidate warnings.
        """
        all_penalised = all(
            samples and max(samples) >= _ROUTER_FAILURE_PENALTY_MS
            for samples in self._samples.values()
        )
        if all_penalised:
            _LOG.error(
                "router.all_candidates_penalised",
                extra={"candidates": [name for name, _ in self._candidates]},
            )


def _p50(samples: deque[int]) -> float:
    """Median of a small deque; ``inf`` for empty so warm-up sorts last."""
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 == 1 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _p95(samples: deque[int]) -> float:
    """95th-percentile of the rolling window; ``inf`` when empty.

    With the default 8-sample window p95 sits at the max element (index
    7 by nearest-rank on N=8: ceil(0.95*8) - 1 = 7). Kept as its own
    helper so a future window resize does not silently change semantics.
    """
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    # Nearest-rank method (RFC-style).
    rank = max(0, min(n - 1, int(-(-95 * n // 100)) - 1))
    return float(xs[rank])


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
        # Preflight Content-Length so an attacker cannot force us to
        # buffer megabytes just to reject on `len(body_bytes)`.
        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body_bytes:
                    raise HTTPException(status_code=413, detail="chat body too large")
            except ValueError:
                pass
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
        # Bound the input list BEFORE materializing dicts - a pathological
        # payload of 10k+ one-char turns would slip past the body-byte cap
        # (each turn is ~20 bytes) and force the interpreter to allocate a
        # huge intermediate list only to slice to the last 8.
        if len(history_raw) > DEFAULT_MAX_HISTORY_ITEMS:
            raise HTTPException(
                status_code=400,
                detail=(f"history exceeds cap ({len(history_raw)} > {DEFAULT_MAX_HISTORY_ITEMS})"),
            )
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


DEFAULT_STREAM_PATH: Final[str] = "/chat/stream"


def _sse(event: str, data: dict[str, Any]) -> bytes:
    """Format one Server-Sent Event frame (``event:`` + ``data:`` + blank)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def make_chat_stream_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    path: str = DEFAULT_STREAM_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Build the ``POST /chat/stream`` route (Server-Sent Events).

    Streams the narrator answer token by token as ``event: token`` frames,
    then a terminal ``event: done`` frame carrying the full answer, model,
    router snapshot, and latency. On failure mid-stream an ``event: error``
    frame is emitted and the stream closes. Backends that do not implement
    ``answer_stream`` fall back to a single-shot ``answer`` emitted as one
    token + done, so the FE can always consume the same protocol.

    Read-only in the FDAI sense - no state mutation, no privileged call.
    """

    async def handler(request: Request) -> StreamingResponse:
        await authorize(request)

        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body_bytes:
                    raise HTTPException(status_code=413, detail="chat body too large")
            except ValueError:
                pass
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
        if len(history_raw) > DEFAULT_MAX_HISTORY_ITEMS:
            raise HTTPException(status_code=400, detail="history exceeds cap")
        history: list[dict[str, str]] = []
        for turn in history_raw:
            if isinstance(turn, dict):
                role = turn.get("role")
                content = turn.get("content")
                if isinstance(role, str) and isinstance(content, str):
                    history.append({"role": role, "content": content})

        clean_prompt = prompt.strip()

        async def event_source() -> AsyncIterator[bytes]:
            started = time.monotonic()
            stream = getattr(backend, "answer_stream", None)
            try:
                if stream is not None:
                    async for event in stream(
                        prompt=clean_prompt, view_context=view_context, history=history
                    ):
                        etype = event.get("type")
                        if etype == "token":
                            yield _sse("token", {"delta": event.get("delta", "")})
                        elif etype == "done":
                            payload = {k: v for k, v in event.items() if k != "type"}
                            payload["latency_ms"] = int((time.monotonic() - started) * 1000)
                            yield _sse("done", payload)
                else:
                    reply = await backend.answer(
                        prompt=clean_prompt, view_context=view_context, history=history
                    )
                    answer = reply.get("answer", "")
                    if isinstance(answer, str) and answer:
                        yield _sse("token", {"delta": answer})
                    yield _sse(
                        "done",
                        {
                            "answer": answer,
                            "model": reply.get("model"),
                            "latency_ms": int((time.monotonic() - started) * 1000),
                        },
                    )
            except ChatBackendUnavailableError:
                yield _sse("error", {"detail": "chat backend not configured"})
            except HTTPException as exc:
                yield _sse("error", {"detail": str(exc.detail)})
            except Exception as exc:  # noqa: BLE001 - surface as a stream error, never 500 mid-stream
                _LOG.warning("chat stream failed: %s", type(exc).__name__)
                yield _sse("error", {"detail": "chat stream failed"})

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return Route(path, handler, methods=["POST"])
