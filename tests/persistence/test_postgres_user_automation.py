from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.persistence.postgres_briefing import (
    PostgresBriefingStoreConfig,
    _run,
    _subscription,
)
from fdai.delivery.persistence.postgres_user_context import PostgresUserContextStoreConfig
from fdai.delivery.persistence.postgres_workflow_definition import (
    PostgresWorkflowDefinitionStoreConfig,
)
from fdai.shared.providers.scheduled_continuation import ContinuationMode

NOW = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "config_type",
    [
        PostgresUserContextStoreConfig,
        PostgresBriefingStoreConfig,
        PostgresWorkflowDefinitionStoreConfig,
    ],
)
def test_postgres_user_automation_configs_reject_empty_dsn(config_type: type) -> None:
    with pytest.raises(ValueError, match="dsn"):
        config_type(dsn="")


@pytest.mark.parametrize(
    "config_type",
    [
        PostgresUserContextStoreConfig,
        PostgresBriefingStoreConfig,
        PostgresWorkflowDefinitionStoreConfig,
    ],
)
def test_postgres_user_automation_configs_reject_bad_timeout(config_type: type) -> None:
    with pytest.raises(ValueError, match="timeouts"):
        config_type(dsn="postgresql://example", statement_timeout_ms=0)


def test_briefing_continuation_row_codecs_preserve_origin_and_digest() -> None:
    origin = {
        "audience": "direct",
        "channel_kind": "web",
        "channel_ref": "console",
        "conversation_ref": "conversation-1",
        "thread_ref": None,
    }
    subscription = _subscription(
        {
            "principal_id": "principal-a",
            "subscription_id": "subscription-1",
            "name": "Scoped briefing",
            "spec": {
                "kind": "major_issues",
                "lookback_seconds": 3600,
                "minimum_severity": "high",
                "categories": [],
                "max_items": 5,
                "include_pending_approvals": True,
                "include_failed_actions": True,
                "scope_ref": "scope-a",
            },
            "cron_expression": "0 7 * * *",
            "timezone": "UTC",
            "delivery_modes": ["in_app"],
            "channel_binding_ref": None,
            "enabled": True,
            "next_run_at": NOW,
            "created_at": NOW,
            "max_lateness_seconds": 3600,
            "continuation_mode": "origin_thread",
            "continuation_origin": origin,
            "continuation_ttl_seconds": 604800,
            "revision": 1,
        }
    )
    run = _run(
        {
            "principal_id": "principal-a",
            "run_id": "run-1",
            "subscription_id": "subscription-1",
            "conversation_id": None,
            "scheduled_for": NOW,
            "started_at": NOW,
            "status": "delivered",
            "idempotency_key": "briefing:subscription-1:slot",
            "title": "Scoped briefing",
            "body_markdown": "No critical issues.",
            "item_count": 0,
            "evidence_refs": [],
            "source_errors": [],
            "continuation_mode": "origin_thread",
            "continuation_origin": origin,
            "result_digest": "a" * 64,
        }
    )

    assert subscription.continuation_mode is ContinuationMode.ORIGIN_THREAD
    assert subscription.continuation_origin == run.continuation_origin
    assert run.result_digest == "a" * 64
