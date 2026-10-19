"""Observe fully settled native cross-check rounds, never inferred action outcomes."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fdai_service_contracts.self_health import SelfHealthSignalName

from fdai.core.quality_gate._verification import CrossCheckObserver, CrossCheckRoundObservation
from fdai.core.quality_gate.gate import CrossCheckModel
from fdai.delivery.self_health_verifier import _RuntimeWindowedHealthSource
from fdai.shared.providers.self_health import (
    ModelProviderObservedProvider,
    SelfHealthExporterUnavailableError,
)

_LOGGER = logging.getLogger(__name__)


def _native_model(model: CrossCheckModel) -> bool:
    """A source descriptor alone cannot establish its caller's actual SDK producer lineage."""
    from fdai.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel
    from fdai.delivery.azure.llm.latency_routed_cross_check import LatencyRoutedCrossCheckModel

    if type(model) is AzureOpenAICrossCheckModel:
        return True
    if type(model) is LatencyRoutedCrossCheckModel:
        return all(
            type(member) is AzureOpenAICrossCheckModel
            for member in model.model_provider_observation_members
        )
    return False


class RuntimeMixedModelHealthSource(_RuntimeWindowedHealthSource):
    """Observe native groups; custom producers need an independently reviewed exporter."""

    signal = SelfHealthSignalName.MIXED_MODEL_DISAGREEMENT_RATE
    _source_prefix = "runtime:t2-cross-check"
    _diagnostic_prefix = "mixed_model_health"
    _bound_models: tuple[CrossCheckModel, ...] = ()

    def bind(self, models: tuple[CrossCheckModel, ...]) -> CrossCheckObserver | None:
        roles: list[str] = []
        for model in models:
            if not isinstance(model, ModelProviderObservedProvider):
                _LOGGER.info("mixed_model_health_source_unavailable")
                return None
            if not _native_model(model):
                _LOGGER.info("mixed_model_health_source_unsupported")
                return None
            try:
                source = model.model_provider_observations(
                    maximum_age_seconds=self._window_ticks // 1_000_000_000
                )
            except SelfHealthExporterUnavailableError as exc:
                _LOGGER.info("mixed_model_health_source_unavailable", extra={"reason": exc.reason})
                return None
            roles.append(source.role)
        if sorted(roles) != ["t2.reasoner.primary", "t2.reasoner.secondary"]:
            _LOGGER.warning("mixed_model_health_role_coverage_incomplete")
            return None
        self._bind()
        self._bound_models = tuple(models)
        return self

    @contextmanager
    def observe_round(
        self, models: tuple[CrossCheckModel, ...]
    ) -> Iterator[CrossCheckRoundObservation]:
        observation = CrossCheckRoundObservation()
        bound = len(models) == len(self._bound_models) and all(
            model is expected for model, expected in zip(models, self._bound_models, strict=True)
        )
        if not bound:
            _LOGGER.error("mixed_model_health_binding_mismatch")
        self._pending += 1
        try:
            yield observation
        finally:
            self._pending -= 1
            self._record(
                observation.all_agreed,
                known=bound and observation.all_agreed is not None,
            )
