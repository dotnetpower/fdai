from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_PLAN_PATH = REPO_ROOT / "config" / "service-decomposition.json"
SUITE_PATH = REPO_ROOT / "tests" / "integration" / "service-suites.json"
RUNNER_PATH = REPO_ROOT / "scripts" / "automation" / "run-service-tests.py"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
GROUPS = ("unit", "contract", "integration", "smoke")
SERVICE_SOURCE_ROOTS = {
    "core-control-plane": "services/core-control-plane",
    "operator-service": "services/operator-service",
    "document-ingestion-api": "services/document-ingestion-api",
    "document-processing-worker": "services/document-processing-worker",
    "isolated-executor": "services/isolated-executor",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _runner_namespace() -> dict[str, Any]:
    return runpy.run_path(str(RUNNER_PATH))


def _write_manifest(tmp_path: Path, services: list[object]) -> Path:
    path = tmp_path / "service-suites.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "coverage": {
                    "source_patterns": [
                        "services/isolated-executor/src/fdai_executor_service/**/*.py"
                    ],
                    "test_patterns": [
                        "services/isolated-executor/tests/test_executor_http_adapters.py"
                    ],
                },
                "services": services,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_suite_plan(tmp_path: Path, suite_plan: dict[str, Any]) -> Path:
    path = tmp_path / "service-suites.json"
    path.write_text(json.dumps(suite_plan), encoding="utf-8")
    return path


def _service(
    *,
    service_id: str = "isolated-executor",
    source_roots: list[str] | None = None,
    test_paths: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": service_id,
        "source_roots": source_roots or [SERVICE_SOURCE_ROOTS[service_id]],
        "test_groups": {
            "unit": test_paths
            if test_paths is not None
            else ["services/isolated-executor/tests/test_executor_http_adapters.py"],
            "contract": [],
            "integration": [],
            "smoke": [],
        },
    }


def test_every_runtime_service_has_one_test_suite() -> None:
    service_plan = _load(SERVICE_PLAN_PATH)
    suite_plan = _load(SUITE_PATH)

    expected = [service["id"] for service in service_plan["services"]]
    actual = [service["id"] for service in suite_plan["services"]]

    assert suite_plan["schema_version"] == 1
    assert actual == expected


def test_service_suites_own_extracted_service_source_roots() -> None:
    suite_plan = _load(SUITE_PATH)

    assert {service["id"]: service["source_roots"] for service in suite_plan["services"]} == {
        service_id: [source_root] for service_id, source_root in SERVICE_SOURCE_ROOTS.items()
    }


def test_service_suite_coverage_includes_distribution_build_inputs() -> None:
    coverage = _load(SUITE_PATH)["coverage"]

    assert coverage["source_patterns"] == [
        "services/*/pyproject.toml",
        "services/*/src/**/*.py",
    ]


def test_service_test_make_targets_do_not_expand_freeform_pytest_args() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert "$(PYTEST_ARGS)" not in makefile


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


def test_service_suite_coverage_patterns_have_exactly_one_owner() -> None:
    suite_plan = _load(SUITE_PATH)
    coverage = suite_plan["coverage"]
    source_claims = _claims(suite_plan, key="source_roots")
    test_claims = _claims(suite_plan, key="test_groups")

    _assert_pattern_coverage(coverage["source_patterns"], source_claims)
    _assert_pattern_coverage(coverage["test_patterns"], test_claims)


def test_service_suite_coverage_rejects_unclassified_new_test(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    orphan = REPO_ROOT / "services" / "isolated-executor" / "tests" / "test_unowned_service.py"
    orphan.write_text("def test_orphan(): pass\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="requires one owner"):
            namespace["_load_services"]()
    finally:
        orphan.unlink(missing_ok=True)


def test_service_suite_manifest_rejects_canonical_service_order_drift(
    tmp_path: Path,
) -> None:
    namespace = _runner_namespace()
    suite_plan = _load(SUITE_PATH)
    services = suite_plan["services"]
    services[0], services[1] = services[1], services[0]
    manifest = _write_suite_plan(tmp_path, suite_plan)
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="canonical service ids and order"):
        namespace["_load_services"]()


@pytest.mark.parametrize("target", ("root", "service"))
def test_service_suite_manifest_rejects_unknown_keys(tmp_path: Path, target: str) -> None:
    namespace = _runner_namespace()
    suite_plan = _load(SUITE_PATH)
    if target == "root":
        suite_plan["schema_verison"] = 1
    else:
        suite_plan["services"][0]["source_root"] = "services/core-control-plane/src/fdai/core"
    manifest = _write_suite_plan(tmp_path, suite_plan)
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="unexpected keys"):
        namespace["_load_services"]()


