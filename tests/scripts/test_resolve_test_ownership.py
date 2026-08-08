from __future__ import annotations

import json
from pathlib import Path

from scripts.automation.resolve_test_ownership import resolve_owned_tests


def _write_manifest(root: Path) -> None:
    tests = root / "tests"
    tests.mkdir()
    (tests / "service-suites.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "services": [
                    {
                        "id": "core",
                        "source_roots": ["src/fdai/core"],
                        "test_groups": {
                            "unit": ["tests/core"],
                            "contract": ["tests/contracts/test_core.py"],
                            "integration": [],
                            "smoke": [],
                        },
                    },
                    {
                        "id": "operator",
                        "source_roots": ["src/fdai/delivery/operator_api"],
                        "test_groups": {
                            "unit": ["tests/conversation"],
                            "contract": [],
                            "integration": ["tests/delivery/operator_api"],
                            "smoke": [],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_resolves_union_of_unique_service_owned_tests(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    selected = resolve_owned_tests(
        tmp_path,
        [
            tmp_path / "src/fdai/core/risk_gate.py",
            tmp_path / "src/fdai/delivery/operator_api/routes.py",
        ],
    )

    assert selected == [
        Path("tests/core"),
        Path("tests/contracts/test_core.py"),
        Path("tests/conversation"),
        Path("tests/delivery/operator_api"),
    ]


def test_returns_empty_when_any_source_has_no_owner(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    selected = resolve_owned_tests(
        tmp_path,
        [
            tmp_path / "src/fdai/core/risk_gate.py",
            tmp_path / "scripts/automation/helper.py",
        ],
    )

    assert selected == []
