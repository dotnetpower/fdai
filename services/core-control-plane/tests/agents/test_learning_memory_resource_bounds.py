from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.agents._framework.mimir_catalog_journal import MimirCatalogReviewJournal
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.core.operational_learning import CatalogReviewPublicationReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _CountingStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.read_state_page_limits: list[int] = []
        self.read_states_limits: list[int] = []
        self.find_state_calls = 0
        self.cas_calls = 0
        self.max_write_items = 0

    async def read_state_page(
        self,
        prefix: str,
        *,
        limit: int,
        offset: int = 0,
        field: str | None = None,
        value: str | None = None,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        self.read_state_page_limits.append(limit)
        return await super().read_state_page(
            prefix,
            limit=limit,
            offset=offset,
            field=field,
            value=value,
        )

    async def read_states(self, prefix: str, *, limit: int) -> tuple[Mapping[str, Any], ...]:
        self.read_states_limits.append(limit)
        return await super().read_states(prefix, limit=limit)

    async def find_state(
        self,
        prefix: str,
        *,
        field: str,
        value: str,
    ) -> Mapping[str, Any] | None:
        self.find_state_calls += 1
        raise AssertionError("recovery must page, not repeatedly scan with find_state")

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        self._observe_size(value)
        await super().write_state(key, value)

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        self._observe_size(value)
        return await super().write_state_with_audit_if_absent(key, value, audit_entry)

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        self.cas_calls += 1
        self._observe_size(value)
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )

    def _observe_size(self, value: Mapping[str, Any]) -> None:
        size = 0
        for item in value.values():
            if isinstance(item, (dict, list)):
                size += len(item)
            else:
                size += 1
        self.max_write_items = max(self.max_write_items, size)


class _LosingCasStore(_CountingStore):
    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        self.cas_calls += 1
        return False


def _candidate(index: int) -> dict[str, Any]:
    return {
        "producer_principal": "Norns",
        "correlation_id": f"corr-{index}",
        "idempotency_key": f"candidate-{index}",
        "source_signal": "semantic_retrieval_failure",
        "proposal_kind": "revision",
        "target_rule_id": f"rule-{index}",
        "norns_consensus": {
            "decision": "propose",
            "unanimous": True,
            "perspective_count": 3,
        },
    }


async def test_mimir_candidate_review_locks_are_reclaimed() -> None:
    mimir = Mimir()
    for index in range(200):
        payload = _candidate(index)
        payload["producer_principal"] = "spoofed"
        await mimir.on_typed_message("object.rule-candidate", payload)

    assert mimir._review_locks == {}


async def test_mimir_governance_recovery_uses_bounded_pages() -> None:
    store = _CountingStore()
    for index in range(300):
        await store.write_state(
            f"pantheon/mimir/governance/rules/rule-{index}",
            {
                "kind": "mimir_rule_state",
                "revision": 1,
                "rule_id": f"rule-{index}",
                "state": "shadow",
                "source": "manual",
            },
        )
        await store.write_state(
            f"pantheon/mimir/governance/issue-fingerprints/fp-{index}",
            {"fingerprint": f"fp-{index}", "issue_number": index},
        )
    mimir = Mimir(governance_state_store=store)

    restored = await mimir.recover_governance_state()

    assert restored == 600
    assert 50_000 not in store.read_states_limits
    assert max(store.read_state_page_limits) <= 128


async def test_mimir_introspection_does_not_recompute_ready_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mimir = Mimir()

    def fail() -> tuple[dict[str, Any], ...]:
        raise AssertionError("introspection must not scan pending candidates")

    monkeypatch.setattr(mimir, "promotion_ready_candidates", fail)

    result = await mimir.introspect("status", {})

    assert result.facts["promotion_ready_candidates"] is None
    assert result.facts["promotion_ready_candidates_evidence_state"] == "not_recomputed"


