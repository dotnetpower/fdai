"""Independent composition and import boundaries for both ingestion services."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
from fdai_document_worker_service import production as worker_production
from fdai_document_worker_service.application import run_worker
from fdai_document_worker_service.composition import (
    ConfiguredDocumentWorkerComposition,
    DocumentWorkerConfigurationError,
)
from fdai_ingestion_api_service import production as api_production
from fdai_ingestion_api_service.application import create_app
from fdai_ingestion_api_service.composition import (
    ConfiguredIngestionApiComposition,
    IngestionApiConfigurationError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPO_ROOT / "services/document-ingestion-api/src/fdai_ingestion_api_service"
WORKER_SOURCE = REPO_ROOT / "services/document-processing-worker/src/fdai_document_worker_service"
SERVICE_SOURCES = (API_SOURCE, WORKER_SOURCE)


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
def test_service_package_has_no_fdai_implementation_import(source: Path) -> None:
    offenders = {
        path.relative_to(source): sorted(
            name for name in _imports(path) if name == "fdai" or name.startswith("fdai.")
        )
        for path in source.rglob("*.py")
        if any(name == "fdai" or name.startswith("fdai.") for name in _imports(path))
    }
    assert offenders == {}


@pytest.mark.parametrize("source", SERVICE_SOURCES)
def test_service_package_has_no_dynamic_import_loading(source: Path) -> None:
    offenders: list[Path] = []
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            )
            for node in ast.walk(tree)
        ):
            offenders.append(path.relative_to(source))
    assert offenders == []


def test_services_do_not_import_each_other() -> None:
    assert all(
        not name.startswith("fdai_document_worker_service")
        for path in API_SOURCE.rglob("*.py")
        for name in _imports(path)
    )


@pytest.mark.parametrize("production", [api_production, worker_production])
def test_production_azure_credential_uses_exact_attached_identity(
    monkeypatch: pytest.MonkeyPatch,
    production: object,
) -> None:
    observed: list[str] = []

    def credential(*, client_id: str) -> object:
        observed.append(client_id)
        return object()

    monkeypatch.setattr(production, "ManagedIdentityCredential", credential)

    result = production._managed_identity_credential({"FDAI_MI_CLIENT_ID": " identity-client "})

    assert result is not None
    assert observed == ["identity-client"]
    assert all(
        not name.startswith("fdai_ingestion_api_service")
        for path in WORKER_SOURCE.rglob("*.py")
        for name in _imports(path)
    )


def test_local_api_composition_needs_no_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden_credential(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("local API composition requested managed identity")

    monkeypatch.setattr(api_production, "ManagedIdentityCredential", forbidden_credential)
    application = api_production.build_application(
        {
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
            "FDAI_DATABASE_ROLE": "fdai_ingestion_api",
            "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
            "FDAI_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
            "FDAI_DOCUMENT_EVENT_TOPIC": "aw.pipeline.stages",
            "FDAI_ENTRA_TENANT_ID": "tenant",
            "FDAI_API_AUDIENCE": "audience",
            "FDAI_RBAC_READERS_GROUP_ID": "reader",
            "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "contributor",
            "FDAI_RBAC_APPROVERS_GROUP_ID": "approver",
            "FDAI_RBAC_OWNERS_GROUP_ID": "owner",
            "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "break-glass",
            "FDAI_INGESTION_CORS_ALLOW_ORIGINS": "http://127.0.0.1:5273",
            "FDAI_LOCAL_DOCUMENT_STORE_DIR": str(tmp_path),
        }
    )

    assert application is not None


def test_local_worker_composition_needs_no_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden_credential(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("local worker composition requested managed identity")

    monkeypatch.setattr(worker_production, "ManagedIdentityCredential", forbidden_credential)
    runtime = worker_production.build_runtime(
        {
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
            "FDAI_DATABASE_ROLE": "fdai_ingestion_worker",
            "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
            "FDAI_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
            "FDAI_DOCUMENT_EVENT_TOPIC": "aw.pipeline.stages",
            "FDAI_CLAMAV_HOST": "127.0.0.1",
            "FDAI_CLAMAV_PORT": "3310",
            "FDAI_LOCAL_DOCUMENT_STORE_DIR": str(tmp_path),
        }
    )

    assert runtime.worker_service is not None


async def test_local_embedding_vectors_match_across_document_services() -> None:
    from fdai_document_worker_service.adapters.local import (
        DeterministicLocalEmbeddingModel as WorkerEmbedding,
    )
    from fdai_ingestion_api_service.adapters.local import (
        DeterministicLocalEmbeddingModel as ApiEmbedding,
    )

    assert await ApiEmbedding().embed("same document") == await WorkerEmbedding().embed(
        "same document"
    )


def test_outbox_drainers_are_service_owned_without_cohost_seam() -> None:
    api_source = "\n".join(path.read_text(encoding="utf-8") for path in API_SOURCE.glob("*.py"))
    worker_supervisor = (WORKER_SOURCE / "supervisor.py").read_text(encoding="utf-8")

    assert "background_services" not in api_source
    assert "api_outbox_drainers=(drain_api_outbox,)" in api_source
    assert "FROM document_api_outbox" in (API_SOURCE / "adapters" / "postgres.py").read_text(
        encoding="utf-8"
    )
    assert "FROM document_worker_outbox" in (WORKER_SOURCE / "adapters" / "activity.py").read_text(
        encoding="utf-8"
    )
    assert 'name="document-outbox-drainer"' in worker_supervisor


@pytest.mark.parametrize(
    "project",
    [
        REPO_ROOT / "services/document-ingestion-api/pyproject.toml",
        REPO_ROOT / "services/document-processing-worker/pyproject.toml",
    ],
)
def test_service_distribution_has_no_fdai_dependency(project: Path) -> None:
    document = tomllib.loads(project.read_text(encoding="utf-8"))
    dependencies = document["project"]["dependencies"]
    assert all(
        not value.startswith("fdai==") and not value.startswith("fdai[") for value in dependencies
    )
    assert "fdai" not in document.get("tool", {}).get("uv", {}).get("sources", {})


@pytest.mark.parametrize("role", [None, "worker"])
def test_api_role_mismatch_prevents_factory_call(role: str | None) -> None:
    called = False

    def factory(_environ: Mapping[str, str]) -> object:
        nonlocal called
        called = True
        return object()

    env = {} if role is None else {"FDAI_INGESTION_DEPLOYMENT_ROLE": role}
    with pytest.raises(IngestionApiConfigurationError, match="does not match"):
        create_app(
            env,
            composition=ConfiguredIngestionApiComposition(application_factory=factory),
        )
    assert not called


def test_api_fixed_factory_receives_environment_snapshot() -> None:
    marker = object()
    received: list[Mapping[str, str]] = []

    def factory(environ: Mapping[str, str]) -> object:
        received.append(environ)
        return marker

    env = {"FDAI_INGESTION_DEPLOYMENT_ROLE": "api"}
    assert (
        create_app(
            env,
            composition=ConfiguredIngestionApiComposition(application_factory=factory),
        )
        is marker
    )
    assert received == [env]
    assert received[0] is not env


@pytest.mark.parametrize("role", [None, "api"])
def test_worker_role_mismatch_prevents_factory_call(role: str | None) -> None:
    called = False

    def factory(_environ: Mapping[str, str]) -> int:
        nonlocal called
        called = True
        return 0

    env = {} if role is None else {"FDAI_INGESTION_DEPLOYMENT_ROLE": role}
    with pytest.raises(DocumentWorkerConfigurationError, match="does not match"):
        run_worker(
            env,
            composition=ConfiguredDocumentWorkerComposition(worker_factory=factory),
        )
    assert not called


def test_worker_fixed_factory_receives_environment_snapshot() -> None:
    received: list[Mapping[str, str]] = []

    def factory(environ: Mapping[str, str]) -> int:
        received.append(environ)
        return 17

    env = {"FDAI_INGESTION_DEPLOYMENT_ROLE": "worker"}
    assert (
        run_worker(
            env,
            composition=ConfiguredDocumentWorkerComposition(worker_factory=factory),
        )
        == 17
    )
    assert received == [env]
    assert received[0] is not env
