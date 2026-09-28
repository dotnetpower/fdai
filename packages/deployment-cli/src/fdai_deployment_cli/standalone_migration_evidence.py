"""Check the adoption evidence one service migration bootstrap may write."""

from __future__ import annotations

from pathlib import Path

from fdai_deployment_cli.standalone_host_state import private_json


def verify_service_evidence(evidence: Path, service: str) -> bool:
    """Verify fresh adoption evidence; return False when the lineage was already adopted.

    `bootstrap` writes adoption evidence only when it adopts a legacy baseline. When an earlier
    run already adopted the service lineage, bootstrap only advances it to head and writes
    nothing, so absent evidence is a verified resume rather than a failure. A partial or
    inconsistent pair still fails closed.
    """

    migration_path = evidence / f"{service}.json"
    schema_path = evidence / f"{service}-schema.json"
    if not migration_path.exists() and not schema_path.exists():
        return False
    for path in (migration_path, schema_path):
        path.chmod(0o600)
    migration = private_json(migration_path, f"{service} migration evidence")
    schema = private_json(schema_path, f"{service} migration schema")
    if (
        migration.get("service_id") != service
        or not isinstance(migration.get("observed_schema_fingerprint"), str)
        or schema.get("schema_version") != 1
        or schema.get("service_id") != service
        or schema.get("observed_schema_fingerprint") != migration.get("observed_schema_fingerprint")
    ):
        raise ValueError("service migration evidence is incomplete")
    return True


__all__ = ["verify_service_evidence"]
