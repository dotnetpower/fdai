"""Active-inventory to security report-signal projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.report_feed.models import ReportSignal
from fdai.delivery.azure.security_assessment_projection import (
    project_azure_security_assessment,
)
from fdai.shared.providers.inventory import ResourceRecord

_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


class _Reader:
    async def list_security_resources(self):
        return (
            ResourceRecord(
                resource_id="rg-example/aks-example",
                type="kubernetes-cluster",
                props={
                    "sku": {"tier": "Standard"},
                    "properties": {
                        "enableRbac": True,
                        "privateFqdn": "private.example.invalid",
                    },
                },
            ),
        )


class _Writer:
    def __init__(self) -> None:
        self.signals: tuple[ReportSignal, ...] = ()

    async def record_many(self, signals) -> None:
        self.signals = tuple(signals)


async def test_projector_records_timestamped_inventory_controls() -> None:
    writer = _Writer()
    count = await project_azure_security_assessment(
        reader=_Reader(),
        writer=writer,
        assessed_at=_AT,
    )

    assert count == 15
    assert len(writer.signals) == 15
    assert all(signal.occurred_at == _AT for signal in writer.signals)
    assert all(_AT.isoformat() in signal.signal_id for signal in writer.signals)
    by_control = {signal.metadata["control_id"]: signal for signal in writer.signals}
    assert by_control["aks-rbac"].metadata["status"] == "pass"
    assert by_control["aks-defender"].metadata["status"] == "unknown"
