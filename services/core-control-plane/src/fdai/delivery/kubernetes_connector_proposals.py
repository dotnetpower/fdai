"""Core-owned proactive observer recommendations from authenticated private-AKS discovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentContext,
    ObserverDeploymentProposal,
)

from fdai.delivery.aks_subscription_discovery import AksPrivateClusterObservation
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
from fdai.shared.providers.state_store import StateStore

OBSERVER_PROPOSAL_PREFIX = "observer-deployment:proposal:v1:"
OBSERVER_CONSTRAINT_PREFIX = "observer-deployment:constraints:v1:"


class ObserverConstraintReader(Protocol):
    """Return server-owned, target-scoped preflight evidence without performing deployment."""

    async def read(self, target_ref: str, *, now: datetime) -> ObserverDeploymentContext | None: ...


class StateStoreObserverConstraints:
    """Read server-owned preflight context; a content digest is integrity, not authentication.

    No public write endpoint is exposed. The injected preflight owner must establish source
    provenance before retaining this context. Missing producers remain missing evidence.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def read(self, target_ref: str, *, now: datetime) -> ObserverDeploymentContext | None:
        value = await self._store.read_state(
            OBSERVER_CONSTRAINT_PREFIX + canonical_digest({"target_ref": target_ref})
        )
        if value is None:
            return None
        if set(value) != {"context", "context_digest"}:
            raise ValueError("observer constraint record has an invalid shape")
        context = ObserverDeploymentContext.model_validate(value["context"])
        if (
            context.target_ref != target_ref
            or canonical_digest(context.model_dump(mode="json")) != value["context_digest"]
        ):
            raise ValueError("observer constraint record does not match its target or digest")
        if context.observed_at > connector_time(now):
            raise ValueError("observer constraints are from the future")
        return context


def _context_digest(context: ObserverDeploymentContext) -> str:
    values = context.model_dump(mode="json")
    values["facts"] = sorted(values["facts"], key=lambda item: item["name"])
    return canonical_digest(values)


def _checkpoint(
    value: Mapping[str, Any], *, target: str
) -> tuple[ObserverDeploymentContext, ObserverDeploymentProposal, int]:
    if (
        set(value) != {"record_type", "revision", "fingerprint", "context", "proposal"}
        or value["record_type"] != "observer_deployment_proposal"
    ):
        raise ValueError("observer proposal checkpoint has an invalid shape")
    context = ObserverDeploymentContext.model_validate(value["context"])
    proposal = ObserverDeploymentProposal.model_validate(value["proposal"])
    revision = value["revision"]
    if (
        type(revision) is not int
        or not 1 <= revision < 2**63 - 1
        or context.target_ref != target
        or proposal.target_ref != target
    ):
        raise ValueError("observer proposal checkpoint is invalid")
    if (
        _context_digest(context) != proposal.context_digest
        or _fingerprint(context, proposal) != value["fingerprint"]
    ):
        raise ValueError("observer proposal checkpoint evidence is invalid")
    if propose_observer_deployment(context, now=proposal.evaluated_at) != proposal:
        raise ValueError("observer proposal checkpoint cannot be replayed")
    return context, proposal, revision


def _fingerprint(context: ObserverDeploymentContext, proposal: ObserverDeploymentProposal) -> str:
    return canonical_digest(
        {
            "target_ref": proposal.target_ref,
            "discovery_digest": context.discovery_digest,
            "status": proposal.status,
            "candidates": [item.model_dump(mode="json") for item in proposal.candidates],
            "recommended": proposal.recommended.model_dump(mode="json")
            if proposal.recommended
            else None,
            "existing_method": context.existing_method,
            "requested_method": context.requested_method,
            "facts": sorted(
                [fact.model_dump(mode="json") for fact in context.facts],
                key=lambda item: item["name"],
            ),
        }
    )


