"""Scheduled, restart-safe stewardship identity liveness observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from fdai.core.stewardship import (
    IdentityDirectory,
    StewardshipMap,
    audit_stale_oids,
    load_stewardship_from_yaml,
)
from fdai.delivery.identity.entra_directory import EntraHumanIdentityDirectory
from fdai.shared.providers.human_identity import HumanIdentityDirectory
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_CURRENT_KEY = "stewardship_health:current"
_LAST_SUCCESS_KEY = "stewardship_health:last_success"
_LOGGER = logging.getLogger("fdai.stewardship.identity_health")


@dataclass(slots=True)
class _CachedIdentityDirectory(IdentityDirectory):
    directory: HumanIdentityDirectory
    cache: dict[str, bool] = field(default_factory=dict)

    async def is_active(self, oid: str) -> bool:
        if oid in self.cache:
            return self.cache[oid]
        identity = await self.directory.get_by_subject_id(oid)
        active = identity is not None and identity.active
        self.cache[oid] = active
        return active


@dataclass(frozen=True, slots=True)
class StewardshipIdentityHealthWorker:
    """Persist current identity health and audit only material transitions."""

    store: StateStore
    stewardship: StewardshipMap
    directory: HumanIdentityDirectory
    interval_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.interval_seconds < 60:
            raise ValueError("stewardship identity audit interval MUST be at least 60 seconds")

    async def run_once(self) -> str:
        """Observe all distinct user subjects and persist one bounded snapshot."""

        checked = datetime.now(UTC)
        checked_at = checked.isoformat()
        assignment_digest = _assignment_digest(self.stewardship)
        try:
            findings = await audit_stale_oids(
                self.stewardship,
                _CachedIdentityDirectory(self.directory),
            )
        except (ConnectionError, OSError, RuntimeError, TimeoutError, httpx.HTTPError) as exc:
            snapshot: dict[str, Any] = {
                "assignment_digest": assignment_digest,
                "status": "unavailable",
                "findings": [],
                "provider_error_type": type(exc).__name__,
                "checked_at": checked_at,
            }
            await self._persist(snapshot)
            return "unavailable"

        snapshot = {
            "assignment_digest": assignment_digest,
            "status": "degraded" if findings else "healthy",
            "findings": [
                {
                    "code": finding.code,
                    "severity": finding.severity.value,
                    "message": finding.message,
                    "agent": finding.agent,
                }
                for finding in findings
            ],
            "provider_error_type": None,
            "checked_at": checked_at,
            "expires_at": (checked + timedelta(seconds=self.interval_seconds * 2)).isoformat(),
        }
        revision = await self._persist(snapshot)
        await self.store.write_state(_LAST_SUCCESS_KEY, {**snapshot, "revision": revision})
        return str(snapshot["status"])

    async def _persist(self, snapshot: Mapping[str, Any]) -> int:
        current = await self.store.read_state(_CURRENT_KEY)
        current_revision = _revision(current)
        changed = current is None or _transition_signature(current) != _transition_signature(
            snapshot
        )
        value = {**snapshot, "revision": current_revision + int(changed)}
        if not changed:
            return current_revision
        recorded = await self.store.compare_and_set_state_with_audit(
            _CURRENT_KEY,
            value,
            expected_revision=current_revision,
            audit_entry={
                "actor": "Saga",
                "action_kind": "stewardship.identity_health_transition",
                "assignment_digest": snapshot["assignment_digest"],
                "status": snapshot["status"],
                "finding_count": len(snapshot["findings"]),
                "provider_error_type": snapshot["provider_error_type"],
                "recorded_at": snapshot["checked_at"],
            },
        )
        if not recorded:
            raise RuntimeError("stewardship identity health state changed concurrently")
        return int(value["revision"])

    async def run(self, stop: asyncio.Event) -> None:
        """Repeat the liveness observation until shutdown."""

        while not stop.is_set():
            try:
                status = await self.run_once()
                _LOGGER.info("stewardship_identity_health_observed", extra={"status": status})
            except Exception:  # noqa: BLE001 - preserve the last successful durable observation
                _LOGGER.exception("stewardship_identity_health_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


def build_stewardship_identity_health_worker(
    *,
    store: StateStore,
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    environment: Mapping[str, str],
    config_path: Path,
) -> StewardshipIdentityHealthWorker | None:
    """Compose the scheduled Graph observation when its interval is configured."""

    raw_interval = environment.get("FDAI_STEWARDSHIP_AUDIT_INTERVAL_SECONDS", "").strip()
    if not raw_interval:
        return None
    if not environment.get("FDAI_STATE_STORE_DSN", "").strip():
        raise RuntimeError("stewardship identity health requires FDAI_STATE_STORE_DSN")
    if http_client is None or identity is None:
        raise RuntimeError("stewardship identity health requires HTTP and workload identity")
    try:
        interval_seconds = float(raw_interval)
    except ValueError as exc:
        raise RuntimeError("FDAI_STEWARDSHIP_AUDIT_INTERVAL_SECONDS MUST be numeric") from exc
    return StewardshipIdentityHealthWorker(
        store=store,
        stewardship=load_stewardship_from_yaml(config_path, environ=environment),
        directory=EntraHumanIdentityDirectory(
            client=http_client,
            identity=identity,
        ),
        interval_seconds=interval_seconds,
    )


def _assignment_digest(stewardship: StewardshipMap) -> str:
    payload = {
        "version": stewardship.version,
        "maintainers": list(stewardship.maintainer_oids),
        "agents": {
            name: [
                {
                    "kind": subject.kind.value,
                    "id": subject.id,
                    "responsibility": subject.responsibility.value,
                    "duty": subject.duty.value if subject.duty is not None else None,
                }
                for subject in agent.stewards
            ]
            for name, agent in sorted(stewardship.agents.items())
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _revision(snapshot: Mapping[str, Any] | None) -> int:
    if snapshot is None:
        return 0
    value = snapshot.get("revision")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _transition_signature(snapshot: Mapping[str, Any]) -> tuple[object, ...]:
    findings = snapshot.get("findings")
    return (
        snapshot.get("assignment_digest"),
        snapshot.get("status"),
        json.dumps(findings, sort_keys=True, separators=(",", ":"), default=str),
        snapshot.get("provider_error_type"),
    )


__all__ = [
    "StewardshipIdentityHealthWorker",
    "build_stewardship_identity_health_worker",
]
