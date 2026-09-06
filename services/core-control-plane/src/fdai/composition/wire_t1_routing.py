"""Compose opt-in presentation probes from the same verified model registry."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

import httpx

from fdai.core.conversation.adaptive_models import DEFAULT_ADAPTIVE_POLICY
from fdai.delivery.azure.llm.t1_latency import T1MiniRouting
from fdai.delivery.azure.llm.t1_probe import T1MiniProbe
from fdai.shared.config.models import LlmMode
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container
from .adaptive_model_targets import resolved_model_config, t1_narrator_targets
from .resolved_models_revision import resolved_models_for_binding

_LOGGER = logging.getLogger(__name__)


def build_t1_mini_probe(
    *,
    container: Container,
    environment: Mapping[str, str],
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    state_store: StateStore,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
) -> T1MiniProbe | None:
    """Bind without network calls; billed synthetic probes require explicit opt-in."""
    enabled_raw = environment.get("FDAI_T1_MINI_PROBE_ENABLED", "0").strip().lower()
    if enabled_raw not in {"0", "1", "false", "true"}:
        raise ValueError("FDAI_T1_MINI_PROBE_ENABLED MUST be 0, 1, false, or true")
    interval = int(environment.get("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS", "300"))
    if not 30 <= interval <= 3600:
        raise ValueError("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS MUST be in [30, 3600]")
    if (
        container.config.llm.mode != LlmMode.AZURE
        or container.config.llm.resolved_models_path is None
        or identity is None
        or http_client is None
    ):
        return None
    resolved = resolved_models_for_binding(container)
    config = resolved_model_config(
        resolved,
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
        held_capabilities=container.held_model_capabilities,
        timeout_seconds=DEFAULT_ADAPTIVE_POLICY.per_stage_seconds,
        max_tokens=DEFAULT_ADAPTIVE_POLICY.reserved_output_tokens,
    )
    candidates = t1_narrator_targets(resolved, container.held_model_capabilities)
    minis = tuple(item for item in candidates if item.family.casefold().endswith("-mini"))
    if config is None or len(minis) < 2:
        _LOGGER.warning("t1_mini_routing_unavailable", extra={"reason": "independent_pair_missing"})
        return None
    routing = T1MiniRouting(
        candidates=minis,
        config=config,
        identity=identity,
        http_client=http_client,
        enabled=enabled_raw in {"1", "true"},
        interval_seconds=interval,
    )
    return T1MiniProbe(
        routing=routing,
        identity=identity,
        http_client=http_client,
        state_store=state_store,
    )