async def test_mimir_promotion_persistence_uses_one_worker_task() -> None:
    store = _CountingStore()
    mimir = Mimir(governance_state_store=store)

    for index in range(50):
        mimir.promote(
            f"static-rule-{index}",
            source="manual",
            reviewed_change_ref="catalog-pr:https://git.example.com/fdai/control-plane/pull/1@sha256:"
            + "a" * 64,
        )

    assert len(mimir._promotion_persist_tasks) <= 1
    await mimir.drain_governance_writes()
    assert len(mimir._promotion_persist_tasks) == 0


async def test_mimir_catalog_terminal_receipts_are_compacted() -> None:
    store = InMemoryStateStore()
    journal = MimirCatalogReviewJournal(store, capacity=3)
    receipt = CatalogReviewPublicationReceipt(
        package_digest="b" * 64,
        review_ref="catalog-review:1",
        already_existed=False,
    )
    for index in range(5_010):
        candidate = _candidate(index)
        package = SimpleNamespace(
            candidate=SimpleNamespace(digest="a" * 64),
            content_digest="b" * 64,
        )
        await journal.retain(candidate, package)
        await journal.mark_published(candidate, package, receipt)

    rows, total = await store.read_state_page("pantheon/mimir/catalog-review/", limit=6_000)

    assert total <= 5_003
    assert all(row["status"] == "published" for row in rows)


async def test_mimir_quarantine_retains_summary_not_full_payload() -> None:
    store = InMemoryStateStore()
    mimir = Mimir(governance_state_store=store)
    payload = _candidate(1)
    payload["producer_principal"] = "spoofed"
    payload["large_body"] = "x" * 10_000

    await mimir.on_typed_message("object.rule-candidate", payload)

    [row] = await store.read_states(
        "pantheon/mimir/governance/catalog-review/quarantine/",
        limit=10,
    )
    assert "payload" not in row
    assert row["summary"]["candidate_digest"]
    assert (
        mimir.quarantined_candidates()[0]["candidate_digest"] == row["summary"]["candidate_digest"]
    )


async def test_muninn_projection_recovery_and_update_are_per_record() -> None:
    durable = _CountingStore()
    for index in range(300):
        await durable.write_state(
            f"pantheon/muninn/conversation-projections/conversation_turns/turn-{index}",
            {
                "kind": "muninn_conversation_projection",
                "revision": 1,
                "bucket": "conversation_turns",
                "projection_key": f"turn-{index}",
                "idempotency_key": f"turn-{index}",
                "correlation_id": "corr",
                "record": {"idempotency_key": f"turn-{index}", "correlation_id": "corr"},
            },
        )
    muninn = Muninn(durable_state_store=durable)

    restored = await muninn.recover_conversation_projections()
    await muninn._sync_projection_record(
        "conversation_turns",
        "turn-new",
        {"idempotency_key": "turn-new", "correlation_id": "corr"},
    )

    assert restored == 300
    assert max(durable.read_state_page_limits) <= 128
    assert muninn.state_store.get("conversation_turns", "turn-new") is not None


async def test_muninn_outbox_compacts_and_bounds_cas_retries() -> None:
    durable = _CountingStore()
    muninn = Muninn(durable_state_store=durable)
    for index in range(5_010):
        payload = {"idempotency_key": f"id-{index}", "correlation_id": "corr"}
        key = f"pantheon/muninn/operational-outbox/test/{index}"
        await muninn._claim_publication(key, payload)
        await muninn._mark_publication_published(key, payload)
    _rows, total = await durable.read_state_page("pantheon/muninn/operational-outbox/", limit=6000)
    assert 5_000 <= total < 5_000 + 64
    await muninn.maintenance_tick()
    _rows, total = await durable.read_state_page("pantheon/muninn/operational-outbox/", limit=6000)
    assert total == 5_000

    losing = _LosingCasStore()
    muninn_losing = Muninn(durable_state_store=losing)
    await muninn_losing._claim_publication(
        "pantheon/muninn/operational-outbox/test/losing",
        {"idempotency_key": "losing", "correlation_id": "corr"},
    )
    with pytest.raises(RuntimeError, match="CAS did not converge"):
        await muninn_losing._mark_publication_published(
            "pantheon/muninn/operational-outbox/test/losing",
            {"idempotency_key": "losing", "correlation_id": "corr"},
        )
    assert losing.cas_calls == 8


