"""Operator-owned proposal ports for scoped duty review, independent of personal IAM."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_service_contracts.scoped_duty import ScopedDutyRequest


class ScopedDutyOutbox(Protocol):
    """Accept authenticated immutable proposals and expose only Core-owned observations."""

    async def create(
        self,
        *,
        principal: IamPrincipal,
        idempotency_key: str,
        request: ScopedDutyRequest,
        justification: str,
    ) -> Mapping[str, object]:
        """Persist one ownership-only request; do not create a Core case or change IAM."""
        ...

    async def get(self, case_id: str) -> Mapping[str, object]:
        """Read one exact request and its independently materialized Core state."""
        ...

    async def transition(
        self,
        *,
        principal: IamPrincipal,
        case_id: str,
        expected_revision: int,
        decision: str | None = None,
        plan_digest: str | None = None,
    ) -> Mapping[str, object]:
        """Persist submit or human-review intent; Core revalidates all current evidence."""
        ...

    async def projection(self, *, agent_name: str, scope_ref: str) -> Mapping[str, object]:
        """Return the exact bounded fresh scope projection; no parent or platform fallback."""
        ...

    async def catalog(self) -> Mapping[str, object]:
        """Return current Core catalog availability and source revision without IAM authority."""
        ...


__all__ = ["ScopedDutyOutbox"]
