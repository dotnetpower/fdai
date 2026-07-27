"""Installed plugin factory for SREGym."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fdai.benchmarking import BENCHMARK_API_VERSION, BenchmarkBindings
from fdai_bench_sregym.adapter import SregymAdapter, SregymAdapterConfig


@dataclass(frozen=True, slots=True)
class SregymPlugin:
    """Create SREGym bindings from the isolated agent process environment."""

    plugin_id: str = "sregym"
    api_version: str = BENCHMARK_API_VERSION

    def create_bindings(self) -> BenchmarkBindings:
        artifact_id = os.environ.get("SREGYM_ARTIFACT_ID", "").strip()
        if not artifact_id:
            raise RuntimeError("SREGYM_ARTIFACT_ID is required")
        hostname = os.environ.get("API_HOSTNAME", "127.0.0.1").strip()
        if hostname in {"0.0.0.0", "::"}:  # noqa: S104 - bind address becomes client loopback
            hostname = "127.0.0.1"
        port = os.environ.get("API_PORT", "8000").strip()
        adapter = SregymAdapter(
            config=SregymAdapterConfig(
                conductor_url=f"http://{hostname}:{port}",
                artifact_id=artifact_id,
            )
        )
        return BenchmarkBindings(adapter=adapter)


def create_plugin() -> SregymPlugin:
    """Return the API-compatible SREGym plugin instance."""

    return SregymPlugin()


__all__ = ["SregymPlugin", "create_plugin"]
