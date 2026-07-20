"""Read-only ARB contract, production, and runtime status projection."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from fdai.core.architecture_review import ArchitectureReviewReadiness, evaluate_readiness
from fdai.core.views import ViewEngine

_WORKFLOW = "architecture-review"
_FAILED_STATUSES = frozenset({"failed", "timed_out", "cancelled"})
_NEXT_ACTION = {
    "evidence": "publish evidence.updated",
    "design_approval": "record design approval quorum",
    "design_decision": "record design decision",
    "production_evidence": "publish production.evidence.ready",
    "production_gate": "resolve production readiness failures",
    "production_approval": "record owner approval quorum",
    "production_decision": "record production decision",
}


class ArchitectureReviewStatusPanel:
    path = "/arb/status"
    name = "architecture-review-status"

    def __init__(self, *, manifest_path: Path, repo_root: Path, engine: ViewEngine) -> None:
        self._manifest_path = manifest_path
        self._repo_root = repo_root
        self._engine = engine

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        raw, readiness = self._read_manifest()
        review = raw.get("architecture_review") if isinstance(raw, dict) else None
        processes = await self._engine.list_processes(workflow_ref=_WORKFLOW, limit=1)
        process = processes[0] if processes else None
        return {
            "contract": {
                "healthy": readiness.structure_valid,
                "manifest": str(self._manifest_path.relative_to(self._repo_root)),
            },
            "production": {
                "ready": readiness.production_ready,
                "design_status": _string(review, "design_review_status"),
                "approval_status": _string(review, "production_approval_status"),
                "failures": list(readiness.failures),
            },
            "runtime": _runtime_status(process),
        }

    def _read_manifest(self) -> tuple[Any, ArchitectureReviewReadiness]:
        try:
            raw = yaml.safe_load(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return None, ArchitectureReviewReadiness(
                structure_valid=False,
                production_ready=False,
                failures=(f"manifest_unavailable:{type(exc).__name__}",),
            )
        return raw, evaluate_readiness(raw, repo_root=self._repo_root)


def _runtime_status(process: Mapping[str, Any] | None) -> dict[str, Any]:
    if process is None:
        return {
            "health": "not_started",
            "process": None,
            "next_action": "start architecture-review workflow",
        }
    status = str(process.get("status") or "unknown")
    current_step = str(process.get("current_step") or "")
    return {
        "health": "unhealthy" if status in _FAILED_STATUSES else "healthy",
        "process": dict(process),
        "next_action": _NEXT_ACTION.get(current_step),
    }


def _string(value: object, key: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    item = value.get(key)
    return item if isinstance(item, str) else None


__all__ = ["ArchitectureReviewStatusPanel"]
