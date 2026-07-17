from __future__ import annotations

import pytest

from fdai.delivery.chaos.gpu_governance import GpuSkuMismatchProbe


@pytest.mark.parametrize(
    ("assessment", "expected"),
    [
        ({"observed_sku": "H100", "recommended_sku": "A100", "confidence": 0.9}, True),
        ({"observed_sku": "A100", "recommended_sku": "A100", "confidence": 0.9}, False),
        ({"observed_sku": "H100", "recommended_sku": "A100", "confidence": 0.7}, False),
    ],
)
async def test_gpu_sku_mismatch_probe_is_bounded_by_assessment(
    assessment: dict[str, object],
    expected: bool,
) -> None:
    probe = GpuSkuMismatchProbe(
        assess=lambda _targets: assessment,
        expected_observed_sku="H100",
        expected_recommended_sku="A100",
    )

    assert await probe.observed(signal="gpu_sku_mismatch", targets=("profile",)) is expected


async def test_gpu_sku_mismatch_probe_rejects_other_signal() -> None:
    probe = GpuSkuMismatchProbe(
        assess=lambda _targets: pytest.fail("wrong signal MUST skip the provider"),
        expected_observed_sku="H100",
        expected_recommended_sku="A100",
    )

    assert not await probe.observed(signal="gpu_idle_hours_wasted", targets=("profile",))
