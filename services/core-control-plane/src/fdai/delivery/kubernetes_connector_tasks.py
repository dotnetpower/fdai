"""Guarded connector work delivery without execution authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from fdai_service_contracts.cluster_connector import (
    ConnectorRegistration,
    ConnectorWork,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest

from fdai.shared.providers.state_store import StateStore

TASK_PREFIX = "kubernetes-connector:work:v1:"


class ConnectorTaskDeliveryError(ValueError):
    """Reject task delivery when authorization, freshness or recovery is not current."""


class ConnectorTaskRegistrationReader(Protocol):
    async def read(self, principal_ref: str) -> ConnectorRegistration | None: ...


@dataclass(frozen=True, slots=True)
class ConnectorTaskDeliveryReceipt:
    status: Literal["delivered", "duplicate", "unknown_outcome"]
    work_digest: str
    claim_fence: str
    execution_authority: Literal[False] = False


class ConnectorTaskDeliveryQueue:
    """Deliver finite ConnectorWork records only while current authorization is valid.

    Delivery is a broker claim, not execution. If a prior claim expires before a terminal
    acknowledgment, the queue records an unknown outcome and refuses blind redispatch.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        registrations: ConnectorTaskRegistrationReader,
        now: Callable[[], datetime],
        claim_seconds: int = 60,
    ) -> None:
        if type(claim_seconds) is not int or not 1 <= claim_seconds <= 900:
            raise ValueError("connector task claim window must be in [1, 900]")
        self._store, self._registrations, self._now = store, registrations, now
        self._claim_seconds = claim_seconds

    async def deliver(
        self, work: ConnectorWork, *, principal_ref: str
    ) -> ConnectorTaskDeliveryReceipt:
        work = ConnectorWork.model_validate_json(work.model_dump_json())
        registration = await self._registration(principal_ref)
        current = connector_time(self._now())
        work.admit(registration, principal_ref=principal_ref, now=current)
        key = _task_key(work)
        previous = await self._store.read_state(key)
        if previous is not None:
            old_work, revision = _decode(previous, work=work)
            if old_work != work:
                raise ConnectorTaskDeliveryError("connector task identity changed")
            status = str(previous["status"])
            fence = str(previous["claim_fence"])
            if status == "claimed":
                claim_expires_at = connector_time(previous["claim_expires_at"])
                if current < claim_expires_at:
                    return ConnectorTaskDeliveryReceipt("duplicate", work.digest, fence)
                unknown = {
                    **dict(previous),
                    "revision": revision + 1,
                    "status": "unknown_outcome",
                    "recovered_at": current.isoformat(),
                }
                audit = _audit(
                    "kubernetes.connector.work.unknown_outcome",
                    work,
                    current,
                    claim_fence=fence,
                )
                if await self._store.compare_and_set_state_with_audit(
                    key, unknown, expected_revision=revision, audit_entry=audit
                ):
                    return ConnectorTaskDeliveryReceipt("unknown_outcome", work.digest, fence)
                raise ConnectorTaskDeliveryError("connector task changed during recovery")
            if status in {"acknowledged", "unknown_outcome"}:
                return ConnectorTaskDeliveryReceipt("duplicate", work.digest, fence)
            raise ConnectorTaskDeliveryError("connector task checkpoint has an invalid status")
        fence = canonical_digest(
            {
                "work_digest": work.digest,
                "principal_ref": principal_ref,
                "claimed_at": current.isoformat(),
            }
        )
        record = {
            "revision": 1,
            "status": "claimed",
            "work": work.model_dump(mode="json"),
            "work_digest": work.digest,
            "claim_fence": fence,
            "claimed_at": current.isoformat(),
            "claim_expires_at": (current + timedelta(seconds=self._claim_seconds)).isoformat(),
            "execution_authority": False,
        }
        audit = _audit("kubernetes.connector.work.delivered", work, current, claim_fence=fence)
        if await self._store.write_state_with_audit_if_absent(key, record, audit):
            return ConnectorTaskDeliveryReceipt("delivered", work.digest, fence)
        return await self.deliver(work, principal_ref=principal_ref)

    async def acknowledge(
        self,
        work: ConnectorWork,
        *,
        principal_ref: str,
        claim_fence: str,
        outcome_digest: str,
    ) -> bool:
        work = ConnectorWork.model_validate_json(work.model_dump_json())
        registration = await self._registration(principal_ref)
        current = connector_time(self._now())
        work.admit(registration, principal_ref=principal_ref, now=current)
        key = _task_key(work)
        previous = await self._store.read_state(key)
        if previous is None:
            raise ConnectorTaskDeliveryError("connector task has no delivery claim")
        _, revision = _decode(previous, work=work)
        if previous["status"] != "claimed" or previous["claim_fence"] != claim_fence:
            raise ConnectorTaskDeliveryError("connector task acknowledgment is not current")
        if current >= connector_time(previous["claim_expires_at"]):
            raise ConnectorTaskDeliveryError("connector task claim expired before acknowledgment")
        _digest(outcome_digest)
        record = {
            **dict(previous),
            "revision": revision + 1,
            "status": "acknowledged",
            "outcome_digest": outcome_digest,
            "acknowledged_at": current.isoformat(),
        }
        audit = _audit(
            "kubernetes.connector.work.acknowledged",
            work,
            current,
            claim_fence=claim_fence,
            outcome_digest=outcome_digest,
        )
        return await self._store.compare_and_set_state_with_audit(
            key, record, expected_revision=revision, audit_entry=audit
        )

    async def _registration(self, principal_ref: str) -> ConnectorRegistration:
        registration = await self._registrations.read(principal_ref)
        if registration is None:
            raise ConnectorTaskDeliveryError("connector executor registration is unavailable")
        return ConnectorRegistration.model_validate_json(registration.model_dump_json())


def _task_key(work: ConnectorWork) -> str:
    return TASK_PREFIX + canonical_digest(
        {"scope": work.scope.model_dump(mode="json"), "work_id": work.work_id}
    )


def _decode(value: Mapping[str, object], *, work: ConnectorWork) -> tuple[ConnectorWork, int]:
    required = {
        "revision",
        "status",
        "work",
        "work_digest",
        "claim_fence",
        "claimed_at",
        "claim_expires_at",
        "execution_authority",
    }
    if not required <= set(value) or value["execution_authority"] is not False:
        raise ConnectorTaskDeliveryError("connector task checkpoint has an invalid shape")
    revision = value["revision"]
    stored = ConnectorWork.model_validate(value["work"])
    if (
        type(revision) is not int
        or not 1 <= revision < 2**63 - 1
        or value["work_digest"] != stored.digest
        or stored.digest != work.digest
    ):
        raise ConnectorTaskDeliveryError("connector task checkpoint failed integrity checks")
    _digest(str(value["claim_fence"]))
    connector_time(value["claimed_at"])
    connector_time(value["claim_expires_at"])
    return stored, revision


def _audit(
    kind: str,
    work: ConnectorWork,
    recorded_at: datetime,
    *,
    claim_fence: str,
    outcome_digest: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "kind": kind,
        "correlation_id": work.correlation_id,
        "work_digest": work.digest,
        "claim_fence": claim_fence,
        "recorded_at": connector_time(recorded_at).isoformat(),
        "execution_authority": False,
    }
    if outcome_digest is not None:
        entry["outcome_digest"] = outcome_digest
    return entry


def _digest(value: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ConnectorTaskDeliveryError("connector task digest is invalid")
    int(value.removeprefix("sha256:"), 16)
