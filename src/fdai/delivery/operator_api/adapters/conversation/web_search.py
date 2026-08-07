"""Azure web-search adapter construction for Operator Console conversations."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import httpx

from fdai.delivery.azure.web_search import (
    AzureResponsesWebSearchCandidate,
    AzureResponsesWebSearchConfig,
    FoundryAgentWebSearchCandidate,
    FoundryAgentWebSearchConfig,
    LatencyRoutedWebSearchProvider,
    WebSearchModelCandidate,
)
from fdai.delivery.operator_api.application.conversation.capabilities.web_search import (
    ChatWebSearchConfig,
    ChatWebSearchResolver,
    WebSearchDeploymentDescriptor,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ENABLED_ENV: Final = "FDAI_WEB_SEARCH_ENABLED"
_DOMAINS_ENV: Final = "FDAI_WEB_SEARCH_ALLOWED_DOMAINS"
_MAX_RESULTS_ENV: Final = "FDAI_WEB_SEARCH_MAX_RESULTS"
_BUDGET_MS_ENV: Final = "FDAI_WEB_SEARCH_BUDGET_MS"
_PROBE_INTERVAL_ENV: Final = "FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS"
_FOUNDRY_PROJECT_ENDPOINT_ENV: Final = "FDAI_WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT"
_FOUNDRY_AGENT_NAME_ENV: Final = "FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME"
_FOUNDRY_MODEL_DEPLOYMENT_ENV: Final = "FDAI_WEB_SEARCH_FOUNDRY_MODEL_DEPLOYMENT"
_RESOLVED_MODELS_ENV: Final = "LLM_RESOLVED_MODELS_PATH"

_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$", re.IGNORECASE)


def chat_web_search_from_env(
    env: Mapping[str, str] | None = None,
    *,
    identity: WorkloadIdentity | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ChatWebSearchResolver | None:
    """Build the opt-in Azure Responses web-search resolver from config."""

    source = env if env is not None else os.environ
    if not _parse_enabled(source.get(_ENABLED_ENV)):
        return None
    domains = _parse_domains(source.get(_DOMAINS_ENV, ""))
    config = ChatWebSearchConfig(
        allowed_domains=domains,
        max_results=_parse_int(source, _MAX_RESULTS_ENV, 3),
        budget_ms=_parse_int(source, _BUDGET_MS_ENV, 15_000),
        probe_interval_seconds=_parse_int(source, _PROBE_INTERVAL_ENV, 300),
    )
    model_data = _load_resolved_models(source)
    raw_candidates = model_data.get("web_search_candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    candidates: list[tuple[str, WebSearchModelCandidate]] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        endpoint = raw.get("endpoint")
        deployment = raw.get("deployment")
        if not isinstance(endpoint, str) or not isinstance(deployment, str):
            continue
        if deployment in seen:
            continue
        seen.add(deployment)
        candidates.append(
            (
                deployment,
                AzureResponsesWebSearchCandidate(
                    config=AzureResponsesWebSearchConfig(
                        endpoint=endpoint,
                        deployment=deployment,
                    ),
                    identity=identity,
                    http_client=http_client,
                ),
            )
        )
    if not candidates:
        raise ValueError(
            "web search is enabled but resolved-models.json has no web-search candidates"
        )
    direct_model_deployment = candidates[0][0]
    foundry_project_endpoint = source.get(_FOUNDRY_PROJECT_ENDPOINT_ENV, "").strip()
    foundry_agent_name = source.get(_FOUNDRY_AGENT_NAME_ENV, "").strip()
    if bool(foundry_project_endpoint) != bool(foundry_agent_name):
        raise ValueError(
            f"{_FOUNDRY_PROJECT_ENDPOINT_ENV} and {_FOUNDRY_AGENT_NAME_ENV} "
            "MUST be configured together"
        )
    deployment = WebSearchDeploymentDescriptor(model_deployment=direct_model_deployment)
    if foundry_project_endpoint:
        intent_candidate = candidates[0][1]
        foundry_model_deployment = (
            source.get(_FOUNDRY_MODEL_DEPLOYMENT_ENV, "").strip() or direct_model_deployment
        )
        candidates = [
            (
                f"foundry-agent:{foundry_agent_name}",
                FoundryAgentWebSearchCandidate(
                    config=FoundryAgentWebSearchConfig(
                        project_endpoint=foundry_project_endpoint,
                        agent_name=foundry_agent_name,
                        allowed_domains=config.allowed_domains,
                    ),
                    intent_candidate=intent_candidate,
                    identity=identity,
                    http_client=http_client,
                ),
            )
        ]
        deployment = WebSearchDeploymentDescriptor(
            provider="foundry-agent",
            project_configured=True,
            agent_name=foundry_agent_name,
            model_deployment=foundry_model_deployment,
        )
    provider = LatencyRoutedWebSearchProvider(candidates=candidates)
    return ChatWebSearchResolver(
        provider=provider,
        intent_classifier=provider,
        config=config,
        deployment=deployment,
    )


def _parse_enabled(raw: str | None) -> bool:
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{_ENABLED_ENV} MUST be a boolean")


def _parse_domains(raw: str) -> tuple[str, ...]:
    domains = tuple(
        dict.fromkeys(part.strip().lower().rstrip(".") for part in raw.split(",") if part.strip())
    )
    if not domains:
        raise ValueError(f"{_DOMAINS_ENV} MUST contain at least one domain")
    if any(_DOMAIN.fullmatch(domain) is None for domain in domains):
        raise ValueError(f"{_DOMAINS_ENV} contains an invalid domain")
    return domains


def _parse_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc


def _load_resolved_models(source: Mapping[str, str]) -> Mapping[str, Any]:
    path = _find_resolved_models(source)
    if path is None:
        raise ValueError("web search is enabled but LLM_RESOLVED_MODELS_PATH could not be resolved")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("resolved-models.json is not readable JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("resolved-models.json MUST contain an object")
    return payload


def _find_resolved_models(source: Mapping[str, str]) -> Path | None:
    explicit = source.get(_RESOLVED_MODELS_ENV)
    if explicit is not None:
        path = Path(explicit)
        return path if path.is_file() else None
    for start in (Path.cwd(), Path(__file__).resolve()):
        for directory in (start, *start.parents):
            candidate = directory / "resolved-models.json"
            if candidate.is_file():
                return candidate
    return None


__all__ = ["chat_web_search_from_env"]
