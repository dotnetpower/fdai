"""Bind installation-scoped read-only discussions without inventing authorization."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from fdai_core_service.agent_discussion import AgentDiscussionPresenter

from fdai.agents import PantheonRuntime
from fdai.composition import Container
from fdai.composition.pantheon_synthesis import PantheonSynthesisBindings, build_pantheon_synthesis
from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.delivery.operational_evidence_configuration import (
    OperationalEvidenceSettings,
    load_registry_history,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.runtime.configuration import _model_endpoint_resolver

if TYPE_CHECKING:
    from fdai_core_service.semantic_turn_processor import SemanticTurnProcessor

    from fdai.runtime.bootstrap_pantheon_models import PantheonInitialization

_LOGGER = logging.getLogger(__name__)


def _runtime_asset_root() -> Path:
    """Locate shipped runtime assets in either checkout or installed image layout."""
    return repo_asset_root()


def bind_discussion(
    container: Container,
    environment: Mapping[str, str],
    pantheon: PantheonRuntime | None,
    processor: SemanticTurnProcessor,
) -> None:
    discussion = build_agent_discussion(
        container=container, environment=environment, pantheon=pantheon
    )
    if discussion is not None:
        processor.bind_agent_discussion(discussion)


def build_runtime_pantheon_synthesis(
    config: PantheonInitialization, asset_root: Path
) -> PantheonSynthesisBindings | None:
    bindings = config.container.llm_bindings
    if (
        bindings is None
        or bindings.conversation_t2_synthesizer is not None
        or bindings.conversation_synthesis_verifier is not None
    ):
        return None
    endpoint = config.environment.get("FDAI_LLM_ENDPOINT", "")
    return build_pantheon_synthesis(
        resolved=config.container.resolved_models,
        identity=config.identity,
        http_client=config.http_client,
        endpoint=endpoint or None,
        endpoint_resolver=_model_endpoint_resolver(
            endpoint, config.environment.get("FDAI_MODEL_ENDPOINTS_JSON")
        )
        if endpoint
        else None,
        catalog_root=asset_root / "rule-catalog",
        state_store=config.incident_audit_store,
        pricing=bindings.conversation_pricing,
        metering=bindings.conversation_metering,
        held_capabilities=config.container.held_model_capabilities,
    )


def build_agent_discussion(
    *,
    container: Container,
    environment: Mapping[str, str],
    pantheon: PantheonRuntime | None,
) -> AgentDiscussionPresenter | None:
    """Use only explicitly configured independent admission and exact installation grants."""
    installation = environment.get("FDAI_PANTHEON_INSTALLATION_REF", "")
    scope = environment.get("FDAI_PANTHEON_DISCUSSION_SCOPE_DIGEST", "")
    settings = OperationalEvidenceSettings.from_environment(environment)
    if (
        pantheon is None
        or not settings.enabled
        or container.operational_evidence_requester is None
        or container.decision_evidence_admission_provider is None
        or not installation.startswith("pantheon-installation:")
        or re.fullmatch(r"sha256:[a-f0-9]{64}", scope) is None
    ):
        return None
    try:
        history = load_registry_history(settings, root=repo_asset_root())
        grant = history.current.grants.scope_for(scope.removeprefix("sha256:"))
        if (
            grant is None
            or grant.resource_selectors != (installation,)
            or ("agent-discussion-read" not in grant.purposes)
        ):
            return None
    except (OSError, RegistryUnavailableError, ValueError):
        _LOGGER.warning("agent_discussion_unavailable", extra={"reason": "registry_unavailable"})
        return None
    return AgentDiscussionPresenter(
        runtime=pantheon,
        admission=container.decision_evidence_admission_provider,
        evidence=container.operational_evidence_requester,
        installation_ref=installation,
        access_scope_digest=scope,
        source_revision=history.current.grants.pin,
    )
