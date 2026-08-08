from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from fdai.delivery.investigation import InvestigationToolExecutor
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.metric import MetricPoint, MetricQuery
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallRequest


class _Provider:
    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        if query.metric_name == "http_429_rate":
            yield MetricPoint(
                metric_name=query.metric_name,
                at=datetime.now(tz=UTC),
                value=0.5,
                labels={},
            )


async def test_on_demand_investigation_returns_report_receipt() -> None:
    executor = InvestigationToolExecutor(metric_provider=_Provider())
    receipt = await executor.execute(
        ToolCallRequest(
            action_id=UUID("00000000-0000-0000-0000-000000000001"),
            idempotency_key="investigation-1",
            action_type_name="tool.run-investigation",
            rule_ids=("operator.request",),
            tool_ref="aoai-1",
            arguments={"resource_ref": "aoai-1", "resource_kind": "azure_openai"},
            mode=Mode.SHADOW,
        )
    )
    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("inv-")
    assert "findings=1" in (receipt.detail or "")
