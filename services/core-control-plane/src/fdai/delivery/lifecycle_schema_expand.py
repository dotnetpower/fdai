"""Run the forward-only Hub schema-expand sequence under one installation database lease."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import psycopg

_LEASE_NAME = "fdai:lifecycle-schema-expand:v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_REVISION = re.compile(r"[A-Za-z0-9_]{1,128}\Z", re.ASCII)


class ProcessRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: int,
    ) -> None: ...

    def capture(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: int,
    ) -> str: ...


class SubprocessRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: int,
    ) -> None:
        subprocess.run(  # noqa: S603 - the migration runner constructs every command.
            tuple(command),
            cwd=cwd,
            env=dict(environment),
            timeout=timeout,
            check=True,
        )

    def capture(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: int,
    ) -> str:
        completed = subprocess.run(  # noqa: S603 - the migration runner constructs every command.
            tuple(command),
            cwd=cwd,
            env=dict(environment),
            timeout=timeout,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout


def run_schema_expand(
    *,
    database_url: str,
    release_digest: str,
    schema_target: int,
    classification: Mapping[str, object],
    root: Path,
    evidence_directory: Path,
    runner: ProcessRunner,
    connection: psycopg.Connection[tuple[object, ...]],
) -> dict[str, object]:
    """Run legacy, ordered service, and catalog migrations while holding one lease."""

    revisions = _classification(classification)
    if not database_url or _DIGEST.fullmatch(release_digest) is None or schema_target < 1:
        raise ValueError("schema expand inputs are invalid")
    _validate_revision_files(root, revisions)
    acquired = connection.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
        (_LEASE_NAME,),
    ).fetchone()
    if acquired != (True,):
        raise RuntimeError("schema_expand_lease_unavailable")
    evidence_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    environment = {**os.environ, "FDAI_DATABASE_URL": database_url}
    try:
        runner.run(
            (
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(root / "alembic.ini"),
                "upgrade",
                "head",
            ),
            cwd=root,
            environment=environment,
            timeout=1200,
        )
        order = tuple(
            item
            for item in runner.capture(
                (
                    sys.executable,
                    str(root / "service-migrations/migrate.py"),
                    "all",
                    "order",
                ),
                cwd=root,
                environment=environment,
                timeout=120,
            ).splitlines()
            if item
        )
        for service in order:
            if re.fullmatch(r"[a-z][a-z0-9-]{1,63}", service) is None:
                raise ValueError("service migration order is invalid")
            runner.run(
                (
                    "/bin/sh",
                    str(root / f"service-migrations/bin/{service}"),
                    "bootstrap",
                    "--evidence-output",
                    str(evidence_directory / f"{service}.json"),
                    "--schema-output",
                    str(evidence_directory / f"{service}-schema.json"),
                    "--rollback-reference",
                    f"release:{release_digest}:service-migrations/branches/{service}/adoption.json#rollback",
                ),
                cwd=root,
                environment=environment,
                timeout=1200,
            )
        runner.run(
            (
                sys.executable,
                str(root / "scripts/deployment/local/materialize-authoritative-catalogs.py"),
            ),
            cwd=root,
            environment=environment,
            timeout=600,
        )
        receipt: dict[str, object] = {
            "schema_version": "fdai.schema-expand-receipt.v1",
            "release_digest": release_digest,
            "schema_target": schema_target,
            "classification_digest": _digest(classification),
            "revision_count": len(revisions),
            "service_count": len(order),
            "catalogs_materialized": True,
        }
        receipt["receipt_digest"] = _digest(receipt)
        return receipt
    finally:
        connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (_LEASE_NAME,),
        )


def main() -> int:
    classification = json.loads(os.environ["FDAI_MIGRATION_CLASSIFICATION"])
    database_url = os.environ["FDAI_DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as connection:
        receipt = run_schema_expand(
            database_url=database_url,
            release_digest=os.environ["FDAI_MIGRATION_RELEASE_DIGEST"],
            schema_target=int(os.environ["FDAI_MIGRATION_SCHEMA_TARGET"]),
            classification=classification,
            root=Path("/app"),
            evidence_directory=Path("/tmp/fdai-schema-expand"),  # noqa: S108 - Job-local emptyDir
            runner=SubprocessRunner(),
            connection=connection,
        )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


def _classification(value: Mapping[str, object]) -> dict[str, str]:
    if (
        set(value) != {"schema", "revisions"}
        or value["schema"] != "fdai.migration-classification.v1"
        or not isinstance(value["revisions"], Mapping)
    ):
        raise ValueError("migration classification is invalid")
    revisions = value["revisions"]
    if not revisions or not all(
        isinstance(revision, str) and _REVISION.fullmatch(revision) and migration_class == "expand"
        for revision, migration_class in revisions.items()
    ):
        raise ValueError("migration classification is invalid")
    return {str(revision): str(migration_class) for revision, migration_class in revisions.items()}


def _validate_revision_files(root: Path, revisions: Mapping[str, str]) -> None:
    module_path = root / "service-migrations/service_migrations/classification.py"
    spec = importlib.util.spec_from_file_location("_fdai_migration_classification", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("migration classification analyzer is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    candidates: dict[str, Path] = {}
    for path in (
        *sorted((root / "alembic/versions").glob("*.py")),
        *sorted((root / "service-migrations").glob("*/versions/*.py")),
    ):
        try:
            analysis = module.analyze_revision(path)
        except (module.MigrationClassificationError, SyntaxError):
            continue
        if analysis.revision in revisions:
            if analysis.revision in candidates:
                raise ValueError("migration classification is ambiguous")
            candidates[analysis.revision] = path
    if set(candidates) != set(revisions):
        raise ValueError("migration classification does not match the image")
    try:
        module.plan_expand(candidates, revisions)
    except module.MigrationClassificationError as error:
        raise ValueError(error.reason_code) from None


def _digest(value: Mapping[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
