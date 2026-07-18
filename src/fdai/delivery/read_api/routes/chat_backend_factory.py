"""Environment factory and public metadata for chat backends."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from fdai.core.metering import MeteringEmitter, MeteringSink
from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE
from fdai.delivery.read_api.routes.chat_backend_azure import AzureAdChatBackend
from fdai.delivery.read_api.routes.chat_backend_common import ChatBackend, DisabledChatBackend
from fdai.delivery.read_api.routes.chat_backend_openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)
from fdai.delivery.read_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle
from fdai.shared.providers.workload_identity import WorkloadIdentity

#: Default completion-token ceiling for the console narrator. Raised from the
#: historical 800 because the narrator emits structured, multi-section answers
#: (assumptions / answer / uncertainty) and reasoning models (gpt-5, o-series)
#: also spend part of ``max_completion_tokens`` on hidden reasoning - 800 cut
#: detailed replies mid-sentence (``finish_reason: length``). Override with
#: ``FDAI_NARRATOR_MAX_TOKENS``.
_DEFAULT_NARRATOR_MAX_TOKENS = 2048
_NARRATOR_MAX_TOKENS_ENV = "FDAI_NARRATOR_MAX_TOKENS"


def _narrator_max_tokens(env: dict[str, str]) -> int:
    """Resolve the narrator completion-token ceiling from the environment.

    Returns :data:`_DEFAULT_NARRATOR_MAX_TOKENS` when unset or malformed so a
    bad value never silently disables the narrator.
    """
    raw = env.get(_NARRATOR_MAX_TOKENS_ENV, "").strip()
    if not raw:
        return _DEFAULT_NARRATOR_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_NARRATOR_MAX_TOKENS
    return value if value >= 1 else _DEFAULT_NARRATOR_MAX_TOKENS


def backend_from_env(
    env: dict[str, str] | None = None,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    metering_sink: MeteringSink | None = None,
) -> ChatBackend:
    """Resolve a ChatBackend from environment variables.

    Resolution order (first match wins):

    1. **API-key config** - ``FDAI_NARRATOR_BASE_URL`` +
       ``FDAI_NARRATOR_API_KEY`` + ``FDAI_NARRATOR_MODEL``
    (+ optional ``FDAI_NARRATOR_PROVIDER=openai|azure``,
    ``FDAI_NARRATOR_API_VERSION``).
     2. **Keyless Azure** - if ``resolved-models.json`` has a ``narrator``
         block, build an :class:`AzureAdChatBackend`. Production injects its
         managed identity; local development falls back to ``az login``.
         Every pull-direction channel reuses this backend through the read API.
    3. **Fallback** - :class:`DisabledChatBackend`; the FE falls back
       to its built-in deterministic answerer.
    """
    src = env if env is not None else dict(os.environ)
    max_tokens = _narrator_max_tokens(src)
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
                max_tokens=max_tokens,
            ),
            http_client=http_client,
            metering=_chat_metering(metering_sink, model),
        )
    # 2) Keyless Azure via resolved-models.json + az CLI.
    disk = _resolve_disk_azure_backend(
        src,
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        metering_sink=metering_sink,
    )
    if disk is not None:
        return disk
    return DisabledChatBackend()


def _resolve_disk_azure_backend(
    env: dict[str, str],
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int = _DEFAULT_NARRATOR_MAX_TOKENS,
    metering_sink: MeteringSink | None = None,
) -> ChatBackend | None:
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
    routed = _build_routed_backend(
        data.get("narrator_candidates"),
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        metering_sink=metering_sink,
    )
    if routed is not None:
        return routed
    # 2) Single narrator.
    return _build_single_azure_backend(
        data.get("narrator"),
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        metering_sink=metering_sink,
    )


def _build_single_azure_backend(
    narrator: Any,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int = _DEFAULT_NARRATOR_MAX_TOKENS,
    metering_sink: MeteringSink | None = None,
) -> AzureAdChatBackend | None:
    if not isinstance(narrator, dict):
        return None
    endpoint = narrator.get("endpoint")
    deployment = narrator.get("deployment")
    api_version = narrator.get("api_version")
    api_style = narrator.get("api_style", ModelApiStyle.AZURE_OPENAI.value)
    auth_audience = narrator.get("auth_audience", COGNITIVE_SERVICES_SCOPE)
    if not (isinstance(endpoint, str) and isinstance(deployment, str)):
        return None
    if not isinstance(api_style, str) or not isinstance(auth_audience, str):
        return None
    try:
        parsed_api_style = ModelApiStyle(api_style)
    except ValueError:
        return None
    return AzureAdChatBackend(
        endpoint=endpoint,
        deployment=deployment,
        api_version=api_version if isinstance(api_version, str) else "2024-08-01-preview",
        api_style=parsed_api_style,
        auth_audience=auth_audience,
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        metering=_chat_metering(metering_sink, deployment),
    )


def _build_routed_backend(
    raw: Any,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int = _DEFAULT_NARRATOR_MAX_TOKENS,
    metering_sink: MeteringSink | None = None,
) -> LatencyRoutedChatBackend | None:
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
        api_style = entry.get("api_style", ModelApiStyle.AZURE_OPENAI.value)
        auth_audience = entry.get("auth_audience", COGNITIVE_SERVICES_SCOPE)
        if not (isinstance(endpoint, str) and isinstance(deployment, str)):
            continue
        if not isinstance(api_style, str) or not isinstance(auth_audience, str):
            continue
        try:
            parsed_api_style = ModelApiStyle(api_style)
        except ValueError:
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
                    api_style=parsed_api_style,
                    auth_audience=auth_audience,
                    identity=identity,
                    http_client=http_client,
                    max_tokens=max_tokens,
                    metering=_chat_metering(metering_sink, deployment),
                ),
            )
        )
    if len(candidates) < 2:
        return None
    return LatencyRoutedChatBackend(candidates=candidates)


def _chat_metering(
    sink: MeteringSink | None,
    model_key: str,
) -> MeteringEmitter | None:
    if sink is None:
        return None
    return MeteringEmitter(
        sink=sink,
        capability_id="t1.judge",
        model_key=model_key,
        tier="T1",
    )


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
            "available": backend.has_available_candidate(),
            "mode": (
                "azure-ad-routed"
                if backend.has_available_candidate()
                else "azure-ad-routed-unavailable"
            ),
            "model": chose if backend.has_available_candidate() else None,
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
