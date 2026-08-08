from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = REPO_ROOT / "services"

EXPECTED = {
    "core-control-plane": ("fdai-core-control-plane", "fdai-core-control-plane"),
    "operator-service": ("fdai-operator-service", "fdai-operator-service"),
    "document-ingestion-api": (
        "fdai-document-ingestion-api",
        "fdai-document-ingestion-api",
    ),
    "document-processing-worker": (
        "fdai-document-processing-worker",
        "fdai-document-processing-worker",
    ),
    "isolated-executor": (
        "fdai-isolated-executor-service",
        "fdai-isolated-executor-service",
    ),
}

PACKAGE_ROOTS = {
    "core-control-plane": {"fdai", "fdai_core_service"},
    "operator-service": {"fdai_operator_service"},
    "document-ingestion-api": {"fdai_ingestion_api_service"},
    "document-processing-worker": {"fdai_document_worker_service"},
    "isolated-executor": {"fdai_executor_service"},
}

EXPECTED_DEPENDENCIES = {
    "core-control-plane": {
        "aiokafka",
        "alembic",
        "croniter",
        "fdai-service-contracts",
        "httpx",
        "jsonschema",
        "markdown-it-py",
        "opentelemetry-api",
        "opentelemetry-exporter-otlp-proto-grpc",
        "opentelemetry-sdk",
        "psycopg",
        "pydantic",
        "pypdf",
        "pyyaml",
        "sqlalchemy",
    },
    "operator-service": {
        "fdai-service-contracts",
        "psycopg",
        "pyjwt",
        "starlette",
        "uvicorn",
    },
    "document-ingestion-api": {
        "aiohttp",
        "aiokafka",
        "azure-core",
        "azure-identity",
        "azure-storage-file-datalake",
        "fdai-service-contracts",
        "httpx",
        "psycopg",
        "pydantic",
        "pyjwt",
        "starlette",
        "uvicorn",
    },
    "document-processing-worker": {
        "aiohttp",
        "aiokafka",
        "azure-core",
        "azure-identity",
        "azure-storage-file-datalake",
        "fdai-service-contracts",
        "httpx",
        "psycopg",
        "pydantic",
        "pypdf",
    },
    "isolated-executor": {
        "aiokafka",
        "fdai-service-contracts",
        "httpx",
        "psycopg",
        "pydantic",
    },
}

INDIRECT_RUNTIME_DEPENDENCIES = {
    "document-ingestion-api": {"aiohttp"},
    "document-processing-worker": {"aiohttp"},
}

IMPORT_DISTRIBUTIONS = {
    "aiokafka": "aiokafka",
    "azure.core": "azure-core",
    "azure.identity": "azure-identity",
    "azure.storage.filedatalake": "azure-storage-file-datalake",
    "fdai_service_contracts": "fdai-service-contracts",
    "httpx": "httpx",
    "jwt": "pyjwt",
    "psycopg": "psycopg",
    "pydantic": "pydantic",
    "pypdf": "pypdf",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
}


def _requirement_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower()


def _direct_import_distributions(source_root: Path) -> set[str]:
    local_packages = {path.name for path in source_root.iterdir() if path.is_dir()}
    distributions: set[str] = set()
    for source_file in source_root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module)
        for module in modules:
            root = module.split(".", maxsplit=1)[0]
            if root in sys.stdlib_module_names or root in local_packages or root == "fdai":
                continue
            matches = {
                distribution
                for prefix, distribution in IMPORT_DISTRIBUTIONS.items()
                if module == prefix or module.startswith(f"{prefix}.")
            }
            assert len(matches) == 1, (source_file, module, sorted(matches))
            distributions.update(matches)
    return distributions


