"""Service-owned production composition tests for the independent Operator role."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest
from fdai_operator_service.application import create_app
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.contracts import (
    ApplicationFactory,
    AsgiApplication,
    AsgiMessage,
    AsgiReceive,
    AsgiScope,
    AsgiSend,
)
from fdai_operator_service.environment import (
    DEFAULT_FACTORY,
    FACTORY_ENV,
    HOST_ENV,
    PORT_ENV,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.main import SERVICE
from fdai_operator_service.production import serve
from fdai_operator_service.routes import DelegatingApplication

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_SOURCE = REPO_ROOT / "services/operator-service/src/fdai_operator_service"
LEGACY_ADAPTER = SERVICE_SOURCE / "legacy_adapter.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def _fdai_imports(path: Path) -> set[str]:
    return {name for name in _imports(path) if name == "fdai" or name.startswith("fdai.")}


def test_only_legacy_adapter_imports_operator_implementation() -> None:
    for path in SERVICE_SOURCE.rglob("*.py"):
        implementation_imports = _fdai_imports(path)
        if path == LEGACY_ADAPTER:
            assert implementation_imports == {"fdai.delivery.operator_api.prod"}
        else:
            assert implementation_imports == set()


def test_service_package_imports_no_fdai_core_module() -> None:
    for path in SERVICE_SOURCE.rglob("*.py"):
        assert {
            name for name in _imports(path) if name == "fdai.core" or name.startswith("fdai.core.")
        } == set()


@pytest.mark.parametrize("layer", ["main.py", "application.py", "routes.py", "production.py"])
def test_production_layers_import_no_fdai_implementation(layer: str) -> None:
    assert _fdai_imports(SERVICE_SOURCE / layer) == set()


def test_descriptor_identifies_independent_operator_distribution() -> None:
    assert SERVICE.service_id == "operator-service"
    assert SERVICE.distribution == "fdai-operator-service"
    assert SERVICE.entrypoint == "fdai-operator-service"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({FACTORY_ENV: ""}, FACTORY_ENV),
        ({HOST_ENV: ""}, HOST_ENV),
        ({PORT_ENV: "zero"}, PORT_ENV),
        ({PORT_ENV: "0"}, PORT_ENV),
        ({PORT_ENV: "65536"}, PORT_ENV),
    ],
)
def test_invalid_environment_fails_before_factory_resolution(
    overrides: Mapping[str, str],
    message: str,
) -> None:
    def resolve(reference: str) -> ApplicationFactory:
        del reference
        raise AssertionError("invalid configuration MUST fail before factory loading")

    with pytest.raises(OperatorServiceConfigurationError, match=message):
        create_app(
            overrides,
            composition=ProductionOperatorComposition(resolver=resolve),
        )


def test_factory_loading_delegates_with_an_environment_snapshot() -> None:
    received: list[Mapping[str, str]] = []
    references: list[str] = []

    async def application(
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        del scope, receive, send
        return None

    def factory(environ: Mapping[str, str]) -> AsgiApplication:
        received.append(environ)
        return application

    def resolve(reference: str) -> ApplicationFactory:
        references.append(reference)
        return factory

    environ = {FACTORY_ENV: "example.operator:create_app"}
    assert (
        create_app(
            environ,
            composition=ProductionOperatorComposition(resolver=resolve),
        )
        is application
    )
    assert references == ["example.operator:create_app"]
    assert received == [environ]
    assert received[0] is not environ


def test_default_factory_is_the_single_legacy_adapter() -> None:
    references: list[str] = []

    def resolve(reference: str) -> ApplicationFactory:
        references.append(reference)

        async def application(
            scope: AsgiScope,
            receive: AsgiReceive,
            send: AsgiSend,
        ) -> None:
            del scope, receive, send
            return None

        def factory(environ: Mapping[str, str]) -> AsgiApplication:
            del environ
            return application

        return factory

    create_app(
        {},
        composition=ProductionOperatorComposition(resolver=resolve),
    )
    assert references == [DEFAULT_FACTORY]


async def test_asgi_delegation_preserves_scope_and_channels() -> None:
    calls: list[tuple[object, object, object]] = []
    scope: AsgiScope = {"type": "http", "path": "/healthz"}

    async def receive() -> AsgiMessage:
        return {"type": "http.request"}

    async def send(_message: AsgiMessage) -> None:
        return None

    async def application(
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        calls.append((scope, receive, send))

    await DelegatingApplication(application)(scope, receive, send)
    assert calls == [(scope, receive, send)]


def test_server_lifecycle_uses_validated_listener_without_starting_uvicorn() -> None:
    calls: list[tuple[str, bool, str, int]] = []

    def runner(
        factory_reference: str,
        *,
        factory: bool,
        host: str,
        port: int,
    ) -> object:
        calls.append((factory_reference, factory, host, port))
        return None

    assert (
        serve(
            "example.operator:create_app",
            {HOST_ENV: "127.0.0.1", PORT_ENV: "9123"},
            runner=runner,
        )
        == 0
    )
    assert calls == [("example.operator:create_app", True, "127.0.0.1", 9123)]
