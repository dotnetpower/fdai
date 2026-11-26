"""Restart-safe per-correlation model accounting without execution authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from fdai.core.metering.budget import BudgetSpend, ModelBudget
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class StateStoreBudgetLedger:
    """Persist per-correlation ceilings; configured fleet totals require another binding."""

    store: StateStore
    budget: ModelBudget = field(default_factory=ModelBudget)

    def __post_init__(self) -> None:
        if (
            self.budget.max_calls_total is not None
            or self.budget.max_cost_microusd_total is not None
        ):
            raise ValueError(
                "StateStoreBudgetLedger requires a separate atomic fleet-budget binding"
            )

    @property
    def policy_digest(self) -> str:
        encoded = json.dumps(asdict(self.budget), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _key(self, correlation_id: str) -> str:
        if not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 256:
            raise ValueError("model budget correlation MUST contain between 1 and 256 characters")
        return f"model_budget:conversation:{hashlib.sha256(correlation_id.encode()).hexdigest()}"

    async def _read(self, key: str) -> Mapping[str, Any] | None:
        row = await self.store.read_state(key)
        if row is not None and (
            row.get("schema_version") != "1.0.0"
            or row.get("policy_digest") != self.policy_digest
            or any(
                type(row.get(name)) is not int or row[name] < 0
                for name in ("revision", "calls", "cost_microusd")
            )
            or row["revision"] < 1
        ):
            raise ValueError("model budget state or pinned policy is invalid")
        return row

    def _fits(self, spent: BudgetSpend, *, calls: int, cost_microusd: int) -> bool:
        return (
            spent.calls < self.budget.max_calls_per_correlation
            and spent.calls + calls <= self.budget.max_calls_per_correlation
            and (
                self.budget.max_cost_microusd_per_correlation is None
                or (
                    spent.cost_microusd < self.budget.max_cost_microusd_per_correlation
                    and spent.cost_microusd + cost_microusd
                    <= self.budget.max_cost_microusd_per_correlation
                )
            )
        )

    async def spend(self, correlation_id: str) -> BudgetSpend:
        async with asyncio.timeout(5):
            row = await self._read(self._key(correlation_id))
        return BudgetSpend() if row is None else BudgetSpend(row["calls"], row["cost_microusd"])

    async def allows(self, correlation_id: str) -> bool:
        return self._fits(await self.spend(correlation_id), calls=1, cost_microusd=0)

    async def reserve(self, correlation_id: str, *, calls: int, cost_microusd: int) -> bool:
        return await self._apply(
            correlation_id, calls=calls, cost_microusd=cost_microusd, reserve=True
        )

    async def charge(self, correlation_id: str, *, calls: int, cost_microusd: int) -> None:
        await self._apply(correlation_id, calls=calls, cost_microusd=cost_microusd, reserve=False)

    async def _apply(
        self, correlation_id: str, *, calls: int, cost_microusd: int, reserve: bool
    ) -> bool:
        if any(type(value) is not int or value < 0 for value in (calls, cost_microusd)):
            raise ValueError("model budget charges MUST be non-negative integers")
        key = self._key(correlation_id)
        async with asyncio.timeout(5):
            for _attempt in range(4):
                current = await self._read(key)
                spent = (
                    BudgetSpend()
                    if current is None
                    else BudgetSpend(current["calls"], current["cost_microusd"])
                )
                if reserve and not self._fits(spent, calls=calls, cost_microusd=cost_microusd):
                    return False
                revision = 0 if current is None else current["revision"]
                updated = {
                    "schema_version": "1.0.0",
                    "policy_digest": self.policy_digest,
                    "revision": revision + 1,
                    "calls": spent.calls + calls,
                    "cost_microusd": spent.cost_microusd + cost_microusd,
                }
                applied = (
                    await self.store.write_state_if_absent(key, updated)
                    if current is None
                    else await self.store.compare_and_set_state(
                        key, updated, expected_revision=revision
                    )
                )
                if applied:
                    return True
        raise RuntimeError("model budget reservation changed concurrently")


__all__ = ["StateStoreBudgetLedger"]
