"""Durable delivery-owned production of exact kinetic action proposals."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter

from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.operational_planning import (
    KineticActionProposal,
    OperationalPlan,
    validate_operational_plan_identity,
)
from fdai.shared.providers.state_store import StateStore

_OPERATIONAL_PLAN_ADAPTER = TypeAdapter(OperationalPlan)


class KineticActionProposalConflictError(RuntimeError):
    """One operational-plan identity was reused with different proposal content."""


class StateStoreKineticActionProposalStore:
    """Commit and resolve proposals built only from existing exact planning artifacts."""

    _KEY_PREFIX = "operational-planning:kinetic-proposal:"
    _CORRELATION_KEY_PREFIX = "operational-planning:kinetic-proposal-correlation:"

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def commit(
        self,
        *,
        operational_plan: OperationalPlan,
        mutation_plan: MutationPlan,
        arguments: Mapping[str, Any],
        created_at: datetime,
    ) -> KineticActionProposal:
        """Persist one exact proposal; only byte-equivalent content is replay-safe."""

        validate_operational_plan_identity(operational_plan)
        selected_id = operational_plan.selection.selected_option_id
        if not operational_plan.complete or selected_id is None:
            raise ValueError("kinetic proposal requires a complete operational plan")
        selected = next(
            (
                option
                for option in operational_plan.decision_case.options
                if option.option_id == selected_id
            ),
            None,
        )
        if selected is None or selected.action_type is None:
            raise ValueError("kinetic proposal requires one selected ActionType option")
        if (
            mutation_plan.schema_version != "2.0.0"
            or mutation_plan.operational_plan_ref != operational_plan.plan_id
            or mutation_plan.action_type_ref.name != selected.action_type
            or len(mutation_plan.targets) != 1
            or mutation_plan.targets[0].object_id != operational_plan.target_resource_id
        ):
            raise ValueError("kinetic proposal artifacts do not match operational selection")
        proposal = KineticActionProposal.create(
            correlation_id=operational_plan.decision_case.correlation_id,
            process_id=operational_plan.process_id,
            operational_plan_id=operational_plan.plan_id,
            selected_option_id=selected_id,
            plan=mutation_plan,
            target_resource_ref=operational_plan.target_resource_id,
            arguments=arguments,
            created_at=created_at,
        )
        key = self._key(operational_plan.plan_id)
        record = {
            "kind": "operational_planning.kinetic_proposal",
            "correlation_id": proposal.correlation_id,
            "operational_plan_id": operational_plan.plan_id,
            "operational_plan": _OPERATIONAL_PLAN_ADAPTER.dump_python(
                operational_plan, mode="json"
            ),
            "proposal": proposal.model_dump(mode="json"),
        }
        await self._claim_correlation_index(
            correlation_id=proposal.correlation_id,
            operational_plan_id=operational_plan.plan_id,
        )
        created = await self._store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "action_kind": "kinetic_proposal.committed",
                "actor": "kinetic-proposal-store",
                "operational_plan_id": operational_plan.plan_id,
                "proposal_id": proposal.proposal_id,
                "mutation_plan_digest": mutation_plan.digest,
            },
        )
        if created:
            return proposal
        existing = await self._store.read_state(key)
        if existing is None or dict(existing) != record:
            raise KineticActionProposalConflictError(
                "operational plan identity conflicts with another kinetic proposal"
            )
        return self._parse(existing, operational_plan)

    async def resolve(
        self,
        operational_plan: OperationalPlan,
    ) -> KineticActionProposal | None:
        """Resolve only a proposal bound to the supplied exact OperationalPlan."""

        validate_operational_plan_identity(operational_plan)
        raw = await self._store.read_state(self._key(operational_plan.plan_id))
        return None if raw is None else self._parse(raw, operational_plan)

    async def resolve_by_correlation(
        self,
        correlation_id: str,
    ) -> KineticActionProposal | None:
        """Resolve one exact proposal without synthesizing a planning artifact."""

        if not correlation_id:
            raise ValueError("kinetic proposal correlation id MUST be non-empty")
        index = await self._store.read_state(self._correlation_key(correlation_id))
        if index is None:
            return None
        if (
            index.get("kind") != "operational_planning.kinetic_proposal_correlation"
            or index.get("correlation_id") != correlation_id
            or not isinstance(index.get("operational_plan_id"), str)
        ):
            raise RuntimeError("stored kinetic proposal correlation index is malformed")
        raw = await self._store.read_state(self._key(str(index["operational_plan_id"])))
        if raw is None:
            raise RuntimeError("kinetic proposal correlation index has no proposal record")
        proposal = self._parse_record(raw)
        if proposal.correlation_id != correlation_id:
            raise RuntimeError("stored kinetic proposal correlation does not match its index")
        return proposal

    async def _claim_correlation_index(
        self,
        *,
        correlation_id: str,
        operational_plan_id: str,
    ) -> None:
        record = {
            "kind": "operational_planning.kinetic_proposal_correlation",
            "correlation_id": correlation_id,
            "operational_plan_id": operational_plan_id,
        }
        key = self._correlation_key(correlation_id)
        if await self._store.write_state_if_absent(key, record):
            return
        existing = await self._store.read_state(key)
        if existing is None or dict(existing) != record:
            raise KineticActionProposalConflictError(
                "correlation identity conflicts with another kinetic proposal"
            )

    @classmethod
    def _parse_record(cls, raw: Mapping[str, object]) -> KineticActionProposal:
        try:
            operational_plan = _OPERATIONAL_PLAN_ADAPTER.validate_python(
                raw.get("operational_plan")
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("stored kinetic proposal operational plan is malformed") from exc
        return cls._parse(raw, operational_plan)

    @classmethod
    def _parse(
        cls,
        raw: Mapping[str, object],
        operational_plan: OperationalPlan,
    ) -> KineticActionProposal:
        if (
            raw.get("kind") != "operational_planning.kinetic_proposal"
            or raw.get("operational_plan_id") != operational_plan.plan_id
            or raw.get("operational_plan")
            != _OPERATIONAL_PLAN_ADAPTER.dump_python(operational_plan, mode="json")
        ):
            raise RuntimeError("stored kinetic proposal identity is malformed")
        proposal = KineticActionProposal.model_validate(raw.get("proposal"))
        if proposal.operational_plan_id != operational_plan.plan_id:
            raise RuntimeError("stored kinetic proposal does not match its operational plan")
        return proposal

    @classmethod
    def _key(cls, operational_plan_id: str) -> str:
        return f"{cls._KEY_PREFIX}{operational_plan_id}"

    @classmethod
    def _correlation_key(cls, correlation_id: str) -> str:
        digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()
        return f"{cls._CORRELATION_KEY_PREFIX}{digest}"


__all__ = [
    "KineticActionProposalConflictError",
    "StateStoreKineticActionProposalStore",
]
