"""Capability-specific startup sampling for model candidates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Protocol

from fdai.core.quality_gate.gate import CrossCheckModel, QualityCandidate
from fdai.core.readiness import ModelStartupEvidence, ProbeStatus, StartupProbeResult
from fdai.shared.providers.startup_probe import StartupProbeRequest


def _result(
    probe_id: str,
    started_at: float,
    *,
    model_evidence: ModelStartupEvidence,
) -> StartupProbeResult:
    observed_at = datetime.now(UTC)
    return StartupProbeResult(
        probe_id=probe_id,
        status=ProbeStatus.PASSED,
        observed_at=observed_at,
        expires_at=observed_at + timedelta(minutes=5),
        latency_ms=(perf_counter() - started_at) * 1000,
        model_evidence=model_evidence,
    )


class EmbeddingModel(Protocol):
    async def embed(self, text: str) -> Sequence[float]: ...


class EmbeddingStartupProbe:
    """Collect bounded latency and vector-shape proof for one embedding candidate."""

    def __init__(self, *, probe_id: str, model: EmbeddingModel) -> None:
        self.probe_id = probe_id
        self._model = model

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        latencies: list[float] = []
        dimensions: int | None = None
        for sample in range(request.model_sample_count):
            sample_started = perf_counter()
            vector = await self._model.embed(f"startup readiness sample {sample}")
            latencies.append((perf_counter() - sample_started) * 1000)
            if not vector:
                raise RuntimeError("embedding startup probe returned an empty vector")
            if dimensions is None:
                dimensions = len(vector)
            elif len(vector) != dimensions:
                raise RuntimeError("embedding vector shape changed between startup samples")
        if dimensions is None:
            raise RuntimeError("embedding startup probe collected no samples")
        return _result(
            self.probe_id,
            started_at,
            model_evidence=ModelStartupEvidence(
                sample_count=request.model_sample_count,
                total_latency_ms=tuple(latencies),
                embedding_dimensions=dimensions,
            ),
        )


class CrossCheckModelStartupProbe:
    """Collect bounded structured-output proof for one T2 model candidate."""

    def __init__(self, *, probe_id: str, model: CrossCheckModel) -> None:
        self.probe_id = probe_id
        self._model = model

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        latencies: list[float] = []
        for sample in range(request.model_sample_count):
            sample_started = perf_counter()
            action_type, params = await self._model.propose(
                QualityCandidate(
                    action_type="startup-readiness-probe",
                    target_resource_ref="synthetic:startup-readiness",
                    params={"sample": sample},
                    cited_rule_ids=(),
                )
            )
            latencies.append((perf_counter() - sample_started) * 1000)
            if not action_type or not isinstance(params, Mapping):
                raise RuntimeError("cross-check startup probe returned invalid structured output")
        return _result(
            self.probe_id,
            started_at,
            model_evidence=ModelStartupEvidence(
                sample_count=request.model_sample_count,
                total_latency_ms=tuple(latencies),
                structured_output_proven=True,
            ),
        )


class StreamingModel(Protocol):
    def stream_startup_sample(self, sample: int) -> AsyncIterator[str]: ...


class StreamingModelStartupProbe:
    """Collect per-sample TTFT, total latency, and output-token rate."""

    def __init__(self, *, probe_id: str, model: StreamingModel) -> None:
        self.probe_id = probe_id
        self._model = model

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        totals: list[float] = []
        ttfts: list[float] = []
        rates: list[float] = []
        for sample in range(request.model_sample_count):
            sample_started = perf_counter()
            first_token_at: float | None = None
            token_count = 0
            async for chunk in self._model.stream_startup_sample(sample):
                if not chunk:
                    continue
                now = perf_counter()
                first_token_at = first_token_at or now
                token_count += max(1, len(chunk.split()))
            ended_at = perf_counter()
            if first_token_at is None:
                raise RuntimeError("streaming startup probe returned no output token")
            total_seconds = ended_at - sample_started
            totals.append(total_seconds * 1000)
            ttfts.append((first_token_at - sample_started) * 1000)
            rates.append(token_count / total_seconds if total_seconds > 0 else 0.0)
        return _result(
            self.probe_id,
            started_at,
            model_evidence=ModelStartupEvidence(
                sample_count=request.model_sample_count,
                total_latency_ms=tuple(totals),
                ttft_ms=tuple(ttfts),
                output_token_rate=tuple(rates),
            ),
        )


class CapabilityProofStartupProbe:
    """Prove structured output or tool calling through a bounded callback."""

    def __init__(
        self,
        *,
        probe_id: str,
        prove: Callable[[], Awaitable[bool]],
        capability: str,
    ) -> None:
        if capability not in {"structured_output", "tool_calling"}:
            raise ValueError("model capability proof MUST be structured_output or tool_calling")
        self.probe_id = probe_id
        self._prove = prove
        self._capability = capability

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        started_at = perf_counter()
        proofs = []
        for _ in range(request.model_sample_count):
            proofs.append(await self._prove())
        if not all(proofs):
            raise RuntimeError("model capability proof failed")
        return _result(
            self.probe_id,
            started_at,
            model_evidence=ModelStartupEvidence(
                sample_count=request.model_sample_count,
                total_latency_ms=tuple(0.0 for _ in proofs),
                structured_output_proven=self._capability == "structured_output",
                tool_calling_proven=self._capability == "tool_calling",
            ),
        )


__all__ = [
    "CapabilityProofStartupProbe",
    "CrossCheckModelStartupProbe",
    "EmbeddingModel",
    "EmbeddingStartupProbe",
    "StreamingModelStartupProbe",
]
