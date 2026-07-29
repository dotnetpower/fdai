"""Environment factory for the external CyberGym evaluation adapter."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai_evaluation_sdk import EVALUATION_API_VERSION, ArtifactRef

from fdai_bench_cybergym.adapter import CyberGymAdapter, CyberGymMode, CyberGymTaskConfig

_MANIFEST_ENV = "CYBERGYM_TASK_MANIFEST"


@dataclass(frozen=True, slots=True)
class CyberGymPlugin:
    """Create one task-scoped adapter from a harness-owned manifest."""

    plugin_id: str = "cybergym"
    api_version: str = EVALUATION_API_VERSION

    def create_adapter(self) -> CyberGymAdapter:
        manifest_value = os.environ.get(_MANIFEST_ENV, "").strip()
        if not manifest_value:
            raise RuntimeError(f"{_MANIFEST_ENV} is required")
        manifest_path = Path(manifest_value).expanduser().resolve(strict=True)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("CyberGym task manifest is unreadable or invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("CyberGym task manifest MUST contain a JSON object")
        return CyberGymAdapter(config=_task_config(payload))


def _task_config(payload: dict[str, Any]) -> CyberGymTaskConfig:
    try:
        return CyberGymTaskConfig(
            session_id=payload["session_id"],
            task_id=payload["task_id"],
            mode=CyberGymMode(payload["mode"]),
            source_workspace_ref=payload["source_workspace_ref"],
            deadline=datetime.fromisoformat(payload["deadline"]),
            crash_log=_artifact(payload.get("crash_log")),
            supplied_poc=_artifact(payload.get("supplied_poc")),
            max_poc_bytes=payload.get("max_poc_bytes", 1_048_576),
            max_patch_bytes=payload.get("max_patch_bytes", 4_194_304),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("CyberGym task manifest does not satisfy the adapter contract") from exc


def _artifact(value: object) -> ArtifactRef | None:
    return None if value is None else ArtifactRef.model_validate(value)


def create_plugin() -> CyberGymPlugin:
    """Return the installed-adapter factory used by the FDAI runtime."""

    return CyberGymPlugin()


__all__ = ["CyberGymPlugin", "create_plugin"]