def _claims(
    suite_plan: dict[str, Any],
    *,
    key: str,
) -> list[tuple[Path, str]]:
    claims: list[tuple[Path, str]] = []
    for service in suite_plan["services"]:
        values = service[key]
        if key == "test_groups":
            values = [path for group in GROUPS for path in values[group]]
        claims.extend((REPO_ROOT / path, service["id"]) for path in values)
    return claims


def _assert_pattern_coverage(
    patterns: list[str],
    claims: list[tuple[Path, str]],
) -> None:
    for pattern in patterns:
        matched = tuple(path for path in REPO_ROOT.glob(pattern) if path.is_file())
        assert matched, pattern
        for path in matched:
            owners = {
                owner
                for claimed_path, owner in claims
                if path == claimed_path or path.is_relative_to(claimed_path)
            }
            assert len(owners) == 1, (path.relative_to(REPO_ROOT).as_posix(), sorted(owners))


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
        assert not overlaps, (
            claimed_path.as_posix(),
            service_id,
            owned_path.as_posix(),
            owner,
        )


def test_service_test_runner_lists_only_owned_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = _runner_namespace()
    suite_plan = _load(SUITE_PATH)
    isolated_executor = next(
        service for service in suite_plan["services"] if service["id"] == "isolated-executor"
    )
    expected = [path for group in GROUPS for path in isolated_executor["test_groups"][group]]

    assert namespace["main"](["isolated-executor", "--list"]) == 0

    assert capsys.readouterr().out.splitlines() == expected


def test_service_test_runner_lists_all_services_in_canonical_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = _runner_namespace()
    suite_plan = _load(SUITE_PATH)
    expected = [
        path
        for service in suite_plan["services"]
        for group in GROUPS
        for path in service["test_groups"][group]
    ]

    assert namespace["main"](["--all", "--list"]) == 0

    assert capsys.readouterr().out.splitlines() == expected


