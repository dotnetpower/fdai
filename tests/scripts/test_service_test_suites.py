from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_PLAN_PATH = REPO_ROOT / "config" / "service-decomposition.json"
SUITE_PATH = REPO_ROOT / "tests" / "service-suites.json"
RUNNER_PATH = REPO_ROOT / "scripts" / "automation" / "run-service-tests.py"
GROUPS = ("unit", "contract", "integration", "smoke")


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_runtime_service_has_one_test_suite() -> None:
    service_plan = _load(SERVICE_PLAN_PATH)
    suite_plan = _load(SUITE_PATH)

    expected = [service["id"] for service in service_plan["services"]]
    actual = [service["id"] for service in suite_plan["services"]]

    assert suite_plan["schema_version"] == 1
    assert actual == expected


def test_service_suite_paths_exist_and_have_one_owner() -> None:
    suite_plan = _load(SUITE_PATH)
    source_owners: list[tuple[Path, str]] = []
    test_owners: list[tuple[Path, str]] = []

    for service in suite_plan["services"]:
        service_id = service["id"]
        for source_root in service["source_roots"]:
            assert (REPO_ROOT / source_root).exists(), (service_id, source_root)
            _assert_exclusive(Path(source_root), service_id, source_owners)
            source_owners.append((Path(source_root), service_id))
        assert tuple(service["test_groups"]) == GROUPS
        for group in GROUPS:
            for test_path in service["test_groups"][group]:
                assert (REPO_ROOT / test_path).exists(), (service_id, group, test_path)
                _assert_exclusive(Path(test_path), service_id, test_owners)
                test_owners.append((Path(test_path), service_id))


def _assert_exclusive(
    claimed_path: Path,
    service_id: str,
    existing: list[tuple[Path, str]],
) -> None:
    for owned_path, owner in existing:
        overlaps = (
            claimed_path == owned_path
            or claimed_path.is_relative_to(owned_path)
            or owned_path.is_relative_to(claimed_path)
        )
        assert not overlaps or owner == service_id, (
            claimed_path.as_posix(),
            service_id,
            owned_path.as_posix(),
            owner,
        )


def test_service_test_runner_lists_only_owned_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = runpy.run_path(str(RUNNER_PATH))

    assert namespace["main"](["isolated-executor", "--list"]) == 0
    listed = capsys.readouterr().out.splitlines()
    assert "tests/contracts/test_executor_transport.py" in listed
    assert all("operator_api" not in path for path in listed)
