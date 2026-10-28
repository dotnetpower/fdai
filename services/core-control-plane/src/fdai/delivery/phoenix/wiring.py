"""Composition helper that mirrors a metering store to Phoenix when the flag is on."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fdai.delivery.phoenix.metering_sink import PhoenixMeteringSink, phoenix_config_from_env

_LOGGER = logging.getLogger(__name__)


def observe_metering_store(store: Any, env: Mapping[str, str]) -> Any:
    """Return ``store`` unchanged unless Phoenix tracing is enabled and valid in ``env``.

    When enabled, wrap ``store`` so each record is also exported as a span, and register the
    conversation model-trace observer. The wrapped store remains the system of record.
    """
    config = phoenix_config_from_env(env)
    if config is None:
        return store

    from fdai.core.metering import ObservedMeteringStore
    from fdai.delivery.azure.llm.model_trace import register_model_trace_observer

    sink = PhoenixMeteringSink.from_config(config)
    register_model_trace_observer(sink.record_model_trace)
    _LOGGER.info(
        "metering_observer",
        extra={
            "observer": "phoenix",
            "project": config.project_name,
            "capture_content": config.capture_content,
        },
    )
    return ObservedMeteringStore(store, (sink,))
