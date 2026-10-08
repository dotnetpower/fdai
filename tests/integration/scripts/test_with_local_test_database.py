from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "automation" / "with-local-test-database.py"
    spec = importlib.util.spec_from_file_location("with_local_test_database", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env_file(tmp_path: Path, value: str) -> Path:
    path = tmp_path / "local-runtime.env"
    path.write_text(
        "FDAI_DATABASE_URL=postgresql+psycopg://runtime@127.0.0.1:5432/fdai\n"
        f"FDAI_VALIDATION_DATABASE_URL={value}\n",
        encoding="utf-8",
    )
    return path


def test_reads_only_the_validation_url_from_the_local_file(tmp_path: Path) -> None:
    module = _module()
    url = "postgresql+psycopg://validation@127.0.0.1:5433/fdai_validation"

    assert module.local_test_database_url({}, _env_file(tmp_path, url)) == url


def test_environment_value_wins_over_the_file(tmp_path: Path) -> None:
    module = _module()
    explicit = "postgresql://validation@localhost:15433/other"

    assert (
        module.local_test_database_url(
            {"FDAI_VALIDATION_DATABASE_URL": explicit},
            _env_file(tmp_path, "postgresql://validation@127.0.0.1:5433/fdai_validation"),
        )
        == explicit
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "postgresql://validation@db.example.com:5433/fdai_validation",
        "postgresql://runtime@127.0.0.1:5432/fdai",
        "postgresql://validation@127.0.0.1/fdai_validation",
        "mysql://validation@127.0.0.1:5433/fdai_validation",
    ],
)
def test_missing_remote_runtime_or_non_postgres_urls_are_refused(
    tmp_path: Path, value: str
) -> None:
    module = _module()

    with pytest.raises(module.LocalTestDatabaseError):
        module.local_test_database_url({}, _env_file(tmp_path, value))


def test_missing_file_is_refused(tmp_path: Path) -> None:
    module = _module()

    with pytest.raises(module.LocalTestDatabaseError, match="not configured"):
        module.local_test_database_url({}, tmp_path / "missing.env")


def test_worktrees_resolve_the_primary_checkout() -> None:
    module = _module()

    primary = module.primary_checkout(REPO_ROOT)

    assert (primary / ".git").exists()
