"""Validated environment snapshots for composition entry points."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from fdai.shared.config.loader import load_config_from_env
from fdai.shared.config.models import AppConfig
from fdai.shared.config.provider import EnvVarConfigProvider


def load_environment_config(
    environ: Mapping[str, str] | None,
) -> tuple[AppConfig, int]:
    """Return validated config and telemetry level from one environment snapshot."""

    environment = os.environ if environ is None else environ
    config = load_config_from_env() if environ is None else EnvVarConfigProvider(environment).get()
    level = getattr(
        logging, environment.get("FDAI_LOG_LEVEL", "INFO").upper().strip(), logging.INFO
    )
    return config, level if isinstance(level, int) else logging.INFO


__all__ = ["load_environment_config"]
