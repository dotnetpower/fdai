from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.measurement.cost_retention import CostGovernanceRetentionService

NOW = datetime(2026, 8, 28, 8, tzinfo=UTC)


class _RetentionStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {
            "episode-a": {
                "revision": 1,
                "legal_hold": False,
                "legal_hold_ref": None,
                "purge_after": NOW,
                "purged_at": None,
            },
            "episode-b": {
                "revision": 1,
                "legal_hold": False,
                "legal_hold_ref": None,
                "purge_after": NOW + timedelta(days=1),
                "purged_at": None,
            },
        }
        self.events: list[tuple[str, int, str]] = []

    async def compare_and_set_cost_retention(
        self,
        episode_id: str,
        *,
        expected_revision: int,
        legal_hold: bool,
        legal_hold_ref: str | None,
        recorded_at: datetime,
    ) -> bool:
        del recorded_at
        row = self.rows[episode_id]
        if row["revision"] != expected_revision or row["purged_at"] is not None:
            return False
        row["revision"] = expected_revision + 1
        row["legal_hold"] = legal_hold
        row["legal_hold_ref"] = legal_hold_ref
        self.events.append(
            (
                episode_id,
                expected_revision + 1,
                "hold-applied" if legal_hold else "hold-released",
            )
        )
        return True

    async def purge_due_cost_episodes(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[str, ...]:
        due = sorted(
            episode_id
            for episode_id, row in self.rows.items()
            if row["purge_after"] <= now and not row["legal_hold"] and row["purged_at"] is None
        )[:limit]
        for episode_id in due:
            row = self.rows[episode_id]
            row["revision"] += 1
            row["purged_at"] = now
            self.events.append((episode_id, row["revision"], "purged"))
        return tuple(due)

    async def append_cost_episode(self, *args: object, **kwargs: object) -> bool:
        raise AssertionError("retention service MUST NOT append episodes")

    async def append_cost_recovery_attempt(self, *args: object, **kwargs: object) -> bool:
        raise AssertionError("retention service MUST NOT append recovery")

    async def append_cost_settlement(self, *args: object, **kwargs: object) -> bool:
        raise AssertionError("retention service MUST NOT append settlement")

    async def read_cost_episode(self, episode_id: str) -> None:
        del episode_id
        return None


async def test_legal_hold_blocks_purge_until_revisioned_release() -> None:
    store = _RetentionStore()
    service = CostGovernanceRetentionService(store=store)

    assert await service.set_legal_hold(
        "episode-a",
        expected_revision=1,
        legal_hold_ref="legal-case-1",
        recorded_at=NOW,
    )
    assert await service.purge_due(now=NOW) == ()
    assert await service.release_legal_hold(
        "episode-a",
        expected_revision=2,
        recorded_at=NOW + timedelta(minutes=1),
    )
    assert await service.purge_due(now=NOW + timedelta(minutes=1)) == ("episode-a",)
    assert store.events == [
        ("episode-a", 2, "hold-applied"),
        ("episode-a", 3, "hold-released"),
        ("episode-a", 4, "purged"),
    ]


async def test_stale_retention_revision_is_a_no_op_across_restart() -> None:
    store = _RetentionStore()
    first = CostGovernanceRetentionService(store=store)
    assert await first.set_legal_hold(
        "episode-a",
        expected_revision=1,
        legal_hold_ref="legal-case-1",
        recorded_at=NOW,
    )

    restarted = CostGovernanceRetentionService(store=store)
    assert not await restarted.release_legal_hold(
        "episode-a",
        expected_revision=1,
        recorded_at=NOW,
    )
    assert store.rows["episode-a"]["legal_hold"] is True


async def test_purge_is_bounded_and_does_not_consult_package_activation() -> None:
    store = _RetentionStore()
    store.rows["episode-c"] = {
        "revision": 1,
        "legal_hold": False,
        "legal_hold_ref": None,
        "purge_after": NOW,
        "purged_at": None,
    }
    service = CostGovernanceRetentionService(store=store)

    assert await service.purge_due(now=NOW, limit=1) == ("episode-a",)
    assert store.rows["episode-c"]["purged_at"] is None
