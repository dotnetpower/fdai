"""Service-local composition boundaries for the independent ingestion roles."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest
from fdai_document_worker_service.application import run_worker
from fdai_document_worker_service.composition import (
    DEFAULT_FACTORY as DEFAULT_WORKER_FACTORY,
)
from fdai_document_worker_service.composition import (
    ConfiguredDocumentWorkerComposition,
    DocumentWorkerConfigurationError,
)
from fdai_document_worker_service.providers import WorkerFactory
from fdai_ingestion_api_service.application import create_app
from fdai_ingestion_api_service.composition import (
    DEFAULT_FACTORY as DEFAULT_API_FACTORY,
)
from fdai_ingestion_api_service.composition import (
    ConfiguredIngestionApiComposition,
    IngestionApiConfigurationError,
)
from fdai_ingestion_api_service.providers import ApplicationFactory

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_SOURCES = (
    REPO_ROOT / "services/document-ingestion-api/src/fdai_ingestion_api_service",
    REPO_ROOT / "services/document-processing-worker/src/fdai_document_worker_service",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


@pytest.mark.parametrize("source", SERVICE_SOURCES)
@pytest.mark.parametrize("layer", ["main.py", "application.py"])
def test_main_and_application_layers_import_no_fdai_implementation(
    source: Path,
    layer: str,
) -> None:
    imports = _imports(source / layer)
    assert {name for name in imports if name == "fdai" or name.startswith("fdai.")} == set()


@pytest.mark.parametrize(
    ("source", "service_package"),
    [
        (SERVICE_SOURCES[0], "fdai_ingestion_api_service"),
        (SERVICE_SOURCES[1], "fdai_document_worker_service"),
    ],
)
def test_main_imports_only_service_local_code_and_contract_sdk(
    source: Path,
    service_package: str,
) -> None:
    assert all(
        name == "fdai_service_contracts"
        or name == service_package
        or name.startswith(f"{service_package}.")
        for name in _imports(source / "main.py")
    )


@pytest.mark.parametrize(
    ("source", "expected_import"),
    [
        (SERVICE_SOURCES[0], "fdai.delivery.ingestion_gateway.prod"),
        (SERVICE_SOURCES[1], "fdai.delivery.ingestion_gateway.worker"),
    ],
)
def test_fdai_implementation_import_is_isolated_to_legacy_adapter(
    source: Path,
    expected_import: str,
) -> None:
    adapter = source / "adapters/legacy_fdai.py"
    for path in source.rglob("*.py"):
        implementation_imports = {
            name for name in _imports(path) if name == "fdai" or name.startswith("fdai.")
        }
        if path == adapter:
            assert implementation_imports == {expected_import}
        else:
            assert implementation_imports == set()


@pytest.mark.parametrize("role", [None, "worker"])
def test_api_role_mismatch_prevents_factory_resolution(role: str | None) -> None:
    references: list[str] = []

    def resolve(reference: str) -> ApplicationFactory:
        references.append(reference)
        raise AssertionError("mismatched role MUST fail before factory resolution")

    env = {} if role is None else {"FDAI_INGESTION_DEPLOYMENT_ROLE": role}
    composition = ConfiguredIngestionApiComposition(resolver=resolve)

    with pytest.raises(IngestionApiConfigurationError, match="does not match"):
        create_app(env, composition=composition)
    assert references == []


def test_api_delegates_to_configured_factory_with_environment_snapshot() -> None:
    marker = object()
    resolved: list[str] = []
    received: list[Mapping[str, str]] = []

    def factory(environ: Mapping[str, str]) -> object:
        received.append(environ)
        return marker

    def resolve(reference: str) -> ApplicationFactory:
        resolved.append(reference)
        return factory

    env = {
        "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
        "FDAI_INGESTION_API_FACTORY": "example.api:create_app",
    }

    assert (
        create_app(env, composition=ConfiguredIngestionApiComposition(resolver=resolve)) is marker
    )
    assert resolved == ["example.api:create_app"]
    assert received == [env]
    assert received[0] is not env


def test_api_uses_explicit_legacy_adapter_by_default() -> None:
    resolved: list[str] = []

    def factory(_environ: Mapping[str, str]) -> object:
        return object()

    def resolve(reference: str) -> ApplicationFactory:
        resolved.append(reference)
        return factory

    create_app(
        {"FDAI_INGESTION_DEPLOYMENT_ROLE": "api"},
        composition=ConfiguredIngestionApiComposition(resolver=resolve),
    )

    assert resolved == [DEFAULT_API_FACTORY]


@pytest.mark.parametrize("role", [None, "api"])
def test_worker_role_mismatch_prevents_factory_resolution(role: str | None) -> None:
    references: list[str] = []

    def resolve(reference: str) -> WorkerFactory:
        references.append(reference)
        raise AssertionError("mismatched role MUST fail before factory resolution")

    env = {} if role is None else {"FDAI_INGESTION_DEPLOYMENT_ROLE": role}
    composition = ConfiguredDocumentWorkerComposition(resolver=resolve)

    with pytest.raises(DocumentWorkerConfigurationError, match="does not match"):
        run_worker(env, composition=composition)
    assert references == []


def test_worker_delegates_to_configured_factory_with_environment_snapshot() -> None:
    resolved: list[str] = []
    received: list[Mapping[str, str]] = []

    def factory(environ: Mapping[str, str]) -> int:
        received.append(environ)
        return 17

    def resolve(reference: str) -> WorkerFactory:
        resolved.append(reference)
        return factory

    env = {
        "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
        "FDAI_DOCUMENT_WORKER_FACTORY": "example.worker:run",
    }

    assert run_worker(env, composition=ConfiguredDocumentWorkerComposition(resolver=resolve)) == 17
    assert resolved == ["example.worker:run"]
    assert received == [env]
    assert received[0] is not env


def test_worker_uses_explicit_legacy_adapter_by_default() -> None:
    resolved: list[str] = []

    def factory(_environ: Mapping[str, str]) -> int:
        return 0

    def resolve(reference: str) -> WorkerFactory:
        resolved.append(reference)
        return factory

    assert (
        run_worker(
            {"FDAI_INGESTION_DEPLOYMENT_ROLE": "worker"},
            composition=ConfiguredDocumentWorkerComposition(resolver=resolve),
        )
        == 0
    )
    assert resolved == [DEFAULT_WORKER_FACTORY]
