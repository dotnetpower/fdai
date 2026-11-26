"""OpenTelemetry GenAI, PTU Spillover, Agentic & RAG Observability (Rounds 1-4, E001-E012).

Implements 2025-2026 OpenTelemetry GenAI semantic conventions and Azure AI Foundry /
Azure OpenAI operational diagnostics:
- E001: OTel GenAI semantic convention span contract (``OtelGenAiSpanRecord``)
- E002: Streaming latency decomposition (``GenAiLatencyMetrics``: TTFT, TPOT, queue wait)
- E003: Token usage & prompt-cache efficiency analyzer (``GenAiTokenUsage``)
- E004: Provisioned Throughput Unit (PTU) vs. PAYGO spillover analyzer (``PtuSpilloverAssessment``)
- E005: Agentic multi-turn trajectory & tool-loop detector (``AgenticTrajectoryHealth``)
- E006: Prompt/response PII & secret redaction receipt verifier (``GenAiRedactionReceipt``)
- E007: GenAI KQL & Prometheus query compiler (``compile_genai_telemetry_kql``)
- E008: GenAI multi-metric SLO evaluator (``evaluate_genai_slo``)
- E009: GenAI deterministic causal fault classifier (``classify_genai_causal_fault``)
- E010: Cross-region/deployment model routing readiness advisor (``assess_genai_routing_readiness``)
- E011: RAG & Vector Search (AI Search / pgvector) recall/latency detector (``RagPipelineHealth``)
- E012: Content-Safety & Prompt-Shield block surge detector (``ContentSafetySurgeAssessment``)
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

_SECRET_OR_PII_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:Bearer\s+[A-Za-z0-9._\-]+|api[_-]?key\s*[:=]\s*\S+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)


class GenAiCausalFaultKind(StrEnum):
    """Deterministic fault classes for GenAI and agentic model serving (E009)."""

    HEALTHY = "healthy"
    PTU_QUOTA_EXHAUSTED = "ptu_quota_exhausted"
    RATE_LIMIT_429 = "rate_limit_429"
    TTFT_DEGRADATION = "ttft_degradation"
    TPOT_DECODE_STALL = "tpot_decode_stall"
    AGENT_TOOL_LOOP = "agent_tool_loop"
    RAG_RETRIEVAL_DEGRADATION = "rag_retrieval_degradation"
    CONTENT_SAFETY_SURGE = "content_safety_surge"


@dataclass(frozen=True, slots=True)
class OtelGenAiSpanRecord:
    """E001: OpenTelemetry `gen_ai.*` semantic convention span metadata."""

    trace_id: str
    span_id: str
    gen_ai_system: str
    gen_ai_request_model: str
    gen_ai_operation_name: str
    gen_ai_response_finish_reasons: tuple[str, ...]
    resource_ref: str
    occurred_at: datetime
    status_code: int = 200
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not self.trace_id.strip()
            or not self.span_id.strip()
            or not self.gen_ai_system.strip()
            or not self.gen_ai_request_model.strip()
            or not self.gen_ai_operation_name.strip()
            or not self.resource_ref.strip()
        ):
            raise ValueError("OtelGenAiSpanRecord string fields MUST be non-empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("OtelGenAiSpanRecord.occurred_at MUST be timezone-aware")
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("OtelGenAiSpanRecord.status_code MUST be a valid HTTP status")
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError(
                "OtelGenAiSpanRecord MUST remain read-only (execution_authority=False)"
            )


@dataclass(frozen=True, slots=True)
class GenAiLatencyMetrics:
    """E002: Streaming LLM latency decomposition (TTFT, TPOT/ITL, queue wait)."""

    time_to_first_token_ms: float
    time_per_output_token_ms: float
    queue_wait_ms: float
    total_duration_ms: float
    ttft_slo_ms: float = 1500.0
    tpot_slo_ms: float = 60.0

    def __post_init__(self) -> None:
        for val in (
            self.time_to_first_token_ms,
            self.time_per_output_token_ms,
            self.queue_wait_ms,
            self.total_duration_ms,
            self.ttft_slo_ms,
            self.tpot_slo_ms,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("GenAiLatencyMetrics values MUST be finite non-negative numbers")

    @property
    def ttft_breached(self) -> bool:
        return self.time_to_first_token_ms > self.ttft_slo_ms

    @property
    def tpot_breached(self) -> bool:
        return self.time_per_output_token_ms > self.tpot_slo_ms


@dataclass(frozen=True, slots=True)
class GenAiTokenUsage:
    """E003: OTel `gen_ai.usage.*` token accounting and prompt-cache efficiency."""

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    baseline_tpm: float = 10_000.0
    observed_tpm: float = 10_000.0

    def __post_init__(self) -> None:
        for count in (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.reasoning_tokens,
        ):
            if type(count) is not int or count < 0:
                raise ValueError("GenAiTokenUsage token counts MUST be non-negative integers")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens MUST NOT exceed input_tokens")
        if (
            type(self.baseline_tpm) is bool
            or type(self.observed_tpm) is bool
            or not math.isfinite(self.baseline_tpm)
            or not math.isfinite(self.observed_tpm)
            or self.baseline_tpm <= 0
            or self.observed_tpm < 0
        ):
            raise ValueError("TPM values MUST be finite and baseline_tpm > 0")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def prompt_cache_hit_ratio(self) -> float:
        return (
            round(self.cached_input_tokens / self.input_tokens, 4) if self.input_tokens > 0 else 0.0
        )

    @property
    def token_surge_ratio(self) -> float:
        return round(self.observed_tpm / self.baseline_tpm, 4)


@dataclass(frozen=True, slots=True)
class PtuSpilloverAssessment:
    """E004: Azure OpenAI PTU (Provisioned Managed) utilization and PAYGO spillover analysis."""

    ptu_utilization_percent: float
    ptu_requests: int
    paygo_spillover_requests: int
    http_429_count: int

    def __post_init__(self) -> None:
        if (
            type(self.ptu_utilization_percent) is bool
            or not math.isfinite(self.ptu_utilization_percent)
            or not 0.0 <= self.ptu_utilization_percent <= 200.0
        ):
            raise ValueError("ptu_utilization_percent MUST be in [0, 200]")
        for cnt in (self.ptu_requests, self.paygo_spillover_requests, self.http_429_count):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("PTU request counts MUST be non-negative integers")

    @property
    def spillover_ratio(self) -> float:
        total = self.ptu_requests + self.paygo_spillover_requests
        return round(self.paygo_spillover_requests / total, 4) if total > 0 else 0.0

    @property
    def ptu_saturated(self) -> bool:
        return self.ptu_utilization_percent >= 95.0 or self.http_429_count > 0


@dataclass(frozen=True, slots=True)
class AgenticTrajectoryHealth:
    """E005: Agentic multi-turn tool-call loop and budget burn assessment."""

    turn_count: int
    tool_call_count: int
    tool_error_count: int
    repeated_identical_tool_calls: int
    abstained_turns: int
    max_allowed_turns: int = 15

    def __post_init__(self) -> None:
        for val in (
            self.turn_count,
            self.tool_call_count,
            self.tool_error_count,
            self.repeated_identical_tool_calls,
            self.abstained_turns,
            self.max_allowed_turns,
        ):
            if type(val) is not int or val < 0:
                raise ValueError("AgenticTrajectoryHealth counts MUST be non-negative integers")

    @property
    def loop_detected(self) -> bool:
        return self.repeated_identical_tool_calls >= 3 or self.turn_count > self.max_allowed_turns

    @property
    def tool_error_rate(self) -> float:
        return (
            round(self.tool_error_count / self.tool_call_count, 4)
            if self.tool_call_count > 0
            else 0.0
        )


@dataclass(frozen=True, slots=True)
class GenAiRedactionReceipt:
    """E006: Proof that GenAI telemetry attributes had PII/secrets scrubbed before retention."""

    span_id: str
    redacted_payload_digest: str
    pii_patterns_scrubbed: int
    unredacted_content_retained: bool = False

    def __post_init__(self) -> None:
        if not self.span_id.strip() or not self.redacted_payload_digest.startswith("sha256:"):
            raise ValueError("GenAiRedactionReceipt requires span_id and sha256 digest")
        if type(self.pii_patterns_scrubbed) is not int or self.pii_patterns_scrubbed < 0:
            raise ValueError("pii_patterns_scrubbed MUST be a non-negative integer")
        if type(self.unredacted_content_retained) is not bool or self.unredacted_content_retained:
            raise ValueError("GenAiRedactionReceipt MUST NOT retain unredacted content")


def verify_and_redact_genai_text(span_id: str, raw_text: str) -> tuple[str, GenAiRedactionReceipt]:
    """E006: Scrub bearer tokens, API keys, and emails and return a signed redaction receipt."""
    matches = list(_SECRET_OR_PII_RE.finditer(raw_text))
    scrubbed = _SECRET_OR_PII_RE.sub("[REDACTED]", raw_text)
    digest = "sha256:" + hashlib.sha256(scrubbed.encode("utf-8")).hexdigest()
    return scrubbed, GenAiRedactionReceipt(
        span_id=span_id,
        redacted_payload_digest=digest,
        pii_patterns_scrubbed=len(matches),
        unredacted_content_retained=False,
    )


def _require_safe_resource_id(resource_id: str) -> str:
    clean = resource_id.strip()
    if not clean or any(ord(ch) < 32 or ch in {"'", ";"} for ch in clean):
        raise ValueError("Invalid resource_id for GenAI KQL compilation")
    return clean.lower()


def compile_genai_telemetry_kql(resource_id: str, *, lookback_minutes: int = 15) -> str:
    """E007: Compile a bounded KQL query for Azure OpenAI / Foundry OTel telemetry."""
    clean_id = _require_safe_resource_id(resource_id)
    if type(lookback_minutes) is not int or not 1 <= lookback_minutes <= 1440:
        raise ValueError("lookback_minutes MUST be in 1..1440")
    return (
        "AzureDiagnostics\n"
        f"| where TimeGenerated >= ago({lookback_minutes}m)\n"
        "| where tolower(coalesce(column_ifexists('_ResourceId', ''), "
        f"column_ifexists('ResourceId', ''))) == '{clean_id}'\n"
        "| summarize request_count=count(), http_429=countif(ResultType == '429'), "
        "p95_duration_ms=percentile(todouble(DurationMs), 95) by bin(TimeGenerated, 1m)"
    )


@dataclass(frozen=True, slots=True)
class RagPipelineHealth:
    """E011: RAG & Vector Search (Azure AI Search / pgvector) recall and latency health."""

    embedding_latency_ms: float
    vector_search_p95_ms: float
    empty_retrieval_ratio: float
    stale_index_lag_seconds: float

    def __post_init__(self) -> None:
        for val in (
            self.embedding_latency_ms,
            self.vector_search_p95_ms,
            self.empty_retrieval_ratio,
            self.stale_index_lag_seconds,
        ):
            if type(val) is bool or not math.isfinite(val) or val < 0:
                raise ValueError("RagPipelineHealth metrics MUST be finite non-negative numbers")

    @property
    def degraded(self) -> bool:
        return (
            self.vector_search_p95_ms > 500.0
            or self.empty_retrieval_ratio > 0.20
            or self.stale_index_lag_seconds > 600.0
        )


@dataclass(frozen=True, slots=True)
class ContentSafetySurgeAssessment:
    """E012: Azure AI Content Safety & Prompt Shield block surge assessment."""

    total_requests: int
    blocked_requests: int
    jailbreak_attempt_detections: int
    baseline_block_ratio: float = 0.02

    def __post_init__(self) -> None:
        for cnt in (
            self.total_requests,
            self.blocked_requests,
            self.jailbreak_attempt_detections,
        ):
            if type(cnt) is not int or cnt < 0:
                raise ValueError("ContentSafetySurgeAssessment counts MUST be non-negative")
        if self.blocked_requests > self.total_requests:
            raise ValueError("blocked_requests MUST NOT exceed total_requests")

    @property
    def block_ratio(self) -> float:
        return (
            round(self.blocked_requests / self.total_requests, 4)
            if self.total_requests > 0
            else 0.0
        )

    @property
    def surge_detected(self) -> bool:
        return (
            self.block_ratio >= max(0.10, self.baseline_block_ratio * 3.0)
            or self.jailbreak_attempt_detections > 0
        )


def evaluate_genai_slo(
    *,
    latency: GenAiLatencyMetrics,
    ptu: PtuSpilloverAssessment,
    total_requests: int,
    failed_requests: int,
) -> dict[str, object]:
    """E008: Evaluate GenAI TTFT, TPOT, availability, and PTU error-budget SLOs."""
    if (
        type(total_requests) is not int
        or type(failed_requests) is not int
        or total_requests < 0
        or failed_requests < 0
        or failed_requests > total_requests
    ):
        raise ValueError("Invalid request counts for GenAI SLO evaluation")
    availability = (
        (total_requests - failed_requests) / total_requests if total_requests > 0 else 1.0
    )
    slo_met = (
        not latency.ttft_breached
        and not latency.tpot_breached
        and availability >= 0.99
        and ptu.http_429_count == 0
    )
    return {
        "slo_met": slo_met,
        "availability": round(availability, 4),
        "ttft_breached": latency.ttft_breached,
        "tpot_breached": latency.tpot_breached,
        "ptu_saturated": ptu.ptu_saturated,
        "spillover_ratio": ptu.spillover_ratio,
        "execution_authority": False,
    }


def classify_genai_causal_fault(
    *,
    latency: GenAiLatencyMetrics,
    ptu: PtuSpilloverAssessment,
    trajectory: AgenticTrajectoryHealth,
    rag: RagPipelineHealth,
    safety: ContentSafetySurgeAssessment,
) -> GenAiCausalFaultKind:
    """E009: Deterministic root-cause classification across GenAI, PTU, Agent, and RAG signals."""
    if safety.surge_detected:
        return GenAiCausalFaultKind.CONTENT_SAFETY_SURGE
    if trajectory.loop_detected:
        return GenAiCausalFaultKind.AGENT_TOOL_LOOP
    if ptu.http_429_count > 0:
        return GenAiCausalFaultKind.RATE_LIMIT_429
    if ptu.ptu_saturated:
        return GenAiCausalFaultKind.PTU_QUOTA_EXHAUSTED
    if rag.degraded:
        return GenAiCausalFaultKind.RAG_RETRIEVAL_DEGRADATION
    if latency.ttft_breached:
        return GenAiCausalFaultKind.TTFT_DEGRADATION
    if latency.tpot_breached:
        return GenAiCausalFaultKind.TPOT_DECODE_STALL
    return GenAiCausalFaultKind.HEALTHY


def assess_genai_routing_readiness(
    *,
    primary_deployment_ref: str,
    fallback_deployment_refs: Sequence[str],
    ptu: PtuSpilloverAssessment,
    latency: GenAiLatencyMetrics,
) -> dict[str, object]:
    """E010: Assess multi-region/deployment model failover readiness (proposal-only)."""
    if not primary_deployment_ref.strip():
        raise ValueError("primary_deployment_ref MUST be non-empty")
    valid_fallbacks = tuple(ref.strip() for ref in fallback_deployment_refs if ref.strip())
    failover_recommended = ptu.ptu_saturated or latency.ttft_breached or latency.tpot_breached
    return {
        "primary_deployment_ref": primary_deployment_ref.strip(),
        "fallback_count": len(valid_fallbacks),
        "failover_ready": len(valid_fallbacks) > 0,
        "failover_recommended": failover_recommended and len(valid_fallbacks) > 0,
        "execution_authority": False,
    }


__all__ = [
    "AgenticTrajectoryHealth",
    "ContentSafetySurgeAssessment",
    "GenAiCausalFaultKind",
    "GenAiLatencyMetrics",
    "GenAiRedactionReceipt",
    "GenAiTokenUsage",
    "OtelGenAiSpanRecord",
    "PtuSpilloverAssessment",
    "RagPipelineHealth",
    "assess_genai_routing_readiness",
    "classify_genai_causal_fault",
    "compile_genai_telemetry_kql",
    "evaluate_genai_slo",
    "verify_and_redact_genai_text",
]
