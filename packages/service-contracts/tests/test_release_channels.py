from __future__ import annotations

import pytest
from fdai_service_contracts.release_channels import (
    ReleaseChannelError,
    current_release_channel,
    verified_release_channel,
)


@pytest.mark.parametrize("channel", ["DEV", "RELEASE_CANDIDATE", "RELEASE"])
def test_current_channels_are_exact(channel: str) -> None:
    assert current_release_channel(channel) == channel
    assert verified_release_channel(channel) == channel


@pytest.mark.parametrize(
    ("legacy", "current"),
    [("development", "DEV"), ("beta", "RELEASE_CANDIDATE"), ("stable", "RELEASE")],
)
def test_legacy_names_are_verify_only(legacy: str, current: str) -> None:
    assert verified_release_channel(legacy) == current
    with pytest.raises(ReleaseChannelError):
        current_release_channel(legacy)


@pytest.mark.parametrize(
    "channel", ["", "dev", "Dev", "BETA", "release", "DEV ", " DEV", "DEV\n", "CUSTOM", "ＤＥＶ"]
)
def test_unrecognised_names_are_not_eligibility(channel: str) -> None:
    with pytest.raises(ReleaseChannelError):
        current_release_channel(channel)
    with pytest.raises(ReleaseChannelError):
        verified_release_channel(channel)
