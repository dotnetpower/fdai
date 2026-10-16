"""Linearized persistence seam for dormant Rule activation cohort state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol


class RuleActivationCohortCommitStore(Protocol):
    """Atomically recheck lease time while committing cohort candidate state."""

    async def advance_prepare(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int,
    ) -> bool: ...

    async def activate_candidate(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int,
        latest_prepare_key: str,
        expected_latest_prepare: Mapping[str, Any],
        lease_expires_at: datetime,
    ) -> bool: ...

    async def insert_applied(
        self,
        *,
        candidate_key: str,
        expected_candidate: Mapping[str, Any],
        replacement_candidate: Mapping[str, Any],
        insert_key: str,
        insert_value: Mapping[str, Any],
        applied_at: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...


__all__ = ["RuleActivationCohortCommitStore"]
