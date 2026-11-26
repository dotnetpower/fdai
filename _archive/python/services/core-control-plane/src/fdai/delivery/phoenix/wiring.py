"""Composition helper that mirrors a metering store to Phoenix and Application Insights."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fdai.delivery.phoenix.app_insights_sink import app_insights_llm_sink_from_env
from fdai.delivery.phoenix.metering_sink import PhoenixMeteringSink, phoenix_config_from_env

_LOGGER = logging.getLogger(__name__)


def observe_metering_store(store: Any, env: Mapping[str, str]) -> Any:
    """Return ``store`` unchanged unless Phoenix or Application Insights LLM tracing is configured.

    When enabled, wrap ``store`` so each record is also exported as a span, and register the
    model-trace observers. The wrapped store remains the system of record.
    """
    from fdai.core.metering import ObservedMeteringStore
    from fdai.delivery.azure.llm.model_trace import register_model_trace_observer

    observers: list[Any] = []
    config = phoenix_config_from_env(env)
    if config is not None:
        sink = PhoenixMeteringSink.from_config(config)
        register_model_trace_observer(sink.record_model_trace)
        observers.append(sink)
        _LOGGER.info(
            "metering_observer",
            extra={
                "observer": "phoenix",
                "project": config.project_name,
                "capture_content": config.capture_content,
            },
        )
    app_insights_sink = app_insights_llm_sink_from_env(env)
    if app_insights_sink is not None:
        register_model_trace_observer(app_insights_sink.record_model_trace)
        observers.append(app_insights_sink)
        effective = app_insights_sink._effective_config()
        _LOGGER.info(
            "metering_observer",
            extra={
                "observer": "application_insights",
                "tracing_enabled": effective.tracing_enabled,
                "capture_content": effective.capture_content,
            },
        )
    if not observers:
        return store
    return ObservedMeteringStore(store, tuple(observers))
