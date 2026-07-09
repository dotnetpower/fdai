"""Tests for per-channel render locale on the notification matrix (Option C, C1)."""

from __future__ import annotations

from typing import Any

import pytest

from fdai.core.notifications.matrix import (
    MatrixValidationError,
    load_matrix_from_mapping,
)


def _matrix(channels: Any = None) -> dict[str, Any]:
    matrix: dict[str, Any] = {
        "version": 1,
        "default_route": "ops",
        "routes": {
            "ops": {"trust_tier": "a2_operational_alert", "primary": "c1"},
        },
    }
    if channels is not None:
        matrix["channels"] = channels
    return {"matrix": matrix}


def test_locale_defaults_to_en_when_unconfigured() -> None:
    matrix = load_matrix_from_mapping(_matrix())
    assert matrix.locale_for("c1") == "en"
    assert matrix.locale_for("does-not-exist") == "en"


def test_channel_locale_is_parsed() -> None:
    matrix = load_matrix_from_mapping(_matrix({"c1": {"locale": "ko"}, "c2": {}}))
    assert matrix.locale_for("c1") == "ko"
    assert matrix.locale_for("c2") == "en"  # empty channel cfg -> default en


def test_channels_must_be_a_mapping() -> None:
    with pytest.raises(MatrixValidationError, match="channels"):
        load_matrix_from_mapping(_matrix("not-a-map"))


def test_channel_locale_must_be_a_non_empty_string() -> None:
    with pytest.raises(MatrixValidationError, match="locale"):
        load_matrix_from_mapping(_matrix({"c1": {"locale": ""}}))
