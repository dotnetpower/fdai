"""Provider-neutral contracts for deterministic startup readiness."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from fdai.shared.contracts.models import ContractBase


class StartupPhase(StrEnum):
    STATIC_LOAD = "static_load"
    REQUIRED_REACHABILITY = "required_reachability"
    CAPABILITY_WARMUP = "capability_warmup"
    ACTIVE_SMOKE = "active_smoke"


class ProbeCriticality(StrEnum):
    PROCESS_CRITICAL = "process_critical"
    AUTHORITY_CRITICAL = "authority_critical"
    OPTIONAL = "optional"


class ProbeStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CRASHED = "crashed"


class ReadinessDecision(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class AuthorityCeiling(StrEnum):
    DISABLED = "disabled"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"
    SHADOW = "shadow"
    HUMAN_APPROVAL = "human_approval"
    DEPLOYMENT = "deployment"


class EvidenceRequirement(StrEnum):
    STANDARD = "standard"
    MODEL_STREAM = "model_stream"
    MODEL_EMBEDDING = "model_embedding"
    MODEL_STRUCTURED_OUTPUT = "model_structured_output"
    MODEL_TOOL_CALLING = "model_tool_calling"


_AUTHORITY_RANK = {
    AuthorityCeiling.DISABLED: 0,
    AuthorityCeiling.DETERMINISTIC_FALLBACK: 1,
    AuthorityCeiling.SHADOW: 2,
    AuthorityCeiling.HUMAN_APPROVAL: 3,
    AuthorityCeiling.DEPLOYMENT: 4,
}


class StartupProbeSpec(ContractBase):
    """One enabled startup check and its deterministic failure response."""

    probe_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    capability: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    phase: StartupPhase
    criticality: ProbeCriticality
    failure_ceiling: AuthorityCeiling = AuthorityCeiling.DISABLED
    evidence_requirement: EvidenceRequirement = EvidenceRequirement.STANDARD
    estimated_cost_usd: Annotated[float, Field(ge=0)] = 0.0
    synthetic_scope: bool = False

    @model_validator(mode="after")
    def validate_process_ceiling(self) -> StartupProbeSpec:
        if (
            self.criticality is ProbeCriticality.PROCESS_CRITICAL
            and self.failure_ceiling is not AuthorityCeiling.DISABLED
        ):
            raise ValueError("process-critical probes MUST use the disabled failure ceiling")
        return self


class ModelStartupEvidence(ContractBase):
    """Bounded startup samples for one enabled model candidate."""

    sample_count: Annotated[int, Field(ge=2)]
    total_latency_ms: tuple[Annotated[float, Field(ge=0)], ...]
    ttft_ms: tuple[Annotated[float, Field(ge=0)], ...] = ()
    output_token_rate: tuple[Annotated[float, Field(ge=0)], ...] = ()
    embedding_dimensions: Annotated[int | None, Field(gt=0)] = None
    structured_output_proven: bool = False
    tool_calling_proven: bool = False
    ttft_p95_ms: Annotated[float | None, Field(ge=0)] = None

    @model_validator(mode="after")
    def validate_samples(self) -> ModelStartupEvidence:
        if len(self.total_latency_ms) != self.sample_count:
            raise ValueError("model total-latency samples MUST match sample_count")
        if self.ttft_ms and len(self.ttft_ms) != self.sample_count:
            raise ValueError("model TTFT samples MUST match sample_count")
        if self.output_token_rate and len(self.output_token_rate) != self.sample_count:
            raise ValueError("model output-token-rate samples MUST match sample_count")
        if self.ttft_p95_ms is not None and self.sample_count < 20:
            raise ValueError("model TTFT p95 requires at least 20 startup samples")
        return self


class StartupProbeResult(ContractBase):
    """Sanitized evidence returned by one startup probe."""

    probe_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    status: ProbeStatus
    observed_at: datetime
    expires_at: datetime
    latency_ms: Annotated[float, Field(ge=0)]
    failure_class: Annotated[
        str | None,
        Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$"),
    ] = None
    evidence: dict[str, bool | float | int | str] = Field(default_factory=dict)
    model_evidence: ModelStartupEvidence | None = None

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("startup evidence timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_result(self) -> StartupProbeResult:
        if self.expires_at <= self.observed_at:
            raise ValueError("startup evidence expiry MUST follow observation time")
        if self.status is ProbeStatus.PASSED and self.failure_class is not None:
            raise ValueError("passed startup probes MUST NOT include a failure class")
        if self.status is not ProbeStatus.PASSED and self.failure_class is None:
            raise ValueError("failed startup probes MUST include a sanitized failure class")
        return self

    @field_validator("evidence")
    @classmethod
    def reject_sensitive_evidence(
        cls,
        value: dict[str, bool | float | int | str],
    ) -> dict[str, bool | float | int | str]:
        sensitive_fragments = (
            "credential",
            "endpoint",
            "error",
            "password",
            "secret",
            "token",
            "url",
        )
        for key, item in value.items():
            normalized_key = key.casefold()
            if any(fragment in normalized_key for fragment in sensitive_fragments):
                raise ValueError("startup evidence contains a sensitive field name")
            if isinstance(item, str) and any(character in item for character in ("/", ":", "@")):
                raise ValueError("startup evidence string values MUST be sanitized tokens")
        return value


class StartupReadinessReport(ContractBase):
    """Deterministic, sanitized reduction of all enabled startup probes."""

    generated_at: datetime
    decision: ReadinessDecision
    results: tuple[StartupProbeResult, ...]
    missing_probe_ids: tuple[str, ...] = ()
    stale_probe_ids: tuple[str, ...] = ()
    authority_ceilings: dict[str, AuthorityCeiling] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        """Return byte-stable JSON for persistence, hashing, and replay."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def more_restrictive(
    left: AuthorityCeiling,
    right: AuthorityCeiling,
) -> AuthorityCeiling:
    """Return the lower authority without relying on enum declaration order."""
    return left if _AUTHORITY_RANK[left] <= _AUTHORITY_RANK[right] else right


__all__ = [
    "AuthorityCeiling",
    "EvidenceRequirement",
    "ModelStartupEvidence",
    "ProbeCriticality",
    "ProbeStatus",
    "ReadinessDecision",
    "StartupPhase",
    "StartupProbeResult",
    "StartupProbeSpec",
    "StartupReadinessReport",
    "more_restrictive",
]
