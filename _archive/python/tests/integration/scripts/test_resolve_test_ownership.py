from __future__ import annotations

import json
from pathlib import Path

from scripts.automation.resolve_test_ownership import resolve_owned_tests


def _write_manifest(root: Path) -> None:
    tests = root / "tests" / "integration"
    tests.mkdir(parents=True)
    (tests / "service-suites.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "services": [
                    {
                        "id": "core",
                        "source_roots": ["services/core-control-plane"],
                        "test_groups": {
                            "unit": ["services/core-control-plane/tests"],
                            "contract": ["tests/integration/contracts/test_core.py"],
                            "integration": [],
                            "smoke": [],
                        },
                    },
                    {
                        "id": "operator",
                        "source_roots": ["services/operator-service"],
                        "test_groups": {
                            "unit": ["services/operator-service/tests"],
                            "contract": [],
                            "integration": ["tests/integration/operator-service"],
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
            tmp_path / "services/core-control-plane/src/fdai/core/risk_gate.py",
            tmp_path / "services/operator-service/src/fdai_operator_service/routes.py",
        ],
    )

    assert selected == [
        Path("services/core-control-plane/tests"),
        Path("tests/integration/contracts/test_core.py"),
        Path("services/operator-service/tests"),
        Path("tests/integration/operator-service"),
    ]


def test_returns_empty_when_any_source_has_no_owner(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    selected = resolve_owned_tests(
        tmp_path,
        [
            tmp_path / "services/core-control-plane/src/fdai/core/risk_gate.py",
            tmp_path / "scripts/automation/helper.py",
        ],
    )

    assert selected == []
