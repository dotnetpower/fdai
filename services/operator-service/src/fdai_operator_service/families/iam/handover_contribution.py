"""Read-only Core revocation holds constrain Operator-owned knowledge contribution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
from fdai_operator_service.families.iam.errors import IamUnavailableError


class HandoverContributionGuard(Protocol):
    """A negative-only current assignment check; it never grants ownership or an App Role."""

    async def may_contribute(self, *, subject_ref: str, agent_name: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PostgresHandoverContributionGuard:
    """Read only one subject's bounded Core cases under the existing Operator SELECT grant."""

    dsn: str

    async def may_contribute(self, *, subject_ref: str, agent_name: str) -> bool:
        try:
            async with await psycopg.AsyncConnection.connect(
                self.dsn, connect_timeout=5
            ) as connection:
                await connection.execute("SET LOCAL statement_timeout = '5s'")
                rows = await (
                    await connection.execute(
                        "SELECT value FROM state_kv "
                        "WHERE starts_with(key, 'human_assignment:case:') "
                        "AND lower(value #>> '{intent,subject,subject_id}') = %s LIMIT 101",
                        (subject_ref.strip().casefold(),),
                    )
                ).fetchall()
        except psycopg.Error as exc:
            raise IamUnavailableError(
                "current assignment contribution evidence is unavailable"
            ) from exc
        if len(rows) > 100:
            raise IamUnavailableError("assignment contribution evidence exceeds its bounded read")
        return contribution_allowed([row[0] for row in rows], agent_name=agent_name)


def contribution_allowed(records: list[Mapping[str, Any]], *, agent_name: str) -> bool:
    """Hold revoked originals until their map changes or a separately converged grant exists."""
    removed, active = False, False
    for record in records:
        if not isinstance(record, Mapping):
            raise IamUnavailableError("assignment contribution record is malformed")
        intent = record.get("intent")
        if not isinstance(intent, Mapping) or not isinstance(intent.get("duty_bindings"), list):
            raise IamUnavailableError("assignment contribution record is malformed")
        if intent.get("revocation") is not None:
            continue
        if not any(
            isinstance(duty, Mapping) and duty.get("agent_name") == agent_name
            for duty in intent["duty_bindings"]
        ):
            continue
        if record.get("revocation_case_id") is not None:
            if record.get("state") == "degraded":
                return False
            removed = True
        elif record.get("state") == "active":
            effects = record.get("effect_receipts", [])
            if not isinstance(effects, list) or {
                item.get("kind") for item in effects if isinstance(item, Mapping)
            } != {"ownership", "iam"}:
                raise IamUnavailableError("active assignment effect evidence is incomplete")
            active = True
    return not removed or active


__all__ = ["HandoverContributionGuard", "PostgresHandoverContributionGuard", "contribution_allowed"]
