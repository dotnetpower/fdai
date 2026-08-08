"""Candidate persistence contract and process-local CAS implementation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from fdai.core.scheduler.blueprints.models import (
    AutomationBlueprintCandidate,
    AutomationBlueprintState,
)


class AutomationBlueprintStore(Protocol):
    async def create(
        self, candidate: AutomationBlueprintCandidate
    ) -> AutomationBlueprintCandidate: ...

    async def get(self, candidate_id: str) -> AutomationBlueprintCandidate: ...

    async def list_all(self) -> Sequence[AutomationBlueprintCandidate]: ...

    async def transition(
        self,
        candidate: AutomationBlueprintCandidate,
        *,
        expected_state: AutomationBlueprintState,
    ) -> AutomationBlueprintCandidate | None: ...

    async def expire(self, *, now: datetime) -> int: ...


class InMemoryAutomationBlueprintStore:
    def __init__(self) -> None:
        self._candidates: dict[str, AutomationBlueprintCandidate] = {}

    async def create(self, candidate: AutomationBlueprintCandidate) -> AutomationBlueprintCandidate:
        prior = self._candidates.get(candidate.candidate_id)
        if prior is not None:
            if (
                prior.dedup_key == candidate.dedup_key
                and prior.evidence_fingerprints == candidate.evidence_fingerprints
            ):
                return prior
            raise ValueError("automation blueprint candidate id collision")
        active = next(
            (
                item
                for item in self._candidates.values()
                if item.dedup_key == candidate.dedup_key
                and item.state
                in {AutomationBlueprintState.DRAFT, AutomationBlueprintState.ACCEPTED}
            ),
            None,
        )
        if active is not None:
            return active
        terminal = [
            item for item in self._candidates.values() if item.dedup_key == candidate.dedup_key
        ]
        if terminal:
            latest = max(terminal, key=lambda item: (item.created_at, item.candidate_id))
            if set(candidate.evidence_fingerprints) <= set(latest.evidence_fingerprints):
                return latest
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    async def get(self, candidate_id: str) -> AutomationBlueprintCandidate:
        try:
            return self._candidates[candidate_id]
        except KeyError as exc:
            raise KeyError(f"automation blueprint {candidate_id!r} was not found") from exc

    async def list_all(self) -> Sequence[AutomationBlueprintCandidate]:
        return tuple(self._candidates[key] for key in sorted(self._candidates))

    async def transition(
        self,
        candidate: AutomationBlueprintCandidate,
        *,
        expected_state: AutomationBlueprintState,
    ) -> AutomationBlueprintCandidate | None:
        current = await self.get(candidate.candidate_id)
        if current.state is not expected_state:
            return None
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    async def expire(self, *, now: datetime) -> int:
        expired = 0
        for candidate_id, candidate in tuple(self._candidates.items()):
            if (
                candidate.state
                in {
                    AutomationBlueprintState.DRAFT,
                    AutomationBlueprintState.ACCEPTED,
                }
                and candidate.expires_at <= now
            ):
                from dataclasses import replace

                self._candidates[candidate_id] = replace(
                    candidate,
                    state=AutomationBlueprintState.EXPIRED,
                    review_reason="candidate_expired",
                )
                expired += 1
        return expired


__all__ = ["AutomationBlueprintStore", "InMemoryAutomationBlueprintStore"]