async def test_norns_learning_checkpoint_writes_only_dirty_delta() -> None:
    store = _CountingStore()
    norns = Norns(operational_state_store=store)
    for index in range(10_000):
        norns._outcomes.set(f"target-{index}", {"success": 1, "rollback": 0})
    norns._outcomes.set("target-changed", {"success": 1, "rollback": 1})
    norns._mark_learning_dirty("outcomes", "target-changed")

    await norns._persist_learning_state()

    assert store.max_write_items < 20
    rows, total = await store.read_state_page(
        "pantheon/norns/learning-state-deltas/outcomes/",
        limit=10,
    )
    assert total == 1
    assert rows[0]["item_key"] == "target-changed"


async def test_norns_issue_learning_recovery_pages_and_fingerprint_rows_stay_bounded() -> None:
    store = _CountingStore()
    norns = Norns(issue_state_store=store, promotion_threshold=10_000)
    fingerprint = "fp"
    for index in range(200):
        await norns._issue_deduplicator.observe(
            norns,
            {"idempotency_key": f"issue-op-{index}", "fingerprint": fingerprint},
        )
    rows, _total = await store.read_state_page(
        "pantheon/norns/issue-learning/fingerprints/",
        limit=1,
    )
    assert rows[0]["occurrence_count"] == 200
    assert len(rows[0]["operation_digests"]) <= 128

    recovered = Norns(issue_state_store=store, promotion_threshold=10_000)
    await recovered.recover_issue_learning()
    assert store.find_state_calls == 0
    assert max(store.read_state_page_limits) <= 128


async def test_norns_issue_learning_recovery_restores_all_pending_fingerprints() -> None:
    store = _CountingStore()
    norns = Norns(issue_state_store=store, promotion_threshold=2)
    for fingerprint in ("fp-a", "fp-b"):
        for index in range(2):
            await norns._issue_deduplicator.observe(
                norns,
                {
                    "idempotency_key": f"issue-op-{fingerprint}-{index}",
                    "fingerprint": fingerprint,
                },
            )

    recovered = Norns(issue_state_store=store, promotion_threshold=2)
    await recovered.recover_issue_learning()

    pending = {
        candidate["evidence"]["fingerprint"]
        for candidate in recovered.pending_candidates
        if isinstance(candidate.get("evidence"), Mapping)
    }
    assert pending == {"fp-a", "fp-b"}


class _FakeOperationalJournal:
    def __init__(self) -> None:
        self.offsets: list[int] = []

    async def pending_page(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[tuple[tuple[dict[str, Any], dict[str, Any], bool], ...], int]:
        self.offsets.append(offset)
        total = 50
        rows = tuple(
            ({"suggested_pattern": f"pattern-{index}"}, {"pattern_id": f"pattern-{index}"}, False)
            for index in range(offset, min(offset + limit, total))
        )
        return rows, total

    async def mark_terminal(self, **_kwargs: Any) -> None:
        return None

    async def retain(self, **_kwargs: Any) -> bool:
        return True


async def test_norns_operational_delivery_indexes_and_bounds_scrub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    norns = Norns(max_pending_candidates=5)
    journal = _FakeOperationalJournal()
    norns._operational_journal = journal  # type: ignore[assignment]

    async def current(_candidate: Mapping[str, Any]) -> bool:
        return True

    monkeypatch.setattr(norns, "_operational_candidate_cases_are_current", current)
    await norns._scrub_durable_source_invalidated_candidates()
    await norns._scrub_durable_source_invalidated_candidates()
    assert journal.offsets[:4] == [0, 0, 0, 5]

    candidate = {"suggested_pattern": "pattern-keep"}
    norns.pending_candidates.append(candidate)
    norns._index_pending_candidate(candidate)
    norns._pattern_publications["pattern-keep"] = {"pattern_id": "pattern-keep"}
    await norns.retain_operational_candidate("pattern-keep")
    assert norns._pending_by_pattern_id["pattern-keep"] is candidate

    for index in range(20):
        norns._published_pattern_ids.add(f"published-{index}")
    assert len(norns._published_pattern_ids) <= norns._max_pending_candidates
