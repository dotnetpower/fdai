"""Export redacted LLM call spans and structured logs to Application Insights.

When ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is configured, Azure Monitor OpenTelemetry Distro
wires the global :mod:`opentelemetry.trace` provider and the ``fdai`` logger hierarchy. This sink
routes metered :class:`~fdai.core.metering.records.LlmInvocation` records and completed
model-call traces through that global tracer and ``fdai.telemetry.llm`` logger whenever the
Runtime Settings ``logging.app_insights.llm_tracing.enabled`` or
``logging.app_insights.llm_prompt_capture.enabled`` are enabled.

Prompt and response content is already redacted and bounded by
:mod:`fdai.delivery.azure.llm.model_trace` before reaching this observer, and is attached only
when ``logging.app_insights.llm_prompt_capture.enabled`` (or its environment default
``FDAI_APPINSIGHTS_LLM_CAPTURE_CONTENT``) is true. Setting changes apply immediately to
subsequent model calls without a process restart.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from opentelemetry import trace as trace_api
from opentelemetry.trace import Status, StatusCode, Tracer

from fdai.core.metering.records import LlmInvocation
from fdai.delivery.azure.llm.model_trace import (
    content_free_model_trace,
    register_model_trace_observer,
    register_model_trace_reset_hook,
)
from fdai.delivery.phoenix.model_trace_span import model_trace_attributes, model_trace_timing
from fdai.shared.telemetry.correlation import current_correlation_id

CONNECTION_STRING_ENV = "APPLICATIONINSIGHTS_CONNECTION_STRING"
TRACING_ENABLED_ENV = "FDAI_APPINSIGHTS_LLM_TRACING_ENABLED"
CAPTURE_CONTENT_ENV = "FDAI_APPINSIGHTS_LLM_CAPTURE_CONTENT"

TRACING_SETTING_KEY = "logging.app_insights.llm_tracing.enabled"
CAPTURE_CONTENT_SETTING_KEY = "logging.app_insights.llm_prompt_capture.enabled"

TRACER_NAME = "fdai.telemetry.llm"
LOGGER_NAME = "fdai.telemetry.llm"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_NS_PER_MS = 1_000_000
_LOGGER = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True, slots=True)
class AppInsightsLlmTraceConfig:
    """Effective Application Insights LLM trace and prompt capture policy."""

    tracing_enabled: bool = False
    capture_content: bool = False

    @property
    def active(self) -> bool:
        """Enabling prompt capture also enables the enclosing LLM call span and log."""
        return self.tracing_enabled or self.capture_content


_RUNTIME_POLICY_OVERRIDE: AppInsightsLlmTraceConfig | None = None
_DEFAULT_SINK: AppInsightsLlmTraceSink | None = None


def app_insights_connection_configured(env: Mapping[str, str] | None = None) -> bool:
    """Return whether an Application Insights connection string is present in ``env``."""
    resolved = os.environ if env is None else env
    return bool(resolved.get(CONNECTION_STRING_ENV, "").strip())


def app_insights_llm_config_from_env(
    env: Mapping[str, str] | None = None,
) -> AppInsightsLlmTraceConfig:
    """Resolve the startup default policy from environment variables."""
    resolved = os.environ if env is None else env
    tracing_enabled = resolved.get(TRACING_ENABLED_ENV, "").strip().casefold() in _TRUTHY
    capture_content = resolved.get(CAPTURE_CONTENT_ENV, "").strip().casefold() in _TRUTHY
    return AppInsightsLlmTraceConfig(
        tracing_enabled=tracing_enabled,
        capture_content=capture_content,
    )


def current_app_insights_llm_config(
    env: Mapping[str, str] | None = None,
) -> AppInsightsLlmTraceConfig:
    """Return the latest durable Runtime Settings policy, falling back to ``env``."""
    if _RUNTIME_POLICY_OVERRIDE is not None:
        return _RUNTIME_POLICY_OVERRIDE
    return app_insights_llm_config_from_env(env)


def apply_app_insights_llm_settings(
    values: Mapping[str, object],
    *,
    env: Mapping[str, str] | None = None,
) -> AppInsightsLlmTraceConfig:
    """Synchronize the in-process LLM trace policy from effective Runtime Settings."""
    global _RUNTIME_POLICY_OVERRIDE, _DEFAULT_SINK
    tracing_raw = values.get(TRACING_SETTING_KEY)
    capture_raw = values.get(CAPTURE_CONTENT_SETTING_KEY)
    if not isinstance(tracing_raw, bool) and not isinstance(capture_raw, bool):
        return current_app_insights_llm_config(env)
    fallback = app_insights_llm_config_from_env(env)
    config = AppInsightsLlmTraceConfig(
        tracing_enabled=tracing_raw if isinstance(tracing_raw, bool) else fallback.tracing_enabled,
        capture_content=capture_raw if isinstance(capture_raw, bool) else fallback.capture_content,
    )
    _RUNTIME_POLICY_OVERRIDE = config
    if config.active and app_insights_connection_configured(env):
        if _DEFAULT_SINK is None:
            _DEFAULT_SINK = AppInsightsLlmTraceSink(env=env)
        register_model_trace_observer(_DEFAULT_SINK.record_model_trace)
    return config


def reset_app_insights_llm_settings() -> None:
    """Clear the in-process Runtime Settings override for test isolation."""
    global _RUNTIME_POLICY_OVERRIDE, _DEFAULT_SINK
    _RUNTIME_POLICY_OVERRIDE = None
    _DEFAULT_SINK = None


def app_insights_llm_sink_from_env(
    env: Mapping[str, str],
) -> AppInsightsLlmTraceSink | None:
    """Build the Application Insights LLM sink when Application Insights is configured.

    Attaching the sink whenever ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is present lets
    an operator toggle ``logging.app_insights.llm_tracing.enabled`` or
    ``logging.app_insights.llm_prompt_capture.enabled`` in Runtime Settings and have subsequent
    LLM calls exported immediately without restarting the service.
    """
    global _DEFAULT_SINK
    if not app_insights_connection_configured(env):
        return None
    sink = AppInsightsLlmTraceSink(env=env)
    _DEFAULT_SINK = sink
    return sink


register_model_trace_reset_hook(reset_app_insights_llm_settings)


class AppInsightsLlmTraceSink:
    """Export LLM invocations and redacted model traces to Application Insights."""

    def __init__(
        self,
        *,
        tracer: Tracer | None = None,
        logger: logging.Logger | None = None,
        config: AppInsightsLlmTraceConfig | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._tracer = tracer
        self._logger = logger or _LOGGER
        self._explicit_config = config
        self._env = env

    def _effective_config(self) -> AppInsightsLlmTraceConfig:
        if self._explicit_config is not None:
            return self._explicit_config
        return current_app_insights_llm_config(self._env)

    def _active_tracer(self) -> Tracer:
        return self._tracer if self._tracer is not None else trace_api.get_tracer(TRACER_NAME)

    async def record(self, invocation: LlmInvocation) -> None:
        """Emit one OpenTelemetry span for a metered LLM or embedding invocation."""
        config = self._effective_config()
        if not config.active:
            return
        end_ns = int(invocation.occurred_at.timestamp() * 1_000_000_000)
        start_ns = end_ns - invocation.duration_ms * _NS_PER_MS
        span = self._active_tracer().start_span(
            f"llm.{invocation.capability_id}",
            start_time=start_ns,
            attributes=_invocation_attributes(invocation),
        )
        span.set_status(Status(StatusCode.OK))
        span.end(end_time=end_ns)

    def record_model_trace(self, trace: Mapping[str, object]) -> None:
        """Emit one span and structured log record for a completed model-call trace."""
        config = self._effective_config()
        if not config.active:
            return
        timing = model_trace_timing(trace)
        correlation_id = current_correlation_id()
        attributes = model_trace_attributes(
            trace,
            correlation_id=correlation_id,
            capture_content=config.capture_content,
        )
        span = self._active_tracer().start_span(
            f"llm.{trace.get('kind', 'unknown')}",
            start_time=timing[0] if timing else None,
            attributes=attributes,
        )
        span.set_status(Status(StatusCode.OK))
        span.end(end_time=timing[1] if timing else None)
        trace_payload = dict(trace) if config.capture_content else content_free_model_trace(trace)
        self._logger.info(
            "llm_model_trace",
            extra={
                "llm_call_id": str(trace.get("call_id", "")),
                "llm_call_kind": str(trace.get("kind", "unknown")),
                "llm_model": str(trace.get("model", "unknown")),
                "llm_usage_scope": str(trace.get("usage_scope", "operator_chat")),
                "llm_duration_ms": trace.get("duration_ms"),
                "llm_capture_content": config.capture_content,
                "llm_trace": trace_payload,
            },
        )


def _invocation_attributes(invocation: LlmInvocation) -> dict[str, str | int]:
    usage = invocation.usage
    attributes: dict[str, str | int] = {
        "openinference.span.kind": (
            "EMBEDDING" if invocation.capability_id.endswith(".embedding") else "LLM"
        ),
        "session.id": invocation.correlation_id,
        "llm.model_name": invocation.model_key,
        "llm.token_count.prompt": usage.prompt_tokens,
        "llm.token_count.completion": usage.completion_tokens,
        "llm.token_count.total": usage.total_tokens,
        "llm.token_count.prompt_details.cache_read": invocation.cached_prompt_tokens,
        "fdai.capability_id": invocation.capability_id,
        "fdai.tier": invocation.tier,
        "fdai.mode": invocation.mode.value,
        "fdai.usage_scope": invocation.usage_scope.value,
        "fdai.turn_family": invocation.turn_family,
        "fdai.disposition": invocation.disposition.value,
        "fdai.locale": invocation.locale,
    }
    if invocation.profile_digest is not None:
        attributes["fdai.profile_digest"] = invocation.profile_digest
    if invocation.cost is not None and invocation.currency is not None:
        attributes["fdai.cost.amount"] = str(invocation.cost)
        attributes["fdai.cost.currency"] = invocation.currency
    return attributes


__all__ = [
    "CAPTURE_CONTENT_ENV",
    "CAPTURE_CONTENT_SETTING_KEY",
    "CONNECTION_STRING_ENV",
    "LOGGER_NAME",
    "TRACER_NAME",
    "TRACING_ENABLED_ENV",
    "TRACING_SETTING_KEY",
    "AppInsightsLlmTraceConfig",
    "AppInsightsLlmTraceSink",
    "app_insights_connection_configured",
    "app_insights_llm_config_from_env",
    "app_insights_llm_sink_from_env",
    "apply_app_insights_llm_settings",
    "current_app_insights_llm_config",
    "reset_app_insights_llm_settings",
]
