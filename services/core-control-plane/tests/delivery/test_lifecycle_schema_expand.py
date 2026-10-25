from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fdai.delivery.lifecycle_schema_expand import run_schema_expand

ROOT = Path(__file__).resolve().parents[4]


class _Result:
    def __init__(self, row: tuple[object, ...]) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...]:
        return self._row


class _Connection:
    def __init__(self, *, acquired: bool = True) -> None:
        self.acquired = acquired
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> _Result:
        self.calls.append((query, parameters))
        return _Result((self.acquired if "try_advisory" in query else True,))


class _Runner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: int,
    ) -> None:
        del cwd, environment, timeout
        self.commands.append(tuple(command))

    def capture(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: int,
    ) -> str:
        del cwd, environment, timeout
        self.commands.append(tuple(command))
        return "core\noperator\n"


def _run(
    tmp_path: Path,
    *,
    connection: Any,
    runner: _Runner | None = None,
) -> dict[str, object]:
    _copy_classification_module(tmp_path / "app")
    versions = tmp_path / "app/alembic/versions"
    versions.mkdir(parents=True, exist_ok=True)
    (versions / "revision_2.py").write_text(
        "revision = 'revision_2'\ndef upgrade():\n    op.create_table('example')\n"
    )
    return run_schema_expand(
        database_url="postgresql://example.invalid/fdai",
        release_digest="sha256:" + "a" * 64,
        schema_target=2,
        classification={
            "schema": "fdai.migration-classification.v1",
            "revisions": {"revision_2": "expand"},
        },
        root=tmp_path / "app",
        evidence_directory=tmp_path / "evidence",
        runner=runner or _Runner(),
        connection=connection,
    )


def test_schema_expand_runs_all_steps_under_one_lease(tmp_path: Path) -> None:
    connection = _Connection()
    runner = _Runner()

    receipt = _run(tmp_path, connection=connection, runner=runner)

    assert "pg_try_advisory_lock" in connection.calls[0][0]
    assert "pg_advisory_unlock" in connection.calls[-1][0]
    flattened = [" ".join(command) for command in runner.commands]
    assert "alembic" in flattened[0]
    assert "service-migrations/migrate.py all order" in flattened[1]
    assert sum(" bootstrap " in f" {command} " for command in flattened) == 2
    assert "materialize-authoritative-catalogs.py" in flattened[-1]
    assert receipt["catalogs_materialized"] is True
    assert receipt["service_count"] == 2
    assert receipt["revision_count"] == 1


def test_schema_expand_refuses_lease_contention_before_commands(tmp_path: Path) -> None:
    runner = _Runner()

    with pytest.raises(RuntimeError, match="schema_expand_lease_unavailable"):
        _run(tmp_path, connection=_Connection(acquired=False), runner=runner)

    assert runner.commands == []


def test_schema_expand_rejects_destructive_declared_revision(tmp_path: Path) -> None:
    _copy_classification_module(tmp_path / "app")
    versions = tmp_path / "app/alembic/versions"
    versions.mkdir(parents=True)
    (versions / "revision_2.py").write_text(
        "revision = 'revision_2'\ndef upgrade():\n    op.drop_table('example')\n"
    )
    runner = _Runner()

    with pytest.raises(ValueError, match="migration_expand_destructive"):
        run_schema_expand(
            database_url="postgresql://example.invalid/fdai",
            release_digest="sha256:" + "a" * 64,
            schema_target=2,
            classification={
                "schema": "fdai.migration-classification.v1",
                "revisions": {"revision_2": "expand"},
            },
            root=tmp_path / "app",
            evidence_directory=tmp_path / "evidence",
            runner=runner,
            connection=_Connection(),
        )

    assert runner.commands == []


def _copy_classification_module(root: Path) -> None:
    destination = root / "service-migrations/service_migrations/classification.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "service-migrations/service_migrations/classification.py",
        destination,
    )
