"""Bind analyzer Job execution identities to durable attempt receipts."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from fdai.delivery.analyzer_receipt_store import StateStoreAnalyzerRunReceiptStore
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

ANALYZER_RUN_ID_ENV = "FDAI_ANALYZER_RUN_ID"
CONTAINER_APP_JOB_EXECUTION_NAME_ENV = "CONTAINER_APP_JOB_EXECUTION_NAME"
STATE_STORE_DSN_ENV = "FDAI_STATE_STORE_DSN"

_LOGGER = logging.getLogger("fdai.analyzer_tick")


class AnalyzerRunReceiptPersistenceError(RuntimeError):
    """A durable analyzer run receipt could not be written."""


def resolve_analyzer_run_id(environment: Mapping[str, str]) -> str | None:
    """Return a retry-stable explicit or platform Job execution identity."""

    run_id = (
        environment.get(ANALYZER_RUN_ID_ENV, "").strip()
        or environment.get(CONTAINER_APP_JOB_EXECUTION_NAME_ENV, "").strip()
    )
    if not run_id:
        return None
    if len(run_id) > 256 or any(char.isspace() for char in run_id):
        raise ValueError("analyzer run identity MUST be bounded and contain no whitespace")
    return run_id


def build_analyzer_run_receipt_store(
    environment: Mapping[str, str],
) -> StateStoreAnalyzerRunReceiptStore | None:
    """Bind complete tick receipts when tracked state is configured."""

    dsn = environment.get(STATE_STORE_DSN_ENV, "").strip()
    if not dsn:
        return None
    return StateStoreAnalyzerRunReceiptStore(
        PostgresStateStore(
            config=PostgresStateStoreConfig(
                dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
            )
        )
    )


async def record_analyzer_run_receipt(
    *,
    environment: Mapping[str, str],
    tick_id: str,
    recorded_at: datetime,
    report: Mapping[str, object],
) -> None:
    """Persist one execution/tick/attempt receipt when identity and state exist."""

    run_id = resolve_analyzer_run_id(environment)
    if run_id is None:
        _LOGGER.info(
            "analyzer_tick_receipt_unbound",
            extra={"reason": "stable_run_identity_absent"},
        )
        return
    store = build_analyzer_run_receipt_store(environment)
    if store is None:
        return
    try:
        await store.record(
            run_id=run_id,
            tick_id=tick_id,
            recorded_at=recorded_at,
            report=report,
        )
    except Exception as exc:  # noqa: BLE001 - persistence failures retry the bounded tick
        raise AnalyzerRunReceiptPersistenceError(
            f"analyzer run receipt persistence failed: {type(exc).__name__}"
        ) from exc
    finally:
        close = getattr(store, "aclose", None)
        if callable(close):
            await close()


__all__ = [
    "ANALYZER_RUN_ID_ENV",
    "AnalyzerRunReceiptPersistenceError",
    "CONTAINER_APP_JOB_EXECUTION_NAME_ENV",
    "build_analyzer_run_receipt_store",
    "record_analyzer_run_receipt",
    "resolve_analyzer_run_id",
]