def test_five_service_distributions_have_owned_entrypoints() -> None:
    assert {
        path.name
        for path in SERVICE_ROOT.iterdir()
        if path.is_dir() and (path / "pyproject.toml").is_file()
    } == set(EXPECTED)
    distributions: set[str] = set()
    scripts: set[str] = set()
    for service_id, (distribution, script) in EXPECTED.items():
        project = tomllib.loads((SERVICE_ROOT / service_id / "pyproject.toml").read_text())
        assert project["project"]["name"] == distribution
        assert project["project"]["version"] == "0.1.3"
        assert script in project["project"]["scripts"]
        assert "fdai-service-contracts==0.1.0" in project["project"]["dependencies"]
        distributions.add(distribution)
        scripts.add(script)
    assert len(distributions) == 5
    assert len(scripts) == 5


def test_service_distributions_declare_only_owned_runtime_dependencies() -> None:
    for service_id, expected in EXPECTED_DEPENDENCIES.items():
        project = tomllib.loads((SERVICE_ROOT / service_id / "pyproject.toml").read_text())
        actual = {_requirement_name(value) for value in project["project"]["dependencies"]}
        assert actual == expected, service_id


def test_extracted_service_direct_imports_are_declared() -> None:
    for service_id in EXPECTED:
        if service_id == "core-control-plane":
            continue
        source_root = SERVICE_ROOT / service_id / "src"
        assert _direct_import_distributions(source_root) == (
            EXPECTED_DEPENDENCIES[service_id] - INDIRECT_RUNTIME_DEPENDENCIES.get(service_id, set())
        )


@pytest.mark.parametrize("service_id", tuple(EXPECTED))
def test_service_wheel_contains_only_owned_package_roots(
    service_id: str,
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    distribution = EXPECTED[service_id][0]
    subprocess.run(  # noqa: S603 - resolved uv executable runs fixed build arguments
        [uv, "build", "--wheel", "--package", distribution, "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
        capture_output=True,
        text=True,
    )
    wheels = tuple(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        roots = {
            member.split("/", maxsplit=1)[0]
            for member in archive.namelist()
            if ".dist-info/" not in member
        }

    assert roots == PACKAGE_ROOTS[service_id]
    assert not (roots & (set().union(*PACKAGE_ROOTS.values()) - PACKAGE_ROOTS[service_id]))


def test_service_contract_sdk_contains_no_fdai_implementation_import() -> None:
    source = REPO_ROOT / "packages" / "service-contracts" / "src" / "fdai_service_contracts"
    text = "\n".join(path.read_text(encoding="utf-8") for path in source.glob("*.py"))
    assert "from fdai." not in text
    assert "import fdai." not in text


def test_root_cannot_build_or_install_a_monolithic_distribution() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["package"] is False
    assert "build-system" not in project
    assert "scripts" not in project["project"]
    assert not (REPO_ROOT / "src" / "fdai").exists()


def test_installed_contract_wheel_validates_its_bundled_manifest(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    wheel_dir = tmp_path / "wheels"
    environment = tmp_path / "venv"
    subprocess.run(  # noqa: S603 - resolved uv executable runs fixed build arguments
        [
            uv,
            "build",
            "--wheel",
            "--package",
            "fdai-service-contracts",
            "--out-dir",
            str(wheel_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("fdai_service_contracts-*.whl"))
    subprocess.run(  # noqa: S603 - resolved uv executable creates an isolated test venv
        [uv, "venv", "--python", sys.executable, str(environment)],
        check=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
        capture_output=True,
        text=True,
    )
    python = environment / "bin" / "python"
    subprocess.run(  # noqa: S603 - resolved uv executable installs the built test wheel
        [uv, "pip", "install", "--python", str(python), str(wheel)],
        check=True,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(  # noqa: S603 - venv Python executes fixed validation code
        [
            str(python),
            "-I",
            "-c",
            (
                "import json; from importlib import resources; "
                "from fdai_service_contracts import validate_manifest; "
                "manifest=json.loads(resources.files('fdai_service_contracts')"
                ".joinpath('compatibility-manifest.json').read_text()); "
                "summary=validate_manifest(manifest); "
                "print(summary.service_count, summary.contract_count, summary.matrix_edge_count)"
            ),
        ],
        cwd=tmp_path,
        check=False,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "5 7 7"
