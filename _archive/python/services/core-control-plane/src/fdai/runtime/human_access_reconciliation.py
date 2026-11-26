"""Bounded mechanical notices for human-access review and delayed effect observation.

This worker never judges, approves, prepares, dispatches or records an effect.
Original request records prevent retry from renewing the five-minute review
window; retained materials make late receipts independently observable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    human_access_record_digest,
)
from fdai_service_contracts.human_access_workflow import (
    HUMAN_ACCESS_EVENT_TYPE,
    HumanAccessWorkNotice,
)

from fdai.core.human_assignment.model import AssignmentCase
from fdai.runtime.human_access_workflow import HumanAccessWorkflowRuntime


@dataclass(slots=True)
class HumanAccessReconciliation:
    """Rotate bounded case/material pages; broker notices contain no private target or decisions."""

    runtime: HumanAccessWorkflowRuntime
    ingress: Callable[[Mapping[str, Any]], Awaitable[object]]
    case_offset: int = 0
    material_offset: int = 0

    async def tick(self) -> int:
        """Bound one rotation; failed work stays revisitable and does not become execution."""
        async with asyncio.timeout(25):
            cases, total = await self.runtime.store.read_state_page(
                "human_assignment:case:", limit=20, offset=self.case_offset
            )
            sent = 0
            for raw in cases:
                try:
                    case = AssignmentCase.from_dict(dict(raw))
                except (ValueError, TypeError, KeyError):
                    await self._invalid("case")
                    continue
                if case.state.value not in {"ownership_merged", "approved"} or (
                    case.state.value == "approved"
                ) != (case.intent.revocation is not None):
                    continue
                action_type = (
                    "ops.revoke-human-access"
                    if case.intent.revocation is not None
                    else "ops.apply-human-access"
                )
                promotion = await self.runtime.store.read_state("action_promotion:" + action_type)
                if promotion is None:
                    continue
                source = human_access_record_digest(
                    {"case": case.to_dict(), "promotion": dict(promotion)}
                )
                request_id = uuid5(NAMESPACE_URL, "fdai:human-access-request:" + source)
                key = "human_assignment:execution-request:" + str(request_id)
                now = self.runtime.clock()
                notice = HumanAccessWorkNotice(
                    request_id=request_id,
                    operation="request",
                    case_id=case.case_id,
                    expected_revision=case.revision,
                    observed_at=now,
                    expires_at=now + timedelta(minutes=5),
                )
                await self.runtime.store.write_state_with_audit_if_absent(
                    key,
                    notice.model_dump(mode="json"),
                    {
                        "actor": "human-access-reconciliation",
                        "action_kind": "human_access.request.observed",
                        "request_id": str(request_id),
                        "mode": "shadow",
                    },
                )
                retained = HumanAccessWorkNotice.model_validate(
                    await self.runtime.store.read_state(key)
                )
                if retained.expires_at > now:
                    await self._publish(retained)
                    sent += 1
            self.case_offset = (
                0 if self.case_offset + len(cases) >= total else self.case_offset + len(cases)
            )
            materials, material_total = await self.runtime.store.read_state_page(
                "human_assignment:execution-material:", limit=20, offset=self.material_offset
            )
            for raw in materials:
                try:
                    material = HumanAccessExecutionMaterial.model_validate(raw)
                    case = await self.runtime.builder.cases.get_case(
                        material.action().params["case_id"]
                    )
                except (ValueError, TypeError, KeyError):
                    await self._invalid("material")
                    continue
                preparation = (
                    case.iam_recovery_preparation
                    if material.inverse is not None
                    else case.iam_preparation
                )
                exact_prepared = (
                    preparation is not None
                    and preparation.material_digest == material.digest
                    and preparation.prepared_revision == case.revision
                )
                if exact_prepared:
                    link = await self.runtime.store.read_state(
                        "runtime:isolated-executor:human-access:" + str(material.action().action_id)
                    )
                    if link is not None:
                        await self._publish(self._notice(material, "reconcile"))
                    elif material.expires_at > self.runtime.clock():
                        await self._publish(self._notice(material, "resume"))
                    else:
                        continue
                    sent += 1
                elif (
                    material.inverse is None
                    and case.state.value == "degraded"
                    and case.iam_preparation is not None
                    and case.iam_preparation.material_digest == material.digest
                    and case.iam_recovery_preparation is None
                ):
                    await self._publish(self._notice(material, "recovery"))
                    sent += 1
                elif case.state.value in {"ownership_merged", "approved", "degraded"} and (
                    material.expires_at > self.runtime.clock()
                ):
                    if all(
                        [
                            await self.runtime.store.read_state("operator-hil-decision:" + slot)
                            is not None
                            for slot in material.approval_ids
                        ]
                    ):
                        await self._publish(
                            self._notice(material, "decision", material.approval_ids[-1])
                        )
                        sent += 1
            self.material_offset = (
                0
                if self.material_offset + len(materials) >= material_total
                else self.material_offset + len(materials)
            )
            return sent

    async def _invalid(self, kind: str) -> None:
        """Audit bounded poison classification without exposing private record contents."""
        await self.runtime.store.append_audit_entry(
            {
                "actor": "human-access-reconciliation",
                "action_kind": "human_access.source.invalid",
                "source_kind": kind,
                "mode": "shadow",
            }
        )

    async def decision(self, approval_id: str) -> None:
        """Resolve original park material and enter Huginn rather than a peer agent."""
        park = await self.runtime.store.read_state("hil_park:" + approval_id)
        metadata = park.get("metadata") if park is not None else None
        if not isinstance(metadata, Mapping) or metadata.get("decision_route") != "human_access":
            raise ValueError("human access decision route is not bound to an original park")
        material = await self.runtime.builder.materials.read(str(metadata.get("action_id")))
        if material is None or approval_id not in material.approval_ids:
            raise ValueError("human access original approval source disappeared")
        await self._publish(self._notice(material, "decision", approval_id))

    def _notice(
        self,
        material: HumanAccessExecutionMaterial,
        operation: str,
        approval_id: str | None = None,
    ) -> HumanAccessWorkNotice:
        action = material.action()
        now = self.runtime.clock()
        return HumanAccessWorkNotice.model_validate(
            {
                "request_id": action.event_id,
                "operation": operation,
                "case_id": action.params["case_id"],
                "expected_revision": action.params["expected_revision"],
                "action_id": action.action_id,
                "approval_id": approval_id,
                "observed_at": now,
                "expires_at": now + timedelta(seconds=30),
            }
        )

    async def _publish(self, notice: HumanAccessWorkNotice) -> None:
        key = human_access_record_digest(
            {
                "notice": notice.model_dump(mode="json"),
                "observation_epoch": int(self.runtime.clock().timestamp()) // 30,
            }
        )
        await self.ingress(
            {
                "source": "human-access-reconciliation",
                "event_type": HUMAN_ACCESS_EVENT_TYPE,
                "event_id": str(uuid5(NAMESPACE_URL, key)),
                "correlation_id": str(notice.request_id),
                "idempotency_key": "human-access-notice:" + key,
                "mode": "shadow",
                "resource_ref": "human-assignment:" + notice.case_id,
                "detected_at": notice.observed_at.isoformat(),
                "ingested_at": notice.observed_at.isoformat(),
                "payload": {"notice": notice.model_dump(mode="json")},
            }
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Reconcile every30seconds under the normal supervised lifecycle and bounded tick."""
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                continue


__all__ = ["HumanAccessReconciliation"]
