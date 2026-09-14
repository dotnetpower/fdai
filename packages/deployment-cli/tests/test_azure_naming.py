from __future__ import annotations

import pytest

from fdai_deployment_cli.azure_naming import azure_region_short_name


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("koreacentral", "krc"),
        ("westus2", "wus2"),
        ("eastus2", "eus2"),
        ("swedencentral", "swede"),
    ],
)
def test_returns_stable_region_short_name(region: str, expected: str) -> None:
    assert azure_region_short_name(region) == expected


@pytest.mark.parametrize("region", ["", "West US 2", "-westus2", "a"])
def test_rejects_invalid_region_name(region: str) -> None:
    with pytest.raises(ValueError, match="region name"):
        azure_region_short_name(region)
