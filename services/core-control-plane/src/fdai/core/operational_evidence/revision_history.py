"""Pinned registry revision history: which earlier pins still admit and which lineage survives.

A revocation revision retires every admission issued under an earlier pin; boundaries then
re-request. Lineage is narrower: it ends only when a later revision revoked, removed, or
narrowed the exact binding or grant the cited admission matched.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from .grant_registry import CaseScopeGrantRegistry
from .grant_registry_loader import classify_grant_revision
from .registry_json import RevisionClass
from .trust_registry import TrustRegistry, classify_trust_revision


@dataclass(frozen=True, slots=True)
class RegistryPins:
    """The two registry revisions behind one proof-store record."""

    trust_pin: str
    grant_pin: str

    @property
    def digest(self) -> str:
        """Return the content address used as the record-key prefix."""

        return content_digest({"grant_registry_pin": self.grant_pin, "trust_pin": self.trust_pin})


@dataclass(frozen=True, slots=True)
class RegistryRevision:
    """One reviewed pair of registry revisions, oldest first in a history."""

    trust: TrustRegistry
    grants: CaseScopeGrantRegistry

    @property
    def pins(self) -> RegistryPins:
        return RegistryPins(trust_pin=self.trust.pin, grant_pin=self.grants.pin)


@dataclass(frozen=True, slots=True)
class LineageBinding:
    """The binding and grants one admission matched when it was issued."""

    purpose_id: str
    verifier_id: str
    verifier_version: str
    trust_anchor_id: str
    matched_grants: tuple[str, ...]


class RegistryHistory:
    """Ordered registry revisions; the newest revision is the only current one."""

    def __init__(self, revisions: Sequence[RegistryRevision]) -> None:
        if not revisions:
            raise ValueError("registry history requires at least the current revision")
        self._revisions = tuple(revisions)
        self._steps = tuple(
            RevisionClass.REVOCATION
            if RevisionClass.REVOCATION
            in (
                classify_trust_revision(before.trust, after.trust),
                classify_grant_revision(before.grants, after.grants),
            )
            else RevisionClass.ROUTINE_ROTATION
            for before, after in zip(self._revisions, self._revisions[1:], strict=False)
        )

    @property
    def current(self) -> RegistryRevision:
        return self._revisions[-1]

    def step_classes(self) -> tuple[RevisionClass, ...]:
        """Return the content-derived class of each consecutive revision step."""

        return self._steps

    def admitting_pins(self) -> frozenset[str]:
        """Return record-key pin digests that no later revocation revision retired."""

        admitting = {self._revisions[-1].pins.digest}
        for index in range(len(self._steps) - 1, -1, -1):
            if self._steps[index] is RevisionClass.REVOCATION:
                break
            admitting.add(self._revisions[index].pins.digest)
        return frozenset(admitting)

    def lineage_intact(self, pins_digest: str, binding: LineageBinding, *, at: datetime) -> bool:
        """Return whether every revision since issuance kept the matched binding and grants."""

        start = next(
            (
                index
                for index, revision in enumerate(self._revisions)
                if revision.pins.digest == pins_digest
            ),
            None,
        )
        if start is None:
            return False
        key = (binding.verifier_id, binding.verifier_version, binding.trust_anchor_id)
        reference = self._revisions[start]
        base_purpose = reference.trust.purposes.get(binding.purpose_id)
        base_verifier = (
            next((item for item in base_purpose.verifiers if item.key == key), None)
            if base_purpose is not None
            else None
        )
        base_windows = reference.grants.entry_windows()
        if base_verifier is None or any(
            ("principal_grant", grant) not in base_windows
            and ("reuse_grant", grant) not in base_windows
            for grant in binding.matched_grants
        ):
            return False
        for revision in self._revisions[start:]:
            purpose = revision.trust.purposes.get(binding.purpose_id)
            verifier = (
                next((item for item in purpose.verifiers if item.key == key), None)
                if purpose is not None and not purpose.revoked
                else None
            )
            if verifier is None or base_verifier.window.narrowed_by(verifier.window):
                return False
            windows = revision.grants.entry_windows()
            for grant in binding.matched_grants:
                grant_key = (
                    ("principal_grant", grant)
                    if ("principal_grant", grant) in base_windows
                    else ("reuse_grant", grant)
                )
                window = windows.get(grant_key)
                if window is None or base_windows[grant_key].narrowed_by(window):
                    return False
        current = self._revisions[-1].trust.purposes[binding.purpose_id]
        active = next(item for item in current.verifiers if item.key == key)
        return active.window.active_at(at)


__all__ = ["LineageBinding", "RegistryHistory", "RegistryPins", "RegistryRevision"]
