"""Executable compatibility and ownership checks for migrated audit projections."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.auth import build_authenticator
from fdai.delivery.operator_api.app.config import OperatorApiConfig
from fdai.delivery.operator_api.main import build_app
from fdai.delivery.operator_api.production.panels import build_production_panels
from fdai.delivery.operator_api.projections.audit import (
    AuditAutonomyMeasurementPanel,
    AuditFinOpsPanel,
)
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[3]
_AUDIT_MODULES = (
    "audit_finops",
    "audit_measurement_events",
    "audit_measurement_projection",
    "audit_measurement_summary",
    "audit_query",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_old_audit_modules_are_exact_public_symbol_shims() -> None:
    for name in _AUDIT_MODULES:
        old = importlib.import_module(f"fdai.delivery.operator_api.routes.{name}")
        new = importlib.import_module(f"fdai.delivery.operator_api.projections.audit.{name}")

        assert old.__all__ == new.__all__
        assert all(getattr(old, symbol) is getattr(new, symbol) for symbol in old.__all__)


def test_facade_exports_exact_composition_surface() -> None:
    facade = importlib.import_module("fdai.delivery.operator_api.projections.audit")
    expected = {
        "AuditAutonomyMeasurementPanel",
        "AuditFinOpsPanel",
        "AuditQueryError",
        "parse_audit_filters",
    }

    assert set(facade.__all__) == expected
    assert (
        facade.AuditFinOpsPanel
        is importlib.import_module(
            "fdai.delivery.operator_api.routes.audit_finops"
        ).AuditFinOpsPanel
    )
    assert (
        facade.AuditAutonomyMeasurementPanel
        is importlib.import_module(
            "fdai.delivery.operator_api.routes.audit_measurement_summary"
        ).AuditAutonomyMeasurementPanel
    )
    assert (
        facade.AuditQueryError
        is importlib.import_module("fdai.delivery.operator_api.routes.audit_query").AuditQueryError
    )


def test_facade_query_import_is_lazy_and_star_export_is_exact() -> None:
    script = (
        "import sys\n"
        "from fdai.delivery.operator_api.projections.audit import "
        "AuditQueryError, parse_audit_filters\n"
        "assert 'fdai.delivery.operator_api.projections.audit.audit_query' in sys.modules\n"
        "assert 'fdai.delivery.operator_api.projections.audit.audit_finops' not in sys.modules\n"
        "assert 'fdai.delivery.operator_api.projections.audit.audit_measurement_summary' "
        "not in sys.modules\n"
        "namespace = {}\n"
        "exec('from fdai.delivery.operator_api.projections.audit import *', namespace)\n"
        "assert {key for key in namespace if not key.startswith('__')} == "
        "{'AuditAutonomyMeasurementPanel', 'AuditFinOpsPanel', "
        "'AuditQueryError', 'parse_audit_filters'}\n"
    )

    result = subprocess.run(  # noqa: S603 - fixed interpreter and source
        [sys.executable, "-c", script],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_audit_projection_package_owns_no_http_or_application_policy() -> None:
    package = _ROOT / "src/fdai/delivery/operator_api/projections/audit"
    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        modules = _imports(path)
        assert "starlette" not in source
        assert "CORSMiddleware" not in source
        assert 'Route("/' not in source
        route_imports = {
            module for module in modules if module.startswith("fdai.delivery.operator_api.routes")
        }
        if route_imports:
            assert path.stem in _AUDIT_MODULES
            assert route_imports == {f"fdai.delivery.operator_api.routes.{path.stem}"}
            tree = ast.parse(source)
            assert not any(
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                for node in tree.body
            )


def test_app_and_panel_composition_use_owned_audit_facade() -> None:
    core_reads = _ROOT / "src/fdai/delivery/operator_api/routes/core_reads.py"
    production_panels = _ROOT / "src/fdai/delivery/operator_api/production/panels.py"
    operator_config = _ROOT / "src/fdai/delivery/operator_api/production/operator_config.py"
    dev_factory = _ROOT / "src/fdai/delivery/operator_api/dev/factory.py"

    assert "fdai.delivery.operator_api.projections.audit" in _imports(core_reads)
    assert "fdai.delivery.operator_api.projections.audit" in _imports(production_panels)
    assert "fdai.delivery.operator_api.production.panels" in _imports(dev_factory)
    production_source = operator_config.read_text(encoding="utf-8")
    dev_source = dev_factory.read_text(encoding="utf-8")
    assert "*build_production_panels(" in production_source
    assert "durable_panels = cast(" in dev_source
    assert "build_production_panels(" in dev_source
    assert "durable_panels=durable_panels" in dev_source


def test_exactly_one_import_surface_owns_each_audit_implementation() -> None:
    routes = _ROOT / "src/fdai/delivery/operator_api/routes"
    projections = _ROOT / "src/fdai/delivery/operator_api/projections/audit"
    for name in _AUDIT_MODULES:
        old_tree = ast.parse((routes / f"{name}.py").read_text(encoding="utf-8"))
        new_tree = ast.parse((projections / f"{name}.py").read_text(encoding="utf-8"))
        old_defines = any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for node in old_tree.body
        )
        new_defines = any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for node in new_tree.body
        )
        assert old_defines is not new_defines


class _ConfiguredInMemoryReadModel(InMemoryConsoleReadModel):
    _config = SimpleNamespace(
        dsn="postgresql://localhost/fdai",
        statement_timeout_ms=1000,
        connect_timeout_s=1.0,
    )


def _production_audit_panels() -> tuple[
    _ConfiguredInMemoryReadModel,
    AuditFinOpsPanel,
    AuditAutonomyMeasurementPanel,
]:
    read_model = _ConfiguredInMemoryReadModel()
    panels = build_production_panels(
        read_model=read_model,
        onboarding_probe=object(),
        onboarding_configured=False,
        state_store=InMemoryStateStore(),
        action_types=(),
        active_rule_count=0,
    )
    return (
        read_model,
        cast(AuditFinOpsPanel, panels[1]),
        cast(AuditAutonomyMeasurementPanel, panels[2]),
    )


def _application_with_real_audit_panels() -> Starlette:
    mapping = GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )

    def verify(_token: str) -> dict[str, object]:
        return {"oid": "reader", "roles": ["Reader"]}

    read_model, finops_panel, autonomy_panel = _production_audit_panels()
    return build_app(
        authenticator=build_authenticator(
            verifier=verify,
            resolver=RoleResolver(group_mapping=mapping),
        ),
        read_model=read_model,
        config=OperatorApiConfig(extra_panels=(finops_panel, autonomy_panel)),
    )


def test_real_audit_panels_preserve_http_contracts() -> None:
    application = _application_with_real_audit_panels()
    client = TestClient(application)
    routes = {
        route.path: (tuple(sorted(route.methods or ())), route.name)
        for route in application.routes
        if hasattr(route, "path")
    }

    assert routes["/finops"] == (("GET", "HEAD"), "panel:finops")
    assert routes["/kpi/autonomy"] == (("GET", "HEAD"), "panel:autonomy")
    for path in ("/finops", "/kpi/autonomy"):
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"authorization": "Bearer reader"})
        assert response.status_code == 200
        assert client.head(path, headers={"authorization": "Bearer reader"}).status_code == 200
        assert client.post(path, headers={"authorization": "Bearer reader"}).status_code == 405
    assert client.get("/finops", headers={"authorization": "Bearer reader"}).json() == {
        "vertical": "finops",
        "total_actions": 0,
        "by_kind": {},
        "estimated_monthly_savings": 0.0,
        "sampled_events": 0,
        "source": "postgres-audit",
        "durable": True,
        "window_days": 30,
        "as_of": None,
    }
    autonomy = client.get("/kpi/autonomy", headers={"authorization": "Bearer reader"}).json()
    assert autonomy["source"] == {
        "name": "postgres-audit",
        "kind": "audit",
        "as_of": None,
    }
    assert autonomy["sample_size"] == 0


def test_production_panel_builder_uses_owned_audit_classes() -> None:
    _, finops_panel, autonomy_panel = _production_audit_panels()

    assert isinstance(finops_panel, AuditFinOpsPanel)
    assert isinstance(autonomy_panel, AuditAutonomyMeasurementPanel)
