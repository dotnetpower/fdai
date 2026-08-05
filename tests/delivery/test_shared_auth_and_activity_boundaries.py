"""Executable boundaries for shared auth and agent-activity delivery."""

from __future__ import annotations

import ast
from pathlib import Path

from fdai.delivery import agent_activity
from fdai.delivery import auth as shared_auth
from fdai.delivery.operator_api import auth as operator_auth
from fdai.delivery.operator_api import entra_verifier as operator_entra

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return modules


def test_ingestion_gateway_does_not_import_operator_api() -> None:
    offenders = {
        path.relative_to(_REPO_ROOT).as_posix(): sorted(
            module for module in _imports(path) if module.startswith("fdai.delivery.operator_api")
        )
        for path in (_REPO_ROOT / "src/fdai/delivery/ingestion_gateway").rglob("*.py")
    }
    assert not {path: modules for path, modules in offenders.items() if modules}


def test_runtime_does_not_import_operator_api() -> None:
    offenders = {
        path.relative_to(_REPO_ROOT).as_posix(): sorted(
            module for module in _imports(path) if module.startswith("fdai.delivery.operator_api")
        )
        for path in (_REPO_ROOT / "src/fdai/runtime").rglob("*.py")
    }
    assert not {path: modules for path, modules in offenders.items() if modules}


def test_shared_delivery_modules_have_no_application_dependencies() -> None:
    forbidden_prefixes = (
        "fdai.delivery.ingestion_gateway",
        "fdai.delivery.operator_api",
        "fdai.runtime",
    )
    paths = sorted((_REPO_ROOT / "src/fdai/delivery/auth").rglob("*.py"))
    paths.append(_REPO_ROOT / "src/fdai/delivery/agent_activity.py")
    for path in paths:
        assert not {module for module in _imports(path) if module.startswith(forbidden_prefixes)}
        source = path.read_text(encoding="utf-8")
        assert 'Route("/' not in source
        assert "CORSMiddleware" not in source


def test_operator_auth_paths_reexport_shared_symbols() -> None:
    assert operator_auth.__all__ == [
        "AuthenticationError",
        "Authenticator",
        "ClaimsVerifier",
        "UnsafeClaimsExtractor",
        "build_authenticator",
    ]
    assert operator_entra.__all__ == ["EntraJwtVerifier", "EntraVerifierConfigError"]
    assert operator_auth.AuthenticationError is shared_auth.AuthenticationError
    assert operator_auth.Authenticator is shared_auth.Authenticator
    assert operator_auth.ClaimsVerifier is shared_auth.ClaimsVerifier
    assert operator_auth.UnsafeClaimsExtractor is shared_auth.UnsafeClaimsExtractor
    assert operator_auth.build_authenticator is shared_auth.build_authenticator
    assert operator_entra.EntraJwtVerifier is shared_auth.EntraJwtVerifier
    assert operator_entra.EntraVerifierConfigError is shared_auth.EntraVerifierConfigError


def test_runtime_publisher_compatibility_path_reexports_neutral_symbols() -> None:
    from fdai.delivery.operator_api.streaming import agent_runtime_state_publisher

    assert (
        agent_runtime_state_publisher.AgentRuntimeStatePublisher
        is agent_activity.AgentRuntimeStatePublisher
    )
    assert (
        agent_runtime_state_publisher.EventBusPantheonActivityObserver
        is agent_activity.EventBusPantheonActivityObserver
    )
    assert (
        agent_runtime_state_publisher.DEFAULT_RUNTIME_STATE_TOPIC
        == agent_activity.DEFAULT_STAGE_TOPIC
        == "aw.pipeline.stages"
    )
