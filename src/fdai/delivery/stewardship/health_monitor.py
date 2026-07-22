"""Scheduled stewardship identity health checks with transition-only audit."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.core.stewardship import IdentityDirectory, StewardshipMap, audit_stale_oids
from fdai.shared.providers.human_identity import HumanIdentityDirectory
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)
_STATE_KEY = "stewardship_health:current"


class HumanIdentityLivenessDirectory(IdentityDirectory):
    """Adapt the production human directory to stewardship liveness checks."""

    def __init__(self, directory: HumanIdentityDirectory) -> None:
        self._directory = directory

    async def is_active(self, oid: str) -> bool:
        identity = await self._directory.get_by_subject_id(oid)
        return identity is not None and identity.active


class StewardshipHealthMonitor:
    """Periodically audit stale steward transitions without blocking startup."""

    def __init__(
        self,
        *,
        stewardship_map: StewardshipMap,
        directory: IdentityDirectory,
        state_store: StateStore,
        interval_seconds: int = 3600,
    ) -> None:
        if interval_seconds < 60:
            raise ValueError("stewardship health interval MUST be at least 60 seconds")
        self._map = stewardship_map
        self._directory = directory
        self._state_store = state_store
        self._interval_seconds = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="stewardship-health")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def run_once(self) -> bool:
        """Persist and audit a changed health snapshot; return whether it changed."""
        findings = await audit_stale_oids(self._map, self._directory)
        finding_rows = tuple(
            {
                "code": finding.code,
                "severity": finding.severity.value,
                "agent": finding.agent,
                "message": finding.message,
            }
            for finding in findings
        )
        previous = await self._state_store.read_state(_STATE_KEY)
        previous_rows = previous.get("findings") if previous is not None else None
        if previous_rows == list(finding_rows):
            return False

        previous_revision = _revision(previous)
        checked_at = datetime.now(tz=UTC).isoformat()
        revision = previous_revision + 1
        state = {
            "revision": revision,
            "checked_at": checked_at,
            "finding_count": len(finding_rows),
            "findings": list(finding_rows),
        }
        fingerprint = _fingerprint(finding_rows)
        audit = {
            "kind": "stewardship.health.changed",
            "event_id": f"stewardship-health:{fingerprint}",
            "idempotency_key": f"stewardship-health:{revision}:{fingerprint}",
            "correlation_id": f"stewardship-health:{fingerprint}",
            "actor_identity": "system:stewardship-health-monitor",
            "timestamp": checked_at,
            "decision": "warn" if finding_rows else "clean",
            "finding_count": len(finding_rows),
            "findings": list(finding_rows),
        }
        if previous is None:
            return await self._state_store.write_state_with_audit_if_absent(
                _STATE_KEY,
                state,
                audit,
            )
        return await self._state_store.compare_and_set_state_with_audit(
            _STATE_KEY,
            state,
            expected_revision=previous_revision,
            audit_entry=audit,
        )

    async def _run(self) -> None:
        await self._run_once_safely()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                await self._run_once_safely()

    async def _run_once_safely(self) -> None:
        try:
            await self.run_once()
        except Exception as exc:  # noqa: BLE001 - scheduled probe retries next interval
            _LOGGER.warning(
                "stewardship_health_check_failed",
                extra={"error_type": type(exc).__name__},
            )


def _revision(state: Mapping[str, object] | None) -> int:
    if state is None:
        return 0
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise RuntimeError("stewardship health state has an invalid revision")
    return revision


def _fingerprint(findings: tuple[Mapping[str, object], ...]) -> str:
    payload = json.dumps(findings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


__all__ = ["HumanIdentityLivenessDirectory", "StewardshipHealthMonitor"]
