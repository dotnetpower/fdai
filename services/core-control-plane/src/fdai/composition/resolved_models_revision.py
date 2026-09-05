"""Attach and expose the startup-owned resolved-model revision."""

from __future__ import annotations

import hmac
from dataclasses import replace

from ..rule_catalog.schema.llm_resolver import ResolvedModels
from ._helpers import Container, LlmBindingsUnavailableError
from .resolved_models import _load_resolved_models


def bind_resolved_models_revision(
    container: Container,
    *,
    models: ResolvedModels,
    artifact_digest: str,
    held_capabilities: tuple[str, ...] = (),
) -> Container:
    """Attach the immutable revision used by every production model binder."""

    expected = container.config.llm.resolved_models_sha256
    if expected is None or not hmac.compare_digest(artifact_digest, expected):
        raise LlmBindingsUnavailableError(
            "resolved-model startup revision does not match the deployment binding"
        )
    held = frozenset(held_capabilities)
    known = {capability.name for capability in models.capabilities}
    if not held.issubset(known):
        raise LlmBindingsUnavailableError(
            "model lifecycle hold references an unknown resolved capability"
        )
    return replace(
        container,
        resolved_models=models,
        resolved_models_artifact_digest=artifact_digest,
        held_model_capabilities=held,
    )


def resolved_models_for_binding(container: Container) -> ResolvedModels:
    """Return the startup-owned revision, retaining direct-call compatibility."""

    if container.resolved_models is not None:
        expected = container.config.llm.resolved_models_sha256
        observed = container.resolved_models_artifact_digest
        if expected is None or observed is None or not hmac.compare_digest(observed, expected):
            raise LlmBindingsUnavailableError(
                "resolved-model startup revision does not match the deployment binding"
            )
        return container.resolved_models
    path = container.config.llm.resolved_models_path
    if path is None:
        raise LlmBindingsUnavailableError("Azure LLM wiring requires resolved model bindings")
    return _load_resolved_models(
        path,
        expected_digest=container.config.llm.resolved_models_sha256,
    )


__all__ = ["bind_resolved_models_revision", "resolved_models_for_binding"]
