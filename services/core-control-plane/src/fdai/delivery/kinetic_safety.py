"""Pre-dispatch persistence for existing exact kinetic proposal artifacts."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.delivery.kinetic_proposal import StateStoreKineticActionProposalStore
from fdai.delivery.reconciliation_artifacts import StateStoreExecutedActionArtifactStore
from fdai.shared.contracts.models import Action, OntologyActionType, OntologyRelease


class ExistingProposalKineticSafetyWriter:
    """Join an existing proposal to an existing Action before dispatch.

    A missing proposal preserves legacy execution. Every present proposal must
    predate and exactly match the Action; no Action, plan, or release is rebuilt.
    """

    def __init__(
        self,
        *,
        proposal_store: StateStoreKineticActionProposalStore,
        artifact_store: StateStoreExecutedActionArtifactStore,
        action_types_by_name: Mapping[str, OntologyActionType],
        active_release: OntologyRelease,
    ) -> None:
        self._proposal_store = proposal_store
        self._artifact_store = artifact_store
        self._action_types_by_name = dict(action_types_by_name)
        self._active_release = active_release

    async def persist(
        self,
        *,
        action: Action,
        correlation_id: str,
    ) -> str | None:
        """Persist and return the exact receipt id, or decline a legacy action."""

        proposal = await self._proposal_store.resolve_by_correlation(correlation_id)
        if proposal is None:
            return None
        if proposal.created_at > action.created_at:
            raise ValueError("kinetic proposal MUST exist before its Action")
        action_type = self._action_types_by_name.get(action.action_type)
        if action_type is None:
            raise ValueError("kinetic proposal ActionType body is unavailable")
        receipt = await self._artifact_store.store(
            action=action,
            plan=proposal.plan,
            action_type=action_type,
            active_release=self._active_release,
        )
        return receipt.receipt_id


__all__ = ["ExistingProposalKineticSafetyWriter"]
