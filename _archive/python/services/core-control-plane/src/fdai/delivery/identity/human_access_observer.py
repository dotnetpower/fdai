"""Heimdall-owned independent Graph membership reads through a separate read-only identity.

No mutation method, retry, arbitrary target or Executor identity is available.
The exact durable isolated dispatch receipt must be verified by the caller before
this reader may inspect its original private material.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    human_access_record_digest,
    require_human_access_time,
)
from fdai_service_contracts.human_access_workflow import HumanAccessMembershipObservation

from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class IndependentHumanAccessObserver:
    """Observe one exact current membership, with immutable source and completion timestamps."""

    client: httpx.AsyncClient
    identity: WorkloadIdentity
    identity_ref: str
    clock: Callable[[], datetime]

    async def observe(
        self,
        *,
        material: HumanAccessExecutionMaterial,
        dispatch_receipt_digest: str,
        dispatch_completed_at: datetime,
    ) -> HumanAccessMembershipObservation:
        """Require current target presence before interpreting membership404 as absence."""
        async with asyncio.timeout(15):
            at = require_human_access_time(self.clock())
            if at < require_human_access_time(dispatch_completed_at):
                raise ValueError("human access observation must follow exact dispatch completion")
            token = await self.identity.get_token("https://graph.microsoft.com/.default")
            if (
                token.expires_at <= self.clock()
                or token.audience != "https://graph.microsoft.com/.default"
            ):
                raise ValueError("human access observer identity is expired")
            headers = {"Authorization": f"Bearer {token.token}"}
            user = await self._read(f"users/{material.subject_id}?$select=id", headers)
            group = await self._read(f"groups/{material.group_id}?$select=id", headers)
            if (
                user is None
                or group is None
                or user.get("id") != material.subject_id
                or group.get("id") != material.group_id
            ):
                raise ValueError("human access independent target observation is incomplete")
            membership = await self._read(
                f"groups/{material.group_id}/members/{material.subject_id}?$select=id",
                headers,
                allow_absent=True,
            )
            if membership is not None and membership.get("id") != material.subject_id:
                raise ValueError("human access independent membership read changed identity")
            current_user = await self._read(f"users/{material.subject_id}?$select=id", headers)
            current_group = await self._read(f"groups/{material.group_id}?$select=id", headers)
            if current_user != user or current_group != group:
                raise ValueError("human access independent targets changed during membership read")
            after = require_human_access_time(self.clock())
            if after < at or after >= at + timedelta(seconds=60):
                raise ValueError("human access independent observation window expired")
            source = human_access_record_digest(
                {
                    "target": material.membership_plan().target_digest,
                    "observer": self.identity_ref,
                    "observed_at": after.isoformat(),
                    "present": membership is not None,
                }
            )
            return HumanAccessMembershipObservation(
                material_digest=material.digest,
                action_digest=material.action_digest,
                target_digest=material.membership_plan().target_digest,
                dispatch_receipt_digest=dispatch_receipt_digest,
                state="membership_present" if membership is not None else "membership_absent",
                observer_identity_ref=self.identity_ref,
                source_ref="graph-observation:" + source,
                observed_at=after,
                valid_until=at + timedelta(seconds=60),
            )

    async def _read(
        self, path: str, headers: dict[str, str], *, allow_absent: bool = False
    ) -> dict[str, object] | None:
        response = await self.client.get(
            "https://graph.microsoft.com/v1.0/" + path,
            headers=headers,
            follow_redirects=False,
            timeout=5,
        )
        if response.status_code == 404 and allow_absent:
            return None
        if response.status_code != 200 or len(response.content) > 65536:
            raise ValueError("human access independent source is unavailable; no retry was made")
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("human access independent source is malformed")
        return value


__all__ = ["IndependentHumanAccessObserver"]
