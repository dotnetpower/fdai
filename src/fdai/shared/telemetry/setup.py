"""One-call telemetry initialization for the composition root.

Wires up JSON logging, OpenTelemetry tracing (console exporter), and OTel
metrics (in-memory reader) using values pulled from :class:`AppConfig`.
Callers do NOT need to configure the individual sub-systems - they call
:func:`configure_telemetry` once and inherit the rest.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from fdai.shared.config.models import AppConfig

from .logging import configure_logging
from .metrics import configure_metrics
from .tracing import configure_tracing

_SERVICE_NAME = "fdai"


def configure_telemetry(config: AppConfig, *, level: int = logging.INFO) -> None:
    """Wire logging + tracing + metrics from :class:`AppConfig`.

    Idempotent at the sub-system layer - each of ``configure_logging``,
    ``configure_tracing``, and ``configure_metrics`` guards against
    repeated installation.
    """
    configure_logging(
        level=level,
        warning_log_path=_local_warning_log_path(config, Path.cwd()),
    )
    endpoint, insecure = _otlp_config(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    configure_tracing(
        service_name=_SERVICE_NAME,
        env=config.runtime.env,
        otlp_endpoint=endpoint,
        otlp_insecure=insecure,
    )
    configure_metrics(
        service_name=_SERVICE_NAME,
        env=config.runtime.env,
        otlp_endpoint=endpoint,
        otlp_insecure=insecure,
    )


def _local_warning_log_path(
    config: AppConfig,
    start: Path,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    resolved_environ = os.environ if environ is None else environ
    if config.runtime.env != "dev" or "PYTEST_CURRENT_TEST" in resolved_environ:
        return None
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() and (candidate / "src/fdai").is_dir():
            return candidate / ".fdai/logs/warnings.jsonl"
    return None


def _otlp_config(raw: str) -> tuple[str | None, bool]:
    value = raw.strip()
    if not value:
        return None, False
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OTLP endpoint MUST be an absolute credential-free HTTP(S) URL")
    insecure = parsed.scheme == "http"
    if insecure and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("OTLP endpoint MUST use HTTPS outside loopback")
    return value, insecure


__all__ = ["configure_telemetry"]
