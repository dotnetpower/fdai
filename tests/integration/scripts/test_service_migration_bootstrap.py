from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _REPO_ROOT / "scripts/deployment/azure/bootstrap-service-migrations.sh"


def test_bootstrap_script_has_bounded_secret_safe_contract() -> None:
    source = _BOOTSTRAP.read_text(encoding="utf-8")

    assert "migration_deadline=$((SECONDS + migration_budget))" in source
    assert 'timeout --kill-after=30s "${remaining}s"' in source
    assert 'echo "::add-mask::$migration_dsn"' in source
    assert 'export FDAI_DATABASE_URL="$migration_dsn"' in source
    assert "uv run --frozen --extra dev alembic upgrade head" in source
    assert "service-migrations/migrate.py all order" in source
    assert 'for service in "${migration_services[@]}"' in source
    assert "integrated bootstrap requires one shared migration DSN secret" in source
    assert "prepare-adoption" not in source
    assert "stamp-baseline" not in source
    for service in (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    ):
        assert f"service-migrations/bin/{service}" not in source


def test_bootstrap_script_rejects_invalid_rollback_revision(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    assert bash is not None

    result = subprocess.run(  # noqa: S603 - repository-owned script under test.
        [bash, str(_BOOTSTRAP), str(tmp_path / "infra"), str(tmp_path / "evidence"), "bad"],
        cwd=_REPO_ROOT,
        env={**os.environ, "FDAI_MIGRATION_BUDGET_SECONDS": "1200"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "rollback revision must be a lowercase 40-character git SHA" in result.stderr
    assert "service migration DSN" not in result.stdout
