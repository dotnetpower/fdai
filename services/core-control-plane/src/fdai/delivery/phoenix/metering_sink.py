"""Development LLM-trace export to Arize Phoenix (OTLP), off by default.

Each metered :class:`~fdai.core.metering.records.LlmInvocation` becomes one
OpenInference ``LLM`` span so token usage, latency, and per-conversation
grouping can be inspected in Phoenix. The span carries bounded metadata
only: token counts, model key, capability, tier, mode, and the correlation
id as ``session.id``. Prompt and completion text never reaches this
module, so it cannot be exported.

The sink owns a private ``TracerProvider``; it never touches the global
OpenTelemetry provider, so these spans reach no other exporter. Phoenix
is an observer, not a system of record: the durable metering store stays
authoritative, and this export grants no authority.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode

from fdai.core.metering.records import LlmInvocation

_log = logging.getLogger(__name__)

ENABLED_ENV = "FDAI_PHOENIX_TRACING_ENABLED"
ENDPOINT_ENV = "FDAI_PHOENIX_OTLP_ENDPOINT"
PROJECT_ENV = "FDAI_PHOENIX_PROJECT_NAME"
ALLOW_REMOTE_ENV = "FDAI_PHOENIX_ALLOW_REMOTE_ENDPOINT"

DEFAULT_PROJECT = "fdai"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_NS_PER_MS = 1_000_000


@dataclass(frozen=True, slots=True)
class PhoenixTracingConfig:
    """Validated settings for the Phoenix OTLP (gRPC) export."""

    endpoint: str
    project_name: str = DEFAULT_PROJECT

    def __post_init__(self) -> None:
        if urlparse(self.endpoint).scheme not in {"http", "https"}:
            raise ValueError("Phoenix OTLP endpoint MUST be an http(s) URL")
        if not self.project_name.strip():
            raise ValueError("Phoenix project name MUST NOT be empty")

    @property
    def insecure(self) -> bool:
        return urlparse(self.endpoint).scheme == "http"

    @property
    def is_loopback(self) -> bool:
        host = urlparse(self.endpoint).hostname or ""
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False


def phoenix_config_from_env(env: Mapping[str, str]) -> PhoenixTracingConfig | None:
    """Return the export config, or ``None`` when the feature is off or unusable.

    The feature is off unless ``FDAI_PHOENIX_TRACING_ENABLED`` is truthy.
    When it is on but misconfigured (missing or invalid endpoint, or a
    non-loopback endpoint without ``FDAI_PHOENIX_ALLOW_REMOTE_ENDPOINT``),
    the export stays disabled and one warning names the reason, because an
    observability flag must never stop the control plane from starting.
    """
    if env.get(ENABLED_ENV, "").strip().casefold() not in _TRUTHY:
        return None
    endpoint = env.get(ENDPOINT_ENV, "").strip()
    if not endpoint:
        _log.warning("phoenix_tracing_disabled", extra={"reason": f"{ENDPOINT_ENV} is not set"})
        return None
    try:
        config = PhoenixTracingConfig(
            endpoint=endpoint,
            project_name=env.get(PROJECT_ENV, "").strip() or DEFAULT_PROJECT,
        )
    except ValueError as error:
        _log.warning("phoenix_tracing_disabled", extra={"reason": str(error)})
        return None
    if not config.is_loopback and env.get(ALLOW_REMOTE_ENV, "").strip().casefold() not in _TRUTHY:
        _log.warning(
            "phoenix_tracing_disabled",
            extra={"reason": f"endpoint is not loopback; set {ALLOW_REMOTE_ENV} to allow it"},
        )
        return None
    return config


class PhoenixMeteringSink:
    """A :class:`~fdai.core.metering.sink.MeteringSink` that emits OpenInference spans."""

    def __init__(
        self,
        *,
        exporter: SpanExporter,
        project_name: str = DEFAULT_PROJECT,
        batch: bool = True,
    ) -> None:
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": "fdai", "openinference.project.name": project_name}
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
        )
        self._provider = provider
        self._tracer = provider.get_tracer("fdai.delivery.phoenix")

    @classmethod
    def from_config(cls, config: PhoenixTracingConfig) -> PhoenixMeteringSink:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=config.endpoint, insecure=config.insecure)
        return cls(exporter=exporter, project_name=config.project_name)

    async def record(self, invocation: LlmInvocation) -> None:
        end_ns = int(invocation.occurred_at.timestamp() * 1_000_000_000)
        start_ns = end_ns - invocation.duration_ms * _NS_PER_MS
        span = self._tracer.start_span(
            f"llm.{invocation.capability_id}",
            context=Context(),
            start_time=start_ns,
            attributes=_attributes(invocation),
        )
        span.set_status(Status(StatusCode.OK))
        span.end(end_time=end_ns)

    def flush(self) -> bool:
        """Export queued spans now; return ``False`` when the flush timed out."""
        return self._provider.force_flush()

    def shutdown(self) -> None:
        self._provider.shutdown()


def _attributes(invocation: LlmInvocation) -> dict[str, str | int]:
    usage = invocation.usage
    attributes: dict[str, str | int] = {
        "openinference.span.kind": "LLM",
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
    "ALLOW_REMOTE_ENV",
    "ENABLED_ENV",
    "ENDPOINT_ENV",
    "PROJECT_ENV",
    "PhoenixMeteringSink",
    "PhoenixTracingConfig",
    "phoenix_config_from_env",
]
