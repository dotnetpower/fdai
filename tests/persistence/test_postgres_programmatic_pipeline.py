from __future__ import annotations

import os
from datetime import UTC, datetime

import psycopg
import pytest

from fdai.core.programmatic_pipeline.models import (
    ProgrammaticCallStatus,
    ProgrammaticPipelineCallReceipt,
    ProgrammaticPipelineStats,
    ProgrammaticPipelineStatus,
    ProgrammaticToolPipelineResult,
)
from fdai.delivery.persistence.postgres_programmatic_pipeline import (
    PostgresProgrammaticPipelineStore,
    PostgresProgrammaticPipelineStoreConfig,
    _receipt_from_dict,
    _receipt_to_dict,
    _result_from_dict,
    _result_to_dict,
)

NOW = datetime(2026, 7, 20, 23, 0, tzinfo=UTC)


def _receipt() -> ProgrammaticPipelineCallReceipt:
    return ProgrammaticPipelineCallReceipt(
        run_id="pipeline-store-example",
        call_id="call-1",
        tool_id="tool.read-inventory",
        sequence=1,
        status=ProgrammaticCallStatus.SUCCEEDED,
        input_digest="a" * 64,
        output_digest="b" * 64,
        receipt_ref="pipeline-call:pipeline-store-example:1",
        started_at=NOW,
        finished_at=NOW,
        latency_ms=2,
        input_bytes=10,
        output_bytes=20,
    )


def _result() -> ProgrammaticToolPipelineResult:
    return ProgrammaticToolPipelineResult(
        run_id="pipeline-store-example",
        status=ProgrammaticPipelineStatus.SUCCEEDED,
        source_digest="c" * 64,
        stdout="",
        stderr="",
        final_json='{"count":2}',
        receipt_refs=("pipeline-call:pipeline-store-example:1",),
        stats=ProgrammaticPipelineStats(1, 1, 0, 10, 20, 4),
        complete=True,
    )


def test_postgres_pipeline_codecs_round_trip() -> None:
    assert _receipt_from_dict(_receipt_to_dict(_receipt())) == _receipt()
    assert _result_from_dict(_result_to_dict(_result())) == _result()


def test_postgres_pipeline_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresProgrammaticPipelineStoreConfig(dsn="")


@pytest.mark.integration
async def test_postgres_pipeline_store_live_round_trip() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL")
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    store = PostgresProgrammaticPipelineStore(
        config=PostgresProgrammaticPipelineStoreConfig(dsn=dsn)
    )
    receipt = _receipt()
    result = _result()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "DELETE FROM programmatic_pipeline_call WHERE run_id = %s",
            (result.run_id,),
        )
        await connection.execute(
            "DELETE FROM programmatic_pipeline_run WHERE idempotency_key = %s",
            ("pipeline-store-idempotency",),
        )
        await connection.commit()
    try:
        await store.append_call(receipt)
        await store.complete(
            idempotency_key="pipeline-store-idempotency",
            result=result,
        )
        assert await store.calls_for(result.run_id) == (receipt,)
        assert await store.result_for("pipeline-store-idempotency") == result
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM programmatic_pipeline_call WHERE run_id = %s",
                (result.run_id,),
            )
            await connection.execute(
                "DELETE FROM programmatic_pipeline_run WHERE idempotency_key = %s",
                ("pipeline-store-idempotency",),
            )
            await connection.commit()
