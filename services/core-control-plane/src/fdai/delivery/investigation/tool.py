"""Tool-call adapter for bounded on-demand investigations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fdai.core.investigation import (
    InvestigationCoordinator,
    InvestigationRequest,
    default_analyzers,
)
from fdai.core.report_feed import signals_from_investigation
from fdai.core.report_feed.models import ReportSignal
from fdai.shared.providers.metric import MetricProvider
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolPreconditionError,
)


class ReportSignalWriter(Protocol):
    async def record_many(self, signals: list[ReportSignal]) -> None: ...


class InvestigationToolExecutor:
    """Run the reference analyzers against one explicitly requested resource."""

    def __init__(
        self,
        *,
        metric_provider: MetricProvider,
        signal_writer: ReportSignalWriter | None = None,
    ) -> None:
        self._coordinator = InvestigationCoordinator(analyzers=default_analyzers(metric_provider))
        self._signal_writer = signal_writer

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        resource_ref = _required_string(request.arguments, "resource_ref")
        resource_kind = _required_string(request.arguments, "resource_kind")
        window_seconds = _positive_number(request.arguments, "window_seconds", 300.0)
        budget_seconds = _positive_number(request.arguments, "budget_seconds", 60.0)
        report = await self._coordinator.investigate(
            InvestigationRequest(
                requested_by=request.metadata.get("initiator_principal", "operator"),
                resources=((resource_ref, resource_kind),),
                window_seconds=window_seconds,
                budget_seconds=budget_seconds,
            )
        )
        if self._signal_writer is not None:
            await self._signal_writer.record_many(signals_from_investigation(report))
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=report.investigation_id,
            detail=(
                f"{report.outcome.value}; findings={len(report.findings)}; "
                f"within_budget={str(report.within_budget).lower()}"
            ),
        )


def _required_string(arguments: Mapping[str, object], field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ToolPreconditionError(f"{field} MUST be a non-empty string")
    return value.strip()


def _positive_number(arguments: Mapping[str, object], field: str, default: float) -> float:
    value = arguments.get(field, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ToolPreconditionError(f"{field} MUST be a positive number")
    return float(value)


__all__ = ["InvestigationToolExecutor", "ReportSignalWriter"]
