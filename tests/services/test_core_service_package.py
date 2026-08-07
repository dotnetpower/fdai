"""Core service wheel ownership and isolated-import regression tests."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_PROJECT = REPO_ROOT / "services" / "core-control-plane"
CONTRACT_PROJECT = REPO_ROOT / "service-contracts"
DOCKERFILE = REPO_ROOT / "services" / "Dockerfile"

EXPECTED_FDAI_ROOTS = {
    "__init__.py",
    "__main__.py",
    "agents",
    "composition",
    "core",
    "delivery",
    "deployment_cli",
    "py.typed",
    "rule_catalog",
    "runtime",
    "shared",
}

EXPECTED_RUNTIME_MODULES = {
    "__init__.py",
    "bootstrap.py",
    "bootstrap_bindings.py",
    "bootstrap_lifecycle.py",
    "bootstrap_shutdown.py",
    "case_history.py",
    "catalog_ontology.py",
    "configuration.py",
    "consumers.py",
    "control_loop.py",
    "conversation_assurance.py",
    "conversation_assurance_lifecycle.py",
    "delivery.py",
    "dynamic_evidence.py",
    "forecast_learning.py",
    "health.py",
    "human_access.py",
    "human_assignment_reconciliation.py",
    "inventory_ontology.py",
    "isolated_executor_client.py",
    "operating_model.py",
    "post_turn_review.py",
    "providers.py",
    "readiness.py",
    "t2_recovery.py",
    "t2_route_registry.py",
}

PROHIBITED_WHEEL_PREFIXES = (
    "fdai/delivery/ingestion_gateway/",
    "fdai/delivery/operator_api/",
)

PROHIBITED_RUNTIME_MODULES = {
    "evaluation_runner.py",
    "evaluation_runner_cli.py",
    "executor_authority_probe_cli.py",
    "isolated_executor.py",
    "isolated_executor_cli.py",
    "isolated_executor_lock.py",
    "isolated_executor_runtime.py",
}


def _requirement_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower()


def _build_wheel(project: str, output: Path) -> Path:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for service packaging tests"
    subprocess.run(  # noqa: S603 - resolved uv executable runs fixed build arguments
        [uv, "build", "--wheel", "--package", project, "--out-dir", str(output)],
        cwd=REPO_ROOT,
        check=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
        capture_output=True,
        text=True,
    )
    wheels = sorted(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="module")
def core_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("core-wheel")
    return _build_wheel("fdai-core-control-plane", output)


def _wheel_members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def test_core_wheel_metadata_has_no_monolithic_fdai_dependency(core_wheel: Path) -> None:
    with zipfile.ZipFile(core_wheel) as archive:
        metadata_path = next(name for name in archive.namelist() if name.endswith("/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_path))

    assert metadata["Name"] == "fdai-core-control-plane"
    requirements = metadata.get_all("Requires-Dist", [])
    assert "fdai-service-contracts==0.1.0" in requirements
    assert all(_requirement_name(requirement) != "fdai" for requirement in requirements)


def test_core_wheel_contains_only_the_declared_fdai_payload(core_wheel: Path) -> None:
    members = _wheel_members(core_wheel)
    roots = {
        member.split("/", 2)[1]
        for member in members
        if member.startswith("fdai/") and len(member.split("/", 2)) >= 2
    }
    runtime_modules = {
        Path(member).name
        for member in members
        if member.startswith("fdai/runtime/") and member.count("/") == 2
    }

    assert roots == EXPECTED_FDAI_ROOTS
    assert runtime_modules == EXPECTED_RUNTIME_MODULES
    assert not (runtime_modules & PROHIBITED_RUNTIME_MODULES)
    assert all(not member.startswith(PROHIBITED_WHEEL_PREFIXES) for member in members)
    assert all(
        Path(member).suffix in {".json", ".md", ".py", ".typed"}
        for member in members
        if member.startswith("fdai/")
    )
    assert "fdai/runtime/isolated_executor_client.py" in members
    assert "fdai_core_service/main.py" in members


def test_core_wheel_cold_imports_without_fdai_distribution(
    core_wheel: Path,
    tmp_path: Path,
) -> None:
    contract_wheel = _build_wheel("fdai-service-contracts", tmp_path)
    uv = shutil.which("uv")
    assert uv is not None
    script = """
from importlib.metadata import PackageNotFoundError, distribution

try:
    distribution("fdai")
except PackageNotFoundError:
    pass
else:
    raise AssertionError("monolithic fdai distribution is installed")

import fdai.agents
import fdai.composition
import fdai.core.control_loop
import fdai.rule_catalog.schema.action_type
import fdai.runtime.bootstrap
import fdai.runtime.isolated_executor_client
import fdai.shared.contracts
import fdai_core_service.main

assert distribution("fdai-core-control-plane").version == "0.1.0"
"""
    subprocess.run(  # noqa: S603 - resolved uv executable runs fixed import arguments
        [
            uv,
            "run",
            "--isolated",
            "--no-project",
            "--offline",
            "--python",
            sys.executable,
            "--with",
            str(core_wheel),
            "--with",
            str(contract_wheel),
            "python",
            "-I",
            "-c",
            script,
        ],
        cwd=tmp_path,
        check=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
        capture_output=True,
        text=True,
    )


def test_core_image_has_no_monolithic_source_fallback() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "--no-install-package fdai" in dockerfile
    assert 'PYTHONPATH="/app/src"' not in dockerfile
    assert "COPY --chown=65532:65532 src/ /app/src/" not in dockerfile
