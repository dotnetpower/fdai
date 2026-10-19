"""Apply the audited collection preference without granting forecast-scoring authority."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fdai.core.detection.forecast_history_ingress import ForecastHistoryCollector
from fdai.delivery.runtime_settings import RuntimeSettingsService, RuntimeSettingsUnavailableError
from fdai.shared.providers.forecast_context import (
    ForecastContextRequest,
    ForecastContextUnavailableError,
)

_LOGGER = logging.getLogger(__name__)
FORECAST_HISTORY_COLLECTION_KEY = "forecast.history_collection.enabled"


class PreferenceGatedForecastHistoryCollector:
    """Recheck durable preference before collection and before returning its result."""

    def __init__(
        self, *, collector: ForecastHistoryCollector, settings: RuntimeSettingsService
    ) -> None:
        self._collector = collector
        self._settings = settings

    async def _preference(self) -> tuple[bool, int]:
        if not self._settings.durable:
            raise RuntimeSettingsUnavailableError("forecast history requires durable settings")
        return await self._settings.forecast_history_collection_preference()

    async def collect(self, request: ForecastContextRequest) -> Mapping[str, Any]:
        enabled, revision = await self._preference()
        if not enabled:
            _LOGGER.info("forecast_history_collection_disabled")
            raise ForecastContextUnavailableError("forecast history collection is disabled")
        result = await self._collector.collect(request)
        if await self._preference() != (True, revision):
            _LOGGER.info("forecast_history_collection_preference_withdrawn")
            raise ForecastContextUnavailableError("forecast history collection preference changed")
        return result
