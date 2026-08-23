"""Operational catalog review runtime composition tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fdai.runtime.operational_catalog_review import (
    _load_scenarios,
    build_operational_catalog_review_bindings,
)


def test_unconfigured_catalog_review_remains_unavailable() -> None:
    assert (
        build_operational_catalog_review_bindings(
            control_loop=object(),  # type: ignore[arg-type]
            http_client=None,
            environment={},
            catalog_root=Path("rule-catalog"),
            policies_root=Path("policies"),
        )
        is None
    )


def test_enabled_catalog_review_requires_complete_configuration() -> None:
    with pytest.raises(RuntimeError, match="configuration is incomplete"):
        build_operational_catalog_review_bindings(
            control_loop=object(),  # type: ignore[arg-type]
            http_client=httpx.AsyncClient(),
            environment={"FDAI_CATALOG_REVIEW_ENABLED": "1"},
            catalog_root=Path("rule-catalog"),
            policies_root=Path("policies"),
        )


def test_disabled_catalog_review_rejects_partial_settings() -> None:
    with pytest.raises(RuntimeError, match="require FDAI_CATALOG_REVIEW_ENABLED=1"):
        build_operational_catalog_review_bindings(
            control_loop=object(),  # type: ignore[arg-type]
            http_client=None,
            environment={
                "FDAI_CATALOG_REVIEW_ENABLED": "0",
                "FDAI_CATALOG_REVIEW_SCENARIO_SET_ID": "partial",
            },
            catalog_root=Path("rule-catalog"),
            policies_root=Path("policies"),
        )


def test_scenario_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    (tmp_path / "scenario.json").symlink_to(target)

    with pytest.raises(RuntimeError, match="MUST be a regular file"):
        _load_scenarios(tmp_path)


def test_scenario_over_byte_limit_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "scenario.json").write_bytes(b" " * (1024 * 1024 + 1))

    with pytest.raises(RuntimeError, match="exceeds its byte limit"):
        _load_scenarios(tmp_path)
