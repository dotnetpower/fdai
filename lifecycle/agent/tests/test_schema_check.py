from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Column, MetaData, String, Table, create_engine, event, text

from fdai_lifecycle_agent import schema_check
from fdai_lifecycle_agent.schema_check import check_heads, schema_configs


def migration_config(root: Path, name: str, revision: str) -> Path:
    directory = root / name
    versions = directory / "versions"
    versions.mkdir(parents=True)
    (versions / "revision.py").write_text(
        f"revision = {revision!r}\ndown_revision = None\n", encoding="utf-8"
    )
    path = root / f"{name}.ini"
    path.write_text(
        f"[alembic]\nscript_location = {directory}\nversion_table = version_{name}\n",
        encoding="utf-8",
    )
    return path


def test_heads_gate_checks_legacy_then_services_without_writes(tmp_path: Path) -> None:
    # SQLite proves the head-comparison mechanics, not PostgreSQL/Job runtime readiness.
    configs = [
        migration_config(tmp_path, "legacy", "legacy_head"),
        migration_config(tmp_path, "core", "core_head"),
        migration_config(tmp_path, "operator", "operator_head"),
    ]
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for name in ("legacy", "core", "operator"):
            table = Table(f"version_{name}", MetaData(), Column("version_num", String(128)))
            table.create(connection)
            connection.execute(table.insert(), {"version_num": f"{name}_head"})
    statements: list[str] = []
    event.listen(
        engine, "before_cursor_execute", lambda _c, _s, sql, *_args: statements.append(sql)
    )
    with engine.connect() as connection:
        assert check_heads(connection, configs)
    reads = [sql for sql in statements if sql.startswith("SELECT version_")]
    assert [
        "version_legacy" in reads[0],
        "version_core" in reads[1],
        "version_operator" in reads[2],
    ] == [
        True,
        True,
        True,
    ]
    assert all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements)
    engine.dispose()


def test_absent_or_wrong_service_revision_fails_closed(tmp_path: Path) -> None:
    config = migration_config(tmp_path, "operator", "operator_head")
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        assert not check_heads(connection, [config])
        connection.execute(text("CREATE TABLE version_operator (version_num VARCHAR(128))"))
        connection.execute(text("INSERT INTO version_operator VALUES ('old-head')"))
        assert not check_heads(connection, [config])
    engine.dispose()


def test_job_script_is_self_contained_and_never_runs_migrations() -> None:
    source = Path(__file__).resolve().parents[1] / "src/fdai_lifecycle_agent/schema_check.py"
    script = source.read_text()
    ast.parse(script)
    assert "fdai_lifecycle_agent" not in script
    assert "from service_migrations.ownership import" in script
    assert "SET TRANSACTION READ ONLY" in script
    assert "command.upgrade" not in script
    assert "command.downgrade" not in script


def test_real_image_migration_inventory_and_configs_resolve_without_database() -> None:
    root = Path(__file__).resolve().parents[3]
    configs = schema_configs(root)
    assert configs[0] == root / "alembic.ini"
    assert len(configs) == 6
    assert {path.stem for path in configs[1:]} == {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
    for path in configs:
        assert ScriptDirectory.from_config(Config(str(path))).get_heads()


def test_main_resolves_real_inventory_before_database_verification(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(__file__).resolve().parents[3]
    requested_roots: list[Path] = []
    original = schema_check.schema_configs

    def resolve(image_root: Path) -> list[Path]:
        requested_roots.append(image_root)
        return original(root)

    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    verify = MagicMock(return_value=True)
    monkeypatch.setattr(schema_check, "schema_configs", resolve)
    monkeypatch.setattr(schema_check, "create_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(schema_check, "check_heads", verify)
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://schema-reader@localhost/test")
    assert schema_check.main() == 0
    assert requested_roots == [Path("/app")]
    verify.assert_called_once_with(connection, original(root))
    assert [str(call.args[0]) for call in connection.execute.call_args_list] == [
        "SET statement_timeout = '10s'",
        "SET TRANSACTION READ ONLY",
    ]
    assert capsys.readouterr().out == "schema_check_verified\n"
