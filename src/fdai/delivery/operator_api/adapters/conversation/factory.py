"""Environment factory and public metadata for chat backends."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

import httpx

from fdai.core.metering import MeteringEmitter, MeteringSink, PricingTable
from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE
from fdai.delivery.operator_api.adapters.conversation.azure import AzureAdChatBackend
from fdai.delivery.operator_api.adapters.conversation.openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    DisabledChatBackend,
    LatencyRoutedChatBackend,
)
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
_DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS = 30.0
_NARRATOR_TURN_TIMEOUT_SECONDS_ENV = "FDAI_NARRATOR_TURN_TIMEOUT_SECONDS"


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


def _narrator_turn_timeout_seconds(env: dict[str, str]) -> float:
    """Resolve the total routed-turn deadline from bounded configuration."""

    raw = env.get(_NARRATOR_TURN_TIMEOUT_SECONDS_ENV, "").strip()
    if not raw:
        return _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS
    return value if 1.0 <= value <= 300.0 else _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS


def backend_from_env(
    env: dict[str, str] | None = None,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    metering_sink: MeteringSink | None = None,
    pricing: PricingTable | None = None,
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
         Every pull-direction channel reuses this backend through the Operator API.
    3. **Fallback** - :class:`DisabledChatBackend`; the FE falls back
       to its built-in deterministic answerer.
    """
    src = env if env is not None else dict(os.environ)
    max_tokens = _narrator_max_tokens(src)
    turn_timeout_seconds = _narrator_turn_timeout_seconds(src)
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
            metering=_chat_metering(metering_sink, model, pricing=pricing),
        )
    # 2) Keyless Azure via resolved-models.json + az CLI.
    disk = _resolve_disk_azure_backend(
        src,
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        turn_timeout_seconds=turn_timeout_seconds,
        metering_sink=metering_sink,
        pricing=pricing,
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
    turn_timeout_seconds: float = _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS,
    metering_sink: MeteringSink | None = None,
    pricing: PricingTable | None = None,
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
    resolved_model_keys = _resolved_model_keys(data)
    vision_candidates = _validated_vision_candidates(data)
    # 1) Multi-candidate router (preferred when present).
    routed = _build_routed_backend(
        data.get("narrator_candidates"),
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        turn_timeout_seconds=turn_timeout_seconds,
        metering_sink=metering_sink,
        pricing=pricing,
        resolved_model_keys=resolved_model_keys,
    )
    if routed is not None:
        vision_backend = _build_candidate_pool(
            vision_candidates,
            identity=identity,
            http_client=http_client,
            max_tokens=max_tokens,
            turn_timeout_seconds=turn_timeout_seconds,
            metering_sink=metering_sink,
            pricing=pricing,
            resolved_model_keys=resolved_model_keys,
            vision_capable=True,
        )
        if vision_backend is not None:
            routed.bind_vision_backend(vision_backend)
        return routed
    # 2) Single narrator. Wrap it only when image dispatch needs the same
    # capability-aware boundary as the multi-candidate router.
    single = _build_single_azure_backend(
        data.get("narrator"),
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        metering_sink=metering_sink,
        pricing=pricing,
        resolved_model_keys=resolved_model_keys,
    )
    if single is None:
        return None
    vision_backend = _build_candidate_pool(
        vision_candidates,
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        turn_timeout_seconds=turn_timeout_seconds,
        metering_sink=metering_sink,
        pricing=pricing,
        resolved_model_keys=resolved_model_keys,
        vision_capable=True,
    )
    narrator = data.get("narrator")
    if vision_backend is None or not isinstance(narrator, dict):
        return single
    deployment = narrator.get("deployment")
    if not isinstance(deployment, str):
        return single
    wrapped = LatencyRoutedChatBackend(
        candidates=[(deployment, single)],
        turn_timeout_seconds=turn_timeout_seconds,
    )
    wrapped.bind_vision_backend(vision_backend)
    return wrapped


def _build_single_azure_backend(
    narrator: Any,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int = _DEFAULT_NARRATOR_MAX_TOKENS,
    metering_sink: MeteringSink | None = None,
    pricing: PricingTable | None = None,
    resolved_model_keys: Mapping[str, str] | None = None,
    metering_capability_id: str = "t1.judge",
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
        metering=_chat_metering(
            metering_sink,
            deployment,
            pricing=pricing,
            resolved_model_keys=resolved_model_keys,
            capability_id=metering_capability_id,
        ),
    )


def _candidate_route(entry: Any) -> tuple[str, str, str, str, str] | None:
    if not isinstance(entry, dict):
        return None
    endpoint = entry.get("endpoint")
    deployment = entry.get("deployment")
    api_version = entry.get("api_version", "2024-08-01-preview")
    api_style = entry.get("api_style", ModelApiStyle.AZURE_OPENAI.value)
    auth_audience = entry.get("auth_audience", COGNITIVE_SERVICES_SCOPE)
    if (
        not isinstance(endpoint, str)
        or not endpoint.strip()
        or not isinstance(deployment, str)
        or not deployment.strip()
        or not isinstance(api_version, str)
        or not api_version.strip()
        or not isinstance(api_style, str)
        or not api_style.strip()
        or not isinstance(auth_audience, str)
        or not auth_audience.strip()
    ):
        return None
    return endpoint, deployment, api_version, api_style, auth_audience


def _validated_vision_candidates(data: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    raw = data.get("vision_candidates")
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    narrator_raw = data.get("narrator_candidates")
    narrator_entries = (
        narrator_raw if isinstance(narrator_raw, list) and narrator_raw else [data.get("narrator")]
    )
    narrator_routes = {
        route[1]: route
        for entry in narrator_entries
        if (route := _candidate_route(entry)) is not None
    }
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        route = _candidate_route(entry)
        if route is None or route[1] in seen or narrator_routes.get(route[1]) != route:
            return None
        seen.add(route[1])
        validated.append(entry)
    return validated


def _build_routed_backend(
    raw: Any,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int = _DEFAULT_NARRATOR_MAX_TOKENS,
    turn_timeout_seconds: float = _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS,
    metering_sink: MeteringSink | None = None,
    pricing: PricingTable | None = None,
    resolved_model_keys: Mapping[str, str] | None = None,
    vision_capable: bool = False,
    metering_capability_id: str = "t1.judge",
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
                    metering=_chat_metering(
                        metering_sink,
                        deployment,
                        pricing=pricing,
                        resolved_model_keys=resolved_model_keys,
                        capability_id=metering_capability_id,
                    ),
                ),
            )
        )
    if len(candidates) < 2:
        return None
    return LatencyRoutedChatBackend(
        candidates=candidates,
        turn_timeout_seconds=turn_timeout_seconds,
        vision_capable=vision_capable,
    )