def test_service_test_runner_executes_canonical_all_service_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _runner_namespace()
    suite_plan = _load(SUITE_PATH)
    expected = [
        path
        for service in suite_plan["services"]
        for group in GROUPS
        for path in service["test_groups"][group]
    ]
    observed: list[str] = []
    observed_environment: dict[str, str] = {}

    def completed(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.extend(command)
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        observed_environment.update(environment)
        return subprocess.CompletedProcess(args=command, returncode=0)

    monkeypatch.setattr(subprocess, "run", completed)

    assert namespace["main"](["--all", "-q"]) == 0
    assert observed[:4] == [namespace["sys"].executable, "-m", "pytest", "-q"]
    assert observed[4:] == expected
    python_path = observed_environment["PYTHONPATH"].split(namespace["os"].pathsep)
    assert str(REPO_ROOT / "packages" / "service-contracts" / "src") in python_path
    assert str(REPO_ROOT / "services" / "core-control-plane") in python_path
    for service_id in SERVICE_SOURCE_ROOTS:
        assert str(REPO_ROOT / "services" / service_id / "src") in python_path


def test_service_test_python_path_ignores_hostile_inherited_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _runner_namespace()
    path_separator = namespace["os"].pathsep
    monkeypatch.setenv(
        "PYTHONPATH",
        path_separator.join((str(REPO_ROOT / "src"), str(tmp_path / "hostile"))),
    )

    assert namespace["_python_path"](("isolated-executor",)).split(path_separator) == [
        str(REPO_ROOT / "services" / "isolated-executor" / "src"),
        str(REPO_ROOT / "packages" / "service-contracts" / "src"),
    ]
    assert namespace["_python_path"](("core-control-plane",)).split(path_separator) == [
        str(REPO_ROOT / "services" / "core-control-plane" / "src"),
        str(REPO_ROOT / "packages" / "service-contracts" / "src"),
        str(REPO_ROOT / "services" / "core-control-plane"),
    ]


@pytest.mark.parametrize(
    "arguments",
    (
        [],
        ["isolated-executor", "--all"],
    ),
)
def test_service_test_runner_requires_exactly_one_service_selection(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = _runner_namespace()

    def fail_if_called(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise AssertionError("pytest MUST NOT run with an ambiguous service selection")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    assert namespace["main"](arguments) == 2
    assert "exactly one service or --all" in capsys.readouterr().err


def test_service_test_runner_rejects_foreign_pytest_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = _runner_namespace()

    def fail_if_called(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise AssertionError("pytest MUST NOT run with a foreign service path")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    assert (
        namespace["main"](
            ["isolated-executor", "--", "services/core-control-plane/tests/delivery/operator_api"]
        )
        == 2
    )
    assert "pytest argument is not allowed" in capsys.readouterr().err


def test_service_test_runner_rejects_pytest_args_with_list(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = _runner_namespace()

    def fail_if_called(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise AssertionError("pytest MUST NOT run while listing owned paths")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    assert namespace["main"](["isolated-executor", "--list", "-q"]) == 2
    assert "cannot be combined with --list" in capsys.readouterr().err


def test_service_test_runner_propagates_pytest_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _runner_namespace()

    def completed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(args=(), returncode=7)

    monkeypatch.setattr(subprocess, "run", completed)

    assert namespace["main"](["isolated-executor", "-q"]) == 7


@pytest.mark.parametrize(
    "unsafe_path",
    (
        "/outside.py",
        "tests/../services/core-control-plane/src/fdai/runtime/isolated_executor.py",
    ),
)
def test_service_suite_manifest_rejects_unconfined_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    namespace = _runner_namespace()
    manifest = _write_manifest(tmp_path, [_service(test_paths=[unsafe_path])])
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="MUST stay within"):
        namespace["_load_services"]()


def test_service_suite_manifest_rejects_symlink_escape(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    outside = tmp_path / "outside.py"
    outside.write_text("def test_outside(): pass\n", encoding="utf-8")
    link = REPO_ROOT / "services" / "isolated-executor" / "tests" / ".service-suite-escape.py"
    link.symlink_to(outside)
    try:
        manifest = _write_manifest(
            tmp_path,
            [_service(test_paths=[link.relative_to(REPO_ROOT).as_posix()])],
        )
        namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

        with pytest.raises(ValueError, match="symlink|MUST stay within"):
            namespace["_load_services"]()
    finally:
        link.unlink(missing_ok=True)


def test_service_test_runner_rejects_empty_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    namespace = _runner_namespace()
    manifest = _write_manifest(tmp_path, [_service(test_paths=[])])
    namespace["main"].__globals__["MANIFEST_PATH"] = manifest

    def fail_if_called(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise AssertionError("pytest MUST NOT fall back to repository discovery")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    assert namespace["main"](["isolated-executor"]) == 2
    assert "MUST own at least one test path" in capsys.readouterr().err


def test_service_suite_manifest_rejects_malformed_service_entry(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    manifest = _write_manifest(tmp_path, [42])
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="service entry MUST be an object"):
        namespace["_load_services"]()


def test_service_suite_manifest_rejects_overlap_within_one_service(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    service = _service(
        source_roots=[
            "services/isolated-executor/src",
            "services/isolated-executor/src/fdai_executor_service",
        ]
    )
    manifest = _write_manifest(tmp_path, [service])
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="overlaps service isolated-executor"):
        namespace["_load_services"]()


def test_service_suite_manifest_reports_unreadable_file(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    missing = tmp_path / "missing.json"
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = missing

    with pytest.raises(ValueError, match=f"manifest is unreadable: {missing}"):
        namespace["_load_services"]()


def test_service_suite_manifest_reports_invalid_json(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    manifest = tmp_path / "service-suites.json"
    manifest.write_text('{"schema_version": 1,', encoding="utf-8")
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match=r"manifest is invalid JSON: .*:1"):
        namespace["_load_services"]()


def test_service_suite_manifest_reports_unsupported_schema_version(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    manifest = tmp_path / "service-suites.json"
    manifest.write_text(
        json.dumps({"schema_version": 2, "services": []}),
        encoding="utf-8",
    )
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="schema_version MUST be 1; got 2"):
        namespace["_load_services"]()


def test_service_suite_manifest_reports_invalid_services_type(tmp_path: Path) -> None:
    namespace = _runner_namespace()
    manifest = tmp_path / "service-suites.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "services": {}}),
        encoding="utf-8",
    )
    namespace["_load_services"].__globals__["MANIFEST_PATH"] = manifest

    with pytest.raises(ValueError, match="services MUST be an array"):
        namespace["_load_services"]()
