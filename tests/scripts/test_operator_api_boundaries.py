"""Regression tests for the Operator API dependency-direction gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "scripts/quality/architecture/check-operator-api-boundaries.py"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(
    root: Path,
    *,
    paths: tuple[str, ...] = (),
    allowlist: str | None = None,
    debt_budget: str | None = None,
    fanout_limit: int = 40,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(_GATE),
        "--root",
        str(root),
        "--fanout-limit",
        str(fanout_limit),
    ]
    for path in paths:
        command.extend(("--path", path))
    if allowlist is not None:
        command.extend(("--allowlist", allowlist))
    if debt_budget is not None:
        command.extend(("--debt-budget", debt_budget))
    return subprocess.run(  # noqa: S603 - fixed interpreter and script
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_dependency_directions_pass(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/fdai/core/service.py",
        "from fdai.shared.providers.event_bus import EventBus\n",
    )
    _write(
        tmp_path,
        "src/fdai/runtime/worker.py",
        "from fdai.delivery.agent_activity import AgentStateEvent\n",
    )
    _write(
        tmp_path,
        "src/fdai/delivery/ingestion_gateway/main.py",
        "from fdai.delivery.auth import Authenticator\n",
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "check-operator-api-boundaries: OK" in result.stdout


@pytest.mark.parametrize(
    ("relative", "source", "rule"),
    (
        (
            "src/fdai/core/service.py",
            "from fdai.delivery.auth import Authenticator\n",
            "core-to-delivery",
        ),
        (
            "src/fdai/runtime/worker.py",
            "from fdai.delivery.operator_api.auth import Authenticator\n",
            "runtime-to-operator-api",
        ),
        (
            "src/fdai/delivery/ingestion_gateway/main.py",
            "from fdai.delivery.operator_api.auth import Authenticator\n",
            "ingestion-to-operator-api",
        ),
        (
            "src/fdai/delivery/auth/adapter.py",
            "from fdai.delivery.operator_api.routes.audit import route\n",
            "shared-delivery-to-application",
        ),
        (
            "src/fdai/core/service.py",
            "from ..delivery import operator_api\n",
            "core-to-delivery",
        ),
        (
            "src/fdai/runtime/worker.py",
            "from ..delivery import operator_api\n",
            "runtime-to-operator-api",
        ),
        (
            "src/fdai/delivery/ingestion_gateway/main.py",
            "from .. import operator_api\n",
            "ingestion-to-operator-api",
        ),
        (
            "src/fdai/runtime/worker.py",
            "from fdai.delivery import operator_api\n",
            "runtime-to-operator-api",
        ),
        (
            "src/fdai/runtime/worker.py",
            "import importlib\n"
            'operator_api = importlib.import_module("fdai.delivery.operator_api.auth")\n',
            "runtime-to-operator-api",
        ),
        (
            "src/fdai/runtime/worker.py",
            'operator_api = __import__("fdai.delivery.operator_api.auth")\n',
            "runtime-to-operator-api",
        ),
        (
            "src/fdai/delivery/agent_activity/__init__.py",
            "from fdai.delivery.operator_api.routes.audit import route\n",
            "shared-delivery-to-application",
        ),
    ),
)
def test_enforced_violation_is_detected(
    tmp_path: Path,
    relative: str,
    source: str,
    rule: str,
) -> None:
    _write(tmp_path, relative, source)

    result = _run(tmp_path)

    assert result.returncode == 1
    assert f"[{rule}]" in result.stdout


def test_known_operator_debt_is_reported_without_blocking(tmp_path: Path) -> None:
    debt_budget = "debt.txt"
    _write(
        tmp_path,
        "src/fdai/delivery/operator_api/routes/audit.py",
        "from fdai.core.audit import AuditEntry\n",
    )
    _write(
        tmp_path,
        "src/fdai/delivery/operator_api/production/identity.py",
        "from fdai.runtime.health import RuntimeHealth\n"
        "from fdai.delivery.ingestion_gateway.main import build_app\n",
    )
    _write(
        tmp_path,
        debt_budget,
        "# Fixture route debt.\nreport-route-core-policy|1\n"
        "# Fixture runtime debt.\nreport-operator-to-runtime|1\n"
        "# Fixture ingestion debt.\nreport-operator-to-ingestion|1\n",
    )

    result = _run(tmp_path, debt_budget=debt_budget)

    assert result.returncode == 0, result.stdout
    assert "[report-route-core-policy]" in result.stdout
    assert "[report-operator-to-runtime]" in result.stdout
    assert "[report-operator-to-ingestion]" in result.stdout


def test_composition_fanout_requires_reviewed_exception(tmp_path: Path) -> None:
    relative = "src/fdai/delivery/operator_api/production/factory.py"
    _write(
        tmp_path,
        relative,
        "from fdai.core.audit import AuditEntry\nfrom fdai.delivery.auth import Authenticator\n",
    )

    result = _run(tmp_path, fanout_limit=2)

    assert result.returncode == 1
    assert "[composition-fanout]" in result.stdout


def test_justified_fanout_exception_passes(tmp_path: Path) -> None:
    relative = "src/fdai/delivery/operator_api/production/factory.py"
    allowlist = "allowlist.txt"
    _write(
        tmp_path,
        relative,
        "from fdai.core.audit import AuditEntry\nfrom fdai.delivery.auth import Authenticator\n",
    )
    _write(
        tmp_path,
        allowlist,
        f"# This fixture is the reviewed composition root.\ncomposition-fanout|{relative}|2\n",
    )

    result = _run(
        tmp_path,
        allowlist=allowlist,
        fanout_limit=2,
    )

    assert result.returncode == 0, result.stdout
    assert f"fanout {relative}: 2 unique fdai imports (reviewed)" in result.stdout


def test_fanout_allowlist_requires_justification(tmp_path: Path) -> None:
    allowlist = "allowlist.txt"
    _write(
        tmp_path,
        allowlist,
        "composition-fanout|src/fdai/runtime/bootstrap.py|2\n",
    )

    result = _run(tmp_path, allowlist=allowlist)

    assert result.returncode == 2
    assert "requires a preceding justification" in result.stdout


def test_stale_fanout_allowlist_entry_fails(tmp_path: Path) -> None:
    relative = "src/fdai/runtime/bootstrap.py"
    allowlist = "allowlist.txt"
    _write(tmp_path, relative, "from fdai.core.audit import AuditEntry\n")
    _write(
        tmp_path,
        allowlist,
        f"# This entry should become stale below the threshold.\ncomposition-fanout|{relative}|2\n",
    )

    result = _run(tmp_path, allowlist=allowlist, fanout_limit=2)

    assert result.returncode == 1
    assert "stale allowlist entry" in result.stdout


def test_selected_path_ignores_unrelated_violation_and_allowlist(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/fdai/core/service.py",
        "from fdai.delivery.auth import Authenticator\n",
    )
    _write(
        tmp_path,
        "src/fdai/runtime/worker.py",
        "from fdai.delivery.agent_activity import AgentStateEvent\n",
    )
    _write(
        tmp_path,
        "allowlist.txt",
        "# Unselected composition root exception.\n"
        "composition-fanout|src/fdai/delivery/operator_api/production/factory.py|40\n",
    )

    result = _run(
        tmp_path,
        paths=("src/fdai/runtime",),
        allowlist="allowlist.txt",
    )

    assert result.returncode == 0, result.stdout


def test_reviewed_fanout_ceiling_blocks_growth(tmp_path: Path) -> None:
    relative = "src/fdai/delivery/operator_api/production/factory.py"
    allowlist = "allowlist.txt"
    _write(
        tmp_path,
        relative,
        "from fdai.core.audit import AuditEntry\n"
        "from fdai.delivery.auth import Authenticator\n"
        "from fdai.shared.providers.event_bus import EventBus\n",
    )
    _write(
        tmp_path,
        allowlist,
        "# The reviewed ceiling is intentionally below the fixture fanout.\n"
        f"composition-fanout|{relative}|2\n",
    )

    result = _run(tmp_path, allowlist=allowlist, fanout_limit=2)

    assert result.returncode == 1
    assert "exceeds its reviewed ceiling 2" in result.stdout


def test_report_only_debt_cannot_grow_above_budget(tmp_path: Path) -> None:
    debt_budget = "debt.txt"
    _write(
        tmp_path,
        "src/fdai/delivery/operator_api/routes/audit.py",
        "from fdai.core.audit import AuditEntry\nfrom fdai.core.rbac import Role\n",
    )
    _write(
        tmp_path,
        debt_budget,
        "# One report-only import is the reviewed ceiling.\nreport-route-core-policy|1\n",
    )

    result = _run(tmp_path, debt_budget=debt_budget)

    assert result.returncode == 1
    assert "[report-debt-growth]" in result.stdout


def test_nonliteral_dynamic_import_fails_closed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/fdai/runtime/worker.py",
        "import importlib\nmodule_name = get_module_name()\n"
        "target = importlib.import_module(module_name)\n",
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "[dynamic-import-unresolved]" in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\n"
        'target = importlib.import_module(".operator_api", package="fdai.delivery")\n',
        'target = __import__("operator_api", globals(), locals(), (), 2)\n',
    ],
)
def test_relative_dynamic_import_fails_closed(tmp_path: Path, source: str) -> None:
    _write(tmp_path, "src/fdai/runtime/worker.py", source)

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "[dynamic-import-unresolved]" in result.stdout


def test_absolute_safe_dynamic_import_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/fdai/runtime/worker.py",
        'import importlib\ntarget = importlib.import_module("fdai.delivery.agent_activity")\n',
    )

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout


def test_missing_debt_budget_fails_when_report_debt_exists(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/fdai/delivery/operator_api/routes/audit.py",
        "from fdai.core.audit import AuditEntry\n",
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "[report-debt-unbudgeted]" in result.stdout


def test_unbudgeted_report_rule_fails(tmp_path: Path) -> None:
    debt_budget = "debt.txt"
    _write(
        tmp_path,
        "src/fdai/delivery/operator_api/production/identity.py",
        "from fdai.runtime.health import RuntimeHealth\n",
    )
    _write(
        tmp_path,
        debt_budget,
        "# A different report rule is budgeted.\nreport-route-core-policy|0\n",
    )

    result = _run(tmp_path, debt_budget=debt_budget)

    assert result.returncode == 1
    assert "[report-debt-unbudgeted]" in result.stdout


def test_selected_path_enforces_violation_inside_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/fdai/runtime/worker.py",
        "from fdai.delivery.operator_api.auth import Authenticator\n",
    )

    result = _run(tmp_path, paths=("src/fdai/runtime",))

    assert result.returncode == 1
    assert "[runtime-to-operator-api]" in result.stdout


def test_equivalent_submodule_imports_share_one_fanout_identity(tmp_path: Path) -> None:
    relative = "src/fdai/delivery/operator_api/production/factory.py"
    _write(tmp_path, "src/fdai/core/audit.py", "class AuditEntry:\n    pass\n")
    _write(
        tmp_path,
        relative,
        "import fdai.core.audit\nfrom fdai.core import audit\n",
    )

    result = _run(tmp_path, fanout_limit=2)

    assert result.returncode == 0, result.stdout
    assert f"fanout {relative}: 1 unique fdai imports (within-limit)" in result.stdout


@pytest.mark.parametrize("path", ["missing.py", "../outside.py"])
def test_unsafe_or_missing_selected_path_fails(tmp_path: Path, path: str) -> None:
    result = _run(tmp_path, paths=(path,))

    assert result.returncode == 2
    assert "invalid configuration or scope" in result.stdout


def test_absolute_selected_path_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, paths=(str((tmp_path / "outside.py").resolve()),))

    assert result.returncode == 2
    assert "invalid configuration or scope" in result.stdout


def test_missing_root_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing")

    assert result.returncode == 2
    assert "repository root is not a directory" in result.stdout


def test_source_directory_symlink_fails_closed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _write(
        outside,
        "bad.py",
        "from fdai.delivery.operator_api.auth import Authenticator\n",
    )
    core = tmp_path / "src/fdai/core"
    core.mkdir(parents=True)
    (core / "linked").symlink_to(outside, target_is_directory=True)

    result = _run(tmp_path)

    assert result.returncode == 2
    assert "source tree must not contain directory symlink" in result.stdout


def test_python_syntax_error_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "src/fdai/runtime/worker.py", "def broken(:\n")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "[python-parse]" in result.stdout