def _build_candidate_pool(
    raw: Any,
    *,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    max_tokens: int,
    turn_timeout_seconds: float,
    metering_sink: MeteringSink | None,
    pricing: PricingTable | None,
    resolved_model_keys: Mapping[str, str],
    vision_capable: bool,
) -> ChatBackend | None:
    routed = _build_routed_backend(
        raw,
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        turn_timeout_seconds=turn_timeout_seconds,
        metering_sink=metering_sink,
        pricing=pricing,
        resolved_model_keys=resolved_model_keys,
        vision_capable=vision_capable,
        metering_capability_id=("t1.vision" if vision_capable else "t1.judge"),
    )
    if routed is not None:
        return routed
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        return None
    single = _build_single_azure_backend(
        raw[0],
        identity=identity,
        http_client=http_client,
        max_tokens=max_tokens,
        metering_sink=metering_sink,
        pricing=pricing,
        resolved_model_keys=resolved_model_keys,
        metering_capability_id=("t1.vision" if vision_capable else "t1.judge"),
    )
    if single is None or not vision_capable:
        return single
    deployment = raw[0].get("deployment")
    if not isinstance(deployment, str):
        return None
    return LatencyRoutedChatBackend(
        candidates=[(deployment, single)],
        turn_timeout_seconds=turn_timeout_seconds,
        vision_capable=True,
    )


def _chat_metering(
    sink: MeteringSink | None,
    model_key: str,
    *,
    pricing: PricingTable | None = None,
    resolved_model_keys: Mapping[str, str] | None = None,
    capability_id: str = "t1.judge",
) -> MeteringEmitter | None:
    if sink is None:
        return None
    resolved_model_key = (resolved_model_keys or {}).get(model_key, model_key)
    return MeteringEmitter(
        sink=sink,
        capability_id=capability_id,
        model_key=resolved_model_key,
        tier="T1",
        pricing=pricing,
    )


def _resolved_model_keys(data: Mapping[str, Any]) -> dict[str, str]:
    """Return explicit deployment-to-family bindings from resolver output."""

    result: dict[str, str] = {}
    ambiguous: set[str] = set()
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        return result
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        deployment = capability.get("name")
        family = capability.get("family")
        if not isinstance(deployment, str) or not deployment:
            continue
        if not isinstance(family, str) or not family:
            continue
        existing = result.get(deployment)
        if existing is not None and existing != family:
            ambiguous.add(deployment)
            result.pop(deployment, None)
        elif deployment not in ambiguous:
            result[deployment] = family
    return result


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
