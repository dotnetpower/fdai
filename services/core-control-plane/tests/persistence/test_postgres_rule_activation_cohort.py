from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_rule_activation_cohort import (
    PostgresRuleActivationCohortCommitStore,
)


def _config() -> PostgresStateStoreConfig:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return PostgresStateStoreConfig(dsn=value.replace("postgresql+psycopg://", "postgresql://", 1))


async def test_candidate_insert_guards_exact_latest_prepare() -> None:
    config = _config()
    store = PostgresStateStore(config=config)
    commit = PostgresRuleActivationCohortCommitStore(config=config)
    suffix = uuid4().hex
    latest_key = f"test:rule-cohort:latest:{suffix}"
    candidate_key = f"test:rule-cohort:candidate:{suffix}"
    stale_candidate_key = f"test:rule-cohort:stale:{suffix}"
    latest = {
        "revision": 1,
        "prepare_digest": "sha256:" + ("a" * 64),
        "serving_inventory_digest": "sha256:" + ("b" * 64),
    }
    assert await store.write_state_if_absent(latest_key, latest)

    assert await commit.activate_candidate(
        key=candidate_key,
        value={"revision": 1, "candidate": {"prepare_digest": latest["prepare_digest"]}},
        expected_revision=0,
        latest_prepare_key=latest_key,
        expected_latest_prepare=latest,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=1),
    )
    successor = {
        "revision": 2,
        "prepare_digest": "sha256:" + ("c" * 64),
        "serving_inventory_digest": "sha256:" + ("d" * 64),
    }
    assert await store.compare_and_set_state(latest_key, successor, expected_revision=1)

    assert not await commit.activate_candidate(
        key=stale_candidate_key,
        value={"revision": 1, "candidate": {"prepare_digest": latest["prepare_digest"]}},
        expected_revision=0,
        latest_prepare_key=latest_key,
        expected_latest_prepare=latest,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=1),
    )
