"""Bounded live readiness probe for the T1 embedding and T2 reasoner deployments.

Explicit operator tool, never started by the runtime. It spends at most three embedding calls and
one one-token chat call, never retries, and stops on the first provider error, so a provider
``429`` ends the attempt instead of compounding it. The T1 check embeds a paraphrase pair and an
unrelated pair with the production embedding adapter and compares each cosine score with the T1
similarity threshold, so "no neighbour" can be told apart from a broken embedding path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final

import httpx

from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel, cosine_similarity
from fdai.shared.providers.workload_identity import WorkloadIdentity

_COGNITIVE_SERVICES_SCOPE: Final = "https://cognitiveservices.azure.com/.default"
_CHAT_API_VERSION: Final = "2024-10-21"
_EMBEDDING_DIM: Final = 384
_PROBE_TEXTS: Final[tuple[str, str, str]] = (
    "network.load-balancer inventory.resource_changed: backend pool lost a healthy node",
    "network.load-balancer inventory.resource_changed: a backend pool member became unhealthy",
    "authorization.role-assignment created for a new service principal at subscription scope",
)


@dataclass(frozen=True, slots=True)
class TierProbeReport:
    """Redacted result: scores, dimensions, status codes, and counts only."""

    t1_embedding_dim: int | None = None
    t1_similar_score: float | None = None
    t1_unrelated_score: float | None = None
    t1_threshold: float = 0.8
    t1_passed: bool = False
    t2_status: int | None = None
    t2_passed: bool = False
    pattern_library: str = "not_checked"
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.t1_passed and self.t2_passed and not self.errors


async def probe_t1(
    embedding_model: EmbeddingModel, *, threshold: float
) -> tuple[int, float, float]:
    """Return the vector dimension, the paraphrase score, and the unrelated score."""
    anchor, paraphrase, unrelated = [await embedding_model.embed(text) for text in _PROBE_TEXTS]
    return (
        len(anchor),
        cosine_similarity(anchor, paraphrase),
        cosine_similarity(anchor, unrelated),
    )


async def probe_t2(
    *, client: httpx.AsyncClient, identity: WorkloadIdentity, endpoint: str, deployment: str
) -> int:
    """Send one one-token chat request and return the provider status code."""
    token = (await identity.get_token(_COGNITIVE_SERVICES_SCOPE)).token
    response = await client.post(
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions",
        params={"api-version": _CHAT_API_VERSION},
        headers={"Authorization": f"Bearer {token}"},
        json={
            "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
            "max_completion_tokens": 16,
        },
    )
    return response.status_code


def pattern_library_status(dsn: str | None, counter: Callable[[str], int]) -> str:
    """Describe the T1 library backend without exposing the DSN."""
    if not dsn:
        return "in_memory_empty_after_restart"
    return f"durable_patterns={counter(dsn)}"


async def run_probe(
    *,
    embedding_model: EmbeddingModel,
    t2_call: Callable[[], Awaitable[int]],
    threshold: float,
    pattern_status: str,
) -> TierProbeReport:
    """Run both probes once; any provider error is recorded and ends that probe."""
    report: dict[str, Any] = {"t1_threshold": threshold, "pattern_library": pattern_status}
    errors: list[str] = []
    try:
        dim, similar, unrelated = await probe_t1(embedding_model, threshold=threshold)
        report.update(
            t1_embedding_dim=dim,
            t1_similar_score=round(similar, 3),
            t1_unrelated_score=round(unrelated, 3),
            t1_passed=dim == _EMBEDDING_DIM and similar >= threshold > unrelated,
        )
    except Exception as exc:  # noqa: BLE001 - a probe reports the failure class, never the body
        errors.append(f"t1:{type(exc).__name__}")
    try:
        status = await t2_call()
        report.update(t2_status=status, t2_passed=status == 200)
        if status != 200:
            errors.append(f"t2:http_{status}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"t2:{type(exc).__name__}")
    return TierProbeReport(**report, errors=errors)


def _count_patterns(dsn: str) -> int:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        row = connection.execute("SELECT count(*) FROM t1_pattern_library").fetchone()
    return int(row[0]) if row else 0


async def _amain(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="authorize the bounded provider calls")
    parser.add_argument("--embedding-deployment", default="t1.embedding")
    parser.add_argument("--t2-deployment", default="t2.reasoner.primary")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args(argv)
    if not args.live:
        print(
            "refused: pass --live to authorize 3 embedding calls and 1 chat call", file=sys.stderr
        )
        return 2
    from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
    from fdai.delivery.azure.llm.embeddings import (
        AzureOpenAIEmbeddingModel,
        AzureOpenAIEmbeddingModelConfig,
    )

    endpoint = os.environ.get("FDAI_LLM_ENDPOINT", "").strip()
    if not endpoint:
        print("FDAI_LLM_ENDPOINT MUST be configured", file=sys.stderr)
        return 2
    identity = AsyncAzureCliWorkloadIdentity.from_env()
    timeout = httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        embedding_model = AzureOpenAIEmbeddingModel(
            identity=identity,
            http_client=client,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint=endpoint,
                deployment=args.embedding_deployment,
                api_version="2024-08-01-preview",
                dim=_EMBEDDING_DIM,
            ),
        )
        dsn = os.environ.get("FDAI_T1_PATTERN_LIBRARY_DSN", "").strip() or None
        try:
            status = pattern_library_status(dsn, _count_patterns)
        except Exception as exc:  # noqa: BLE001
            status = f"durable_unreachable:{type(exc).__name__}"
        report = await run_probe(
            embedding_model=embedding_model,
            t2_call=lambda: probe_t2(
                client=client,
                identity=identity,
                endpoint=endpoint,
                deployment=args.t2_deployment,
            ),
            threshold=args.threshold,
            pattern_status=status,
        )
    print(json.dumps({**asdict(report), "passed": report.passed}, sort_keys=True))
    return 0 if report.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    started = time.monotonic()
    code = asyncio.run(_amain(list(argv) if argv is not None else sys.argv[1:]))
    print(f"elapsed_seconds={time.monotonic() - started:.1f}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
