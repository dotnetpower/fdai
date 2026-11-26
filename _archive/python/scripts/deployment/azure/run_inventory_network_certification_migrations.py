#!/usr/bin/env python3
"""Run legacy and service-owned migrations for inventory network certification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SERVICE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CREDENTIAL = re.compile(r"[a-z+]+://[^\s/@]*@")
_MAX_SERVICES = 16
_COMMAND_TIMEOUT_SECONDS = 840
_MAX_EVIDENCE_BYTES = 1024 * 1024
_MAX_DIAGNOSTIC_LINES = 12
_MAX_DIAGNOSTIC_CHARS = 2000
_SIGNAL = re.compile(
    r"(\w+Error\b|\bFATAL\b|\bDETAIL\b|\bHINT\b|permission denied"
    r"|does not exist|already exists|could not connect|timeout)",
    re.IGNORECASE,
)


class InventoryNetworkMigrationError(RuntimeError):
    """Report a bounded migration failure without rendering credentials."""


def _diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    """Return a bounded, credential-free reason so a failure is diagnosable in place."""

    combined = f"{result.stdout}\n{result.stderr}".strip()
    if not combined:
        return "no command output"
    redacted = _CREDENTIAL.sub("<redacted-credential>@", combined)
    lines = [line.strip() for line in redacted.splitlines() if line.strip()]
    # SQLAlchemy prints the failing statement after its reason, so a plain tail hides
    # the cause. Prefer explicit error signals and fall back to the tail.
    signals = [line for line in lines if _SIGNAL.search(line)]
    selected = (signals or lines)[-_MAX_DIAGNOSTIC_LINES:]
    return "; ".join(selected)[:_MAX_DIAGNOSTIC_CHARS] or "no command output"


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise InventoryNetworkMigrationError(f"{name} is required")
    return value


def _run_command(
    label: str,
    arguments: Sequence[str],
    *,
    repository_root: Path,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            tuple(arguments),
            cwd=repository_root,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise InventoryNetworkMigrationError(
            f"{label} exceeded its {_COMMAND_TIMEOUT_SECONDS}-second deadline"
        ) from exc
    if result.returncode != 0:
        raise InventoryNetworkMigrationError(
            f"{label} failed with exit code {result.returncode}: {_diagnostic(result)}"
        )
    return result


def _service_order(output: str) -> tuple[str, ...]:
    services = tuple(line.strip() for line in output.splitlines() if line.strip())
    if (
        not services
        or len(services) > _MAX_SERVICES
        or len(set(services)) != len(services)
        or any(_SERVICE_ID.fullmatch(service) is None for service in services)
    ):
        raise InventoryNetworkMigrationError("service migration order is malformed")
    return services


def _evidence_digest(path: Path, label: str) -> str:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > _MAX_EVIDENCE_BYTES:
        raise InventoryNetworkMigrationError(f"{label} is missing or outside its size bound")
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def run_inventory_network_migrations(
    environment: Mapping[str, str],
    *,
    repository_root: Path | None = None,
    python_executable: str | None = None,
) -> dict[str, object]:
    """Advance the complete shared schema without exposing migration credentials."""

    _required(environment, "FDAI_DATABASE_URL")
    source_revision = _required(environment, "FDAI_NETWORK_CERT_SOURCE_REVISION")
    if _SOURCE_REVISION.fullmatch(source_revision) is None:
        raise InventoryNetworkMigrationError(
            "FDAI_NETWORK_CERT_SOURCE_REVISION must be a lowercase 40-character commit SHA"
        )

    root = repository_root or Path(__file__).resolve().parents[3]
    python = python_executable or sys.executable
    migration_entry = root / "service-migrations" / "migrate.py"
    if not (root / "alembic.ini").is_file() or not migration_entry.is_file():
        raise InventoryNetworkMigrationError("migration assets are unavailable")

    process_environment = dict(environment)
    _run_command(
        "legacy migration",
        (python, "-m", "alembic", "upgrade", "head"),
        repository_root=root,
        environment=process_environment,
    )
    order_result = _run_command(
        "service migration order",
        (python, str(migration_entry), "all", "order"),
        repository_root=root,
        environment=process_environment,
    )
    services = _service_order(order_result.stdout)
    evidence_digests: dict[str, str] = {}
    schema_digests: dict[str, str] = {}

    with tempfile.TemporaryDirectory(prefix="fdai-inventory-network-migrations-") as directory:
        evidence_root = Path(directory)
        for service in services:
            evidence = evidence_root / f"{service}.json"
            schema = evidence_root / f"{service}-schema.json"
            _run_command(
                f"{service} migration",
                (
                    python,
                    str(migration_entry),
                    service,
                    "bootstrap",
                    "--evidence-output",
                    str(evidence),
                    "--schema-output",
                    str(schema),
                    "--rollback-reference",
                    (
                        f"git:{source_revision}:service-migrations/branches/"
                        f"{service}/adoption.json#rollback"
                    ),
                ),
                repository_root=root,
                environment=process_environment,
            )
            evidence_digests[service] = _evidence_digest(evidence, f"{service} migration evidence")
            schema_digests[service] = _evidence_digest(schema, f"{service} schema evidence")

    order_digest = hashlib.sha256("\n".join(services).encode()).hexdigest()
    return {
        "schema_version": "fdai.inventory-network-migration.v1",
        "source_revision": source_revision,
        "legacy_revision": "head",
        "services": list(services),
        "service_order_digest": f"sha256:{order_digest}",
        "service_evidence_digests": evidence_digests,
        "schema_evidence_digests": schema_digests,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }


def main() -> int:
    """Run the migration closure and emit one secret-free receipt."""

    try:
        receipt = run_inventory_network_migrations(os.environ)
    except (InventoryNetworkMigrationError, OSError) as exc:
        print(f"inventory-network-migrations: ERROR {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
