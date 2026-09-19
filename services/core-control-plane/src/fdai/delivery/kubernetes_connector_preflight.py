"""Authenticated observer preflight admission and current source verification."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Any, Protocol, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_service_contracts.cluster_connector import ConnectorContract, Digest, connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    ConstraintName,
    ConstraintSource,
    ObserverDeploymentContext,
    ObserverDeploymentFact,
    ObserverPreflightReceipt,
    TargetRef,
)
from pydantic import Field, field_validator, model_validator

from fdai.shared.providers.state_store import StateStore

PREFLIGHT_PREFIX = "observer-deployment:preflight:v1:"


def _contribution(receipt: ObserverPreflightReceipt) -> tuple[str, tuple[str, ...]]:
    return receipt.issuer_ref, tuple(sorted(fact.name for fact in receipt.context.facts))


class ObserverPreflightGrant(ConnectorContract):
    """Deployment-owned verifier enrollment; the issuer cannot register or widen itself."""

    issuer_ref: TargetRef
    key_ref: Digest
    public_key: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    target_ref: TargetRef
    allowed_facts: Annotated[
        dict[ConstraintName, tuple[ConstraintSource, ...]], Field(min_length=1, max_length=16)
    ]
    producer_revision: Digest
    valid_from: datetime
    expires_at: datetime
    revoked: Annotated[bool, Field(strict=True)] = False
    can_select_owner: Annotated[bool, Field(strict=True)] = False

    @field_validator("valid_from", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if self.key_ref != "sha256:" + hashlib.sha256(bytes.fromhex(self.public_key)).hexdigest():
            raise ValueError("observer verifier key digest is invalid")
        if self.expires_at <= self.valid_from:
            raise ValueError("observer verifier grant has an invalid window")
        if any(
            not sources or len(set(sources)) != len(sources)
            for sources in self.allowed_facts.values()
        ):
            raise ValueError("observer verifier fact sources must be nonempty and unique")
        return self


class ObserverPreflightGrants(Protocol):
    async def read(
        self, target_ref: str, issuer_ref: str, key_ref: str
    ) -> ObserverPreflightGrant | None: ...


async def verify_preflight(
    receipt: ObserverPreflightReceipt,
    *,
    grants: ObserverPreflightGrants,
    now: datetime,
    clock: Callable[[], datetime] | None = None,
) -> ObserverPreflightGrant:
    receipt = ObserverPreflightReceipt.model_validate_json(receipt.model_dump_json())
    cutoff = connector_time(now)
    grant = await grants.read(receipt.context.target_ref, receipt.issuer_ref, receipt.key_ref)
    if clock is not None:
        completed = connector_time(clock())
        if completed < cutoff:
            raise ValueError("observer preflight clock moved backwards")
        cutoff = completed
    if grant is None:
        raise ValueError("observer preflight verifier is not enrolled")
    grant = ObserverPreflightGrant.model_validate_json(grant.model_dump_json())
    if (
        grant.revoked
        or grant.target_ref != receipt.context.target_ref
        or grant.issuer_ref != receipt.issuer_ref
        or grant.key_ref != receipt.key_ref
        or grant.producer_revision != receipt.producer_revision
        or not grant.valid_from <= receipt.issued_at <= cutoff < grant.expires_at
        or receipt.context.expires_at > grant.expires_at
        or cutoff >= receipt.context.expires_at
    ):
        raise ValueError("observer preflight enrollment or lifetime is invalid")
    if not grant.can_select_owner and (
        receipt.context.existing_method is not None or receipt.context.requested_method is not None
    ):
        raise ValueError("observer verifier cannot attest installation ownership")
    if any(
        fact.source not in grant.allowed_facts.get(fact.name, ()) for fact in receipt.context.facts
    ):
        raise ValueError("observer verifier exceeded its fact scope")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(grant.public_key)).verify(
            bytes.fromhex(receipt.signature), receipt.signing_bytes()
        )
    except InvalidSignature as exc:
        raise ValueError("observer preflight signature is invalid") from exc
    return grant


class SignedObserverConstraints:
    """Retain current verifier receipts atomically and reauthenticate every recommendation read."""

    def __init__(
        self, store: StateStore, *, grants: ObserverPreflightGrants, now: Callable[[], datetime]
    ) -> None:
        self._store, self._grants, self._now = store, grants, now

    async def retain(self, receipt: ObserverPreflightReceipt) -> bool:
        receipt = ObserverPreflightReceipt.model_validate_json(receipt.model_dump_json())
        grant = await verify_preflight(
            receipt, grants=self._grants, now=self._now(), clock=self._now
        )
        key = PREFLIGHT_PREFIX + canonical_digest({"target_ref": receipt.context.target_ref})
        previous = await self._store.read_state(key)
        revision = 0
        receipts: tuple[ObserverPreflightReceipt, ...] = ()
        if previous is not None:
            receipts, revision = self._decode(previous)
            if any(item.context.target_ref != receipt.context.target_ref for item in receipts):
                raise ValueError("observer preflight checkpoint changed target")
            identity = _contribution(receipt)
            for item in receipts:
                prior_identity = _contribution(item)
                if (
                    prior_identity[0] == identity[0]
                    and prior_identity != identity
                    and set(prior_identity[1]) & set(identity[1])
                ):
                    raise ValueError("observer preflight contribution overlaps retained evidence")
            old = next((item for item in receipts if _contribution(item) == identity), None)
            if old is not None:
                if old == receipt:
                    await verify_preflight(
                        receipt, grants=self._grants, now=self._now(), clock=self._now
                    )
                    return False
                if (
                    old.issued_at >= receipt.issued_at
                    or old.context.observed_at > receipt.context.observed_at
                ):
                    raise ValueError("observer preflight conflicts with current evidence")
        receipts = tuple(
            sorted(
                (
                    *[item for item in receipts if _contribution(item) != _contribution(receipt)],
                    receipt,
                ),
                key=_contribution,
            )
        )
        if len(receipts) > 16:
            raise ValueError("observer preflight contribution count exceeds its bound")
        current = await verify_preflight(
            receipt, grants=self._grants, now=self._now(), clock=self._now
        )
        if current != grant:
            raise ValueError("observer verifier grant changed during admission")
        value = {
            "revision": revision + 1,
            "receipts": [item.model_dump(mode="json") for item in receipts],
            "receipt_digest": canonical_digest([item.model_dump(mode="json") for item in receipts]),
        }
        audit = {
            "kind": "observer.preflight.retained",
            "correlation_id": value["receipt_digest"],
            "actor": receipt.issuer_ref,
            "execution_authority": False,
        }
        written = (
            await self._store.write_state_with_audit_if_absent(key, value, audit)
            if previous is None
            else await self._store.compare_and_set_state_with_audit(
                key, value, expected_revision=revision, audit_entry=audit
            )
        )
        if not written:
            winner = await self._store.read_state(key)
            if winner is None or receipt not in self._decode(winner)[0]:
                raise ValueError("observer preflight changed concurrently")
            await verify_preflight(receipt, grants=self._grants, now=self._now(), clock=self._now)
        return written

    async def read(self, target_ref: str, *, now: datetime) -> ObserverDeploymentContext | None:
        value = await self._store.read_state(
            PREFLIGHT_PREFIX + canonical_digest({"target_ref": target_ref})
        )
        if value is None:
            return None
        receipts, _ = self._decode(value)
        for receipt in receipts:
            if receipt.context.target_ref != target_ref:
                raise ValueError("observer preflight target mismatch")
            await verify_preflight(
                receipt,
                grants=self._grants,
                now=max(connector_time(now), connector_time(self._now())),
                clock=self._now,
            )
        facts: dict[ConstraintName, ObserverDeploymentFact] = {}
        for receipt in receipts:
            for fact in receipt.context.facts:
                if fact.name in facts and facts[fact.name] != fact:
                    raise ValueError("observer preflight sources conflict on a constraint")
                facts[fact.name] = fact
        owners = {
            item.context.existing_method
            for item in receipts
            if item.context.existing_method is not None
        }
        methods = {
            item.context.requested_method
            for item in receipts
            if item.context.requested_method is not None
        }
        discoveries = {
            (item.context.discovery_digest, item.context.private_cluster) for item in receipts
        }
        if len(owners) > 1 or len(methods) > 1 or len(discoveries) != 1:
            raise ValueError("observer preflight sources conflict on deployment identity")
        context = ObserverDeploymentContext(
            target_ref=target_ref,
            discovery_digest=receipts[0].context.discovery_digest,
            private_cluster=receipts[0].context.private_cluster,
            observed_at=max(item.context.observed_at for item in receipts),
            expires_at=min(item.context.expires_at for item in receipts),
            facts=tuple(sorted(facts.values(), key=lambda fact: fact.name)),
            existing_method=next(iter(owners), None),
            requested_method=next(iter(methods), None),
        )
        if not context.observed_at <= connector_time(self._now()) < context.expires_at:
            raise ValueError("observer preflight expired during readback")
        return context

    @staticmethod
    def _decode(value: Mapping[str, Any]) -> tuple[tuple[ObserverPreflightReceipt, ...], int]:
        if (
            set(value) != {"revision", "receipts", "receipt_digest"}
            or type(value["revision"]) is not int
            or not 1 <= value["revision"] < 2**63 - 1
        ):
            raise ValueError("observer preflight checkpoint is invalid")
        raw = value["receipts"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
            raise ValueError("observer preflight receipts exceed their bound")
        receipts = tuple(ObserverPreflightReceipt.model_validate(item) for item in raw)
        if len({_contribution(item) for item in receipts}) != len(receipts):
            raise ValueError("observer preflight contributions must be unique")
        per_issuer: dict[str, set[str]] = {}
        for item in receipts:
            issuer, names = _contribution(item)
            retained = per_issuer.setdefault(issuer, set())
            if retained.intersection(names):
                raise ValueError("observer preflight contributions overlap")
            retained.update(names)
        if (
            canonical_digest([item.model_dump(mode="json") for item in receipts])
            != value["receipt_digest"]
        ):
            raise ValueError("observer preflight checkpoint digest mismatch")
        return receipts, value["revision"]
