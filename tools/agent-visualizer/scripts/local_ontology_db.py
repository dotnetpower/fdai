"""Bounded read-only access to the existing service-owned loopback ontology database."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[3]


def local_connection_parameters(env_path: Path) -> dict[str, Any]:
    """Read one known environment key without shell evaluation or credential output."""
    dsn = None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, raw = line.removeprefix("export ").partition("=")
        if separator and key.strip() == "FDAI_STATE_STORE_DSN":
            values = shlex.split(raw, comments=True)
            if len(values) != 1:
                raise ValueError("Local service DSN must be one literal value.")
            dsn = values[0]
    if not dsn:
        raise ValueError("The local runtime environment does not contain a service DSN.")
    params = conninfo_to_dict(dsn)
    if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Only the existing loopback database is permitted.")
    if params.get("hostaddr") not in {None, "127.0.0.1", "::1"}:
        raise ValueError("A non-loopback database address is prohibited.")
    if params.get("port", "5432") != "5432" or "service" in params:
        raise ValueError("Only the standard local application database is permitted.")
    # Explicit connection fields prevent ambient libpq service/host settings changing the venue.
    if any(os.environ.get(key) for key in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR")):
        raise ValueError("Ambient PostgreSQL routing overrides must be removed for this reader.")
    return {**params, "connect_timeout": 5, "row_factory": dict_row}


def connect_readonly(env_path: Path | None = None) -> psycopg.Connection:
    """Open a repeatable-read, read-only snapshot; callers must close it."""
    params = local_connection_parameters(env_path or ROOT / ".fdai/local-runtime.env")
    connection = psycopg.connect(**params)
    try:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '15s'")
        connection.execute("SET LOCAL lock_timeout = '2s'")
        mode = connection.execute("SHOW transaction_read_only").fetchone()
        if mode is None or mode["transaction_read_only"] != "on":
            raise RuntimeError("Database reader is not read-only.")
    except Exception:
        connection.close()
        raise
    return connection


def inspect() -> dict[str, Any]:
    """Report counts and schema names only, never row values or connection identity."""
    with connect_readonly() as connection:
        counts = connection.execute(
            "SELECT object_type, count(*) AS count FROM ontology_resource "
            "GROUP BY object_type ORDER BY object_type"
        ).fetchall()
        links = connection.execute("SELECT count(*) AS count FROM ontology_link").fetchone()
        types = connection.execute("SELECT count(*) AS count FROM ontology_object_type").fetchone()
        graph = connection.execute(
            "SELECT value FROM state_kv WHERE key = %s",
            ("operator-projection:operations:ontology.graph",),
        ).fetchone()
        value = graph["value"] if graph else None
        if isinstance(value, str):
            import json

            value = json.loads(value)
        history = connection.execute(
            "SELECT to_regclass('public.operational_state_transition') IS NOT NULL AS available"
        ).fetchone()
        topology = value.get("catalog_topology", {}) if isinstance(value, dict) else {}
        topology_nodes = topology.get("nodes", []) if isinstance(topology, dict) else []
        topology_edges = topology.get("edges", []) if isinstance(topology, dict) else []
        history_count = (
            connection.execute(
                "SELECT count(*) AS count FROM operational_state_transition"
            ).fetchone()
            if history and history["available"]
            else None
        )
        property_keys = connection.execute(
            "SELECT DISTINCT jsonb_object_keys(properties) AS key FROM ontology_resource "
            "WHERE object_type = 'Resource' ORDER BY key"
        ).fetchall()
        return {
            "read_only": True,
            "object_type_count": types["count"] if types else None,
            "instance_counts": counts,
            "stored_links": links["count"] if links else None,
            "console_projection_keys": sorted(value) if isinstance(value, dict) else [],
            "state_history_table": bool(history and history["available"]),
            "state_history_count": history_count["count"] if history_count else None,
            "catalog_topology_keys": sorted(topology) if isinstance(topology, dict) else [],
            "catalog_nodes": len(topology_nodes),
            "catalog_edges": len(topology_edges),
            "catalog_node_fields": sorted(topology_nodes[0]) if topology_nodes else [],
            "catalog_edge_fields": sorted(topology_edges[0]) if topology_edges else [],
            "resource_property_keys": [row["key"] for row in property_keys],
        }


if __name__ == "__main__":
    import json

    try:
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
    except (psycopg.Error, OSError, ValueError) as error:
        raise SystemExit(
            f"Local ontology inspection failed: {type(error).__name__}. "
            "Check the service-owned local database; credentials are withheld."
        ) from None
