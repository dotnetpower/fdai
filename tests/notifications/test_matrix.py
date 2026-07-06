"""Matrix loader edge-case coverage.

Kept separate from :mod:`.test_router` so the validation branch matrix
stays legible: each test targets exactly one rejection path in
``load_matrix_from_mapping`` / ``load_matrix_from_yaml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.core.notifications import (
    MatrixValidationError,
    load_matrix_from_mapping,
    load_matrix_from_yaml,
)


class TestMatrixEdgeCases:
    def test_top_level_matrix_key_missing_or_wrong_type(self) -> None:
        with pytest.raises(MatrixValidationError, match="top-level 'matrix'"):
            load_matrix_from_mapping({"matrix": "not a mapping"})

    def test_version_must_be_positive_int(self) -> None:
        with pytest.raises(MatrixValidationError, match="matrix.version"):
            load_matrix_from_mapping(
                {"matrix": {"version": 0, "default_route": "r", "routes": {"r": {}}}}
            )
        with pytest.raises(MatrixValidationError, match="matrix.version"):
            load_matrix_from_mapping(
                {"matrix": {"version": "1", "default_route": "r", "routes": {"r": {}}}}
            )

    def test_routes_must_be_non_empty_mapping(self) -> None:
        with pytest.raises(MatrixValidationError, match="matrix.routes"):
            load_matrix_from_mapping({"matrix": {"version": 1, "default_route": "r", "routes": {}}})
        with pytest.raises(MatrixValidationError, match="matrix.routes"):
            load_matrix_from_mapping(
                {"matrix": {"version": 1, "default_route": "r", "routes": "no"}}
            )

    def test_route_name_must_be_non_empty_string(self) -> None:
        with pytest.raises(MatrixValidationError, match="route name"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r",
                        "routes": {"": {"trust_tier": "a2_operational_alert", "primary": "c"}},
                    }
                }
            )

    def test_route_value_must_be_mapping(self) -> None:
        with pytest.raises(MatrixValidationError, match="MUST be a mapping"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r",
                        "routes": {"r": "not a mapping"},
                    }
                }
            )

    def test_default_route_type(self) -> None:
        with pytest.raises(MatrixValidationError, match="matrix.default_route"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": 42,
                        "routes": {"r": {"trust_tier": "a2_operational_alert", "primary": "c"}},
                    }
                }
            )

    def test_trust_tier_type(self) -> None:
        with pytest.raises(MatrixValidationError, match="trust_tier"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r",
                        "routes": {"r": {"trust_tier": 42, "primary": "c"}},
                    }
                }
            )

    def test_primary_type(self) -> None:
        with pytest.raises(MatrixValidationError, match="primary"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r",
                        "routes": {"r": {"trust_tier": "a2_operational_alert", "primary": ""}},
                    }
                }
            )

    def test_fallback_entry_type(self) -> None:
        with pytest.raises(MatrixValidationError, match="fallback"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r",
                        "routes": {
                            "r": {
                                "trust_tier": "a2_operational_alert",
                                "primary": "c",
                                "fallback": ["", "ok"],
                            }
                        },
                    }
                }
            )

    def test_on_all_fail_type(self) -> None:
        with pytest.raises(MatrixValidationError, match="on_all_fail"):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r",
                        "routes": {
                            "r": {
                                "trust_tier": "a2_operational_alert",
                                "primary": "c",
                                "on_all_fail": 42,
                            }
                        },
                    }
                }
            )

    def test_yaml_loader_rejects_non_mapping_document(self, tmp_path: Path) -> None:
        bad = tmp_path / "matrix.yaml"
        bad.write_text("- just a list\n", encoding="utf-8")
        with pytest.raises(MatrixValidationError, match="YAML mapping"):
            load_matrix_from_yaml(bad)

    def test_yaml_loader_reads_valid_document(self, tmp_path: Path) -> None:
        good = tmp_path / "matrix.yaml"
        good.write_text(
            (
                "matrix:\n"
                "  version: 1\n"
                "  default_route: r\n"
                "  routes:\n"
                "    r:\n"
                "      trust_tier: a2_operational_alert\n"
                "      primary: teams-ops-prd\n"
            ),
            encoding="utf-8",
        )
        matrix = load_matrix_from_yaml(good)
        assert "r" in matrix.routes
