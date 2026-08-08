"""Validation tests for :class:`ReportEngineConfig.__post_init__`.

The config is the boundary that keeps a fork from dialing the render loop
into a denial-of-service (unbounded concurrency, an infinite per-widget
timeout, a report with tens of thousands of widgets). Each hard ceiling
MUST reject an out-of-range value at construction time, fail-fast, rather
than let the engine discover it mid-render.
"""

from __future__ import annotations

import pytest
from fdai.core.reporting.config import ReportEngineConfig


class TestReportEngineConfigDefaults:
    def test_default_is_permissive_and_valid(self) -> None:
        cfg = ReportEngineConfig()
        assert cfg.per_widget_timeout_seconds is None
        assert cfg.max_concurrent_widgets is None
        assert cfg.max_widgets_per_report == 200
        assert cfg.max_error_message_chars == 512

    def test_valid_bounded_values_are_accepted(self) -> None:
        cfg = ReportEngineConfig(
            per_widget_timeout_seconds=120.0,
            max_concurrent_widgets=32,
            max_widgets_per_report=1,
            max_error_message_chars=32,
        )
        assert cfg.per_widget_timeout_seconds == 120.0
        assert cfg.max_concurrent_widgets == 32


class TestReportEngineConfigValidation:
    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="per_widget_timeout_seconds MUST be > 0"):
            ReportEngineConfig(per_widget_timeout_seconds=0)

    def test_timeout_above_ceiling_rejected(self) -> None:
        with pytest.raises(ValueError, match="per_widget_timeout_seconds MUST be <= 120"):
            ReportEngineConfig(per_widget_timeout_seconds=120.1)

    def test_non_positive_concurrency_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_concurrent_widgets MUST be > 0"):
            ReportEngineConfig(max_concurrent_widgets=0)

    def test_concurrency_above_ceiling_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_concurrent_widgets MUST be <= 32"):
            ReportEngineConfig(max_concurrent_widgets=33)

    def test_widget_cap_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"max_widgets_per_report MUST be in \[1, 200\]"):
            ReportEngineConfig(max_widgets_per_report=0)
        with pytest.raises(ValueError, match=r"max_widgets_per_report MUST be in \[1, 200\]"):
            ReportEngineConfig(max_widgets_per_report=201)

    def test_error_message_cap_below_floor_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_error_message_chars MUST be >= 32"):
            ReportEngineConfig(max_error_message_chars=31)
