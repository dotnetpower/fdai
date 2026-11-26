"""Workflow journal adapter for immutable safeguard pre-bundle commitments."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.safeguard_pre_bundle import (
    SafeguardPreBundleCommitment,
    safeguard_pre_bundle_commitment_from_mapping,
    safeguard_pre_bundle_commitment_to_mapping,
)
from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
)


class ProcessRuntimeSafeguardCommitmentStore:
    """Bind one exact commitment to a Process step attempt before dispatch."""

    def __init__(self, process_store: ProcessRuntimeStore) -> None:
        self._process_store = process_store

    async def read(
        self,
        *,
        process_id: str,
        step_id: str,
        attempt: int,
    ) -> SafeguardPreBundleCommitment | None:
        events = await self._process_store.events(process_id)
        matches = tuple(
            item
            for item in events
            if item.kind is ProcessEventKind.ACTION_PRE_BUNDLE_COMMITTED
            and item.step_id == step_id
            and item.attempt == attempt
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise RuntimeError("workflow step has conflicting pre-bundle commitments")
        raw = matches[0].payload.get("commitment")
        if not isinstance(raw, dict):
            raise ValueError("workflow pre-bundle commitment is malformed")
        return safeguard_pre_bundle_commitment_from_mapping(raw)

    async def bind(
        self,
        *,
        process_id: str,
        step_id: str,
        attempt: int,
        correlation_id: str,
        commitment: SafeguardPreBundleCommitment,
    ) -> SafeguardPreBundleCommitment:
        existing = await self.read(
            process_id=process_id,
            step_id=step_id,
            attempt=attempt,
        )
        if existing is not None:
            if existing != commitment:
                raise RuntimeError("workflow pre-bundle commitment conflicts with durable evidence")
            return existing
        events = await self._process_store.events(process_id)
        approval_event_ids = tuple(
            item.event_id
            for item in events
            if item.kind is ProcessEventKind.APPROVAL_RECORDED and item.attempt == attempt
        )
        commitment_mapping = safeguard_pre_bundle_commitment_to_mapping(commitment)
        approval_binding_digest = content_digest(
            {
                "domain": "workflow-pre-bundle-approval-binding",
                "process_id": process_id,
                "step_id": step_id,
                "attempt": attempt,
                "commitment_digest": commitment.commitment_digest,
                "approval_event_ids": approval_event_ids,
            }
        )
        created = await self._process_store.append_event(
            ProcessEvent(
                event_id=event_id(
                    process_id,
                    f"step:{step_id}:attempt:{attempt}:pre-bundle-committed",
                ),
                process_id=process_id,
                kind=ProcessEventKind.ACTION_PRE_BUNDLE_COMMITTED,
                idempotency_key=(
                    f"{process_id}:step:{step_id}:attempt:{attempt}:pre-bundle-committed"
                ),
                recorded_at=commitment.committed_at,
                correlation_id=correlation_id,
                step_id=step_id,
                attempt=attempt,
                payload={
                    "commitment": commitment_mapping,
                    "approval_event_ids": approval_event_ids,
                    "approval_binding_digest": approval_binding_digest,
                    "execution_authority": False,
                    "effect_verified": False,
                },
            )
        )
        bound = await self.read(
            process_id=process_id,
            step_id=step_id,
            attempt=attempt,
        )
        if bound is None:
            raise RuntimeError("workflow pre-bundle commitment readback is unavailable")
        if bound != commitment:
            raise RuntimeError("workflow pre-bundle commitment readback mismatched")
        if not created and bound != commitment:
            raise RuntimeError("workflow pre-bundle commitment duplicate conflicts")
        return bound


__all__ = ["ProcessRuntimeSafeguardCommitmentStore"]