class ObserverDeploymentProposalService:
    """Persist one current recommendation per exact cluster with audited compare-and-set.

    Missing preflight facts create an inspection proposal, never an inferred eligible plan.
    Equivalent fresh recommendations are reused; renewal does not create a new approval or
    notification. This read-model owner never installs, approves or invokes a privileged tool.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        constraints: ObserverConstraintReader,
        now: Callable[[], datetime],
    ) -> None:
        self._store, self._constraints, self._now = store, constraints, now

    async def observe(self, observations: tuple[AksPrivateClusterObservation, ...]) -> int:
        if len(observations) > 128:
            raise ValueError("observer proposal discovery bound exceeded")
        targets = [item.cluster_ref.casefold() for item in observations]
        if len(set(targets)) != len(targets):
            raise ValueError("observer proposal discovery contains duplicate clusters")
        changed = 0
        for observation in observations:
            changed += int(await self._observe(observation))
        return changed

    async def _observe(self, observation: AksPrivateClusterObservation) -> bool:
        now = connector_time(self._now())
        cutoff = connector_time(observation.observed_at)
        if not cutoff <= now < cutoff + timedelta(minutes=10):
            raise ValueError("private cluster discovery evidence is future or stale")
        target = to_neutral_id(observation.cluster_ref)
        constraints = await self._constraints.read(target, now=now)
        values: dict[str, object] = {
            "target_ref": target,
            "discovery_digest": observation.source_digest,
            "observed_at": cutoff,
            "expires_at": cutoff + timedelta(minutes=10),
            "private_cluster": True,
        }
        if constraints is not None:
            constraints = ObserverDeploymentContext.model_validate_json(
                constraints.model_dump_json()
            )
            if constraints.target_ref != target:
                raise ValueError("observer constraints changed target")
            if constraints.observed_at > now:
                raise ValueError("observer constraints are from the future")
            values.update(
                {
                    "existing_method": constraints.existing_method,
                    "requested_method": constraints.requested_method,
                }
            )
            if now < constraints.expires_at:
                values.update(
                    {
                        "facts": constraints.facts,
                        "expires_at": min(constraints.expires_at, cutoff + timedelta(minutes=10)),
                    }
                )
        context = ObserverDeploymentContext.model_validate(values)
        proposal = propose_observer_deployment(context, now=now)
        fingerprint = _fingerprint(context, proposal)
        key = OBSERVER_PROPOSAL_PREFIX + canonical_digest({"target_ref": target})
        previous = await self._store.read_state(key)
        if not now <= connector_time(self._now()) < proposal.expires_at:
            raise ValueError("observer proposal expired before persistence")
        revision = 0
        if previous is not None:
            old_context, old, revision = _checkpoint(previous, target=target)
            if constraints is None:
                values.update(
                    {
                        "existing_method": old_context.existing_method,
                        "requested_method": old_context.requested_method,
                    }
                )
                context = ObserverDeploymentContext.model_validate(values)
                proposal = propose_observer_deployment(context, now=now)
                fingerprint = _fingerprint(context, proposal)
            if (
                old.evaluated_at > proposal.evaluated_at
                or old_context.observed_at > context.observed_at
            ):
                raise ValueError("observer proposal evidence moved backwards")
            if (
                previous.get("fingerprint") == fingerprint
                and now + timedelta(minutes=1) < old.expires_at <= proposal.expires_at
            ):
                return False
        materially_changed = previous is None or previous.get("fingerprint") != fingerprint
        record = {
            "record_type": "observer_deployment_proposal",
            "revision": revision + 1,
            "fingerprint": fingerprint,
            "context": context.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        }
        audit = {
            "kind": "observer.deployment.proposed"
            if materially_changed
            else "observer.deployment.refreshed",
            "correlation_id": proposal.proposal_digest,
            "target_digest": canonical_digest({"target_ref": target}),
            "status": proposal.status,
            "execution_authority": False,
            "approval_required": True,
        }
        if not now <= connector_time(self._now()) < proposal.expires_at:
            raise ValueError("observer proposal expired before persistence")
        if previous is None:
            written = await self._store.write_state_with_audit_if_absent(key, record, audit)
        else:
            written = await self._store.compare_and_set_state_with_audit(
                key, record, expected_revision=revision, audit_entry=audit
            )
        if not written:
            winner = await self._store.read_state(key)
            if winner is None or winner.get("fingerprint") != fingerprint:
                raise ValueError("observer proposal changed concurrently; reinspection required")
            winner_context, winner_proposal, _ = _checkpoint(winner, target=target)
            if (
                winner_context.observed_at < cutoff
                or not winner_proposal.evaluated_at
                <= connector_time(self._now())
                < winner_proposal.expires_at
            ):
                raise ValueError("observer proposal concurrent winner is stale")
            return False
        return materially_changed

    async def current(self, target_ref: str) -> ObserverDeploymentProposal | None:
        """Read an exact target's replay-verified current proposal, or reject stale evidence."""
        key = OBSERVER_PROPOSAL_PREFIX + canonical_digest({"target_ref": target_ref})
        value = await self._store.read_state(key)
        if value is None:
            return None
        context, proposal, _ = _checkpoint(value, target=target_ref)
        now = connector_time(self._now())
        constraints = await self._constraints.read(target_ref, now=now)
        if constraints is not None:
            constraints = ObserverDeploymentContext.model_validate_json(
                constraints.model_dump_json()
            )
            if constraints.target_ref != target_ref or constraints.observed_at > now:
                raise ValueError("observer proposal constraints are invalid")
        current_facts = (
            constraints.facts if constraints is not None and now < constraints.expires_at else ()
        )
        if sorted(context.facts, key=lambda fact: fact.name) != sorted(
            current_facts, key=lambda fact: fact.name
        ) or (
            constraints is not None
            and (
                context.existing_method != constraints.existing_method
                or context.requested_method != constraints.requested_method
            )
        ):
            raise ValueError("observer proposal constraints changed; reinspection required")
        if not proposal.evaluated_at <= connector_time(self._now()) < proposal.expires_at:
            raise ValueError("observer proposal is stale; reinspection required")
        return proposal
