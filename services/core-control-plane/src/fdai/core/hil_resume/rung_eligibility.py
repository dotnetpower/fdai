"""Current directory-backed HIL eligibility; stewardship alone is never RBAC proof."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.shared.providers.human_identity import HumanIdentityDirectory


@dataclass(frozen=True, slots=True)
class DirectoryRungEligibility:
    """Read current active human identity and role evidence inside one bounded attempt."""

    directory: HumanIdentityDirectory
    role_group_ids: Mapping[str, str]
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 10:
            raise ValueError("rung eligibility timeout MUST be in (0, 10]")

    async def is_eligible(
        self,
        *,
        subject_ref: str,
        minimum_role: str,
        context: Mapping[str, Any] | None = None,
        at: datetime | None = None,
    ) -> bool:
        """Only an active exact human with fresh ordinary Approver/Owner membership qualifies."""
        del context, at
        if minimum_role not in {"Approver", "Owner"}:
            return False
        async with asyncio.timeout(self.timeout_seconds):
            identity = await self.directory.get_by_subject_id(subject_ref)
            if (
                identity is None
                or not identity.active
                or identity.provider != "entra"
                or identity.subject_id.strip().casefold() != subject_ref.strip().casefold()
            ):
                return False
            roster = await self.directory.list_role_roster(self.role_group_ids, limit=500)
            matching = [
                row
                for row in roster
                if row.subject_id.strip().casefold() == subject_ref.strip().casefold()
                and row.provider == identity.provider
                and row.principal_type == "person"
            ]
            if not matching or any(not row.active for row in matching):
                return False
            roles = {role for row in matching for role in row.roles}
            return "Owner" in roles or (minimum_role == "Approver" and "Approver" in roles)


__all__ = ["DirectoryRungEligibility"]
