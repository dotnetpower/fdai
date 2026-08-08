"""Tests for Azure Windows timezone conversion."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fdai.delivery.azure.windows_timezones import WINDOWS_TO_IANA


def test_every_azure_windows_timezone_maps_to_an_installed_iana_zone() -> None:
    assert len(WINDOWS_TO_IANA) >= 100
    for windows_name, iana_name in WINDOWS_TO_IANA.items():
        assert windows_name
        assert ZoneInfo(iana_name).key == iana_name


def test_reviewer_timezone_examples_are_supported() -> None:
    assert WINDOWS_TO_IANA["China Standard Time"] == "Asia/Shanghai"
    assert WINDOWS_TO_IANA["W. Europe Standard Time"] == "Europe/Berlin"
    assert WINDOWS_TO_IANA["AUS Eastern Standard Time"] == "Australia/Sydney"
