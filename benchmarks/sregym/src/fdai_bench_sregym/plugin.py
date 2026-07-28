"""Environment factory for the external SREGym evaluation adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fdai_evaluation_sdk import EVALUATION_API_VERSION

from fdai_bench_sregym.adapter import SregymAdapter, SregymAdapterConfig


@dataclass(frozen=True, slots=True)
class SregymPlugin:
    """Compatibility factory that creates only the external adapter."""

    plugin_id: str = "sregym"
    api_version: str = EVALUATION_API_VERSION

    def create_adapter(self) -> SregymAdapter:
        artifact_id = os.environ.get("SREGYM_ARTIFACT_ID", "").strip()
        if not artifact_id:
            raise RuntimeError("SREGYM_ARTIFACT_ID is required")
        hostname = os.environ.get("API_HOSTNAME", "127.0.0.1").strip()
        if hostname in {"0.0.0.0", "::"}:  # noqa: S104 - bind address becomes client loopback
            hostname = "127.0.0.1"
        port = os.environ.get("API_PORT", "8000").strip()
        return SregymAdapter(
            config=SregymAdapterConfig(
                conductor_url=f"http://{hostname}:{port}",
                artifact_id=artifact_id,
            )
        )


def create_plugin() -> SregymPlugin:
    """Return the temporary compatibility factory for existing callers."""

    return SregymPlugin()


__all__ = ["SregymPlugin", "create_plugin"]
